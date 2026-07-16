"""Regression tests for the check_poster gates.

Each test pins a contract that was silently broken before -- a gate that
looked green because it never actually ran, or a breaker that counted the
wrong thing:

  * ``slack``'s circuit breaker counted every INVOCATION, incremented
    before the browser even launched, and never cleared. So a converged
    poster inherited the debt of the rounds that converged it, a run that
    never got geometry (nav timeout, MathJax settle failure) burned budget
    it never used, and (once the count became consecutive-failures) a poster
    failing only a polish gate cleared its budget every round and could
    never trip the breaker at all.
  * The class->role compat shim bailed on the FIRST explicit
    ``data-measure-role`` it saw. ``assets/layouts_portrait/full.html``
    declares exactly one (``column``, on ``.method-hero``), so poster+card
    stayed at zero and ``polish`` hard-failed its own shipped template.
  * ``polish`` skipped the broken-image check for anything whose src looked
    like an SVG, on the theory that vector art can legitimately report zero
    natural size. Chromium never does that -- it resolves a viewBox-less
    ``<img>``'d SVG to 300x150 -- so the exemption only ever white-printed
    genuinely broken vector art.
  * The gates trusted a static regex estimate of the role markup, which can
    claim a card the browser does not render -- so they could measure
    nothing, emit no warnings, and PASS.
  * Nothing checked for a void in the MIDDLE of a card: CARD/TRAILING
    skips space-distributing cards and reads ~0 when a tail is pinned to
    the bottom, and Gate C only looks between cards in a column.

Run:  pytest ResearchStudio-Reel/skills/paper2poster/tests/ -q

The DOM tests need Playwright + Chromium and skip themselves when it is
unavailable; the rest are browser-free.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

from utils import polish as _polish        # noqa: E402
from utils import preflight as _preflight  # noqa: E402
from utils import render as _render        # noqa: E402
from utils import slack as _slack          # noqa: E402


@pytest.fixture(scope="session")
def chromium():
    """Skip unless Playwright + Chromium are usable. Holds NO live context:
    the tests that drive `cmd_slack` need it to open its own
    `sync_playwright()`, and the sync API cannot be re-entered on one
    thread."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:                          # no browser binary
        pytest.skip(f"Chromium not available ({exc})")
    return True


