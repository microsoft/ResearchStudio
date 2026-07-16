"""Shared Playwright launch + page-settle helpers.

Used by the Chromium-driven commands -- ``slack``, ``polish``, and the
standalone ``render_poster`` script. Centralises:

1. Print-emulated Chromium context at the correct viewport.
2. MathJax detection + bounded typeset wait (so a stuck CDN can't
   hang the script forever).
3. ``document.fonts.ready`` + two RAFs + a fixed settle ms — so
   the layout is locked before any geometry is read.
4. A sanity check that catches the "page has ``$…$`` TeX in body text
   but no rendered ``<mjx-container>``" case — MathJax never ran
   (CDN blocked, script error, …). Measurement / polish must NOT
   silently pass against a raw-TeX layout.

The ``settle_page`` helper returns a :class:`SettleResult` with the raw
status flags. ``slack``/``polish`` treat MathJax issues as hard fails;
``render_poster`` warns and continues (rendering raw-TeX is at least
visible to the user, whereas a silent measure PASS isn't).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .textutil import ascii_safe


def bundled_mathjax_path() -> Path | None:
    """Absolute path to the skill's bundled MathJax ``tex-svg.js``.

    The layouts load MathJax from a jsdelivr CDN by default (works when the
    machine is online). On a restricted/offline host that fetch fails
    intermittently, so formulas render on some posters and not others (the
    "Figure 20 renders, Figure 21 doesn't" symptom). We ship a single
    self-contained ``tex-svg.js`` (SVG output inlines the math fonts as
    paths — no separate woff files needed) and ``open_print_emulated_page``
    routes the CDN request to it, making typeset deterministic and offline-
    safe. Returns None if the bundle is missing (route then falls back to
    the network, preserving the old behavior).
    """
    p = Path(__file__).resolve().parents[2] / "assets" / "mathjax" / "tex-svg.js"
    return p if p.is_file() else None


def route_mathjax_local(page) -> bool:
    """Intercept the MathJax CDN request and fulfill it from the bundled
    ``tex-svg.js``. Must be called BEFORE navigation (open_print_emulated_page
    does this). Returns True if a local bundle was found and the route
    registered. The glob ``**/tex-svg.js`` matches the CDN path
    ``/npm/mathjax@3/es5/tex-svg.js`` as well as any local ``mathjax/tex-svg.js``
    override, so a poster.html pointing at either resolves to the bundle.
    """
    mj = bundled_mathjax_path()
    if mj is None:
        return False

    def _handler(route):
        try:
            route.fulfill(path=str(mj), content_type="application/javascript")
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    try:
        page.route("**/tex-svg.js", _handler)
        return True
    except Exception:
        return False


def bundled_katex_dir() -> Path | None:
    """Absolute path to the skill's bundled KaTeX mirror (css/js/woff2 fonts)."""
    p = Path(__file__).resolve().parents[2] / "assets" / "katex"
    return p if p.is_dir() else None


