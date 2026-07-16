"""Per-section bbox measurement driven by real Chromium layout.

Replaces the older ``measure_layout.js`` estimator and the previous
column-only `slack` gate. The estimator guessed text-block heights via
``@chenglou/pretext`` plus fixed budgets for figures/tables/stat-grids
-- close enough most of the time, but it diverged from the real
browser whenever a card had unusual padding, ``flex: grow``,
image-aspect-driven sizing, MathJax-rendered math, or any of the
visual-polish components (``.callout`` / ``.arch`` / ``.stat-grid``)
at non-default sizes. ``slack`` now reads the browser's own geometry
at the **section level** -- per-section card bbox, padding box, and
content bbox (union of children) -- so the staged-fill loop knows
*which specific section* is too empty or too full, not just "the
column needs more stuff".

The content bbox is a DEEP union over every descendant -- not just
the section's direct children -- so a descendant that **overflows**
an intermediate wrapper (e.g. ``<figure>`` inside ``.method-body``
inside ``.section``) still contributes its true post-layout bbox to
the section's union. Direct-children unions miss this: the wrapper's
``getBoundingClientRect()`` reports its allocated flex box, not its
overflowing content, so a Method figure painted 300px past the
section's bottom border would silently report the section as FULL
while visibly bleeding into the next card. The deep walk catches
that and produces the OVERFLOW / SPILLAGE verdict the eye sees.

Per-section ``fullRatio`` = (content_bottom - card_top) / card_h
(i.e. how far down the card the content's bottom edge reaches, as a
fraction of the full card height -- padding included):

  * > 1.10  OVERFLOW  -- content past the border; remove Additional / optional section
  * 1.00-1.10 SPILLAGE -- just past border; polish to reduce content
  *   .90-1.00  FULL   -- fills the card; healthy
  *   .70-.90   SPARSE -- visible underfill; polish to enhance content
  * <  .70  EMPTY     -- clearly underfilled; add Additional / optional section

``fillRatio`` (content_h / padding_box_h) is still emitted for
inspection but no longer drives the verdict -- ``fullRatio`` is the
metric the human eye actually sees ("does the content reach the
bottom of the card?") because it includes the card's own padding in
the denominator. The two diverge most on cards with heavy padding or
a top-of-card-only block: ``fillRatio`` can read high while
``fullRatio`` says the card still looks empty.

All sections are classified by the same thresholds, including the
bottom ``.section.grow`` card (``flex: 1 1 auto``) in each column.
A grown card that ends up SPARSE or EMPTY is still under-filled to
the eye -- its whitespace came from absorbing leftover column space,
but the staged-fill loop should grow real content into that space
rather than leave it blank. ``isGrow`` is reported on each section
for downstream tooling but no longer changes the verdict.

The gate is per-section: the loop is done when every measurable
section is in {FULL}. Column-level slackRatio is still
reported for context but is no longer the primary verdict.

Output JSON shape (back-compat fields preserved for old consumers):

    {
      "page":    { "width": W, "height": H, "contentHeight": H' },
      "columns": [
        { "index": 0, "width": W0, "used": U0, "slack": S0,
          "slackRatio": R0,
          "sections": [
            { "id": "problem",
              "card":         { "x":..., "y":..., "w":..., "h":... },
              "padding_box":  { "x":..., "y":..., "w":..., "h":... },
              "content_bbox": { "x":..., "y":..., "w":..., "h":... },
              "fillRatio":    0.96,
              "fullRatio":    0.93,
              "verdict":      "FULL",
              "isGrow":       false,
              "hasFigure":    false,
              "used":         508
            }, ...
          ]
        }, ...
      ],
      "verdict": {
        "overflowSections": ["problem", "motivation"],
        "spillageSections":  [],
        "sparseSections":    ["takeaway"],
        "emptySections":     [],
        "sparseColumns":     [2]
      }
    }
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import canvas as _canvas
from . import polish as _polish
from . import preflight as _preflight
from . import render as _render
from .cli_common import eprint as _eprint, import_playwright
from .textutil import ascii_safe


# Per-section verdict thresholds. Driven by ``fullRatio`` = (content
# bottom - card top) / card_h. Denominator is the card's full height
# (padding included), so the ratio matches what the eye sees -- "does
# the content reach the bottom of the card?". Calibrated against
# paper2poster's `.section` cards, which have ~32pt padding top/bottom:
# a healthy section's content typically reaches 85-100% of the card
# height even when the padding-box fillRatio is ~95%.
OVERFLOW_THRESHOLD = 1.10   # > 1.10   -- content visibly past card border
SPILLAGE_THRESHOLD = 0.99   # 0.99-1.10 -- too tight / past the border
FULL_THRESHOLD     = float(os.environ.get("POSTER_FULL_THRESHOLD", "0.90"))
                            # 0.90-0.99 -- ideal band. USER-CONFIGURABLE via the
                            # POSTER_FULL_THRESHOLD env var (default 0.90). 0.90 was
                            # chosen after a 4-paper Opus A/B; tighter gates
                            # (0.92 / 0.94) make more compact posters but used to
                            # grind ~59% more rounds. The per-element slack
                            # localization (the `elements` / `slackElementIdx`
                            # fields below) is what makes a tighter band reachable
                            # without that oscillation -- so a user who wants a
                            # tighter, more-compact gate can now set e.g.
                            # POSTER_FULL_THRESHOLD=0.94 and rely on per-element
                            # lever targeting to still converge fast.
                            # NB: the SHIPPED poster is also visually filled by
                            # render_poster.py's render-time "expand" pass
                            # (POSTER_EXPAND_THRESHOLD, default 0.98) -- so 0.90
                            # here converges the LAYOUT fast and the expand makes
                            # the final deliverable READ full, no re-grinding.
SPARSE_SEC_THRESHOLD = 0.70 # 0.70-0.90 -- underfill; suggest append
                            # < 0.70    -- EMPTY

# Scan-to-Read aspect-suppress threshold. A scan section that renders wide and
# flat -- its OWN width >= this many times its OWN height -- holds a small QR
# marooned in horizontal empty space (poster #8: a grid column blown out to ~2x
# width left the directory scan variant a 730x156 band with one QR filling ~15%
# of it). The slack gate flags such a section so the staged-fill loop deletes it
# EARLY and refills the freed column with real content (the neighbours go SPARSE
# and grow), instead of leaving render_poster.py's render-time backstop to hide
# it into whitespace. Same metric + default as that backstop (POSTER_SCAN_SUPPRESS_WH,
# default 3.8; in the v2 benchmark only #8 reaches ~4.7, the next-widest is 3.6).
SCAN_SUPPRESS_WH = float(os.environ.get("POSTER_SCAN_SUPPRESS_WH", "3.8"))

# Padding-zone violation gate (general). The card's outer padding is a
# visual "no-paint" breathing zone -- it exists to separate inner content
# from the card border. When ANY descendant that PAINTS a visible
# background or border (e.g. .callout, .arch-banner, .stat tile, future
# .highlight-strip, etc.) extends its bottom past the padding box, the
# eye perceives crowding even when the slack ``fullRatio`` reads in band.
# This is class-name-agnostic -- it works for any current or future
# tinted block element. Plain text overflow is ignored (already counted
# in fillRatio, but lacks a tinted bg to draw the eye to the crowding).
PADDING_VIOLATION_TOLERANCE_PX = 1.0  # subpixel tolerance for browser
                                       # rounding; any painted bg beyond
                                       # this past padding_box.bottom is
                                       # a real violation

# Column-level threshold kept for back-compat. The new per-section
# verdict supersedes it for the staged-fill gate, but tooling that
# still parses `sparseColumns` (eg older notes) keeps working.
SPARSE_THRESHOLD = 0.08

# Figure fill floor (mirrors polish.py Gate A). A card figure should
# paint at FIG_MIN_RATIO–FIG_MAX_RATIO on at least one axis (width OR
# height) of its section. Below that floor the figure reads as a
# stamp marooned in whitespace; above the ceiling it overflows. The
# slack gate now surfaces this alongside per-section fill verdicts so
# the staged-fill loop knows "this section is FULL but its figure is
# narrow" without having to round-trip to `polish`.
FIG_MIN_RATIO = float(os.environ.get("POSTER_FIG_MIN_RATIO", "0.90"))
FIG_MAX_RATIO = 1.00


# JS run inside the print-emulated page. Returns one record per column,
# each carrying its bounding box, the box of every `.section` child
# (with its `data-section` id and a hasFigure flag), and the rendered
# inner-content height of the column.
_SLACK_JS = r"""
() => {
  // Measure the page exactly as the browser laid it out — including the
  // `.section.grow` cards that flex-stretched to absorb column slack. The
  // in-browser debug overlay (poster_*.html `stampBadges`) reads
  // getBoundingClientRect() as-is, so this gate must match it byte-for-byte
  // or the staged-fill loop will disagree with what the reviewer sees when
  // they press `d`. (Earlier versions of this script temporarily zeroed
  // out flex-grow before measuring, which produced "natural" heights that
  // disagreed with the browser whenever a `.grow` card had real column
  // slack to absorb — verdict drifted SPARSE-in-browser / FULL-in-Python.)
  // Columns include both standard .col children and the .mid-wide block
  // (which spans grid cols 2-3 to host a wide Method on top of a 2-col
  // sub-grid). Without this, sections inside .mid-wide (Method, Dataset,
  // Key Result) are invisible to the staged-fill gate and stay SPARSE
  // forever while the gate reports "all FULL".
  const cols = Array.from(
    document.querySelectorAll('.columns > .col, .columns > .mid-wide, [data-measure-role="column"]')
  );
  const rect = el => {
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height,
             bottom: r.bottom, right: r.right };
  };
  const out = cols.map((col, i) => {
    const cs  = getComputedStyle(col);
    const padTop = parseFloat(cs.paddingTop)    || 0;
    const padBot = parseFloat(cs.paddingBottom) || 0;
    const colBox = rect(col);
    const innerH   = Math.max(0, colBox.h - padTop - padBot);
    const innerTop = colBox.y + padTop;

    const sections = Array.from(
      // Descendant query (not :scope >) so sections nested inside
      // .mid-wide > .mid-sub are picked up. Neither .col nor .mid-wide
      // ever contains another column, so descending past them is safe.
      col.querySelectorAll('.section')
    ).filter(s => {
      // PSEUDO-SECTION SUPPORT (2026-06-14): a .section can opt OUT of
      // measurement by setting data-measure-skip="true". Used by the
      // portrait_full .method-hero outer wrapper, which contains the
      // h2 + bullets + figure all at once — its fullRatio would always
      // read ~100% and crowd the verdict list. The real measurement
      // target is the inner pseudo-section data-section="method-text"
      // (the bullets cell), which stays in the list and lets the
      // staged-fill loop expand bullets when the figure stretches the
      // row taller than the bullets need.
      return s.getAttribute('data-measure-skip') !== 'true';
    }).map(s => {
      const sb = rect(s);
      const cs = getComputedStyle(s);
      const padT = parseFloat(cs.paddingTop)    || 0;
      const padR = parseFloat(cs.paddingRight)  || 0;
      const padB = parseFloat(cs.paddingBottom) || 0;
      const padL = parseFloat(cs.paddingLeft)   || 0;
      const padBox = {
        x: sb.x + padL,
        y: sb.y + padT,
        w: Math.max(0, sb.w - padL - padR),
        h: Math.max(0, sb.h - padT - padB),
      };
      // Content bbox via INK-LEAF walk, not direct-children union.
      //
      // Old approach (`Array.from(s.children).map(getBoundingClientRect)`)
      // measured layout containers like `.method-body` whose `flex: 1 1 auto`
      // stretches them to fill the section's available height — so their
      // bottom == section inner-bottom even when the actual image+caption
      // inside stops earlier. This inflated fillRatio to ~99% for cards
      // with 100+ px of invisible whitespace below the figure caption.
      //
      // New approach: walk all descendants and only take bboxes from
      // ink-bearing nodes — images, SVGs, table cells, the figcaption,
      // and any text-node range. Flex/grid containers are SKIPPED; only
      // their pixel-painting descendants count. This makes contentBox.h
      // match what the eye sees as filled.
      const INK_TAGS = new Set([
        'IMG','SVG','CANVAS','VIDEO','PICTURE',
        'TD','TH','LI','FIGCAPTION','BUTTON','CODE','PRE'
      ]);
      // A bare <div>/<span> can paint a raster via CSS `background-image:
      // url(...)` (the Scan-to-Read QR tiles `.qr-img`, an inline logo).
      // Such a node carries real visual ink but is NOT an INK_TAG and holds
      // no text, so the ink-leaf walk would skip it -- a QR-only section then
      // reads falsely EMPTY and the fill loop chases a phantom +Npx grow it
      // can never satisfy. Count url()-backed images at their rendered box.
      // A CSS gradient (`linear-gradient(...)`) is decorative, not content,
      // so we require the literal `url(` token.
      const paintsRasterBg = (node) => {
        const bi = getComputedStyle(node).backgroundImage || '';
        return bi.includes('url(');
      };
      let l = +Infinity, t = +Infinity, r = -Infinity, b = -Infinity;
      let any = false;
      const include = (rc) => {
        if (!rc) return;
        if (rc.width === 0 && rc.height === 0) return;
        l = Math.min(l, rc.left);  t = Math.min(t, rc.top);
        r = Math.max(r, rc.right); b = Math.max(b, rc.bottom);
        any = true;
      };
      // Walk descendants for ink-bearing elements.
      const walker = document.createTreeWalker(s, NodeFilter.SHOW_ELEMENT);
      let node = walker.nextNode();
      while (node) {
        if (node.classList && (node.classList.contains('listen-btn')
                            || node.classList.contains('dbg-badge')
                            || node.classList.contains('dbg-bbox'))) {
          node = walker.nextSibling() || walker.nextNode();
          continue;
        }
        if (INK_TAGS.has(node.tagName) || paintsRasterBg(node)) include(node.getBoundingClientRect());
        node = walker.nextNode();
      }
      // Walk text nodes — captures inline text inside <p>, <h2>, <strong>,
      // <span>, etc., using Range so we get pixel-accurate bottoms
      // (an empty <p>'s bbox extends past its text; a Range over its text
      // node does not).
      const textWalker = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
      let tn = textWalker.nextNode();
      const rng = document.createRange();
      while (tn) {
        if (tn.nodeValue && tn.nodeValue.trim()) {
          // skip text inside listen-btn / dbg-badge / dbg-bbox
          let p = tn.parentElement, skip = false;
          while (p && p !== s) {
            if (p.classList && (p.classList.contains('listen-btn')
                             || p.classList.contains('dbg-badge')
                             || p.classList.contains('dbg-bbox'))) { skip = true; break; }
            p = p.parentElement;
          }
          if (!skip) {
            rng.selectNodeContents(tn);
            const rects = rng.getClientRects();
            for (const rc of rects) include(rc);
          }
        }
        tn = textWalker.nextNode();
      }
      const contentBox = any
        ? { x: l, y: t, w: r - l, h: b - t }
        : null;
      const isGrow = s.classList.contains('grow');
      // Find the bottom-most descendant whose computed style PAINTS a
      // visible background or border. Class-name-agnostic so it
      // generalizes to any current or future tinted block element
      // (callouts, arch banners, stat tiles, future highlight strips).
      // Excludes the section itself (its bg is the card chrome) and
      // descendants that paint via inherited card styles only.
      let paintedBottom = -Infinity;
      s.querySelectorAll('*').forEach(el => {
        const cs = getComputedStyle(el);
        const bg = cs.backgroundColor || '';
        // CSS bg is rgba(0,0,0,0) or transparent when not painted.
        // Any rgba/rgb with alpha > 0 is a real paint.
        const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)'
                        && bg !== 'transparent' && !bg.startsWith('rgba(0, 0, 0, 0');
        const borderW = (parseFloat(cs.borderTopWidth)    || 0)
                      + (parseFloat(cs.borderBottomWidth) || 0)
                      + (parseFloat(cs.borderLeftWidth)   || 0)
                      + (parseFloat(cs.borderRightWidth)  || 0);
        const hasBorder = borderW > 0
                          && cs.borderTopColor !== 'rgba(0, 0, 0, 0)';
        if (!(hasBg || hasBorder)) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        if (r.bottom > paintedBottom) paintedBottom = r.bottom;
      });
      const paintedBottomRel = (paintedBottom === -Infinity)
        ? null
        : paintedBottom - sb.y;  // relative to section top
      // Figure-fill metric: for the FIRST <img> with painted_w >= 50
      // inside this section's <figure>, capture the painted image dims
      // (the actual pixels the eye sees -- accounting for `object-fit:
      // contain` letterboxing), the section's own card dims, and
      // natural dims for AR. We mirror polish.py's Gate A here so the
      // slack report can flag FIG/NARROW (figure < 90% of section on
      // BOTH axes) inline with the per-section verdicts.
      //
      // CRITICAL: <img> in this template uses `object-fit: contain`,
      // so the <img> bounding box can be much larger than the actual
      // painted image (the rest is empty letterbox / pillarbox). The
      // reviewer perceives the painted box, not the <img> box -- so
      // the gate must measure painted dimensions. We derive painted
      // w/h from naturalAR vs boxAR: when natural is wider than the
      // box, the image fills width and letterboxes top/bottom; when
      // natural is taller, the image fills height and pillarboxes
      // left/right. A section with no figure (or only inline icons
      // under 50px painted) reports figure: null.
      const figEl = s.querySelector('figure');
      let figure = null;
      if (figEl) {
        const imgs = Array.from(figEl.querySelectorAll('img'));
        for (const img of imgs) {
          const ir = img.getBoundingClientRect();
          const boxW = ir.width;
          const boxH = ir.height;
          const nw = img.naturalWidth  || 0;
          const nh = img.naturalHeight || 0;
          // Derive the painted image dimensions under `object-fit:
          // contain`. Fall back to the box dims when natural is
          // unavailable (e.g. SVG that didn't report intrinsic size)
          // so the metric still reads, just less precisely.
          let paintedW = boxW;
          let paintedH = boxH;
          if (nw > 0 && nh > 0 && boxW > 0 && boxH > 0) {
            const boxAR = boxW / boxH;
            const natAR = nw   / nh;
            if (natAR > boxAR) {
              // image wider than box -> fills width, letterboxes
              paintedW = boxW;
              paintedH = boxW / natAR;
            } else {
              // image taller than (or equal to) box -> fills height
              paintedH = boxH;
              paintedW = boxH * natAR;
            }
          }
          if (paintedW < 50) continue;
          figure = {
            src: img.getAttribute('src') || '',
            alt: img.getAttribute('alt') || '',
            box_w: boxW,
            box_h: boxH,
            rendered_w: paintedW,
            rendered_h: paintedH,
            natural_w: nw,
            natural_h: nh,
          };
          break;
        }
      }
      // Per-element decomposition (ADDITIVE -- does not touch contentBox).
      // inkBox(root): ink-leaf bounding box of a subtree, a DUPLICATE of
      // the contentBox ink-leaf logic above (the INK_TAGS element walk +
      // the text-Range walk) but scoped to `root` instead of `s`. Used to
      // measure each DIRECT child of the section on its own so the Python
      // side can locate WHERE the slack is (below which paragraph / the
      // figure) instead of collapsing the whole section into one union.
      const inkBox = (root) => {
        let l = +Infinity, t = +Infinity, r = -Infinity, b = -Infinity;
        let any = false;
        const include = (rc) => {
          if (!rc) return;
          if (rc.width === 0 && rc.height === 0) return;
          l = Math.min(l, rc.left);  t = Math.min(t, rc.top);
          r = Math.max(r, rc.right); b = Math.max(b, rc.bottom);
          any = true;
        };
        // Walk descendants for ink-bearing elements (scoped to root).
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
        let node = walker.nextNode();
        while (node) {
          if (node.classList && (node.classList.contains('listen-btn')
                              || node.classList.contains('dbg-badge')
                              || node.classList.contains('dbg-bbox'))) {
            node = walker.nextSibling() || walker.nextNode();
            continue;
          }
          if (INK_TAGS.has(node.tagName) || paintsRasterBg(node)) include(node.getBoundingClientRect());
          node = walker.nextNode();
        }
        // Walk text nodes (scoped to root), skipping chrome subtrees.
        const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let tn = textWalker.nextNode();
        const rng = document.createRange();
        while (tn) {
          if (tn.nodeValue && tn.nodeValue.trim()) {
            let p = tn.parentElement, skip = false;
            while (p && p !== root) {
              if (p.classList && (p.classList.contains('listen-btn')
                               || p.classList.contains('dbg-badge')
                               || p.classList.contains('dbg-bbox'))) { skip = true; break; }
              p = p.parentElement;
            }
            if (!skip) {
              rng.selectNodeContents(tn);
              const rects = rng.getClientRects();
              for (const rc of rects) include(rc);
            }
          }
          tn = textWalker.nextNode();
        }
        return any ? { x: l, y: t, w: r - l, h: b - t } : null;
      };
      const elements = [];
      Array.from(s.children).forEach(k => {
        if (k.classList && (k.classList.contains('listen-btn')
                         || k.classList.contains('dbg-badge')
                         || k.classList.contains('dbg-bbox'))) return;
        elements.push({
          tag: k.tagName.toLowerCase(),
          cls: (k.getAttribute('class') || ''),
          bbox: inkBox(k),
          isFigure: (k.tagName === 'FIGURE' || !!k.querySelector('figure')),
          text: (k.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 48),
        });
      });
      return {
        id:    s.getAttribute('data-section') || '',
        x: sb.x, y: sb.y, w: sb.w, h: sb.h, bottom: sb.bottom,
        padding_box: padBox,
        content_bbox: contentBox,
        isGrow,
        hasFigure: !!figEl,
        paintedBottomRel,
        figure,
        elements,
      };
    });
    return {
      index: i,
      box: colBox,
      innerH, innerTop,
      sections,
    };
  });

  return out;
}
"""


def _section_source_blocks(
    html_text: str, ids: list[str], cap: int = 4000
) -> dict[str, str]:
    """Verbatim source of each `<div ... data-section="id">...</div>` block.

    Depth-aware: section divs contain nested divs, so a flat regex would stop at
    the first inner `</div>`; we balance `<div`/`</div>` to find the real close.
    This lets the staged-fill loop lift an `Edit` ``old_string`` straight from the
    slack report instead of re-reading the whole ~100 KB ``poster.html`` each
    round -- the input-context cost that overflows a smaller model's window and
    triggers thrashing auto-compaction. Blocks longer than ``cap`` are tail-cut.
    """
    out: dict[str, str] = {}
    for sid in ids:
        m = re.search(rf'<div\b[^>]*\bdata-section="{re.escape(sid)}"', html_text)
        if not m:
            continue
        start = html_text.rfind("<div", 0, m.end())
        i, depth = start, 0
        while i < len(html_text):
            o = html_text.find("<div", i)
            c = html_text.find("</div>", i)
            if c == -1:
                break
            if o != -1 and o < c:
                depth += 1
                i = o + 4
            else:
                depth -= 1
                i = c + len("</div>")
                if depth == 0:
                    block = html_text[start:i]
                    if len(block) > cap:
                        block = (
                            block[:cap]
                            + f"\n  ...[+{len(block) - cap} chars truncated; "
                            "pick a unique sub-snippet above as your Edit old_string]"
                        )
                    out[sid] = block
                    break
    return out


#: A ``.fill_budget.json`` untouched for this long describes a PREVIOUS
#: working session, not the current loop, so its count is dropped. The
#: batch pipeline renders a poster in one sitting; a human re-opening the
#: same run_dir the next day should not inherit yesterday's debt.
BUDGET_STALE_AFTER_HOURS = 12.0


def _load_budget(path: Path) -> int:
    """Consecutive non-converged measurements recorded for this poster.

    Any unreadable / implausible / stale state degrades to ``0`` -- the
    breaker must never invent a count that stops a legitimate loop, and
    budget I/O must never raise into the fill gate.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        count = int(data["count"])
    except (OSError, ValueError, TypeError, KeyError):
        return 0
    if count < 0:
        return 0
    updated = data.get("updated")
    if updated is None:
        # State written before this field existed. Fall back to the file's
        # mtime rather than honouring the count forever: the pre-upgrade
        # format is exactly where a large stale count is most likely to be
        # sitting (the old counter never reset), and a months-old 80 would
        # otherwise trip the breaker on the very first measurement after the
        # upgrade. An in-flight legacy loop still keeps its count -- its file
        # was touched minutes ago.
        try:
            ts = _dt.datetime.fromtimestamp(path.stat().st_mtime,
                                            _dt.timezone.utc)
        except OSError:
            return 0
    else:
        try:
            ts = _dt.datetime.fromisoformat(str(updated))
        except (ValueError, TypeError):
            return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    now = _dt.datetime.now(_dt.timezone.utc)
    if ts > now + _dt.timedelta(minutes=5):
        return 0        # clock skew, or a run_dir copied from another host
    if (now - ts) > _dt.timedelta(hours=BUDGET_STALE_AFTER_HOURS):
        return 0        # previous session
    return count