@pytest.fixture
def page(chromium):
    """A blank Chromium page. Function-scoped so the context is closed before
    any test that lets the tool launch its own browser."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1200, "height": 900})
        yield pg
        browser.close()


# --------------------------------------------------------------------------
# slack: circuit-breaker state
# --------------------------------------------------------------------------

def test_budget_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / ".fill_budget.json"
    assert _slack._load_budget(p) == 0          # missing == fresh
    _slack._write_budget(p, 5)
    assert _slack._load_budget(p) == 5


def test_budget_clear_removes_state(tmp_path: Path) -> None:
    """A count surviving a converged measurement would break the
    CONSECUTIVE-failure contract on the next run."""
    p = tmp_path / ".fill_budget.json"
    _slack._write_budget(p, 7)
    _slack._clear_budget(p)
    assert not p.exists()
    assert _slack._load_budget(p) == 0


def test_budget_expires_when_stale(tmp_path: Path) -> None:
    """A counter idle past the window is a PREVIOUS session, not this loop."""
    p = tmp_path / ".fill_budget.json"
    old = (_dt.datetime.now(_dt.timezone.utc)
           - _dt.timedelta(hours=_slack.BUDGET_STALE_AFTER_HOURS + 1))
    p.write_text(json.dumps({"count": 9, "updated": old.isoformat()}))
    assert _slack._load_budget(p) == 0
    fresh = (_dt.datetime.now(_dt.timezone.utc)
             - _dt.timedelta(hours=_slack.BUDGET_STALE_AFTER_HOURS - 1))
    p.write_text(json.dumps({"count": 9, "updated": fresh.isoformat()}))
    assert _slack._load_budget(p) == 9


@pytest.mark.parametrize("payload", [
    "{ not json",
    json.dumps({"count": -3}),
    json.dumps({"nope": 1}),
    json.dumps({"count": "many"}),
])
def test_budget_bad_state_never_invents_a_count(tmp_path: Path,
                                                payload: str) -> None:
    """Unreadable state must degrade to 0, never to a phantom breaker that
    stops a legitimate loop."""
    p = tmp_path / ".fill_budget.json"
    p.write_text(payload)
    assert _slack._load_budget(p) == 0


def test_budget_future_timestamp_resets(tmp_path: Path) -> None:
    """Clock skew, or a run_dir copied from another host."""
    p = tmp_path / ".fill_budget.json"
    ahead = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=2)
    p.write_text(json.dumps({"count": 9, "updated": ahead.isoformat()}))
    assert _slack._load_budget(p) == 0


def test_budget_fresh_legacy_state_is_honoured(tmp_path: Path) -> None:
    """State in the pre-expiry format (no `updated` field) must not be
    silently zeroed: an in-flight loop upgrading mid-run keeps its count.
    Its mtime is seconds old, so it is not stale."""
    p = tmp_path / ".fill_budget.json"
    p.write_text(json.dumps({"count": 4}))
    assert _slack._load_budget(p) == 4


def test_budget_old_legacy_state_expires_by_mtime(tmp_path: Path) -> None:
    """The migration case: the OLD counter never reset, so a large stale
    count is exactly what a pre-upgrade file holds. Without an `updated`
    field to age it, fall back to the file's mtime -- otherwise a
    months-old 80 trips the breaker on the first measurement after upgrade."""
    import os
    p = tmp_path / ".fill_budget.json"
    p.write_text(json.dumps({"count": 80}))
    old = (_dt.datetime.now(_dt.timezone.utc)
           - _dt.timedelta(hours=_slack.BUDGET_STALE_AFTER_HOURS + 5)).timestamp()
    os.utime(p, (old, old))
    assert _slack._load_budget(p) == 0


# --------------------------------------------------------------------------
# slack: the breaker must see the MERGED verdict, not slack's alone
# --------------------------------------------------------------------------

# A poster tuned so every section is FULL (fullRatio ~0.909) with no figures,
# so `slack` alone reports a fully clean verdict -- while polish's ORPHAN gate
# fails on the trailing arrow. That combination is the whole point: budget
# accounting keyed on slack's verdict alone would clear the count every round
# and the breaker could never fire for a poster the loop cannot fix.
_ORPHAN_LINE = ('<p>Consistency regularization along the probability-flow path '
                'keeps the student aligned with the teacher marginal at every '
                'noise scale.</p>')
_CONVERGED_BUT_ORPHANED = """<!doctype html><html><head><meta charset="utf-8">
<style>
  @page { size: 20in 10in; margin: 0; }
  html,body { margin:0; padding:0; width:1920px; height:960px;
              font-family:sans-serif; }
  .poster { width:1920px; height:960px; display:flex; flex-direction:column; }
  .columns { display:grid; grid-template-columns:1fr; flex:1 1 auto; }
  .col { display:flex; flex-direction:column; }
  .section { height:900px; padding:0; overflow:hidden; }
  p { font-size:28px; line-height:1.4; margin:0 0 10px 0; }
  .stat { font-size:40px; margin:0; }
</style></head><body>
<div class="poster"><div class="columns"><div class="col">
  <div class="section" data-section="only">
    <div class="stat">accuracy 1.18-1.30x &uarr;</div>
""" + "\n".join([_ORPHAN_LINE] * 16) + """
  </div>
