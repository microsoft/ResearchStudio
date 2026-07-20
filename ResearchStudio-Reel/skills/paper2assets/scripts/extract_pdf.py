#!/usr/bin/env python3
"""Extract text, figures, AND figure captions from a research paper PDF.

Usage: extract.py <pdf> --outdir <dir>

Produces (under the canonical assets/ bundle layout — see utils/layout.py):
  <outdir>/assets/figures/      — PNG images extracted from the PDF
  <outdir>/assets/meta/text.txt — full text via pdftotext (layout-preserving)
  <outdir>/assets/meta/figures.json   — manifest [{file, page, width, height, caption, caption_label}, ...]
                            where `file` is the root-relative `assets/figures/<name>.png`.
  <outdir>/assets/meta/captions.json  — all "Figure N: ..." / "Table N: ..." captions parsed from text
                            keyed by label ("Figure 1", "Table 2", ...)
  <outdir>/assets/meta/metadata.json  — first-page metadata: {venue, year, emails, code_url,
                            project_url, paper_url, arxiv_id, doi}
                            Every field is best-effort; unparseable fields are empty
                            strings (or empty lists for `emails`). Never fabricated.

Why captions matter: a poster lives or dies on picking the right figure (architecture
diagram, headline results plot) and skipping decorative or equation-as-image junk.
Captions are the cheapest, most reliable signal of what a figure actually shows, so
we extract them alongside the images and let the model match figures to captions.
"""
import argparse, json, re, subprocess, sys
from urllib.parse import urlparse
from pathlib import Path

# Make `utils` importable when this file is run directly (mirrors the pattern in
# paper2poster/scripts/check_poster.py) so all paper2assets scripts share one
# canonical bundle layout (utils/layout.py).
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from utils import layout  # noqa: E402