def route_katex_local(page) -> bool:
    """Intercept KaTeX CDN requests (css / js / auto-render / woff2 fonts) and
    fulfill them from the bundled ``assets/katex/`` mirror, so KaTeX-typeset
    posters render offline/deterministically like MathJax. Matches any
    ``katex@<ver>/dist/**`` URL and maps the path tail into the mirror
    (``contrib/`` flattened to top level). Must be called BEFORE navigation.
    Returns True if the mirror exists and the route registered."""
    kdir = bundled_katex_dir()
    if kdir is None:
        return False
    ctypes = {".css": "text/css", ".js": "application/javascript",
              ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf"}

    def _handler(route):
        try:
            m = re.search(r"/dist/(.+)$", route.request.url)
            tail = (m.group(1) if m else "").split("?")[0].replace("contrib/", "")
            f = kdir / tail
            if tail and f.is_file():
                route.fulfill(path=str(f),
                              content_type=ctypes.get(f.suffix, "application/octet-stream"))
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    try:
        page.route("**/katex@*/dist/**", _handler)
        return True
    except Exception:
        return False


@dataclass
class SettleResult:
    mathjax_intended: bool
    """The page intended to load MathJax — either a ``<script src=…mathjax…>``
    tag is present or ``window.MathJax`` config was set. Used to gate the
    ``tex_without_mathjax`` failure: a poster that documents TeX syntax in
    prose without ever loading MathJax is a perfectly valid use case and
    must NOT trip the sanity check."""

    has_mathjax: bool
    """``window.MathJax.startup.promise`` was defined at settle time
    (MathJax actually initialized)."""

    mathjax_status: str
    """One of ``'ok'``, ``'timeout'``, ``'error'``, ``'not-needed'``."""

    mathjax_error: str | None
    """Exception message if ``mathjax_status == 'error'``, else None."""

    tex_without_mathjax: bool
    """Body innerText has TeX delimiters but no ``<mjx-container>`` rendered.
    Only counted as a failure when ``mathjax_intended`` is True (otherwise
    the ``$…$`` is most likely prose, not math)."""


# JS shim: where the poster uses paper2poster's conventional class names
# (.poster, .col, .section, .titlebar/.banner, .footer-strip/.footer)
# but the element carries no `data-measure-role`, copy the role over from
# the class so `slack`/`polish` can reason about it. Explicit markup wins
# PER ELEMENT: an element that declares a role is never re-tagged, but a
# declared role elsewhere does not switch the shim off (see the comment
# in _COMPAT_ROLES_JS). Paper2layout-style cards are `.section`, not
# `.card`; we map both. Headlines/titlebar map to `banner`/`header` so
# the alignment spread isn't anchored by the title strip.
_COMPAT_ROLES_JS = r"""
() => {
  // Fill in a role for every conventional-class element that does not
  // already declare one. This used to bail entirely the moment ANY
  // data-measure-role existed anywhere in the document, which broke on
  // `assets/layouts_portrait/full.html`: it declares exactly one
  // (`column`, on .method-hero) and leaves poster/columns/cards to
  // classes, so the shim did nothing, poster+card resolved to zero, and
  // `polish` hard-failed its "poster/columns/cards required" precondition
  // on a template this skill ships (while `slack --with-polish` silently
  // skipped the polish pass).
  //
  // An explicit role is ADDITIVE, not exclusive -- this mirrors slack's own
  // selector (`.columns > .col, .columns > .mid-wide,
  // [data-measure-role="column"]`), where .method-hero's declared role adds
  // a column that no class matches, rather than declaring itself the only
  // one. So do NOT skip a role just because some element already has it:
  // that would leave portrait's ordinary `.col`s unmeasured by every gate
  // that keys off the role (Gate C's space-between scan, for one). The
  // per-element `hasAttribute` guard below is what protects author intent:
  // an element that declares a role is never re-tagged.
  let injected = false;
  const set = (sel, role) => {
    document.querySelectorAll(sel).forEach(el => {
      if (!el.hasAttribute('data-measure-role')) {
        el.setAttribute('data-measure-role', role);
        injected = true;
      }
    });
  };
  set('.poster', 'poster');
  set('.titlebar, header.titlebar, .banner', 'banner');
  set('.columns > .col, .col', 'column');
  // Paper2layout cards are `.section` blocks inside each `.col`.
  set('.col > .section, .section', 'card');
  set('.footer-strip', 'footer-strip');
  set('footer, .footer', 'footer');
  return injected;
}
"""


def inject_class_fallback_roles(page) -> bool:
    """Add `data-measure-role` attributes, from conventional class names,
    to elements that do not already declare one. Additive: a document that
    declares some roles still gets the shim for the elements it left
    untagged. Returns True if any were injected."""
    try:
        return bool(page.evaluate(_COMPAT_ROLES_JS))
    except Exception:
        return False


def count_roles(page) -> dict[str, int]:
    """Exact per-role element counts on the LIVE page, after the shim has run.

    ``preflight.has_required_roles_in_html`` only estimates from the file
    text, so it is only safe as a cheap pre-browser fail-fast. Once the
    browser is open there is no reason to guess: a gate that needs to know
    whether the poster really has cards should ask the DOM.

    Counts are keyed on the RAW attribute value, so they mean exactly what
    the gates' `[data-measure-role="…"]` selectors mean -- see the note in the
    query below.

    A required role is ABSENT whenever its key is missing -- which covers
    both a poster that declares nothing and one whose values do not match
    (an empty attribute keys ``""``, a padded one keys ``" card "``).
    ``{}`` additionally means the query itself failed. Callers must FAIL
    CLOSED on all of these -- a gate that cannot confirm the poster has
    anything to measure has no basis for passing it, and conflating
    "unknown" with "fine" is how an unmeasured poster earns a silent green.
    """
    try:
        return page.evaluate(
            """() => {
                 // Key on the RAW attribute value -- no trim, no filtering.
                 // Every gate selects with an exact attribute match
                 // (`[data-measure-role="card"]`), which does NOT match
                 // ` card `. Normalising here would report a role the gates
                 // then fail to select, which is the fail-open this function
                 // exists to prevent: counts must mean what the selectors mean.
                 const o = {};
                 document.querySelectorAll('[data-measure-role]').forEach(e => {
                   const r = e.getAttribute('data-measure-role') || '';
                   o[r] = (o[r] || 0) + 1;
                 });
                 return o;
               }"""
        ) or {}
    except Exception:
        return {}


def open_print_emulated_page(p, viewport_px: tuple[int, int]):
    """Launch headless Chromium, open a context+page at the viewport,
    emulate print media. Returns ``(browser, ctx, page)``.

    Print emulation is set BEFORE navigation by the caller (via
    ``page.emulate_media``), so MathJax typesets against ``@media print``
    layout from the start. Without that, the screen-mode ``--u`` value
    leaks in and measurement is unreliable.
    """
    w, h = viewport_px
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    # Serve MathJax + KaTeX from the bundled copies instead of the CDN so typeset
    # is deterministic on offline/restricted hosts (registered BEFORE goto).
    route_mathjax_local(page)
    route_katex_local(page)
    page.emulate_media(media="print")
    page.set_viewport_size({"width": w, "height": h})
    return browser, ctx, page


def settle_page(
    page,
    *,
    mathjax_timeout_ms: int = 15000,
    settle_ms: int = 500,
) -> SettleResult:
    """Wait for MathJax, fonts, two RAFs, and an extra fixed ms.

    Returns a :class:`SettleResult` rather than raising — the caller
    decides whether each flag is a hard fail or a soft warning.
    Idempotent on math-free pages: detection is synchronous and the
    typeset wait is skipped when MathJax wasn't loaded.
    """
    # 1a) Did the page INTEND to load MathJax? A <script src="…mathjax…">
    #     tag OR a window.MathJax config object counts. Used to decide
    #     whether stray `$…$` in body text is "math that failed to render"
    #     (intended) vs "prose that happens to mention TeX" (not intended).
    try:
        mathjax_intended = bool(page.evaluate(
            "() => !!(document.querySelector('script[src*=\"mathjax\" i]') "
            "|| (window.MathJax && Object.keys(window.MathJax).length > 0))"
        ))
    except Exception:
        mathjax_intended = False

    # 1b) Did MathJax actually initialise?
    try:
        has_mj = bool(page.evaluate(
            "() => !!(window.MathJax && window.MathJax.startup "
            "&& window.MathJax.startup.promise)"
        ))
    except Exception:
        has_mj = False

    mj_status = "not-needed"
    mj_error: str | None = None

    # 2) If present, bound the typeset wait with Promise.race so a
    #    stuck MathJax can't hang us.
    if has_mj:
        mj_js = (
            f"() => Promise.race(["
            f"  MathJax.startup.promise"
            f"    .then(() => (MathJax.typesetPromise"
            f"      ? MathJax.typesetPromise() : null))"
            f"    .then(() => 'ok'),"
            f"  new Promise(r => setTimeout("
            f"    () => r('timeout'), {mathjax_timeout_ms}))"
            f"])"
        )
        try:
            mj_status = page.evaluate(mj_js) or "timeout"
        except Exception as e:
            mj_status = "error"
            mj_error = str(e)

    # 3) Fonts (best-effort) + two RAFs + fixed settle ms.
    try:
        page.evaluate(
            "() => document.fonts && document.fonts.ready "
            "? document.fonts.ready : null"
        )
    except Exception:
        pass
    page.evaluate(
        "() => new Promise(r => "
        "requestAnimationFrame(() => requestAnimationFrame(r)))"
    )
    page.wait_for_timeout(settle_ms)

    # 4) Sanity check for the silent-fail case: page has TeX in body
    #    text but no rendered mjx-container. Covers all four delimiter
    #    pairs the templates configure (`$...$`, `$$...$$`, `\(...\)`,
    #    `\[...\]`). No length bound — earlier `{1,1500}` regex limits
    #    were Codex-flagged for letting long raw-TeX paste slip past.
    #    `[^$\n]+` (inline) and `[\s\S]+?` (display, non-greedy) avoid
    #    catastrophic backtracking even on multi-paragraph segments.
    try:
        sanity = page.evaluate(
            "() => {"
            "  const has_mjx = "
            "    document.querySelectorAll('mjx-container').length > 0;"
            "  const txt = document.body && document.body.innerText || '';"
            "  const has_dollar  = /\\$[^$\\n]+\\$/.test(txt);"
            "  const has_ddollar = /\\$\\$[\\s\\S]+?\\$\\$/.test(txt);"
            "  const has_paren   = /\\\\\\([\\s\\S]+?\\\\\\)/.test(txt);"
            "  const has_brack   = /\\\\\\[[\\s\\S]+?\\\\\\]/.test(txt);"
            "  return {has_mjx, has_tex: has_dollar || has_ddollar "
            "                          || has_paren  || has_brack};"
            "}"
        )
        tex_without_mathjax = bool(
            sanity.get("has_tex") and not sanity.get("has_mjx")
        )
    except Exception:
        tex_without_mathjax = False

    return SettleResult(
        mathjax_intended=mathjax_intended,
        has_mathjax=has_mj,
        mathjax_status=mj_status,
        mathjax_error=mj_error,
        tex_without_mathjax=tex_without_mathjax,
    )


def hard_fail_on_settle_problems(
    result: SettleResult,
    *,
    mathjax_timeout_ms: int,
) -> str | None:
    """Return a one-line failure message if ``slack`` / ``polish``
    must hard-fail given a settle result, else None.

    Centralised so the two strict gates agree on what counts as a fail.
    """
    if result.mathjax_status == "error":
        return (
            f"MathJax typeset error: {ascii_safe(result.mathjax_error)}. "
            f"Refusing to measure a broken-script page."
        )
    if result.mathjax_status == "timeout":
        return (
            f"MathJax typeset did not finish within "
            f"{mathjax_timeout_ms} ms. Refusing to measure a "
            f"partially typeset poster."
        )
    # Only fail when MathJax was INTENDED to load (script tag or config
    # present) but didn't render anything. A poster that documents TeX
    # syntax in prose without ever loading MathJax is a valid use case.
    if result.mathjax_intended and result.tex_without_mathjax:
        return (
            "page intended to load MathJax (script/config present) "
            "but no rendered <mjx-container> was found despite TeX "
            "delimiters in body text. MathJax likely failed to load "
            "(CDN block? script error?). Refusing to measure raw-TeX "
            "layout."
        )
    return None