</div></div></div>
</body></html>"""


def _slack_args(html: Path, **over):
    ns = argparse.Namespace(
        html=str(html), canvas=None, settle_ms=120, mathjax_timeout_ms=15000,
        json=False, json_out=None, strict=False, max_iterations=2,
        reset_budget=False, with_polish=True,
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def orphaned_poster(tmp_path: Path, chromium) -> Path:
    """Depends on `chromium`, NOT `page`: cmd_slack opens its own browser."""
    f = tmp_path / "poster.html"
    f.write_text(_CONVERGED_BUT_ORPHANED)
    return f


def _count(html: Path) -> int:
    p = html.parent / "assets" / "meta" / ".fill_budget.json"
    return _slack._load_budget(p)


def test_strict_polish_failure_counts_against_the_breaker(
        orphaned_poster: Path, capsys) -> None:
    """slack is CONVERGED here, so accounting on its verdict alone would
    clear the budget every round -- an unbounded `--with-polish --strict`
    loop, which is exactly what the breaker is supposed to bound."""
    codes = []
    for _ in range(3):
        codes.append(_slack.cmd_slack(_slack_args(orphaned_poster, strict=True)))
        capsys.readouterr()
    assert _count(orphaned_poster) == 3
    assert codes[-1] == 3           # breaker tripped (2 allowed, 3rd trips)
    assert codes[0] == 1            # earlier rounds are ordinary gate failures


def test_advisory_polish_does_not_burn_budget(
        orphaned_poster: Path, capsys) -> None:
    """Without --strict polish is advisory, so the same poster IS converged:
    the count must clear and the command must succeed."""
    for _ in range(2):
        assert _slack.cmd_slack(_slack_args(orphaned_poster)) == 0
        capsys.readouterr()
    assert _count(orphaned_poster) == 0


def test_converged_run_clears_budget_even_when_breaker_disabled(
        orphaned_poster: Path, capsys) -> None:
    """A converged measurement clears the count -- the documented contract,
    with no exception for `--max-iterations 0`. Seed a real count first --
    without that, a regression to "disabled means don't touch the file" would
    still pass, since there would be nothing to clear."""
    meta = orphaned_poster.parent / "assets" / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    _slack._write_budget(meta / ".fill_budget.json", 7)
    assert _count(orphaned_poster) == 7                  # seeded

    _slack.cmd_slack(_slack_args(orphaned_poster, max_iterations=0))
    capsys.readouterr()
    assert _count(orphaned_poster) == 0


def test_polish_output_still_follows_the_slack_report(
        orphaned_poster: Path, capsys) -> None:
    """The polish gates now run BEFORE the breaker decision so their verdict
    can feed it, but their output is buffered and replayed here -- readers
    must not see it move above the slack report."""
    _slack.cmd_slack(_slack_args(orphaned_poster, max_iterations=0))
    out = capsys.readouterr().out
    assert out.index("verdict:") < out.index("=== POLISH")
    assert "ORPHAN" in out


def test_json_mode_keeps_stdout_pure_json(
        orphaned_poster: Path, capsys) -> None:
    """--json pipes to another tool: the buffered polish output must be
    dropped, with only the exit code and report["polish"] carrying its
    verdict."""
    rc = _slack.cmd_slack(
        _slack_args(orphaned_poster, json=True, strict=True, max_iterations=0))
    out = capsys.readouterr().out
    assert "=== POLISH" not in out and "ORPHAN" not in out
    payload = json.loads(out[out.index("{"):])
    assert payload["polish"] == {"ran": True, "failed": True,
                                 "skippedReason": None}
    assert rc == 1                  # polish still gated the exit


def test_breaker_round_still_shows_why_it_tripped(
        orphaned_poster: Path, capsys) -> None:
    """The breaker returns before _finish_ok, so the round that trips it must
    still replay the polish warnings that caused it -- this is the round a
    freshly compacted context is most likely to read first, and a bare banner
    over a clean slack verdict is no evidence at all."""
    for _ in range(2):
        _slack.cmd_slack(_slack_args(orphaned_poster, strict=True))
        capsys.readouterr()
    rc = _slack.cmd_slack(_slack_args(orphaned_poster, strict=True))
    captured = capsys.readouterr()
    assert rc == 3
    assert "ORPHAN" in captured.out
    assert "CIRCUIT BREAKER" in captured.err


def test_strict_polish_fail_stays_on_stderr(
        orphaned_poster: Path, capsys) -> None:
    """report_polish writes its FAIL line to STDERR. It is buffered now -- but
    replayed to STDERR, not folded into stdout: moving it would silently break
    anyone grepping stderr for it."""
    _slack.cmd_slack(_slack_args(orphaned_poster, strict=True,
                                 max_iterations=0))
    captured = capsys.readouterr()
    assert "[polish] FAIL" in captured.err       # still stderr, as before
    assert "[polish] FAIL" not in captured.out   # not folded into stdout
    # and the human report it belongs to is replayed after the slack verdict
    assert captured.out.index("verdict:") < captured.out.index("=== POLISH")


def test_polish_streams_interleave_correctly_when_merged(
        orphaned_poster: Path) -> None:
    """The real ordering contract, which capsys cannot test: it collects the
    two streams separately, so it passes with or without the flush. Only a
    genuinely merged pipe (`>log 2>&1`, what a user actually types) shows
    whether stdout was flushed before stderr was written."""
    import subprocess
    cli = SKILL / "scripts" / "check_poster.py"
    proc = subprocess.run(
        [sys.executable, str(cli), "slack", str(orphaned_poster),
         "--with-polish", "--strict", "--max-iterations", "0",
         "--settle-ms", "120"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=180,
    )
    merged = proc.stdout
    # Assert rather than skip: the `chromium` fixture already established that
    # the environment works, so a missing heading here means the CLI failed or
    # stopped running polish -- exactly the regression this test should catch,
    # not a reason to go green.
    assert "=== POLISH" in merged, (
        f"polish never ran (rc={proc.returncode}); output:\n{merged}"
    )
    # The polish report must appear after the slack verdict, and its stderr
    # FAIL line after the report body it belongs to -- not hoisted above both
    # by an unflushed stdout buffer.
    assert merged.index("verdict:") < merged.index("=== POLISH")
    assert merged.index("=== POLISH") < merged.index("[polish] FAIL")


# --- --strict must not pass a polish gate that never ran ------------------

_NO_ROLES = """<!doctype html><html><head><meta charset="utf-8"><style>
  @page { size: 20in 10in; margin: 0; }
  html,body { margin:0; padding:0; width:1920px; height:960px; }
  .columns { display:grid; grid-template-columns:1fr; }
  .col { display:flex; flex-direction:column; }
  .section { height:900px; }