# Match captions like:
#   "Figure 1: ..."   "Figure 1. ..."   "Fig. 2: ..."   "Table 3: ..."
# Captions can span multiple lines until a blank line or the next caption-like header.
# In two-column PDFs, captions often appear in the right column mid-line, so we also
# match after 2+ spaces (a column gutter) — not just at line start.
CAPTION_HEADER_RE = re.compile(
    r"^\s*(?P<label>(?:Figure|Fig\.?|Table)\s+\d+)\s*[:.]\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
CAPTION_MID_RE = re.compile(
    r"(?:^|\s{2,})(?P<label>(?:Figure|Fig\.?|Table)\s+\d+)\s*[:.]\s+(?P<rest>\S.*)$",
)


def extract_text(pdf: Path, out: Path) -> str:
    text = subprocess.check_output(
        ["pdftotext", "-layout", str(pdf), "-"], text=True, errors="replace"
    )
    out.write_text(text)
    return text


def parse_captions(text: str) -> dict[str, str]:
    """Scan layout-preserved text for "Figure N: ..." / "Table N: ..." captions.

    Captions in two-column papers can wrap awkwardly; we accumulate continuation
    lines until we hit a blank line or another caption-looking line. The returned
    dict maps normalized labels ("Figure 1", "Table 2") to caption text.
    """
    lines = text.splitlines()
    captions: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = CAPTION_HEADER_RE.match(lines[i]) or CAPTION_MID_RE.search(lines[i])
        if not m:
            i += 1
            continue
        label_raw = m.group("label")
        # Normalize "Fig. 2" / "Fig 2" / "FIGURE 2" -> "Figure 2".
        # Use \b so we don't turn "Figure" into "Figureure".
        label = re.sub(
            r"^(?:Figure|Fig\.?)\b", "Figure", label_raw, flags=re.IGNORECASE
        ).strip()
        label = re.sub(r"\s+", " ", label)
        buf = [m.group("rest").strip()]
        j = i + 1
        # Collect continuation lines until a blank line or a new caption header.
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                break
            if CAPTION_HEADER_RE.match(nxt):
                break
            # Stop if we hit what looks like a section heading (short ALLCAPS or
            # a numbered section like "3.1 G1: ...").
            if re.match(r"^\s*\d+(\.\d+)*\s+[A-Z]", nxt):
                break
            buf.append(nxt.strip())
            j += 1
            # Captions are rarely longer than ~12 lines; cap to keep noise out.
            if j - i > 12:
                break
        caption = " ".join(s for s in buf if s).strip()
        # Compress whitespace.
        caption = re.sub(r"\s+", " ", caption)
        if caption and label not in captions:
            captions[label] = caption
        i = j if j > i else i + 1
    return captions


def find_captions_on_page(text: str, page: int) -> list[tuple[str, str]]:
    """Return (label, caption) pairs whose first line appears on the given page.

    pdftotext with -layout preserves page breaks as form-feed (\f) between pages,
    so we split on \f to recover per-page text and scan each page independently.
    Falls back to empty list if the page is out of range.
    """
    pages = text.split("\f")
    if page < 1 or page > len(pages):
        return []
    page_text = pages[page - 1]
    found = []
    for label, caption in parse_captions(page_text).items():
        found.append((label, caption))
    return found


def _find_caption_rects(page, captions: list[tuple[str, str]], page_text_dict=None):
    """Locate the bounding rect of each caption header on the page.

    Returns list of (label, caption_text, rect). Captions whose header text
    can't be located on the page (rare — usually OCR/ligature mismatches) are
    skipped so we don't generate orphan crops.

    page.search_for(label) matches EVERY occurrence — including in-text mentions
    like "as shown in Figure 1, ...". To avoid picking a body-text mention as
    the caption rect we score each candidate by:
      - line that starts with the label (e.g. "Figure 1:" / "Figure 1.") wins
      - rect that visually matches a caption layout (typically near a figure)
      - fall back to the topmost match if nothing scores well
    """
    import fitz
    # Build a list of (line_rect, line_text) tuples once.
    line_index: list[tuple[fitz.Rect, str]] = []
    if page_text_dict is None:
        try:
            page_text_dict = page.get_text("dict")
        except Exception:
            page_text_dict = {"blocks": []}
    for b in page_text_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            line_index.append((fitz.Rect(ln["bbox"]), txt))

    def line_for_rect(r):
        """Return the text of the line containing r (or empty string)."""
        for lb, txt in line_index:
            # Treat as "containing" if the rect's center sits inside the line bbox.
            cx = (r.x0 + r.x1) / 2
            cy = (r.y0 + r.y1) / 2
            if lb.x0 - 1 <= cx <= lb.x1 + 1 and lb.y0 - 1 <= cy <= lb.y1 + 1:
                return txt
        return ""

    out = []
    for label, text in captions:
        rects = page.search_for(label)
        if not rects:
            num = label.split()[-1]
            for variant in (f"Fig. {num}", f"Fig {num}", label.upper()):
                rects = page.search_for(variant)
                if rects:
                    break
        if not rects:
            continue

        # Score: a real caption line starts with "Figure N:" or "Figure N.".
        # In-text mentions usually look like "...in Figure N, ..." or "...see
        # Figure N." mid-sentence.
        num = label.split()[-1]
        caption_start_re = re.compile(
            rf"^\s*(?:Figure|Fig\.?)\s*{re.escape(num)}\s*[:.]",
            re.IGNORECASE,
        )

        def score(r):
            line_txt = line_for_rect(r).strip()
            if caption_start_re.match(line_txt):
                return 0  # best — caption header
            # Penalize body-text mentions (sentences containing the label).
            if line_txt and not caption_start_re.match(line_txt):
                return 2
            return 1  # unknown line

        # Sort by score, then by y-position (topmost wins on ties — but since
        # captions typically appear LOW on the figure block, prefer larger y on
        # tie-broken score==0). Actually for score==0 we want any of them; pick
        # the bottommost since multi-line caption headers will repeat the label.
        rects_scored = sorted(
            rects,
            key=lambda r: (score(r), -r.y0),  # lowest score, then bottom-most
        )
        chosen = rects_scored[0]
        if score(chosen) >= 2:
            # No real caption line found — likely the label only appears in
            # body text on this page. Skip rather than crop the wrong region.
            continue
        out.append((label, text, chosen))
    return out


def _collect_graphic_rects(page) -> list:
    """Collect bounding rects of all *meaningful* graphic content on the page.

    Combines:
      - Raster image rects (figure photos, screenshots, chart bitmaps).
      - Vector drawing rects (matplotlib SVG-style plots, arrows, diagram boxes).

    Filters:
      - Tiny rects (<8pt either dim) — hairlines and bullet dots.
      - Page-sized white/near-white fills — figure backdrops sometimes span the
        whole page width or even past page margins; these massively inflate
        cluster bounds. We drop any fill rect covering >40% of page area,
        and any near-white fill covering >15% (white backdrops are decorative).
    """
    import fitz
    page_area = page.rect.width * page.rect.height
    rects = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for r in page.get_image_rects(xref):
                if r.width >= 8 and r.height >= 8:
                    rects.append(fitz.Rect(r))
        except Exception:
            continue
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r is None:
                continue
            r = fitz.Rect(r)
            if r.width < 8 or r.height < 8:
                continue
            area = r.width * r.height
            fill = d.get("fill")
            # Detect near-white fills (each channel >= 0.92).
            is_white = (
                fill is not None
                and len(fill) >= 3
                and all(c >= 0.92 for c in fill[:3])
            )
            # Drop oversize page backdrops.
            if area > 0.40 * page_area:
                continue
            if is_white and area > 0.15 * page_area:
                continue
            rects.append(r)
    except Exception:
        pass
    return rects


def _cluster_rects(rects, gap_x: float = 14.0, gap_y: float = 14.0, page_rect=None) -> list:
    """Union-find cluster of rects: any two rects within gap_x/gap_y merge.

    Used to glue a multi-panel figure's sub-images and the surrounding vector
    arrows/labels into one figure group, while keeping distinct figures apart.
    Gaps are tuned for typical academic-paper spacing (~12pt line-height).
    If page_rect is provided, cluster bounds are clipped to the page so off-page
    drawing artifacts don't inflate the crop region.
    """
    import fitz
    n = len(rects)
    if n == 0:
        return []
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def overlaps(a, b):
        return not (
            a.x1 + gap_x < b.x0 or b.x1 + gap_x < a.x0 or
            a.y1 + gap_y < b.y0 or b.y1 + gap_y < a.y0
        )

    for i in range(n):
        for j in range(i + 1, n):
            if overlaps(rects[i], rects[j]):
                union(i, j)

    groups = {}
    for i, r in enumerate(rects):
        root = find(i)
        if root not in groups:
            groups[root] = fitz.Rect(r)
        else:
            groups[root].include_rect(r)

    out = list(groups.values())
    if page_rect is not None:
        clipped = []
        for g in out:
            g = fitz.Rect(g) & page_rect
            if g.width >= 8 and g.height >= 8:
                clipped.append(g)
        out = clipped
    return out


def detect_columns(page, page_text_dict=None) -> list:
    """Detect text columns by histogramming text-line left edges.

    Returns a list of fitz.Rect column boxes (top-to-bottom full page height,
    column-width). Works for 1- and 2-column academic layouts. Falls back to
    a single full-width column if not enough text lines are present (e.g., a
    figure-only page).

    Algorithm:
      1. Collect x0 (left edge) of each non-trivial text line.
      2. Bucket x0 into 5pt bins and keep peaks (>= 10% of total lines).
      3. Merge peaks closer than 30pt (handles indented first lines of
         paragraphs which create a secondary near-peak).
      4. Each peak becomes a column's left edge; the next peak (or page right
         margin) defines its right edge.
    """
    import fitz
    from collections import Counter

    if page_text_dict is None:
        try:
            page_text_dict = page.get_text("dict")
        except Exception:
            page_text_dict = {"blocks": []}

    page_w = page.rect.width
    x0s = []
    for b in page_text_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            r = fitz.Rect(ln["bbox"])
            # Skip very short or very wide lines — neither anchors a column.
            if r.width < 50 or r.width > 0.85 * page_w:
                continue
            x0s.append(int(r.x0))

    if len(x0s) < 8:
        # Not enough body text to infer columns — treat as single column.
        return [fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)]

    buckets = Counter()
    for x in x0s:
        buckets[(x // 5) * 5] += 1
    total = sum(buckets.values())
    # Peaks: buckets carrying >=10% of total line-starts.
    peaks = sorted(x for x, c in buckets.items() if c >= 0.10 * total)
    if not peaks:
        return [fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)]

    # Merge peaks closer than 30pt (paragraph indent ≠ new column).
    merged = []
    for p in peaks:
        if not merged or p - merged[-1] >= 30:
            merged.append(p)

    # Academic papers use 1 or 2 columns. If we detect more, it's usually
    # noise from in-figure text or table cells — collapse to the 2 strongest
    # peaks (most line-starts).
    if len(merged) > 2:
        scored = sorted(merged, key=lambda x: -buckets[x])[:2]
        merged = sorted(scored)

    cols = []
    for i, left in enumerate(merged):
        if i + 1 < len(merged):
            right = merged[i + 1] - 4
        else:
            right = page.rect.x1
        cols.append(fitz.Rect(left, page.rect.y0, right, page.rect.y1))
    return cols


def figure_column_membership(rect, cols, page_rect) -> str:
    """Classify a rect as occupying 'col-0', 'col-1', ..., or 'full' (spans all).

    A rect "occupies" a column if it overlaps >50% of that column's width OR
    the column overlaps >50% of the rect's width (catches figures narrower
    than the column itself).
    """
    if len(cols) <= 1:
        return "full"
    text_width = cols[-1].x1 - cols[0].x0
    # Caption/figure spanning >75% of total text width is a full-width figure.
    if rect.width > 0.75 * text_width:
        return "full"
    occupied = []
    for i, c in enumerate(cols):
        overlap = max(0.0, min(rect.x1, c.x1) - max(rect.x0, c.x0))
        if c.width > 0 and overlap / c.width > 0.5:
            occupied.append(i)
            continue
        if rect.width > 0 and overlap / rect.width > 0.5:
            occupied.append(i)
    if len(occupied) >= len(cols):
        return "full"
    if len(occupied) == 1:
        return f"col-{occupied[0]}"
    if len(occupied) > 1:
        # Spans some but not all columns — treat as full for safety.
        return "full"
    # No column claims it; assign to the column whose center is closest.
    rect_xmid = (rect.x0 + rect.x1) / 2
    nearest = min(range(len(cols)),
                  key=lambda i: abs(rect_xmid - (cols[i].x0 + cols[i].x1) / 2))
    return f"col-{nearest}"


def _caption_line_rect(cap_rect, page_text_dict):
    """Find the bbox of the entire caption first-line (not just the label).

    page.search_for("Figure 2") only matches the label text, giving a tiny
    rect. To know whether the figure is single- or full-width we need the
    width of the caption *line* it sits in, which we get from the text-dict.
    """
    import fitz
    for b in page_text_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            lb = fitz.Rect(ln["bbox"])
            cx = (cap_rect.x0 + cap_rect.x1) / 2
            cy = (cap_rect.y0 + cap_rect.y1) / 2
            if lb.x0 - 1 <= cx <= lb.x1 + 1 and lb.y0 - 1 <= cy <= lb.y1 + 1:
                return lb
    return cap_rect  # fallback


def extract_figures_pymupdf(pdf: Path, figdir: Path, text: str) -> list[dict]:
    """Render each figure as a single image (all sub-panels, no caption text).

    Strategy — caption-anchored, cluster-based region detection:
      1. Find every figure caption's bbox on the page (tables are skipped).
      2. Build figure-content clusters by unioning nearby raster images AND
         vector drawings (so matplotlib plots / vector diagrams are detected).
      3. For each caption, attach the closest cluster above it whose horizontal
         span overlaps the caption's column — this keeps figures in column N
         from sweeping up content from column N+1.
      4. Crop just the figure region at 6× zoom (~432 dpi); caption text is
         clamped off the bottom edge. Caption text is still stored in
         figures.json.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    figdir.mkdir(parents=True, exist_ok=True)
    manifest = []
    doc = fitz.open(pdf)
    zoom = fitz.Matrix(6.0, 6.0)

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        captions = find_captions_on_page(text, page_num)
        if not captions:
            continue

        # Skip tables — we only want figure images. Tables are better consumed
        # as structured text, and their bitmap crops bloat the manifest.
        captions = [(lbl, txt) for lbl, txt in captions if lbl.lower().startswith("figure")]
        if not captions:
            continue

        # Compute the page's text-dict once and reuse it for caption rect
        # resolution and the per-figure text-absorption pass.
        try:
            page_text_dict = page.get_text("dict")
        except Exception:
            page_text_dict = {"blocks": []}

        caption_rects = _find_caption_rects(page, captions, page_text_dict=page_text_dict)
        if not caption_rects:
            continue
        caption_rects.sort(key=lambda t: t[2].y0)

        # All graphic rects (raster + vector), then cluster into figure groups.
        graphic_rects = _collect_graphic_rects(page)
        clusters = _cluster_rects(graphic_rects, page_rect=page.rect)

        # Detect the page's column geometry once. Used to (a) reject cross-
        # column candidate clusters, (b) make prev_y blocking column-aware,
        # and (c) annotate each figure as "col-N" or "full".
        cols = detect_columns(page, page_text_dict=page_text_dict)

        page_rect = page.rect
        used_clusters: set[int] = set()

        # Precompute, per caption: full caption-line bbox AND multi-line
        # caption block (header + wrapped continuation lines). cap_full is
        # what we clamp against to keep caption text out of the figure crop.
        # cap_full.y1 is what we use as a `prev_y` blocker for downstream
        # captions, so a wrapped caption's later lines don't leak into the
        # next figure's search band.
        def _build_cap_full(cap_rect):
            cap_line = _caption_line_rect(cap_rect, page_text_dict)
            cap_full = fitz.Rect(cap_line)
            changed_cap = True
            while changed_cap:
                changed_cap = False
                for b in page_text_dict.get("blocks", []):
                    if b.get("type") != 0:
                        continue
                    for ln in b.get("lines", []):
                        lb = fitz.Rect(ln["bbox"])
                        if lb.intersects(cap_full):
                            continue
                        if lb.y0 < cap_full.y1 - 2 or lb.y0 > cap_full.y1 + 14:
                            continue
                        h_overlap = max(0.0, min(lb.x1, cap_full.x1) - max(lb.x0, cap_full.x0))
                        if h_overlap < 0.5 * min(lb.width, cap_full.width):
                            continue
                        cap_full.include_rect(lb)
                        changed_cap = True
            return cap_full

        caption_fulls = [_build_cap_full(c[2]) for c in caption_rects]

        # Pre-classify each caption's column for column-aware filtering.
        # Use the full caption line's width (not just the label rect) so we
        # can tell single-column captions from full-width captions.
        caption_cols = [
            figure_column_membership(caption_fulls[i], cols, page_rect)
            for i in range(len(caption_rects))
        ]

        for fig_idx, (label, cap_text, cap_rect) in enumerate(caption_rects):
            cap_col = caption_cols[fig_idx]
            cap_full = caption_fulls[fig_idx]

            # Upper search bound = bottom of the previous caption's full
            # block IF its column matches this caption's column (or either
            # is full-width). Using cap_full.y1 (not cap_rect.y1) ensures a
            # wrapped multi-line caption fully blocks downstream figures.
            prev_y = page_rect.y0
            for pi, prior in enumerate(caption_rects[:fig_idx]):
                prior_col = caption_cols[pi]
                if cap_col == "full" or prior_col == "full" or prior_col == cap_col:
                    prev_y = max(prev_y, caption_fulls[pi].y1)

            # Candidate clusters: at least partly above the caption, with the
            # bulk of their content sitting in this caption's vertical band,
            # AND in the same column as the caption.
            best = None  # (key, idx, rect)
            for ci, cl in enumerate(clusters):
                if ci in used_clusters:
                    continue
                # Cluster must START above the caption block (figure is above
                # caption — use cap_full.y0 so wrapped captions are respected).
                if cl.y0 > cap_full.y0 - 2:
                    continue
                # Cluster top must sit at-or-below the previous caption's
                # column-aware bound (prev_y is already column-filtered above),
                # so we don't steal content from a figure further up the page
                # in the same column.
                if cl.y0 < prev_y - 2:
                    continue
                # Most of the cluster's area should be in the band above the
                # caption (drop clusters that mostly live below it — those
                # belong to the next figure / page footer).
                effective_y1 = min(cl.y1, cap_full.y0)
                above_height = max(0.0, effective_y1 - cl.y0)
                if cl.height > 0 and above_height / cl.height < 0.4:
                    continue
                # Column-aware filter: cluster's column must match the
                # caption's column (or either is "full" — full-width figures
                # naturally span all columns).
                cl_col = figure_column_membership(cl, cols, page_rect)
                col_ok = (
                    cap_col == "full"
                    or cl_col == "full"
                    or cl_col == cap_col
                )
                if not col_ok:
                    continue
                # Prefer the cluster whose bottom is nearest above the caption
                # (smallest gap); tie-break on larger above-caption area.
                gap = max(0.0, cap_full.y0 - effective_y1)
                key = (gap, -above_height * cl.width)
                if best is None or key < best[0]:
                    best = (key, ci, cl)

            if best is not None:
                _, ci, region = best
                used_clusters.add(ci)
                # Greedily merge ALL other clusters that belong to this same
                # figure. A figure with sub-panels (e.g., "Figure 3: (a) ...
                # (b) ... (c) ...") may render the panels with gaps wider than
                # _cluster_rects' threshold, leaving each panel as its own
                # cluster. The caption owns ONE figure, so any unclaimed
                # cluster sitting in this caption's vertical band AND column
                # must be a sibling sub-panel — pull them all in.
                changed = True
                while changed:
                    changed = False
                    for ci2, cl2 in enumerate(clusters):
                        if ci2 in used_clusters:
                            continue
                        # Vertical band gate: must sit above the caption and
                        # below the column-aware previous-caption bound.
                        if cl2.y0 > cap_full.y0 - 2 or cl2.y0 < prev_y - 2:
                            continue
                        # Column gate: must be in the same column (or either
                        # is full-width).
                        cl2_col = figure_column_membership(cl2, cols, page_rect)
                        if not (cap_col == "full" or cl2_col == "full" or cl2_col == cap_col):
                            continue
                        # Must mostly live above the caption (same 40% rule).
                        eff_y1 = min(cl2.y1, cap_full.y0)
                        above = max(0.0, eff_y1 - cl2.y0)
                        if cl2.height > 0 and above / cl2.height < 0.4:
                            continue
                        # Accept any cluster within the same horizontal band
                        # (sub-panels are side-by-side) OR vertical band
                        # (sub-panels are stacked). The 80pt slack handles
                        # captions like "(a) blah \n (b) blah" between panels.
                        horiz_neighbor = (
                            cl2.y0 <= region.y1 + 80 and cl2.y1 >= region.y0 - 80
                            and cl2.x0 <= region.x1 + 60 and cl2.x1 >= region.x0 - 60
                        )
                        if horiz_neighbor:
                            region = fitz.Rect(region)
                            region.include_rect(cl2)
                            used_clusters.add(ci2)
                            changed = True
                x0, y0, x1, y1 = region.x0, region.y0, region.x1, region.y1
                # Clamp bottom edge to sit above the caption block — the
                # figure crop should contain the figure image only; caption
                # text lives in figures.json.
                y1 = min(y1, cap_full.y0 - 1)
            else:
                # No graphic cluster found above this caption — likely an
                # orphan caption parse or a figure rendered as text-only. Skip
                # rather than guess.
                continue

            # Symmetric padding around the detected figure region — generous
            # enough to keep axis labels, legends, and panel borders intact
            # without pushing into the caption (already clamped above via
            # `y1 = min(y1, cap_full.y0 - 1)`). Wide pad gives the Step 5.6
            # agent-style crop loop real whitespace to work with — at pad=12
            # the legend's top half was already amputated in the extract, so
            # the crop loop couldn't recover. At pad=50 the agent can decide
            # exactly where to cut.
            pad_x = 50
            pad_y = 50
            clip = fitz.Rect(
                max(page_rect.x0, x0 - pad_x),
                max(page_rect.y0, y0 - pad_y),
                min(page_rect.x1, x1 + pad_x),
                min(page_rect.y1, y1 + pad_y),
            )

            if clip.width < 50 or clip.height < 30:
                continue

            try:
                pix = page.get_pixmap(matrix=zoom, clip=clip, alpha=False)
                safe_label = re.sub(r"\W+", "", label).lower()
                fname = f"page{page_num}_{safe_label}.png"
                fpath = figdir / fname
                pix.save(str(fpath))

                # Classify column span from the relationship between the
                # actual rendered figure width and the page width. Both must
                # be in the same unit — pixmap width is pixels at `zoom`× the
                # PDF point size, so we scale page dimensions to match.
                # Threshold tuned for 2-col academic layouts:
                #   - >= 60% of page width → spans the full text area ("full")
                #   - else → single-column; sub-classify by which half the
                #     figure's center sits in.
                zoom_factor = zoom.a  # uniform 2.0
                page_w_px = page_rect.width * zoom_factor
                page_h_px = page_rect.height * zoom_factor
                width_ratio = pix.width / page_w_px if page_w_px else 0
                fig_xmid_pt = (clip.x0 + clip.x1) / 2
                if width_ratio >= 0.60:
                    col_label = "full"
                    num_cols_eff = 1
                else:
                    # Single-column figure on a presumably 2-col page.
                    num_cols_eff = 2
                    col_label = "col-0" if fig_xmid_pt < page_rect.width / 2 else "col-1"

                manifest.append({
                    "file": f"{layout.FIGURES}/{fname}",
                    "page": page_num,
                    "page_width": round(page_w_px),
                    "page_height": round(page_h_px),
                    "width": pix.width,
                    "height": pix.height,
                    "column": col_label,
                    "num_columns": num_cols_eff,
                    "caption_label": label,
                    "caption": cap_text,
                    "caption_candidates": [{"label": label, "text": cap_text}],
                })
                pix = None
            except Exception as e:
                print(f"  skip {label} on p{page_num}: {e}", file=sys.stderr)

    doc.close()
    return manifest


def parse_metadata(text: str) -> dict:
    """Best-effort extraction of cover-page metadata from the first ~2 pages.

    Returns a dict with these keys (always present, possibly empty):
      - venue:       e.g. "NeurIPS", "ICML", "CVPR", "ICLR", "ACL", "EMNLP" (or "")
      - year:        4-digit string (or "")
      - emails:      list of contact email addresses (deduped, lowercased)
      - code_url:    GitHub/GitLab project URL, if any (or "")
      - project_url: a "project page" / website URL, if any (or "")
      - paper_url:   arXiv abs/pdf URL or other paper-hosting URL (or "")
      - arxiv_id:    bare arXiv id like "1706.03762" (or "")
      - doi:         DOI like "10.1145/3534678.3539200" (or "")

    Strategy: scan the first two `\\f`-delimited pages (cover + sometimes
    spillover). Use multiple regexes per field; first hit wins. No guessing —
    if a field can't be extracted, leave it empty. The poster renderer will
    fall back to "unknown" / omit-the-element when fields are missing.
    """
    pages = text.split("\f")
    head = "\n".join(pages[:2]) if pages else ""

    metadata = {
        "venue": "",
        "year": "",
        "emails": [],
        "code_url": "",
        "project_url": "",
        "paper_url": "",
        "arxiv_id": "",
        "doi": "",
    }

    # --- Emails ---
    # Standard email regex; lowercased + deduped, preserving first-seen order.
    email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    seen_email = set()
    for m in email_re.finditer(head):
        e = m.group(0).lower().rstrip(".,;")
        if e not in seen_email:
            seen_email.add(e)
            metadata["emails"].append(e)

    # --- arXiv id + paper_url ---
    # Matches "arXiv:1706.03762v7", "arXiv:cs.CL/0301012", or bare "1706.03762".
    arxiv_re = re.compile(
        r"arXiv[:\s]*([0-9]{4}\.[0-9]{4,5})(?:v\d+)?",
        re.IGNORECASE,
    )
    m = arxiv_re.search(head)
    if m:
        metadata["arxiv_id"] = m.group(1)
        metadata["paper_url"] = f"https://arxiv.org/pdf/{m.group(1)}"

    # --- DOI ---
    doi_re = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
    m = doi_re.search(head)
    if m:
        metadata["doi"] = m.group(1).rstrip(".,;")

    # --- Code URL (GitHub / GitLab / Bitbucket) ---
    code_re = re.compile(
        r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org)/"
        r"[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+",
        re.IGNORECASE,
    )
    m = code_re.search(head)
    if m:
        metadata["code_url"] = m.group(0).rstrip(".,);")

    # --- Project page URL ---
    # Heuristic: a URL on a line containing "project page", "website",
    # "demo", or that looks like a github.io / *.io / *.dev / personal-site URL.
    # Pick the first URL we see that's NOT the code_url and NOT arXiv.
    url_re = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
    candidates = []
    for line in head.splitlines():
        line_lower = line.lower()
        is_project_line = any(
            kw in line_lower for kw in ("project page", "website", "homepage", "demo", "project:")
        )
        for m in url_re.finditer(line):
            url = m.group(0).rstrip(".,);")
            if url == metadata["code_url"]:
                continue
            if "arxiv.org" in url:
                continue
            parsed_host = urlparse(url).hostname or ""
            is_github_io = parsed_host == "github.io" or parsed_host.endswith(".github.io")
            if is_github_io or is_project_line or re.search(r"\.(io|dev|page)/", url):
                candidates.append(url)
    if candidates:
        metadata["project_url"] = candidates[0]

    # --- Venue + year ---
    # Common venue marker patterns near the title:
    #   "31st Conference on Neural Information Processing Systems (NIPS 2017)"
    #   "Proceedings of the 40th International Conference on Machine Learning"
    #   "Published as a conference paper at ICLR 2024"
    #   "Accepted to ACL 2023"
    #   "CVPR 2024", "ICML 2023", "NeurIPS 2024", "ICLR 2025", "AAAI 2024"
    venue_year_re = re.compile(
        r"\b(NeurIPS|NIPS|ICML|ICLR|CVPR|ECCV|ICCV|ACL|EMNLP|NAACL|"
        r"AAAI|IJCAI|KDD|SIGGRAPH|UAI|COLT|AISTATS|WACV|BMVC|"
        r"INTERSPEECH|ICASSP|ICRA|IROS|RSS)\s*[''']?\s*(\d{4})\b",
        re.IGNORECASE,
    )
    m = venue_year_re.search(head)
    if m:
        venue = m.group(1).upper()
        # Normalize NIPS → NeurIPS (the venue renamed in 2018; modern usage prefers NeurIPS).
        if venue == "NIPS":
            venue = "NeurIPS"
        metadata["venue"] = venue
        metadata["year"] = m.group(2)
    else:
        # Fall back: look for a bare 4-digit year on the cover (2010–2099 range).
        # Only accept if it appears near a "Conference"/"Workshop"/"Proceedings" keyword.
        for line in head.splitlines():
            if not re.search(r"\b(Conference|Workshop|Proceedings|Symposium)\b", line, re.IGNORECASE):
                continue
            ym = re.search(r"\b(20\d{2})\b", line)
            if ym:
                metadata["year"] = ym.group(1)
                break

    return metadata


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--no-figures", action="store_true",
                    help="skip figure extraction (write text.txt + captions.json only). "
                         "Use when source_figures.py already supplied the original figures.")
    args = ap.parse_args()

    pdf = Path(args.pdf).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting text from {pdf.name}...")
    text_path = layout.meta_file(outdir, "text", create_parent=True)
    text = extract_text(pdf, text_path)
    nchars = text_path.stat().st_size
    print(f"  text.txt: {nchars} chars")

    print("Parsing captions...")
    captions = parse_captions(text)
    layout.meta_file(outdir, "captions").write_text(json.dumps(captions, indent=2))
    print(f"  {len(captions)} captions parsed -> captions.json")
    for lbl in list(captions)[:5]:
        snippet = captions[lbl][:90].replace("\n", " ")
        print(f"    - {lbl}: {snippet}{'...' if len(captions[lbl])>90 else ''}")

    print("Parsing first-page metadata...")
    metadata = parse_metadata(text)
    layout.meta_file(outdir, "metadata").write_text(json.dumps(metadata, indent=2))
    populated = [k for k, v in metadata.items() if v]
    print(f"  metadata.json populated fields: {populated or '(none)'}")
    if metadata.get("venue") or metadata.get("year"):
        print(f"    venue/year: {metadata.get('venue','?')} {metadata.get('year','?')}")
    if metadata.get("emails"):
        em = ", ".join(metadata["emails"][:3])
        more = "" if len(metadata["emails"]) <= 3 else f" (+{len(metadata['emails'])-3} more)"
        print(f"    emails: {em}{more}")
    if metadata.get("code_url"):
        print(f"    code: {metadata['code_url']}")
    if metadata.get("project_url"):
        print(f"    project: {metadata['project_url']}")
    if metadata.get("arxiv_id"):
        print(f"    arXiv: {metadata['arxiv_id']}")
    if metadata.get("doi"):
        print(f"    DOI: {metadata['doi']}")

    if args.no_figures:
        print("Skipping figure extraction (--no-figures; original figures supplied by source_figures.py).")
        return

    print("Extracting figures...")
    figdir = layout.figures_dir(outdir, create=True)
    figs = extract_figures_pymupdf(pdf, figdir, text)
    layout.meta_file(outdir, "figures").write_text(json.dumps(figs, indent=2))
    print(f"  {len(figs)} figures saved to {figdir}")
    if figs:
        for f in figs[:8]:
            cap_hint = f.get("caption_label") or "no caption found"
            print(f"    - {f['file']} ({f['width']}x{f['height']}, p{f['page']}) [{cap_hint}]")
        if len(figs) > 8:
            print(f"    ... and {len(figs)-8} more")
    else:
        print("  (no usable figures found — proceed text-only)")


if __name__ == "__main__":
    main()
