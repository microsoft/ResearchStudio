"""Static HTML lint — runs before any rendering.

Catches the classes of errors that would otherwise burn a render cycle:

- LaTeX residue (``\\ref{`` / ``\\cite{`` / ``\\textbf{`` / lone ``\\ ``).
- Raw ``<`` inside ``$…$`` / ``$$…$$`` / ``\\(…\\)`` / ``\\[…\\]`` —
  MathJax may HTML-parse it as a tag start depending on its loader mode.
- Local ``src="..."`` images that don't exist on disk.
- Missing or unknown ``data-measure-role`` values.

The line numbers reported by preflight refer to **the original HTML file**.
Earlier versions stripped ``<style>`` / ``<script>`` / ``<!-- … -->``
blocks with ``re.sub(... , "")``, which collapsed newlines and shifted
every subsequent line number by N. We now replace each stripped block
with the SAME NUMBER OF NEWLINES, so character offsets after the strip
still map to the same line in the original file.
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .cli_common import eprint as _eprint
from .textutil import ascii_safe


# Roles understood by ``slack`` / ``polish``. Anything outside this
# set in a ``data-measure-role`` attribute is almost certainly a typo
# and would silently be ignored by the geometry pass.
KNOWN_ROLES: set[str] = {
    "poster", "header", "banner", "body",
    "column", "card", "hero", "footer-strip", "footer",
}


# (regex, human description) pairs for LaTeX residue. The patterns are
# scanned over the body with style/script/comments stripped (newline-
# preserved), so each match's character offset still maps to the right
# line in the original file.
LATEX_PATTERNS: list[tuple[str, str]] = [
    (r"\\ref\{",        r"\\ref{...} residue"),
    (r"\\cite\{",       r"\\cite{...} residue"),
    (r"\\textbf\{",     r"\\textbf{...} residue (use <b> or **bold**)"),
    (r"\\textit\{",     r"\\textit{...} residue (use <i> or *italic*)"),
    (r"\\emph\{",       r"\\emph{...} residue"),
    (r"\\section\{",    r"\\section{...} residue"),
    (r"\\label\{",      r"\\label{...} residue"),
    (r"\\begin\{",      r"\\begin{...} residue (use HTML structures)"),
    (r"\\end\{",        r"\\end{...} residue"),
    (r"(?<![\\a-zA-Z])\\\s",
        r"backslash-space '\\ ' (will render literally)"),
]


def _newline_preserving_sub(pattern: str, html: str, *,
                            flags: int = 0) -> str:
    """Replace each match with ``\\n`` * <newline-count-in-match>.

    This preserves line numbers across ``<style>`` / ``<script>`` /
    ``<!-- … -->`` blocks so a regex match's character offset in the
    stripped output still maps to the same line in the original file.
    """
    def keep_newlines(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")
    return re.sub(pattern, keep_newlines, html, flags=flags)


def strip_for_lint(html: str) -> str:
    """Remove ``<style>``, ``<script>``, and HTML comments while
    preserving newline counts. The output is what every preflight rule
    scans against.

    ONE document-order pass over all three so a construct nested inside
    another is consumed as a single unit by whichever delimiter opens
    FIRST. Stripping them in separate passes was a bug: a comment that
    contained ``<script>`` (e.g. ``<!-- ... change the <script> src -->``)
    had its closing ``-->`` eaten by the script pass, after which the
    comment pass ran past it and deleted real body markup downstream --
    the root ``<div data-measure-role="poster">`` went missing, so
    preflight false-failed "missing poster". The combined alternation
    also handles the reverse (a ``<style>``/``<script>`` body containing
    ``-->`` or ``<!--``): the tag opens first, so its whole body is taken
    before the comment rule can match inside it.
    """
    return _newline_preserving_sub(
        r"<!--.*?-->"
        r"|<style[^>]*>.*?</style>"
        r"|<script[^>]*>.*?</script>",
        html, flags=re.DOTALL | re.IGNORECASE,
    )


def find_math_segments(text: str) -> list[tuple[int, int, str]]:
    """Find inline + display math segments. Returns ``[(start, end, body)]``.

    Supports the four delimiter pairs every Claude-poster template
    configures MathJax for:

      - ``$$ … $$`` (display)
      - ``$ … $`` (inline; excludes already-covered ``$$`` regions)
      - ``\\[ … \\]`` (display)
      - ``\\( … \\)`` (inline)
    """
    out: list[tuple[int, int, str]] = []

    def add(s: int, e: int, body: str) -> None:
        out.append((s, e, body))

    # $$...$$
    for m in re.finditer(r"\$\$(.+?)\$\$", text, re.DOTALL):
        add(m.start(), m.end(), m.group(1))
    # \[...\]
    for m in re.finditer(r"\\\[(.+?)\\\]", text, re.DOTALL):
        add(m.start(), m.end(), m.group(1))

    covered = [(s, e) for s, e, _ in out]

    # $...$ — single-line only, not already inside a $$...$$
    for m in re.finditer(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)", text):
        s, e = m.start(), m.end()
        if any(cs <= s < ce or cs < e <= ce for cs, ce in covered):
            continue
        add(s, e, m.group(1))
    # \(...\) — single-line only, not already inside a \[...\]
    for m in re.finditer(r"\\\(([^\n]+?)\\\)", text):
        s, e = m.start(), m.end()
        if any(cs <= s < ce or cs < e <= ce for cs, ce in covered):
            continue
        add(s, e, m.group(1))

    return out


def _delim_label(body: str, segment: str) -> str:
    """Try to label a math segment by its delimiter style in error
    output. ``segment`` is the raw matched text; we look at its first
    char(s)."""
    if segment.startswith("$$") and segment.endswith("$$"):
        return "$$...$$"
    if segment.startswith("$") and segment.endswith("$"):
        return "$...$"
    if segment.startswith("\\["):
        return "\\[...\\]"
    if segment.startswith("\\("):
        return "\\(...\\)"
    return "math"


def cmd_preflight(args: argparse.Namespace) -> int:
    html_path = Path(args.html).resolve()
    if not html_path.exists():
        _eprint(f"ERROR: HTML not found: {ascii_safe(html_path)}")
        return 2
    raw = html_path.read_text(encoding="utf-8", errors="ignore")
    body = strip_for_lint(raw)

    problems: list[str] = []
    warnings: list[str] = []

    # 0) Unclosed <style>/<script>/<!-- --> . strip_for_lint needs the
    #    closer to remove the block, so an unclosed opener SURVIVES in
    #    `body`. A real browser swallows the rest of the document into that
    #    construct -- which makes every post-strip check below (LaTeX scan,
    #    raw-'<' scan, role-presence) untrustworthy: the linter "sees" a
    #    poster div the browser will never render. Fail loudly instead of
    #    silently PASSing on markup we can't actually see past.
    m_open = re.search(r"<!--|<style\b|<script\b", body, re.IGNORECASE)
    if m_open:
        ln = body[: m_open.start()].count("\n") + 1
        problems.append(
            f"L{ln}: unclosed '{ascii_safe(m_open.group(0))}' block -- add "
            "the matching '-->', '</style>', or '</script>'. The browser "
            "would otherwise swallow the rest of the poster into it."
        )

    # 1) LaTeX residue.
    for pat, desc in LATEX_PATTERNS:
        for m in re.finditer(pat, body):
            ln = body[: m.start()].count("\n") + 1
            problems.append(f"L{ln}: {desc} -> '{ascii_safe(m.group(0))}'")

    # 2) Raw '<' inside math segments. The common HTML-parse failure
    #    case is `a<b` / `x<y`. We catch '<' even after a letter/digit.
    #    Suppressed only when it's an escape `\<` or part of `</` / `<!`
    #    (HTML constructs MathJax never sees) or `<=` (a single MathJax
    #    token that is parsed atomically and does NOT trip the HTML
    #    tokenizer's tag-start lookahead).
    for s, e, mbody in find_math_segments(body):
        # Compute the math body's offset inside the original segment so
        # multi-line `$$ … \n a < b \n … $$` reports the `<`'s line,
        # not the segment-start line. find_math_segments hands back the
        # full `(start, end, body)` of the segment; the body's first
        # char is at `body[s + (segment_text_len - body_len)]` — easier
        # to recompute via `body.find(mbody, s)`.
        body_offset_in_body = body.find(mbody, s)
        if body_offset_in_body == -1:
            body_offset_in_body = s  # fallback shouldn't happen
        for m in re.finditer(r"(?<!\\)<(?![=/!])", mbody):
            abs_offset = body_offset_in_body + m.start()
            ln = body[: abs_offset].count("\n") + 1
            label = _delim_label(body[s:e], body[s:e])
            problems.append(
                f"L{ln}: raw '<' inside {label} "
                f"'{ascii_safe(mbody.strip()[:60])}' -- use \\lt"
            )

    # 3) Image src: local must exist; remote http(s) warns. A print
    #    poster should be self-contained -- a CDN image that 404s or is
    #    slow at render time silently breaks the figure, and the render
    #    gates can't see a missing remote image. data: URIs are inline.
    for m in re.finditer(r'src\s*=\s*["\']([^"\']+)["\']', body,
                         re.IGNORECASE):
        src = m.group(1)
        # Scheme matching is case-insensitive (browsers treat `HTTPS:` /
        # `DATA:` like `https:` / `data:`); lower-case only for the scheme
        # test, keep `src` raw for display and local-path resolution.
        src_l = src.lower()
        if src_l.startswith("data:"):
            continue
        if src_l.startswith(("http://", "https://", "//")):
            ln = body[: m.start()].count("\n") + 1
            warnings.append(
                f"L{ln}: remote image '{ascii_safe(src[:60])}' -- inline or "
                "localize "
                "it; a print poster should not depend on a CDN at render "
                "time"
            )
            continue
        # Strip ?query / #fragment and percent-decode before resolving a
        # LOCAL path -- a legit `fig.png?v=2` or `my%20fig.png` otherwise
        # reads as a missing file.
        local = unquote(urlsplit(src).path)
        candidate = (html_path.parent / local).resolve()
        if not candidate.exists():
            ln = body[: m.start()].count("\n") + 1
            problems.append(f"L{ln}: missing local image '{ascii_safe(src)}'")

    # 4) data-measure-role="poster" required on the root. Paper2poster
    #    templates carry no `data-measure-role` attributes and use
    #    `class="poster"` instead; accept that as a valid substitute so
    #    the runtime class-fallback shim in render.py can map it.
    has_attr_poster = bool(
        re.search(r'data-measure-role\s*=\s*["\']poster["\']', body)
    )
    has_class_poster = bool(
        re.search(
            r'class\s*=\s*["\'][^"\']*\bposter\b[^"\']*["\']', body,
        )
    )
    if not (has_attr_poster or has_class_poster):
        problems.append(
            'missing root marker: add data-measure-role="poster" '
            '(or class="poster") to the outer container'
        )

    # 5) Unknown role values flag silent measure misses.
    for m in re.finditer(
        r'data-measure-role\s*=\s*["\']([^"\']+)["\']', body
    ):
        role = m.group(1).strip()
        if role not in KNOWN_ROLES:
            ln = body[: m.start()].count("\n") + 1
            problems.append(
                f"L{ln}: unknown data-measure-role='{ascii_safe(role)}' "
                f"(allowed: {sorted(KNOWN_ROLES)})"
            )

    # 6) Soft sanity: no <title> / no <h1>. Warns, doesn't fail.
    if not re.search(r"<title[^>]*>.+?</title>", raw, re.DOTALL):
        warnings.append("no <title> set")
    if not re.search(r"<h1\b", raw):
        warnings.append(
            "no <h1> -- poster title block usually carries one"
        )

    # 7) Every kept <figure> must carry a non-empty one-line <figcaption>.
    #    A figure whose caption is missing or blank renders as an unlabeled
    #    image -- a recurring defect on method / architecture figures. Warn
    #    (not fail: a purely decorative figure is a rare valid exception) but
    #    surface it every preflight so the caption gets filled from
    #    captions.json instead of shipping a bare figure.
    for m in re.finditer(r"<figure\b[^>]*>(.*?)</figure>", body,
                         re.DOTALL | re.IGNORECASE):
        inner = m.group(1)
        cap = re.search(r"<figcaption\b[^>]*>(.*?)</figcaption>", inner,
                        re.DOTALL | re.IGNORECASE)
        cap_txt = re.sub(r"<[^>]+>", "", cap.group(1)).strip() if cap else ""
        if not cap_txt:
            ln = body[: m.start()].count("\n") + 1
            warnings.append(
                f"L{ln}: <figure> has no non-empty <figcaption> -- every kept "
                "figure needs a one-line caption (from captions.json); an "
                "unlabeled figure is a defect"
            )

    print(f"[preflight] {ascii_safe(html_path)}")
    print(f"  problems: {len(problems)}   warnings: {len(warnings)}")
    for w in warnings:
        print(f"  WARN: {w}")
    for p in problems:
        _eprint(f"  FAIL: {p}")

    if problems:
        return 1
    print("[preflight] PASS")
    return 0


def has_required_roles_in_html(html_path: Path) -> dict[str, int]:
    """Cheap static count of each known role on disk. Used by ``polish``
    so it can hard-fail on a poster lacking ALL measurement markup,
    instead of silently PASSing on "0 figures, 0 columns, 0 stat
    elements".

    Compat fallback for paper2poster-style templates: add the conventional
    CSS classes that the runtime shim (``inject_class_fallback_roles``)
    maps to each role. Without this, polish hard-fails on disk before the
    browser ever opens, even though the runtime would have populated the
    roles fine.

    The fallback is ADDITIVE per role, mirroring the runtime shim: an
    explicit role does not turn the shim off for that role (in
    ``assets/layouts_portrait/full.html`` the single declared
    ``column`` on ``.method-hero`` sits alongside ordinary ``.col``
    columns, and both are measured). Bailing out on the FIRST attribute
    seen reported ``poster=0, card=0`` for that template, which tripped
    ``cmd_polish``'s "missing markup" hard-fail on a poster the runtime
    would have measured fine.

    This is a coarse ESTIMATE, not a prediction of the runtime. Against the
    lowercase, quoted markup this skill's templates emit it over-counts (a
    regex cannot tell which class-matched element already carries a role, so
    an element with both is counted twice), which is the harmless direction
    for its consumer: ``cmd_polish``'s pre-browser "is this file measurable
    at all?" check tests for zero, so erring high keeps it from refusing a
    poster it could measure. It is NOT an upper bound for arbitrary HTML --
    a browser accepts markup this regex does not match (``CLASS=section``,
    unquoted attribute values), where it would under-count instead.

    Either way it is only a fail-fast. Anything needing to know what the
    poster ACTUALLY renders must ask the live page (``render.count_roles``),
    which both ``cmd_polish`` and ``slack --with-polish`` now do before
    trusting a PASS.
    """
    raw = html_path.read_text(encoding="utf-8", errors="ignore")
    body = strip_for_lint(raw)
    counts: dict[str, int] = {role: 0 for role in KNOWN_ROLES}
    for m in re.finditer(
        r'data-measure-role\s*=\s*["\']([^"\']+)["\']', body
    ):
        role = m.group(1).strip()
        if role in counts:
            counts[role] += 1

    # Class-based fallback (paper2poster templates). Keep the selectors in
    # step with `render._COMPAT_ROLES_JS` -- if the two disagree, this
    # static pre-check and the runtime shim disagree about the same file.
    def _count_class(name: str) -> int:
        return len(re.findall(
            r'class\s*=\s*["\'][^"\']*\b' + re.escape(name) + r'\b[^"\']*["\']',
            body,
        ))
    fallbacks: dict[str, Callable[[], int]] = {
        "poster": lambda: _count_class("poster"),
        "column": lambda: _count_class("col"),
        "card": lambda: _count_class("section"),
        "banner": lambda: _count_class("titlebar") + _count_class("banner"),
        "footer-strip": lambda: _count_class("footer-strip"),
        "footer": lambda: _count_class("footer"),
    }
    for role, count_fn in fallbacks.items():
        counts[role] += count_fn()
    return counts