</style></head><body>
<!-- .col/.section resolve for slack, but NOTHING resolves as a poster -->
<div class="columns"><div class="col">
  <div class="section" data-section="only"><p>body</p></div>
</div></div>
</body></html>"""


def test_strict_fails_when_polish_could_not_run(tmp_path: Path, chromium,
                                                capsys) -> None:
    """`--with-polish --strict` asks for the polish gates to bind. If they
    never ran there is no evidence they would pass, so reporting success is
    a fail-open. Previously `polish_collected is None` returned 0."""
    f = tmp_path / "poster.html"
    f.write_text(_NO_ROLES)
    rc = _slack.cmd_slack(_slack_args(f, strict=True, max_iterations=0))
    out = capsys.readouterr().out
    assert rc == 1
    assert "POLISH: NOT RUN" in out


def test_advisory_mode_still_tolerates_a_skipped_polish(
        tmp_path: Path, chromium, capsys) -> None:
    """Without --strict, --with-polish stays the opt-in convenience it was:
    a poster it cannot measure must not fail the fill gate."""
    f = tmp_path / "poster.html"
    f.write_text(_NO_ROLES)
    assert _slack.cmd_slack(_slack_args(f, max_iterations=0)) == 0


# A poster the STATIC scan reads as measurable but the browser does not: the
# only `.section` declares `column`, so the regex (which cannot tell that an
# element already carries a role) counts it as a card while the shim leaves
# it alone and no card exists at render time.
_STATIC_LIES = """<!doctype html><html><head><meta charset="utf-8"><style>
  @page { size: 20in 10in; margin: 0; }
  html,body { margin:0; padding:0; width:1920px; height:960px; }
  .poster { width:1920px; height:960px; }
</style></head><body>
<div class="poster">
  <div class="section" data-measure-role="column"><p>body</p></div>
</div>
</body></html>"""


def test_static_scan_can_overcount_cards(tmp_path: Path) -> None:
    """Pins WHY the live check is needed, not that the estimate is exact."""
    f = tmp_path / "poster.html"
    f.write_text(_STATIC_LIES)
    assert _preflight.has_required_roles_in_html(f)["card"] > 0


# Every element declares an EMPTY role. The shim skips them (hasAttribute is
# true), and `""` is not a role any gate selects -- so no required role is
# present even though every element carries the attribute.
_EMPTY_ROLE_ATTRS = """<!doctype html><html><head><meta charset="utf-8"><style>
  @page { size: 20in 10in; margin: 0; }
  html,body { margin:0; padding:0; width:1920px; height:960px; }
  .poster { width:1920px; height:960px; }
