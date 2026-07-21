#!/usr/bin/env python3
"""poster_check — unified CLI for HTML academic posters.

Four subcommands:

  slack          Per-section + per-column fill measurement for the
                 staged-fill loop -- print-emulated Chromium geometry
                 (replaces the older Node-based ``measure_layout.js``
                 estimator). Emits per-section ``fullRatio`` verdicts
                 (FULL / SPARSE / EMPTY / SPILLAGE / OVERFLOW) plus the
                 column-level ``slackRatio`` kept for back-compat.
                 ``--strict`` fails (exit 1) unless EVERY section is
                 FULL -- the hard staged-fill exit gate.
  preflight      Static HTML scan: LaTeX residue, raw '<' inside
                 ``$…$`` / ``$$…$$`` / ``\\(…\\)`` / ``\\[…\\]``,
                 missing local images, missing data-measure-role.
  polish         Visual-polish warnings on figure sizing, broken
                 images, typography orphans, and space-between fill.
                 Soft gate; warns by default. ``--strict`` to fail.
                 Hard-fails if there's no measurement markup at all.
  verify-final   Run ``pdfinfo`` on a rendered PDF; check page count,
                 dimensions match the expected canvas (``--canvas`` or
                 ``--from-html``), and file size under a limit.

All logic lives in the ``utils`` package next to this file. This
script is a thin argparse dispatcher.
"""
from __future__ import annotations

import argparse
import os
import sys