def _write_budget(path: Path, count: int) -> None:
    """Atomically persist ``count``. Never raises: a poster on a
    read-only mount loses the breaker, not the gate verdict."""
    payload = json.dumps({
        "count": count,
        "updated": _dt.datetime.now(_dt.timezone.utc)
                      .replace(microsecond=0).isoformat(),
    })
    try:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass


def _clear_budget(path: Path) -> None:
    """Drop the state on a converged measurement or ``--reset-budget``.

    A count that survived a PASS would break the CONSECUTIVE-failure
    contract on the next run, so fall back to zeroing the file in place
    when it cannot be removed.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _write_budget(path, 0)


def cmd_slack(args: argparse.Namespace) -> int:
    pw = import_playwright()
    if pw is None:
        return 2
    sync_playwright, PWTimeoutError = pw

    html_path = Path(args.html).resolve()
    if not html_path.exists():
        _eprint(f"ERROR: HTML not found: {ascii_safe(html_path)}")
        return 2

    # Persistent fill-iteration budget — the SCRIPT-enforced circuit breaker.
    # The count lives on disk under the bundle's assets/meta/, so it survives
    # context compaction (an in-prompt round count does not — a continuation
    # wipes it, which is how weaker models grind past a "loop max N rounds"
    # instruction) while keeping the deliverable top level clean. A fresh
    # run_dir starts at 0 automatically; --reset-budget resets it for a genuine
    # re-render. max-iterations <= 0 disables the breaker entirely.
    #
    # What is counted: CONSECUTIVE NON-CONVERGED measurements. The count is
    # read here but only written once the outcome is known (see the
    # "Circuit-breaker accounting" block after the verdict is computed), which
    # gives three properties a straight "+1 per invocation at the top" lacked:
    #   - a converged measurement CLEARS the count, so the touch-up round after
    #     a poster already reached FULL cannot trip a breaker inherited from
    #     the rounds it took to get there;
    #   - a run that never produced geometry (nav timeout, MathJax settle
    #     failure, no columns found) is an environment problem and burns no
    #     budget -- it used to, because the increment landed before the page
    #     was even opened;
    #   - a state file older than BUDGET_STALE_AFTER_HOURS is a previous
    #     session and is dropped.
    _budget_meta = html_path.parent / "assets" / "meta"
    _budget_meta.mkdir(parents=True, exist_ok=True)
    _budget_path = _budget_meta / ".fill_budget.json"
    _max_iter = int(getattr(args, "max_iterations", 0) or 0)
    if getattr(args, "reset_budget", False):
        _clear_budget(_budget_path)
    _iter_count = _load_budget(_budget_path) if _max_iter > 0 else 0
    _breaker_hit = False

    resolved = _canvas.resolve_canvas(
        html_path, args.canvas, label="[slack]"
    )
    if resolved is None:
        _eprint(
            "ERROR: could not find `@page { size: <W> <H> }` in HTML. "
            "Add an @page rule (units: in/mm/cm/pt) or pass "
            "`--canvas <W>x<H>in`."
        )
        return 2
    _canvas_obj, viewport = resolved
    vw, vh = viewport

    with sync_playwright() as p:
        browser, _ctx, page = _render.open_print_emulated_page(p, viewport)
        nav_timed_out = False
        try:
            page.goto(html_path.as_uri(), wait_until="networkidle",
                      timeout=args.mathjax_timeout_ms)
        except PWTimeoutError:
            nav_timed_out = True

        settle = _render.settle_page(
            page,
            mathjax_timeout_ms=args.mathjax_timeout_ms,
            settle_ms=args.settle_ms,
        )
        fail = _render.hard_fail_on_settle_problems(
            settle, mathjax_timeout_ms=args.mathjax_timeout_ms,
        )
        if fail is not None:
            browser.close()
            _eprint(f"FAIL: {fail}")
            return 1
        if nav_timed_out:
            browser.close()
            _eprint(
                "FAIL: page did not reach network-idle within "
                f"{args.mathjax_timeout_ms} ms; refusing to measure a "
                "partially loaded poster."
            )
            return 1

        _render.inject_class_fallback_roles(page)
        cols = page.evaluate(_SLACK_JS)
        # ①.3 merge — run the visual-polish measurement on the SAME rendered
        # page instead of launching a second browser for `polish`. Pure
        # read-only DOM reads, so slack's numbers above are unaffected. If the
        # poster lacks polish's required measure-role markup, skip (don't fail
        # the slack run — --with-polish is an opt-in convenience).
        polish_collected = None
        polish_skipped: str | None = None
        if getattr(args, "with_polish", False):
            # Ask the LIVE page which roles resolved, not the static regex
            # estimate: that estimate only reads the file text, so a poster
            # whose `.section`s all carry some other role reads as "has
            # cards" on disk and yields zero cards in the browser. polish
            # would then measure nothing, emit no warnings, and PASS -- a
            # silent green on an unmeasured poster (invisible in --json,
            # which drops the "cards checked: 0" line). An empty result
            # means nothing resolved OR the query failed; both fail closed.
            _roles = _render.count_roles(page)
            _missing_roles = [
                r for r in ("poster", "card", "column") if _roles.get(r, 0) == 0
            ]
            if _missing_roles:
                polish_skipped = (
                    f"poster resolves no {'/'.join(_missing_roles)} element(s) "
                    "at render time"
                )
                _eprint(
                    "[slack] --with-polish: skipping polish pass, "
                    f"{polish_skipped}"
                )
            else:
                try:
                    polish_collected = _polish.collect_polish_data(page)
                except Exception as _pe:  # never let polish break the fill gate
                    polish_skipped = f"polish measurement failed ({_pe})"
                    _eprint(
                        f"[slack] --with-polish: polish measurement failed, "
                        f"skipped ({_pe})"
                    )
        browser.close()

    if not cols:
        _eprint(
            "ERROR: no `.columns > .col` (or "
            "`[data-measure-role=\"column\"]`) elements found. "
            "Did the HTML render the column grid?"
        )
        return 2

    def _round_box(b: dict[str, float] | None) -> dict[str, float] | None:
        if b is None:
            return None
        return {k: round(v, 1) for k, v in b.items()}

    def _classify(full_ratio: float) -> str:
        # All sections — including `.grow` — share the same thresholds.
        # A grown card with low fullRatio is genuinely under-filled to
        # the eye; downstream tooling can still read `isGrow` per
        # section if it needs to special-case anything.
        if full_ratio > OVERFLOW_THRESHOLD:
            return "OVERFLOW"
        if full_ratio >= SPILLAGE_THRESHOLD:
            return "SPILLAGE"
        if full_ratio >= FULL_THRESHOLD:
            return "FULL"
        if full_ratio >= SPARSE_SEC_THRESHOLD:
            return "SPARSE"
        return "EMPTY"

    def _classify_figure(
        fig: dict[str, float] | None,
        card_w: float,
        card_h: float,
    ) -> dict[str, Any] | None:
        """Mirror polish.py Gate A on a single section's figure.

        Returns ``None`` when there is no qualifying figure. Otherwise
        returns a dict with rendered/natural dims, the per-axis ratios
        of the figure to its containing section's card, and a verdict:
        ``OK`` (fills >=90% on at least one axis), ``NARROW`` (below
        the floor on both axes), ``OVERFLOW`` (>100% on either axis),
        or ``BROKEN`` (image failed to load -- zero natural size, which
        in Chromium means a 404 / unparseable file, SVG or
        raster). The denominator is the section card -- the same
        box used for the slack ``fullRatio`` -- so a figure reading
        100% width here visibly fills its card edge-to-edge.
        """
        if not fig:
            return None
        rw = float(fig.get("rendered_w") or 0)
        rh = float(fig.get("rendered_h") or 0)
        nw = float(fig.get("natural_w") or 0)
        nh = float(fig.get("natural_h") or 0)
        out: dict[str, Any] = {
            "src":        fig.get("src", ""),
            "rendered_w": round(rw, 1),
            "rendered_h": round(rh, 1),
            "natural_w":  nw,
            "natural_h":  nh,
        }
        # Zero natural size == failed to load, SVG included: Chromium (the only
        # renderer this measures in) resolves a viewBox-less <img>'d SVG to the
        # 300x150 CSS default replaced size and never reports 0. The old
        # `is_svg` src-extension exemption therefore only ever spared genuinely
        # broken vector art. Kept in step with polish.py Gate A by hand -- if
        # one gate exempts and the other doesn't, they disagree about the same
        # figure.
        if nw <= 0 or nh <= 0:
            out["verdict"] = "BROKEN"
            out["w_ratio"] = 0.0
            out["h_ratio"] = 0.0
            return out
        w_ratio = (rw / card_w) if card_w > 0 else 0.0
        h_ratio = (rh / card_h) if card_h > 0 else 0.0
        out["w_ratio"] = round(w_ratio, 3)
        out["h_ratio"] = round(h_ratio, 3)
        # Overflow on either axis is its own bug; the hard gate catches
        # it but we surface the verdict here for visibility.
        if w_ratio > FIG_MAX_RATIO or h_ratio > FIG_MAX_RATIO:
            out["verdict"] = "OVERFLOW"
            return out
        if w_ratio < FIG_MIN_RATIO and h_ratio < FIG_MIN_RATIO:
            out["verdict"] = "NARROW"
            return out
        out["verdict"] = "OK"
        return out

    # Per-column capacity budget (column_pack): headroom each column has once
    # figures are floored to 90% + text is at minimum content. A small/negative
    # budget means the column is intrinsically tight -> the fill loop should
    # STOP adding to it (and steer new content to a looser column) rather than
    # push it to FULL and oscillate. Lazy import avoids a slack<->column_pack cycle.
    from . import column_pack as _column_pack
    _pack_by_idx = {d["index"]: d for d in _column_pack.compute_pack(cols)}

    columns_out: list[dict[str, Any]] = []
    overflow_secs: list[str] = []
    spillage_secs: list[str] = []
    sparse_secs:   list[str] = []
    empty_secs:    list[str] = []
    narrow_figs:   list[str] = []
    overflow_figs: list[str] = []
    broken_figs:   list[str] = []
    suppress_secs: list[str] = []   # scan-to-read flagged too wide/flat -> delete
    for c in cols:
        sections = c["sections"]
        # "used" = pixels of column inner-height actually consumed,
        # i.e. from the inner-top down to the bottom of the last
        # section. This includes the inter-section margin/gaps, which
        # matches what the rendered eye sees as "occupied space" and
        # what the user means by "the column is full".
        if sections:
            last_bottom = max(s["bottom"] for s in sections)
            used = max(0.0, last_bottom - c["innerTop"])
        else:
            used = 0.0
        slack = c["innerH"] - used
        slack_ratio = round(slack / c["innerH"], 3) if c["innerH"] else 0.0

        sec_out = []
        for s in sections:
            card = {"x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"]}
            pad  = s["padding_box"]
            content = s["content_bbox"]
            # fillRatio: content_h / padding_box_h. Kept for inspection
            # but no longer the verdict driver.
            pad_h = max(1.0, pad["h"])
            content_h = content["h"] if content else 0.0
            fill_ratio = round(content_h / pad_h, 3)
            # fullRatio: (content_bottom - card_top) / card_h. This is
            # what the eye sees -- does the content reach the bottom of
            # the card? -- because the denominator includes the card's
            # own padding. Drives the verdict.
            card_h = max(1.0, s["h"])
            if content:
                content_bottom_rel = (content["y"] + content["h"]) - s["y"]
                full_ratio = round(content_bottom_rel / card_h, 3)
            else:
                full_ratio = 0.0
            verdict = _classify(full_ratio)
            # Padding-zone violation override (general, class-agnostic).
            # If the bottom-most painted descendant (any element with a
            # visible background or border) extends past the card's
            # inner padding box, the eye sees crowding even when
            # fullRatio reads FULL. Downgrade to SPILLAGE so the fill
            # loop tightens the section. Generalizes to callouts,
            # arch-banners, stat tiles, future highlight strips, etc.
            painted_bottom_rel = s.get("paintedBottomRel")
            pad_bottom_rel = (pad["y"] + pad["h"]) - s["y"]
            painted_overshoot = (
                painted_bottom_rel - pad_bottom_rel
                if painted_bottom_rel is not None else None
            )
            if (verdict == "FULL"
                    and painted_bottom_rel is not None):
                if painted_bottom_rel > pad_bottom_rel + PADDING_VIOLATION_TOLERANCE_PX:
                    verdict = "SPILLAGE"
            # needPx: the signed px the section's content bottom must MOVE to
            # land centered in the FULL band — so the staged-fill loop can
            # apply ONE precise continuous lever (margin-bottom on the bottom
            # element / shrink .col gap / figure max-height) instead of
            # guessing with discrete ~50px text edits and overshooting the
            # 0.05-wide band. Sign: +N => grow (push bottom DOWN ~N px),
            # -N => shrink (pull UP ~N px). null when already FULL.
            # needPxRange = [min, max] signed deltas that still land in-band.
            need_px = None
            need_px_range = None
            if verdict != "FULL":
                if (verdict == "SPILLAGE"
                        and full_ratio < SPILLAGE_THRESHOLD
                        and painted_overshoot is not None
                        and painted_overshoot > 0):
                    # FULL by ratio, but a painted element (callout/table/tile)
                    # pokes past the padding box — the binding constraint is
                    # that overshoot, not the fullRatio band.
                    need_px = -round(painted_overshoot
                                     + PADDING_VIOLATION_TOLERANCE_PX, 1)
                else:
                    _lo = (FULL_THRESHOLD - full_ratio) * card_h
                    _hi = (SPILLAGE_THRESHOLD - full_ratio) * card_h
                    need_px = round((_lo + _hi) / 2.0, 1)   # aim mid-band
                    need_px_range = [round(min(_lo, _hi), 1),
                                     round(max(_lo, _hi), 1)]
            entry: dict[str, Any] = {
                "id":           s["id"],
                "card":         _round_box(card),
                "padding_box":  _round_box(pad),
                "content_bbox": _round_box(content),
                "fillRatio":    fill_ratio,
                "fullRatio":    full_ratio,
                "verdict":      verdict,
                "needPx":       need_px,
                "needPxRange":  need_px_range,
                "isGrow":       s["isGrow"],
                "used":         round(s["h"]),
            }
            if s["hasFigure"]:
                entry["hasFigure"] = True
            fig_info = _classify_figure(
                s.get("figure"), float(s["w"]), float(s["h"])
            )
            if fig_info is not None:
                entry["figure"] = fig_info
                fig_id = f"{s['id']}:{fig_info.get('src', '')}"
                fv = fig_info.get("verdict")
                if fv == "NARROW":
                    narrow_figs.append(fig_id)
                elif fv == "OVERFLOW":
                    overflow_figs.append(fig_id)
                elif fv == "BROKEN":
                    broken_figs.append(fig_id)
            # Per-element slack decomposition (ADDITIVE). content_bbox is
            # ONE union, so a SPARSE/EMPTY verdict can't say WHERE the
            # whitespace is. Decompose the section into its DIRECT children
            # (each measured as its own ink-leaf bbox by the JS `inkBox`
            # helper), then find the gap BELOW each child. The child with
            # the largest gap below it is where the slack lives -> the fill
            # loop can target that element's lever (grow it / enlarge the
            # figure) instead of guessing which lever to pull.
            raw_elements = [
                e for e in (s.get("elements") or [])
                if e.get("bbox") is not None
            ]
            raw_elements.sort(key=lambda e: e["bbox"]["y"])
            pad_bottom = pad["y"] + pad["h"]
            elements_out: list[dict[str, Any]] = []
            slack_element_idx: int | None = None
            slack_gap_px = 0.0
            for ei, e in enumerate(raw_elements):
                eb = e["bbox"]
                e_bottom = eb["y"] + eb["h"]
                if ei + 1 < len(raw_elements):
                    gap_below = raw_elements[ei + 1]["bbox"]["y"] - e_bottom
                else:
                    gap_below = pad_bottom - e_bottom
                gap_below = round(max(0.0, gap_below), 1)
                elements_out.append({
                    "tag":      e.get("tag", ""),
                    "cls":      e.get("cls", ""),
                    "bbox":     _round_box(eb),
                    "gapBelow": gap_below,
                    "isFigure": bool(e.get("isFigure")),
                    "text":     e.get("text", ""),
                })
                # Headings (h1/h2/h3) are not growable content -- the gap below
                # a heading is the normal heading->body margin, not fillable
                # slack. Only attribute the slack to a growable content element
                # so the loop targets a real lever (grow this <p>/<ul>/<figure>),
                # never "grow the title".
                if e.get("tag", "") not in ("h1", "h2", "h3"):
                    if slack_element_idx is None or gap_below > slack_gap_px:
                        slack_gap_px = gap_below
                        slack_element_idx = ei
            entry["elements"] = elements_out
            entry["slackElementIdx"] = slack_element_idx
            entry["slackGapPx"] = round(slack_gap_px, 1)
            sec_out.append(entry)
            if verdict == "OVERFLOW":
                overflow_secs.append(s["id"])
            elif verdict == "SPILLAGE":
                spillage_secs.append(s["id"])
            elif verdict == "SPARSE":
                sparse_secs.append(s["id"])
            elif verdict == "EMPTY":
                empty_secs.append(s["id"])
            # Scan-to-Read aspect guard (loop-internal verdict). A scan section
            # rendered wide and flat -- its OWN width many times its OWN height --
            # holds a small QR marooned in horizontal empty space. Flag it so the
            # staged-fill loop deletes it EARLY (a real verdict, like OVERFLOW) and
            # refills the freed column with real content, rather than leaving
            # render_poster.py's render-time backstop to hide it into whitespace.
            # Same metric + threshold as that backstop: the section's OWN w/h.
            if s["id"] == "scan-to-read" and s["h"] > 8:
                _wh = round(s["w"] / s["h"], 2)
                entry["aspectWH"] = _wh
                if _wh >= SCAN_SUPPRESS_WH:
                    entry["suppress"] = True
                    suppress_secs.append(s["id"])

        columns_out.append({
            "index":      c["index"],
            "width":      round(c["box"]["w"]),
            "used":       round(used),
            "slack":      round(slack),
            "slackRatio": slack_ratio,
            "capacitySlack": (_pack_by_idx.get(c["index"]) or {}).get("slack"),
            "rigidPct":   (_pack_by_idx.get(c["index"]) or {}).get("rigidPct"),
            "sections":   sec_out,
        })

    # contentHeight: inner column height (column padding excluded) of
    # the first column. All columns share the same height in the
    # paper2poster templates; if they ever diverge, the per-column
    # slackRatio is still correct -- this is just the headline number.
    content_height = round(cols[0]["innerH"]) if cols else 0

    # Back-compat: column-level sparse list still emitted so older
    # tooling that reads `verdict.sparseColumns` keeps working. The new
    # per-section lists are the primary signal.
    sparse_cols = [c["index"] for c in columns_out
                   if c["slackRatio"] > SPARSE_THRESHOLD]

    report = {
        "page": {
            "width":         vw,
            "height":        vh,
            "contentHeight": content_height,
        },
        "columns": columns_out,
        "verdict": {
            "overflowSections": overflow_secs,
            "spillageSections": spillage_secs,
            "sparseSections":   sparse_secs,
            "emptySections":    empty_secs,
            "suppressSections": suppress_secs,
            "sparseColumns":    sparse_cols,
            "narrowFigures":    narrow_figs,
            "overflowFigures":  overflow_figs,
            "brokenFigures":    broken_figs,
        },
    }

    # Strict gate: every section must be FULL AND every figure must
    # fill 90-100% on at least one axis (no NARROW / OVERFLOW / BROKEN).
    # Mirrors `polish --strict` Gate A so the staged-fill loop can't
    # terminate on a card that reads FULL but has a figure marooned in
    # whitespace.
    not_full = (
        overflow_secs + spillage_secs + sparse_secs + empty_secs
    )
    bad_figs = narrow_figs + overflow_figs + broken_figs
    strict_fail = bool(
        getattr(args, "strict", False)
        and (not_full or bad_figs or suppress_secs)
    )

    # Run the merged polish gates NOW, buffering their output, so their
    # verdict can join the convergence decision below. They are printed later
    # by `_finish_ok` at the position they have always occupied (after the
    # slack report), or dropped in --json mode; buffering keeps the ordering
    # while letting the breaker see the whole picture. Without this the
    # accounting would run on slack's verdict alone, and a poster that is FULL
    # everywhere but keeps failing a polish gate would clear its budget every
    # round -- the loop `--with-polish --strict` is supposed to bound would
    # never trip the breaker at all.
    _strict = bool(getattr(args, "strict", False))
    _polish_rc = 0
    _polish_out = ""
    _polish_err = ""
    _polish_emitted = False
    if polish_collected is not None:
        import contextlib
        import io
        _pargs = _polish.default_polish_args()
        _pargs.strict = _strict
        # Buffer stderr as well as stdout -- under --strict report_polish
        # writes its FAIL line to stderr, which would otherwise escape and
        # land ahead of the slack report it is supposed to follow -- but keep
        # the two SEPARATE so each is replayed on its original stream. Merging
        # them would quietly move `[polish] FAIL` onto stdout and break anyone
        # who greps stderr for it.
        _obuf, _ebuf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(_obuf), contextlib.redirect_stderr(_ebuf):
            _polish_rc = _polish.report_polish(polish_collected, _pargs,
                                               html_path)
        _polish_out, _polish_err = _obuf.getvalue(), _ebuf.getvalue()
    elif getattr(args, "with_polish", False) and _strict:
        # --with-polish --strict asked for the polish gates to bind. They did
        # not run, so there is no evidence they would pass: failing here is the
        # only answer that keeps `--strict` meaning "verified". Advisory mode
        # (no --strict) still degrades to a warning, as before.
        _polish_rc = 1
        _polish_out = (
            "=== POLISH: NOT RUN ===\n"
            f"  {polish_skipped or 'polish pass unavailable'}.\n"
            "  --strict requires the polish gates to actually run, so this "
            "counts as a FAILURE\n"
            "  rather than a silent pass. Add the measure-role markup (or the "
            "conventional\n"
            "  .poster/.col/.section classes), or drop --with-polish to gate "
            "on fill alone.\n"
        )
        _polish_err = (
            "[polish] FAIL -- --strict and the polish gates could not run\n"
        )

    # Circuit-breaker accounting (see the budget block at the top of this
    # function). Convergence is judged on the MEASUREMENT, not on
    # ``strict_fail`` -- the staged-fill loop is free to run without
    # ``--strict``, and a breaker that only counted under ``--strict`` would
    # never fire for it. This is the same condition ``--strict`` gates on:
    # every section FULL and every figure OK, plus (when merged in) the
    # polish gates, whose failures are equally something the loop must edit
    # its way out of.
    _converged = not (not_full or bad_figs or suppress_secs)
    if _polish_rc != 0:
        _converged = False
    if _converged:
        # Clear even when the breaker is disabled (`--max-iterations 0`).
        # "Converged clears the count" is the documented contract, and a
        # disabled run that left a stale 7 on disk would hand it straight back
        # to the next enabled run inside the staleness window.
        _clear_budget(_budget_path)
        _iter_count = 0
    elif _max_iter > 0:
        _iter_count += 1
        _write_budget(_budget_path, _iter_count)
    if _max_iter > 0:
        _breaker_hit = _iter_count > _max_iter

    # Structured EDIT TARGETS -- verbatim source of each off-band section, so the
    # staged-fill loop can edit straight from this report and never re-Read the
    # whole poster.html (the input-context blowup that compacts + thrashes small
    # models). Computed only when something is off-band (an empty dict otherwise).
    # A suppress-flagged scan section is included so the loop can lift its block
    # straight from here to DELETE it.
    edit_targets: dict[str, str] = {}
    _edit_ids = not_full + [sid for sid in suppress_secs if sid not in not_full]
    if _edit_ids:
        try:
            edit_targets = _section_source_blocks(
                html_path.read_text(encoding="utf-8", errors="replace"), _edit_ids
            )
        except OSError:
            edit_targets = {}

    report["fillBudget"] = {
        "iteration": _iter_count,
        "max": _max_iter,
        "breaker": _breaker_hit,
    }
    if getattr(args, "with_polish", False):
        # Structured, so a --json consumer (which never sees the human polish
        # text) can tell "polish passed" from "polish never ran" instead of
        # inferring it from a bare exit code.
        report["polish"] = {
            "ran": polish_collected is not None,
            "failed": _polish_rc != 0,
            "skippedReason": polish_skipped,
        }

    def _emit_breaker() -> None:
        # Show WHY first. The breaker exists to survive context compaction, so
        # this round is very likely the first one a fresh context ever sees --
        # returning the banner without the polish warnings that caused it would
        # hand that context a clean-looking slack verdict and no evidence.
        _emit_polish()
        _eprint("")
        _eprint(
            f"  CIRCUIT BREAKER -- {_iter_count}/{_max_iter} consecutive "
            "non-converged fill measurements on this poster."
        )
        _eprint(
            "  STOP iterating. Accept the current best state: render "
            "poster.pdf/png NOW,"
        )
        _eprint(
            "  mark the stage DEGRADED (list the still-off-band section ids), "
            "and move on."
        )
        _eprint(
            "  This counter is on disk (.fill_budget.json) and survives context"
        )
        _eprint(
            "  compaction -- you cannot reset it by forgetting. Exit code is 3."
        )
        _eprint(
            "  It clears itself on the first converged measurement, after "
            f"{BUDGET_STALE_AFTER_HOURS:.0f}h idle,"
        )
        _eprint(
            "  or via --reset-budget -- which is for a deliberate re-render, "
            "NOT for"
        )
        _eprint("  grinding the same edits past the cap.")

    def _emit_polish() -> None:
        """Replay the buffered polish output at the position it has always
        occupied: after the slack report, each stream on its own. In --json
        mode stdout stays pure JSON for the downstream pipe, so both are
        dropped and only `report["polish"]` + the exit code carry the verdict.
        Idempotent -- several exit paths call it, only the first does work."""
        nonlocal _polish_emitted
        if _polish_emitted or not (_polish_out or _polish_err):
            return
        _polish_emitted = True
        if getattr(args, "json", False):
            return
        print()
        print("=== POLISH (same render pass -- --with-polish) ===")
        sys.stdout.write(_polish_out)
        # Flush before touching stderr so the two land in this order under a
        # shell `>log 2>&1`, where they share one file description.
        sys.stdout.flush()
        if _polish_err:
            sys.stderr.write(_polish_err)
            sys.stderr.flush()

    def _finish_ok() -> int:
        """Non-breaker success exit. Emits the polish gates that already ran on
        the SHARED render (buffered above so the breaker could see their
        verdict first) and folds their result: the merged command exits
        non-zero if EITHER the fill gate (slack ``--strict``) or a polish gate
        (under the same ``--strict``) fails -- matching the staged-fill exit
        condition 'every section FULL and zero FIG/NARROW'. Without
        ``--strict`` polish is advisory (prints warnings, exit stays 0),
        exactly as a standalone ``polish`` run."""
        _emit_polish()
        return 1 if _polish_rc != 0 else 0

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({**report, "editTargets": edit_targets}, indent=2), encoding="utf-8"
        )
        print(f"[slack] raw report -> {ascii_safe(args.json_out)}")

    if args.json:
        sys.stdout.write(json.dumps({**report, "editTargets": edit_targets}, indent=2) + "\n")
        _emit_polish()
        if _breaker_hit:
            _emit_breaker()
            return 3
        if strict_fail:
            msg_parts = []
            if not_full:
                msg_parts.append(
                    f"non-FULL sections = {json.dumps(not_full)}"
                )
            if bad_figs:
                msg_parts.append(
                    f"non-OK figures = {json.dumps(bad_figs)}"
                )
            if suppress_secs:
                msg_parts.append(
                    f"DELETE wide scan section = {json.dumps(suppress_secs)}"
                )
            _eprint(
                "[slack] FAIL -- --strict: "
                + "; ".join(msg_parts)
            )
            return 1
        return _finish_ok()

    # Pretty-print: per-section verdicts are the main event. Column
    # slackRatio is still shown for continuity with old output, but the
    # per-section lines carry the fill ratios and verdict tags that
    # drive Tier-2 through Tier-6 decisions.
    _VERDICT_TAG = {
        "OVERFLOW": "  <- OVERFLOW (remove Additional / optional section)",
        "SPILLAGE": "  <- SPILLAGE (polish to reduce content)",
        "EMPTY":    "  <- EMPTY (add Additional / optional section)",
        "SPARSE":   "  <- SPARSE (polish to enhance content)",
        "FULL":     "",
    }
    for c in columns_out:
        cap = c.get("capacitySlack")
        if cap is None:
            budget = ""
        elif cap < 0:
            budget = f"  | budget={cap:+.0f}px OVER-PACKED (move content out / cut a figure or text)"
        elif cap < 0.10 * content_height:
            budget = f"  | budget={cap:+.0f}px TIGHT (stop adding here; steer new content to a looser column)"
        else:
            budget = f"  | budget={cap:+.0f}px (room to add)"
        print(
            f"col {c['index']}: width~={c['width']}px  "
            f"used={c['used']}px / {content_height}px  "
            f"slack={c['slack']}px ({c['slackRatio'] * 100:.1f}%){budget}"
        )
        for s in c["sections"]:
            fig = " [fig]" if s.get("hasFigure") else ""
            tag = _VERDICT_TAG.get(s["verdict"], "")
            need = ""
            np = s.get("needPx")
            if np is not None:
                rng = s.get("needPxRange")
                arrow = "grow" if np > 0 else "shrink"
                rng_s = f" [{rng[0]:+.0f}..{rng[1]:+.0f}]" if rng else ""
                need = f"  {arrow} {np:+.0f}px{rng_s}"
            print(
                f"    {s['id']:<18} h={s['used']:>4}px  "
                f"ratio={s['fullRatio'] * 100:>5.1f}%  "
                f"(fill={s['fillRatio'] * 100:>5.1f}%)  "
                f"{s['verdict']:<8}{fig}{tag}{need}"
            )
            if s.get("suppress"):
                print(
                    f"      ^ SUPPRESS: scan-to-read is wide+flat "
                    f"(w/h={s.get('aspectWH')} >= {SCAN_SUPPRESS_WH}) -- a lone QR "
                    "in empty space. DELETE this whole section now (lift its block "
                    "from EDIT TARGETS), then keep filling so the column's other "
                    "sections grow into the freed space."
                )
            # Slack-location hint for under-filled sections: which DIRECT
            # child has the most whitespace below it, and which lever to
            # pull. Lets the staged-fill loop target the exact element
            # instead of guessing where the column slack is.
            if s["verdict"] in ("SPARSE", "EMPTY"):
                _sgap = s.get("slackGapPx") or 0
                _sidx = s.get("slackElementIdx")
                _els = s.get("elements") or []
                if _sgap > 8 and _sidx is not None and 0 <= _sidx < len(_els):
                    _el = _els[_sidx]
                    _lever = (
                        "ENLARGE the figure (raise its max-height)"
                        if _el.get("isFigure")
                        else "GROW this element (add a line / promote Additional)"
                    )
                    print(
                        f"      slack {_sgap:.0f}px below [{_sidx}] "
                        f"<{_el.get('tag', '')}> "
                        f"\"{(_el.get('text') or '')[:36]}\"  -> {_lever}"
                    )
            # Per-figure line: width/height ratio of the figure to its
            # section card, plus a verdict tag mirroring polish.py
            # Gate A. Surfaced inline so a NARROW figure inside a FULL
            # section is impossible to miss in the staged-fill loop.
            f_info = s.get("figure")
            if f_info:
                fv = f_info.get("verdict", "OK")
                f_tag = ""
                if fv == "NARROW":
                    f_tag = (
                        f"  <- NARROW (figure < {FIG_MIN_RATIO * 100:.0f}% on "
                        "both axes; widen it)"
                    )
                elif fv == "OVERFLOW":
                    f_tag = (
                        f"  <- OVERFLOW (figure > {FIG_MAX_RATIO * 100:.0f}% "
                        "on an axis; shrink it)"
                    )
                elif fv == "BROKEN":
                    f_tag = "  <- BROKEN (image failed to load)"
                print(
                    f"      figure  w={f_info['w_ratio'] * 100:>5.1f}%  "
                    f"h={f_info['h_ratio'] * 100:>5.1f}%  "
                    f"{fv:<8}{f_tag}"
                )

    if edit_targets:
        print()
        print(
            "=== EDIT TARGETS (verbatim source of each off-band section -- edit "
            "these directly; do NOT re-Read poster.html) ==="
        )
        print(
            "    You MAY apply ONE edit per INDEPENDENT column this round -- "
            "columns don't cross-reflow except via width nudges, which stay "
            "OUT of the loop. Keep multiple edits to the SAME column one at a "
            "time so each rollback decision stays unambiguous."
        )
        for sid in not_full:
            blk = edit_targets.get(sid)
            if blk:
                print(f"\n--- {sid} ---")
                print(blk)

    print()
    print("verdict:", json.dumps(report["verdict"]))
    print()
    print("--- JSON ---")
    print(json.dumps(report))
    # Emit the polish result on EVERY exit path, not just the success one:
    # when slack strict-fails too, its warnings are still the other half of
    # what the round has to fix.
    _emit_polish()
    if _breaker_hit:
        _emit_breaker()
        return 3
    if strict_fail:
        msg_parts = []
        if not_full:
            msg_parts.append(f"non-FULL sections = {json.dumps(not_full)}")
        if bad_figs:
            msg_parts.append(f"non-OK figures = {json.dumps(bad_figs)}")
        if suppress_secs:
            msg_parts.append(f"DELETE wide scan section = {json.dumps(suppress_secs)}")
        _eprint(
            "[slack] FAIL -- --strict: " + "; ".join(msg_parts)
        )
        return 1
    return _finish_ok()