</style></head><body>
<div class="poster" data-measure-role="">
  <div class="col" data-measure-role="">
    <div class="section" data-measure-role=""><p>body</p></div>
  </div>
</div>
</body></html>"""


# Roles padded with whitespace. `[data-measure-role="card"]` is an EXACT
# attribute match and does not select ` card `, so every gate finds nothing --
# but a count that normalised the value would report all three roles present
# and wave the poster through.
_PADDED_ROLE_ATTRS = """<!doctype html><html><head><meta charset="utf-8"><style>
  @page { size: 20in 10in; margin: 0; }
  html,body { margin:0; padding:0; width:1920px; height:960px; }
  .poster { width:1920px; height:960px; }
</style></head><body>
<div class="poster" data-measure-role=" poster ">
  <div class="col" data-measure-role=" column ">
    <div class="section" data-measure-role=" card "><p>body</p></div>
  </div>
</div>
</body></html>"""


def test_count_roles_means_what_the_gate_selectors_mean(page) -> None:
    """The counts exist to decide whether the gates have anything to select,
    so they must agree with the gates' exact attribute selectors -- trimming
    would report a `card` that `[data-measure-role="card"]` cannot find."""
    page.set_content(_PADDED_ROLE_ATTRS)
    live = _render.count_roles(page)
    assert live.get("card", 0) == 0
    selected = page.evaluate(
        """() => document.querySelectorAll(
                   '[data-measure-role="card"]').length"""
    )
    assert selected == live.get("card", 0)


@pytest.mark.parametrize("markup", [_STATIC_LIES, _EMPTY_ROLE_ATTRS,
                                    _PADDED_ROLE_ATTRS])
def test_standalone_polish_refuses_when_nothing_resolves_live(
        tmp_path: Path, chromium, capsys, markup: str) -> None:
    """The static scan says these posters have cards; the browser says they
    have none. polish must not run its gates over zero cards and report
    success -- that is a silent green on a poster nobody checked. The
    empty-attribute case pins that a role no gate can select counts as
    absent, not as present-but-blank; the padded case pins that the count is
    not normalised out of agreement with the selectors."""
    _assert_polish_refuses(tmp_path, markup, capsys)


def test_polish_refuses_when_the_role_query_itself_fails(
        tmp_path: Path, chromium, capsys, monkeypatch) -> None:
    """An EMPTY live map means either "nothing resolved" or "the query
    failed", and the two are indistinguishable -- so both must fail closed.
    This is the case the empty/padded markup above does NOT pin: those return
    `{"": 3}` / `{" card ": 1}`, which are truthy, so a regression to
    `if live_missing and live_roles:` would still reject them. Only a
    genuinely empty map separates the two guards."""
    monkeypatch.setattr(_render, "count_roles", lambda page: {})
    _assert_polish_refuses(tmp_path, _CONVERGED_BUT_ORPHANED, capsys)


def _assert_polish_refuses(tmp_path: Path, markup: str, capsys) -> None:
    f = tmp_path / "poster.html"
    f.write_text(markup)
    pargs = _polish.default_polish_args()
    pargs.strict = True
    for k, v in (("html", str(f)), ("canvas", None), ("settle_ms", 120),
                 ("mathjax_timeout_ms", 15000)):
        setattr(pargs, k, v)
    rc = _polish.cmd_polish(pargs)
    assert rc == 2
    assert "resolves no" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Class->role fallback: every required role must resolve at RENDER time
# --------------------------------------------------------------------------

_PORTRAIT = SKILL / "assets" / "layouts_portrait" / "full.html"

_MIXED = ('<div class="poster"><div class="method-hero" '
          'data-measure-role="column"><div class="section">x</div></div>'
          '<div class="col"><div class="section">y</div></div></div>')
_CLASSES = ('<div class="poster"><div class="col">'
            '<div class="section">x</div></div></div>')
_EXPLICIT = ('<div data-measure-role="poster"><div data-measure-role="column">'
             '<div data-measure-role="card">x</div></div></div>')


@pytest.mark.parametrize("layout", sorted(
    (SKILL / "assets").rglob("layouts*/[!_]*.html")))
def test_every_shipped_layout_satisfies_polish_precondition(
        layout: Path) -> None:
    """cmd_polish hard-fails (exit 2) unless poster+card+column all resolve.
    The portrait layout declares only `column`, so an all-or-nothing
    fallback reported poster=0/card=0 and failed a template we ship."""
    counts = _preflight.has_required_roles_in_html(layout)
    missing = [r for r in ("poster", "card", "column") if counts.get(r, 0) == 0]
    assert not missing, f"{layout.name} would exit 2: missing {missing}"


def test_declared_role_is_additive_not_exclusive(tmp_path: Path) -> None:
    """A declared role must not switch the fallback OFF for that role.
    Portrait declares `column` on .method-hero to ADD a column no class
    matches (mirroring slack's `.col, .mid-wide, [role=column]` union); if
    that one attribute suppressed the shim, the ordinary `.col`s would go
    unmeasured by every role-keyed gate."""
    f = tmp_path / "m.html"
    f.write_text(_MIXED)
    counts = _preflight.has_required_roles_in_html(f)
    assert counts["column"] == 2        # the declared one AND the .col
    assert counts["poster"] == 1
    assert counts["card"] == 2


@pytest.mark.parametrize("html", [_MIXED, _CLASSES, _EXPLICIT])
def test_runtime_shim_resolves_required_roles(page, html: str) -> None:
    """Whatever mix of declared roles and conventional classes a poster
    uses, all three required roles must exist once the shim has run --
    otherwise polish refuses (or worse, measures nothing)."""
    page.set_content(html)
    _render.inject_class_fallback_roles(page)
    live = _render.count_roles(page)
    for role in ("poster", "column", "card"):
        assert live.get(role, 0) > 0, f"{role} unresolved for {html[:40]}"


def test_fully_explicit_document_is_left_alone(page) -> None:
    """A poster that owns all its roles must not be rewritten by the shim."""
    page.set_content(_EXPLICIT)
    assert _render.inject_class_fallback_roles(page) is False


def test_shim_does_not_overwrite_a_declared_role(page) -> None:
    """`.method-hero` is a `.col`-less column: the shim may add poster/card
    around it but must never re-tag it. The per-element guard -- not a
    per-role bail -- is what protects author intent."""
    page.set_content(_MIXED)
    _render.inject_class_fallback_roles(page)
    assert page.evaluate(
        """() => document.querySelector('.method-hero')
                   .getAttribute('data-measure-role')"""
    ) == "column"


def test_ordinary_cols_still_get_a_role_alongside_a_declared_one(page) -> None:
    """The regression a per-role bail would cause: portrait declares one
    `column` on .method-hero, so skipping the column fallback would leave its
    real `.col`s roleless and invisible to every role-keyed gate (Gate C's
    space-between scan queries `[data-measure-role="column"]` only)."""
    page.set_content(_MIXED)
    _render.inject_class_fallback_roles(page)
    assert page.evaluate(
        """() => document.querySelectorAll(
                   '[data-measure-role="column"]').length"""
    ) == 2      # .method-hero (declared) AND .col (injected)


# --------------------------------------------------------------------------
# polish Gate A: a zero-natural-size vector figure still gets judged
# --------------------------------------------------------------------------

def _card_with(src: str) -> str:
    return (
        '<div class="poster"><div class="col">'
        '<div class="section" style="width:800px;height:600px">'
        f'<img src="{src}" style="width:120px;height:90px">'
        "</div></div></div>"
    )


def _natural(page, src: str) -> tuple[float, float]:
    page.set_content(_card_with(src))
    page.wait_for_timeout(150)
    _render.inject_class_fallback_roles(page)
    figs = _polish.collect_polish_data(page)["data"]["figures"]
    assert figs, "figure not collected"
    return figs[0]["natural_w"], figs[0]["natural_h"]


def _svg_uri(body: str) -> str:
    return "data:image/svg+xml;utf8," + body


_SVG_VIEWBOX = _svg_uri(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 100'>"
    "<rect width='200' height='100'/></svg>"
)
_SVG_NO_INTRINSIC = _svg_uri(
    "<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>"
)
_SVG_CORRUPT = _svg_uri("this is not svg at all")


@pytest.mark.parametrize("src", [_SVG_VIEWBOX, _SVG_NO_INTRINSIC])
def test_valid_svg_never_reports_zero_natural_size(page, src: str) -> None:
    """The premise the dropped `is_svg` exemption rested on -- "a vector
    image can legitimately report zero natural size" -- is false in the only
    renderer these gates run in. Chromium resolves a viewBox-less <img>'d SVG
    to the 300x150 CSS default replaced size. If this ever fails, the
    exemption needs reinstating and FIG/BROKEN needs an img.decode() probe
    instead."""
    nw, nh = _natural(page, src)
    assert (nw, nh) == (300, 150)


def test_corrupt_svg_reports_zero_and_must_be_called_broken(page) -> None:
    """The flip side: zero natural size on an SVG means it FAILED, so the old
    extension-based exemption only ever white-printed broken vector art."""
    assert _natural(page, _SVG_CORRUPT) == (0, 0)


def test_broken_svg_is_reported_broken_not_narrow(page, capsys) -> None:
    """End-to-end through the real reporter: a corrupt SVG must surface as
    FIG/BROKEN. Previously `is_svg` skipped the check and the figure passed
    Gate A silently."""
    page.set_content(_card_with(_SVG_CORRUPT))
    page.wait_for_timeout(150)
    _render.inject_class_fallback_roles(page)
    collected = _polish.collect_polish_data(page)
    _polish.report_polish(collected, _polish.default_polish_args(),
                          Path("poster.html"))
    out = capsys.readouterr().out
    assert "FIG/BROKEN" in out
    assert "FIG/NARROW" not in out      # never measure a blank image for fill


def test_valid_svg_is_not_called_broken(page, capsys) -> None:
    """The safety property of dropping the exemption: real vector art must
    still pass FIG/BROKEN untouched. It does, because Chromium gives it a
    non-zero natural size -- the check needs no knowledge that it is an SVG."""
    page.set_content(_card_with(_SVG_VIEWBOX))
    page.wait_for_timeout(150)
    _render.inject_class_fallback_roles(page)
    collected = _polish.collect_polish_data(page)
    _polish.report_polish(collected, _polish.default_polish_args(),
                          Path("poster.html"))
    assert "FIG/BROKEN" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# polish Gate C: CARD/INNER-VOID
# --------------------------------------------------------------------------

_CARD_CSS = ("<style>.poster{width:900px}"
             ".section{height:800px;display:flex;flex-direction:column}"
             ".section p{margin:0 0 0.5em 0}</style>")


def _inner_voids(page, html: str) -> list[dict]:
    page.set_content(_CARD_CSS + html)
    _render.inject_class_fallback_roles(page)
    data = _polish.collect_polish_data(page)["data"]
    return [
        iv for iv in data["innerVoids"]
        if iv["card_h"] > 0
        and iv["excess"] > _polish.DEFAULT_MIN_CARD_INNER_VOID_PX
        and iv["excess"] / iv["card_h"] > _polish.DEFAULT_MAX_CARD_INNER_VOID
    ]


def test_inner_void_fires_on_a_bottom_pinned_tail(page) -> None:
    """The case the gate exists for: an equal-height row's short card pins
    its tail with margin-top:auto, so CARD/TRAILING reads ~0."""
    voids = _inner_voids(page, (
        '<div class="poster"><div class="col">'
        '<div class="section" data-section="key-result">'
        '<p>short</p><p style="margin-top:auto">pinned</p>'
        "</div></div></div>"
    ))
    assert len(voids) == 1
    assert voids[0]["section"] == "key-result"


@pytest.mark.parametrize("jc", ["space-between", "space-around",
                                "space-evenly"])
def test_inner_void_fires_on_every_space_distributing_card(page,
                                                           jc: str) -> None:
    """CARD/TRAILING skips any card whose justify-content distributes space,
    which left those cards with no void check at all. `space-around` and
    `space-evenly` also reserve space at the BOTTOM, so nothing is flush with
    the content edge -- they must bypass the tail-pinned precondition, or
    this gate re-opens the very hole it was added to close."""
    voids = _inner_voids(page, (
        '<div class="poster"><div class="col">'
        f'<div class="section" data-section="scan" style="justify-content:{jc}">'
        "<p>top</p><p>bottom</p>"
        "</div></div></div>"
    ))
    assert len(voids) == 1


def test_inner_void_silent_on_a_margin_spaced_card(page) -> None:
    """paper2poster cards space children with margins, not row-gap, so the
    stated gap is 0 and every normal paragraph gap reads as `excess`. The
    ratio+px floors must keep an ordinary rhythm quiet."""
    assert _inner_voids(page, (
        '<div class="poster"><div class="col">'
        '<div class="section" data-section="ok" style="height:auto">'
        "<p>one</p><p>two</p><p>three</p>"
        "</div></div></div>"
    )) == []


@pytest.mark.parametrize("style", [
    "display:block",                     # justify-content is inert entirely
    "display:flex;flex-direction:row",   # justify-content runs horizontally
])
def test_inner_void_ignores_space_between_off_the_vertical_axis(
        page, style: str) -> None:
    """`justify-content: space-between` only distributes downward on a flex
    COLUMN. Computed style reports the declared value on a block or row card
    too, so waiving the tail-pin check on the string alone would re-admit the
    short-card heading false positive on cards that distribute nothing
    vertically.

    (`display:grid` is deliberately not covered here: `align-content` defaults
    to stretch, so a grid card really does deal leftover space into its rows
    and open a genuine gap -- it reaches the gate through the ordinary
    pinned-tail path, not this bypass, so it is not a case this test can
    isolate.)"""
    assert _inner_voids(page, (
        '<style>.section h2{font-size:60pt;margin:0 0 0.45em 0;line-height:1.1}'
        "</style>"
        '<div class="poster"><div class="col">'
        f'<div class="section" data-section="s" style="{style};'
        'justify-content:space-between;height:200px">'
        "<h2>T</h2><p>body</p>"
        "</div></div></div>"
    )) == []


def test_inner_void_silent_on_production_heading_rhythm(page) -> None:
    """The false positive this gate must not have. `.section h2` ships at
    60pt with `margin: 0 0 0.45em` (assets/styles/*.css), a real 36px gap
    under EVERY heading. A top-packed card must stay quiet: its content
    simply stops early, which is CARD/TRAILING's job, not this gate's.
    Guarded by the tail-pinned requirement, so it holds at any card height
    -- including a short card where 36px would clear the ratio."""
    voids = _inner_voids(page, (
        '<style>.section h2{font-size:60pt;margin:0 0 0.45em 0;line-height:1.1}'
        "</style>"
        '<div class="poster"><div class="col">'
        '<div class="section" data-section="short" style="height:400px">'
        "<h2>Problem</h2><p>one line of body copy</p>"
        "</div></div></div>"
    ))
    assert voids == []


def test_inner_void_ignores_absolutely_positioned_children(page) -> None:
    """The floating Listen button sits at the card bottom but is not flow
    content -- counting it would mask the void above it."""
    assert _inner_voids(page, (
        '<div class="poster"><div class="col">'
        '<div class="section" data-section="ab" style="position:relative;'
        'height:auto"><p>one</p><p>two</p>'
        '<button style="position:absolute;bottom:0">Listen</button>'
        "</div></div></div>"
    )) == []


def test_inner_void_merges_side_by_side_rows(page) -> None:
    """A block clearing a tall floated sibling is not a void: the gap must
    be measured from the row's tallest member, not its shortest."""
    assert _inner_voids(page, (
        '<div class="poster"><div class="col">'
        '<div class="section" data-section="row" style="height:auto;'
        'display:block"><div style="overflow:hidden">'
        '<div style="float:left;height:400px;width:100px">tall</div>'
        '<div style="height:20px">short</div></div><p>after</p>'
        "</div></div></div>"
    )) == []