# Make `utils` importable when this file is run directly via
# `python tools/check_poster.py …`.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from utils import canvas as _canvas  # noqa: E402
from utils import autofit as _autofit  # noqa: E402
from utils import column_pack as _pack  # noqa: E402
from utils import deliverables as _deliverables  # noqa: E402
from utils import polish as _polish  # noqa: E402
from utils import preflight as _preflight  # noqa: E402
from utils import slack as _slack  # noqa: E402
from utils import verify_final as _verify_final  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poster_check",
        description="Slack / preflight / polish / verify a poster "
                    "HTML+PDF pair.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- slack ----------------------------------------------------------
    ps = sub.add_parser(
        "slack",
        help="per-column slackRatio (drives the staged-fill loop). "
             "Print-emulated, real Chromium geometry.",
    )
    ps.add_argument("html", help="path to poster.html")
    ps.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="override canvas (default: parse @page from HTML)",
    )
    ps.add_argument(
        "--settle-ms", type=int, default=500,
        help="extra wait after MathJax + fonts.ready settle "
             "(default 500)",
    )
    ps.add_argument(
        "--mathjax-timeout-ms", type=int, default=15000,
        help="hard timeout for MathJax typeset (default 15000)",
    )
    ps.add_argument(
        "--json", action="store_true",
        help="print JSON only (no pretty-print summary). Use this "
             "form when piping to another tool.",
    )
    ps.add_argument(
        "--json-out", default=None,
        help="also write the JSON report to this file (the staged-fill "
             "loop's `poster_debug.json` lives here)",
    )
    ps.add_argument(
        "--strict", action="store_true",
        help="exit non-zero unless EVERY section is FULL (fullRatio "
             "0.90-1.00). Any OVERFLOW / SPILLAGE / SPARSE / EMPTY "
             "section fails the gate. Use this as the hard staged-fill "
             "exit check.",
    )
    ps.add_argument(
        "--max-iterations", type=int, default=80,
        help="script-enforced circuit breaker: persist a per-poster count of "
             "CONSECUTIVE non-converged measurements in "
             "<poster_dir>/assets/meta/.fill_budget.json; once it exceeds this "
             "cap, slack "
             "prints a STOP banner and exits 3 (survives context compaction, "
             "unlike an in-prompt round count). A converged measurement clears "
             "the count, a run that produced no geometry (nav timeout, MathJax "
             "settle failure, no columns found) does not count, and a state "
             "file idle >12h is dropped. Default 80. Set <=0 to disable.",
    )
    ps.add_argument(
        "--reset-budget", action="store_true",
        help="clear the persistent .fill_budget.json counter before measuring "
             "(use for a genuine fresh re-render of the same poster_dir).",
    )
    ps.add_argument(
        "--with-polish", action="store_true",
        help="also run the visual-polish pass (figure fill, orphans, "
             "space-between, mid-wide structure) on the SAME rendered page -- "
             "ONE browser launch per round instead of two. Advisory by "
             "default; with --strict the polish warnings also gate the exit "
             "(matching the staged-fill 'every section FULL and zero "
             "FIG/NARROW' condition). Prefer this over a separate `polish` "
             "call inside the fill loop.",
    )
    ps.set_defaults(func=_slack.cmd_slack)

    # --- pack -----------------------------------------------------------
    pk = sub.add_parser(
        "pack",
        help="pre-fill column-packing feasibility: per-column "
             "slack = colHeight - figureFloors - textMin. A negative-slack "
             "column is INFEASIBLE (will oscillate in the fill loop) -> "
             "re-pack it BEFORE the loop. Run once after the initial render.",
    )
    pk.add_argument("html", help="path to poster.html (the initial render)")
    pk.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="override canvas (default: parse @page from HTML)",
    )
    pk.add_argument(
        "--settle-ms", type=int, default=500,
        help="extra wait after MathJax + fonts.ready settle (default 500)",
    )
    pk.add_argument(
        "--mathjax-timeout-ms", type=int, default=15000,
        help="hard timeout for MathJax typeset (default 15000)",
    )
    pk.set_defaults(func=_pack.cmd_pack)

    # --- preflight ------------------------------------------------------
    pp = sub.add_parser(
        "preflight",
        help="static HTML lint (LaTeX residue, math, images, roles)",
    )
    pp.add_argument("html", help="path to poster.html")
    pp.set_defaults(func=_preflight.cmd_preflight)

    # --- polish ---------------------------------------------------------
    ppl = sub.add_parser(
        "polish",
        help="visual-polish warnings (figure size, orphans, "
             "space-between, flex/<br>)",
    )
    ppl.add_argument("html", help="path to poster.html")
    ppl.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="override canvas (default: parse @page from HTML)",
    )
    ppl.add_argument(
        "--settle-ms", type=int, default=500,
        help="extra wait after layout settles (default 500)",
    )
    ppl.add_argument(
        "--mathjax-timeout-ms", type=int, default=15000,
        help="hard timeout for MathJax typeset (default 15000)",
    )
    ppl.add_argument(
        "--fig-min-ratio", type=float, default=_polish.DEFAULT_FIG_MIN_RATIO,
        help="every card figure must occupy >= this fraction of its "
             "card (section) on at least one axis -- width OR height -- "
             "regardless of aspect ratio (default 0.90); figures fill "
             "90-100%% of the section on one axis so they read as part of "
             "it rather than a narrow stamp",
    )
    # Back-compat shims: older callers/scripts may still pass these. They
    # are accepted but no longer drive the gate (superseded by the single
    # --fig-min-ratio width-or-height floor). Kept so existing command lines don't
    # crash; safe to remove once no caller references them.
    ppl.add_argument("--wide-min-ratio", type=float, default=0.80,
                     help=argparse.SUPPRESS)
    ppl.add_argument("--tall-max-ratio", type=float, default=0.70,
                     help=argparse.SUPPRESS)
    ppl.add_argument("--square-min-ratio", type=float, default=0.80,
                     help=argparse.SUPPRESS)
    ppl.add_argument(
        "--max-space-between-fill", type=float,
        default=_polish.DEFAULT_MAX_SPACE_BETWEEN_FILL,
        help="warn if a space-between column has an inter-card gap "
             "exceeding this fraction of column height (default 0.05)",
    )
    ppl.add_argument(
        "--max-card-trailing", type=float,
        default=_polish.DEFAULT_MAX_CARD_TRAILING,
        help="warn (CARD/TRAILING) if a card leaves more than this "
             "fraction of its height blank below the last line "
             "(default 0.05); catches a flex-stretched card padded "
             "with whitespace to fake a full page. Tightened from 0.10 "
             "to 0.05 to match the slack gate's 5pt FULL band — anything "
             "looser hides 5-9%% trailing voids the eye still sees",
    )
    ppl.add_argument(
        "--max-card-inner-void", type=float,
        default=_polish.DEFAULT_MAX_CARD_INNER_VOID,
        help="warn (CARD/INNER-VOID) if a card has an inter-child gap "
             "exceeding this fraction of its height "
             "(default 0.15); catches a void in the MIDDLE of a card, "
             "which CARD/TRAILING cannot see because a bottom-pinned "
             "tail drives trailing to ~0",
    )
    ppl.add_argument(
        "--min-card-inner-void-px", type=float,
        default=_polish.DEFAULT_MIN_CARD_INNER_VOID_PX,
        help="CARD/INNER-VOID also requires the gap to exceed this many "
             "px (default 24) so a sub-line gap on a small card cannot "
             "trip the gate",
    )
    ppl.add_argument(
        "--max-widow-fraction", type=float,
        default=_polish.DEFAULT_MAX_WIDOW_FRACTION,
        help="warn (WIDOW) when a multi-line <p>/<li> has its last "
             "line fill less than this fraction of element width "
             "(default 0.20); catches paragraphs where the trailing "
             "line carries only 1-2 stranded words. The fix is "
             "editorial (rephrase to add/remove 1-2 words), so the "
             "warning is purely informational — layout is unchanged",
    )
    ppl.add_argument(
        "--strict", action="store_true",
        help="exit non-zero when any warning is emitted",
    )
    ppl.set_defaults(func=_polish.cmd_polish)

    # --- verify-final ---------------------------------------------------
    pv = sub.add_parser(
        "verify-final",
        help="run pdfinfo + size/dimension/page checks on PDF",
    )
    pv.add_argument("pdf", help="path to poster.pdf")
    pv.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="expected canvas (e.g. '60x36in' or 'A0 portrait'); "
             "either this or --from-html is required",
    )
    pv.add_argument(
        "--from-html", default=None,
        help="read expected canvas from `@page { size }` in this "
             "HTML; mutually exclusive with --canvas",
    )
    pv.add_argument(
        "--dim-tol-in", type=float, default=0.05,
        help="dimension tolerance in inches (default 0.05)",
    )
    pv.add_argument(
        "--max-size-mb", type=float, default=20.0,
        help="max file size in MB (default 20)",
    )
    pv.add_argument(
        "--allow-rotated", action="store_true",
        help="accept swapped W/H even when PDF declares no page "
             "rotation (most posters should NOT need this)",
    )
    pv.set_defaults(func=_verify_final.cmd_verify_final)

    # --- autofit --------------------------------------------------------
    pa = sub.add_parser(
        "autofit",
        help="deterministically close continuous-lever (row-gap) fill gaps "
             "WITHOUT LLM rounds: grow each under-filled non-figure section's "
             "inner row-gaps by the slack report's needPx (bounded by the "
             "column's capacitySlack + the section's padding ceiling), bake "
             "into poster.html (gate-visible), and report what still needs "
             "LLM edits. Run it before `slack --with-polish` each fill round.",
    )
    pa.add_argument("html", help="path to poster.html (mutated in place)")
    pa.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="override canvas (default: parse @page from HTML)",
    )
    pa.add_argument(
        "--max-passes", type=int, default=3,
        help="max deterministic measure->grow->bake passes (default 3)",
    )
    pa.add_argument(
        "--settle-ms", type=int, default=500,
        help="extra wait after MathJax + fonts settle (default 500)",
    )
    pa.add_argument(
        "--mathjax-timeout-ms", type=int, default=15000,
        help="hard timeout for MathJax typeset (default 15000)",
    )
    pa.set_defaults(func=_autofit.cmd_autofit)

    # --- deliverables ---------------------------------------------------
    # Mandatory final gate: assert all 4 artifacts are on disk before the
    # model declares done. The other gates (slack/polish/verify-final) all
    # demand the model run them — but if Step 10 is skipped, verify-final
    # never even gets called and the missing PDF/PNG go undetected. This
    # one catches that exact failure mode.
    _deliverables.add_parser(sub)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
