---
name: paper2assets
description: Extract a research paper PDF into a structured set of poster-agnostic assets reusable by any downstream renderer (paper2poster, paper2blog, paper2audio, paper2video). Produces a `<outdir>/` containing the paper's full text (assets/meta/text.txt), per-figure captions (assets/meta/captions.json), cleaned figure rasters (assets/figures/*.png + assets/meta/figures.json manifest), paper metadata (assets/meta/metadata.json: title / authors / institutes / venue / paper_url / code_url), institute logos (assets/logos/*), URL QR codes (assets/qr/*), and a 9-section structured paper summary (assets/meta/paper_spec.md). The bundle follows the Output Contract layout (deliverables at top, everything else under `assets/`). Use when the user wants to extract paper content into reusable assets, OR as the mandatory upstream stage of any paper-rendering pipeline — e.g., "extract this paper", "build paper assets", "get the figures and spec from this PDF", "paper2assets".
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, AskUserQuestion, WebFetch, WebSearch
---

# paper2assets — paper PDF → reusable assets

One paper PDF in, a single `<outdir>/` of poster-agnostic assets out, ready for any downstream renderer.

## Output Contract (the shared layout every paper2* skill follows)

paper2assets defines the on-disk shape of **every** deliverable bundle in the pipeline. paper2poster, html2pptx, paper2blog, paper2video, and paper2reel all read from and write to a bundle laid out this way — a teammate adding or changing a downstream skill conforms to this contract.

**Rules**
1. The bundle directory is named after the paper.
2. The bundle's **top level holds ONLY that skill's deliverable FILES** — no loose intermediates, and as few folders as possible.
3. **Every** dependency and intermediate (figures, logos, qr, audio, fonts, captions, slides, the spec / json / txt) lives under one **`assets/`** container.

**Layout**

```
<paper-name>/
|-- <deliverable files>          # see the per-skill table below
|-- manifest.json                # package index (root-relative paths); the one allowed top-level non-deliverable
`-- assets/
    |-- figures/  logos/  qr/  audio/  fonts/   # runtime deps the deliverables reference
    `-- meta/                                    # build intermediates
        |-- paper_spec.md  sections.json  narration.json
        `-- captions.json  figures.json  metadata.json  text.txt
```

Deliverables reference assets with **root-relative** `src` paths -- `assets/figures/...`, `assets/logos/...`, `assets/qr/...`, `assets/audio/...` -- so the bundle is self-contained and movable (no absolute paths leak in). The `path` / `file` fields in `figures.json`, `fetch_logos.py`, and `make_qr.py` output already carry the `assets/` prefix; downstream drops them into `src` verbatim.

**Per-skill deliverables (top-level FILES):**

| Skill | Top-level deliverable files |
|---|---|
| **paper2assets** | `manifest.json` (+ the whole `assets/` package) |
| **paper2poster** | `poster.html`, `poster.pdf`, `poster.png`, `poster.pptx` |
| **paper2blog** | `blog_zh.docx`, `blog_en.docx` |
| **paper2video** | `video.mp4`, `video_no_subtitles.mp4` |
| **paper2reel** | `reel.html` |

`manifest.json`'s `"files"` map records every meta / figure path (root-relative) plus a `"layout": "v2-assets"` marker, so a consumer can locate inputs and tell a new bundle from a legacy flat one without re-walking the tree.

```
   paper.pdf  (+ arXiv id / provided image links)
     │
     ▼  FIGURES — priority: source_figures.py (arXiv source / provided links) → clean assets/figures/*.png + figures.json
     │           └─ fallback only: extract_pdf.py crops from the rendered PDF
     ▼  scripts/extract_pdf.py   → assets/meta/{text.txt, captions.json} (+ figures.json only on the crop fallback; use --no-figures on the source path)
     │
     ▼  Step 3 (model-driven)    → assets/meta/metadata.json
     │
     ▼  Step 4 (model-driven)    → assets/meta/paper_spec.md  (9 canonical sections)
     │
     ▼  scripts/crop_figure.py   → cleaned assets/figures/*.png  (CROP FALLBACK ONLY — skipped when source_figures.py supplied the originals)
     │
     ▼  scripts/fetch_logos.py   → assets/logos/<slug>.{png,svg}
     ▼  scripts/fetch_conf_logo.py → assets/logos/_venue.png  (conference mark; best-effort, skips on miss)
     │
     ▼  scripts/make_qr.py       → assets/qr/{paper,code}.png
     │
     ▼  scripts/build_package.py → assets/meta/{sections.json, narration.json} + manifest.json
     │
     └──→ <outdir>/ — every downstream renderer reads from here

Downstream renderers (paper2poster, paper2blog, paper2audio, ...) consume this outdir; none should re-derive any of these files.
```

## Output contract

After paper2assets finishes, `<outdir>/` MUST contain:

| File | Source | Purpose |
|---|---|---|
| `assets/meta/text.txt` | Step 2 | Full PDF text via `pdftotext`. Page breaks preserved as `\f`. Authoritative source of numbers/claims for any downstream prose. |
| `assets/meta/captions.json` | Step 2 | `[{page, label, text}, ...]` per "Figure N: ..." caption detected in the PDF text. |
| `assets/meta/figures.json` | Step 2 + 5 | `[{file, width, height, page, layout}, ...]` per extracted figure raster. `layout` is `"full"` / `"col-0"` / `"col-1"` etc. — the source-page column placement. `width`/`height` are updated whenever crop_figure.py runs. |
| `assets/figures/<page>_figure<n>.png` | Step 2 + 5 | Cropped figure rasters @ zoom=6 (~432 dpi). Cleaned by Step 5's deterministic pipeline. |
| `assets/figures/_debug/<page>_figure<n>.png.bak` | Step 5 | One-shot backup of the raw extract before Step 5's first crop. Preserved across re-runs (never clobbered). Lives under `_debug/` so the top-level `figures/` listing stays clean — downstream renderers should only ever read from `figures/*.png`. |
| `assets/figures/_debug/<page>_figure<n>.marked-<NN>.png` | Step 5d | Per-iteration overlay showing the bbox each `mark` call proposed (`-01`, `-02`, ...). Audit trail of the bbox-decision history. Never touched by downstream. |
| `assets/meta/metadata.json` | Step 3 | `{title, authors[], author_index_map{}, institutes[], venue, paper_url, code_url?}`. |
| `assets/meta/paper_spec.md` | Step 4 | 9-section structured summary (Problem / Motivation / Contribution / Method / Dataset/Benchmark / Key Result / Ablation Study / Headline Numbers / Takeaway), each section with `Necessary` + `Additional` + `Audio script` subfields. Plus a YAML preamble with title/authors/institutes/venue and audio scripts. |
| `assets/logos/<slug>.{png,svg}` | Step 6 | One logo per institute: Wikimedia Commons first, then a MANDATORY WebSearch/WebFetch fallback (`--add-logo`) for any institute the deterministic pass reports in its `"missing"` list — so logos should rarely be absent. Only genuinely unfindable institutes are dropped. |
| `assets/qr/{paper,code}.png` | Step 6 | QR codes for the paper's links. `make_qr.py` classifies `paper_url`/`project_url`/`code_url` by destination (Paper/Code/Project), **de-duplicates by URL**, and writes up to two slots (slot 0 → `paper.png`, slot 1 → `code.png`) plus a `qr` manifest (path + `label`) into `metadata.json`. A one-link paper yields ONE QR (no `code.png`); the caption follows the URL, not the filename. |
| `assets/meta/sections.json` | Step 7 | `paper_spec.md` parsed to per-section JSON (stable ids + necessary / additional / audio_script). Consumed by paper2blog / paper2video. |
| `assets/meta/narration.json` | Step 7 | Audio **script** only — no mp3. TTS clip list `{provider, voice, sections:[{id, heading, text}]}` from the `**Audio script:**` markers (+ the title clip). Downstream renderers synthesize their own audio from this; paper2assets does NOT run TTS. |
| `manifest.json` | Step 7 | Package inventory (file paths + counts + source-PDF sha256). |

## Workflow

### Step 0 — Cache check (do this FIRST, before any other work)

Re-extracting a paper costs ~5-10 min of Claude tokens (figure-cleanup
visual review + spec synthesis) and risks clobbering edits the user may
have made to `paper_spec.md`, `metadata.json`, or cropped figures.
Before starting, **check whether the assets already exist** under the
default outdir convention (`outdir = <input_pdf_dir>/<pdf_stem>/`) or
the caller-supplied outdir:

```bash
required=("$outdir/assets/meta/paper_spec.md" "$outdir/assets/meta/text.txt" \
          "$outdir/assets/meta/figures.json" "$outdir/assets/meta/metadata.json")
all_present=1
for f in "${required[@]}"; do [[ -f "$f" ]] || all_present=0; done
[[ -d "$outdir/assets/figures" && \
   $(ls "$outdir/assets/figures"/*.png 2>/dev/null | wc -l) -gt 0 ]] \
  || all_present=0
```

If all five artifacts are present, REPORT the cached state in 1-2 lines
and STOP — do not re-extract:

```
[paper2assets] CACHED in <outdir> — assets from prior run, reusing.
  title: "<from metadata.json>"
  figures: N PNGs
  paper_spec.md: <line-count> lines, K sections
```

Re-extract ONLY when:
- one of the required artifacts is missing → resume from the missing step
  (Step 2 extract, Step 3 metadata, Step 4 spec, Step 5 cleanup, Step 6 logos/QR)
- the user explicitly requests it ("re-extract", "regenerate the spec",
  "force", "fresh", "from scratch"). In that case, delete or back up
  the existing `<outdir>/` first so the cache check doesn't fire.

### Step 1 — Validate the PDF path and pick an outdir

Required argument: path to a `.pdf` file. If the file doesn't exist or isn't a PDF, abort with a clear message.

Default outdir convention: `outdir = <input_pdf_dir>/<pdf_stem>/` — a folder under `papers/` named after the input PDF's basename (no extension). Example: `/work/job/ResearchStudio-Reel.pdf` → `/work/job/ResearchStudio-Reel/`. The caller may override with an explicit outdir argument.

Create `<outdir>/` if missing.

### Step 2 — Extract text + figures + captions

```bash
python ~/.claude/skills/paper2assets/scripts/extract_pdf.py <pdf> --outdir <outdir>
```

Writes:
- `assets/meta/text.txt` — full text via `pdftotext` (page breaks preserved as `\f`).
- `assets/meta/captions.json` — `[{page, label, text}, ...]` per detected "Figure N: ..." caption.
- `assets/meta/figures.json` — `[{file, width, height, page, layout}, ...]` per extracted figure raster.
- `assets/figures/<page>_figure<n>.png` — raster crop at zoom=6 (~432 dpi). The extractor uses a column-aware boundary heuristic + 50 px symmetric padding around the detected figure region so subsequent Step 5 cleanup has room to work.

**Figures — choose the source by priority (DO THIS; it is the biggest time/token saver).** The paper's ORIGINAL figure graphics are already clean (no baked caption strips, no column-text bleed) and skip the whole Step 5 crop loop (~6 min + heavy tokens). `scripts/source_figures.py` fetches them and writes `assets/figures/*.png` + `figures.json` in seconds:

1. **Provided image links (FIRST):** the user attached/linked figure images →
   `python ~/.claude/skills/paper2assets/scripts/source_figures.py --images <url|path> … --outdir <outdir>`
2. **arXiv (RECOMMENDED):** the paper is on arXiv →
   `python ~/.claude/skills/paper2assets/scripts/source_figures.py --arxiv <id|url> --outdir <outdir>`
   (downloads `arxiv.org/e-print/<id>`, parses the `.tex` figure order + captions, rasterizes each graphic).
3. **Backup (ONLY if 1 & 2 don't apply, or `source_figures.py` exits non-zero):** the PDF crop path below — full `extract_pdf.py` (with figures) **+ Step 5 `crop_figure.py`**.

**If `source_figures.py` succeeded (exit 0):** run `extract_pdf.py <pdf> --outdir <outdir> --no-figures` (text.txt + captions.json ONLY) and **SKIP Step 5 (`crop_figure.py`) entirely** — the source graphics are already clean. **Otherwise** run the full `extract_pdf.py <pdf> --outdir <outdir>` (with figures) and do Step 5.

**Appendix figures — skipped by DEFAULT.** Process **main-body figures only**. From `text.txt`, find where the appendix / supplementary material begins (the first `Appendix` / `Supplementary` heading, or `A.` / `B.` / `S1`… content after `References`) and note its `\f`-delimited page. **Drop every figure on or after that page** — delete the PNGs from `figures/` and their rows from `figures.json` *before* Step 5, so neither the cleaning loop nor any downstream renderer sees them. **Override only when the user explicitly asks** — e.g. "include the appendix figures" or naming a specific supplementary figure.

### Step 3 — Parse paper metadata

Read `text.txt`'s first page + (if the PDF is from arxiv) the arxiv abs page via WebFetch. Synthesize `<outdir>/assets/meta/metadata.json`:

```json
{
  "title": "...",
  "authors": ["First Last", "Second Author"],
  "author_index_map": {"First Last": [1, 2], "Second Author": [2]},
  "institutes": ["First Institute", "Second Institute"],
  "venue": "NeurIPS 2025",
  "paper_url": "https://arxiv.org/abs/...",
  "code_url": "https://github.com/..."
}
```

- `authors` — display order from the PDF byline.
- `author_index_map` — author → list of 1-indexed institute indices (matches the superscripts in the PDF byline).
- `institutes` — semicolon-separated list, **deduplicated**, in the same order as the numeric indices used in the Authors line (so index `1` = first institute, etc.).
- `venue` — the **real publication venue**: conference / journal short name + year ("NeurIPS 2025", "ICLR 2026", "TPAMI 2026"). **NEVER write "arXiv" (or "Preprint") as the venue** — arXiv is a preprint host, not a publication venue. A paper on arXiv is almost always *also* published at a conference/journal; find that real venue: check the arXiv abs page's **Comments** and **Journal ref** fields (e.g. "Accepted at NeurIPS 2022"), the paper's first-page banner ("Published as a conference paper at ICLR 2024"), or an OpenReview / proceedings listing. For a workshop paper, use the **parent conference** (a NeurIPS 2022 workshop poster → `"NeurIPS 2022"`). Only when no real venue can be found anywhere, leave it an **empty string** (the header then shows no venue badge) — but still never "arXiv".
- `paper_url` — arxiv abs link (preferred) or publisher landing page.
- `code_url` — optional; omit field if no code is released.

### Step 4 — Synthesize the 9-section paper_spec.md

Write `<outdir>/assets/meta/paper_spec.md` with the canonical 9 sections, each carrying three subfields (`Necessary` / `Additional` / `Audio script`) plus a YAML preamble:

```markdown
---
title: <paper title>
authors: <First Last¹, Second Author¹², ...>
institutes: ¹First Institute; ²Second Institute
venue: <venue or empty>
paper_url: <url>
code_url: <url or empty>
title_audio_script: <one-paragraph spoken intro>
---

## Problem
**Necessary:** <≤40 words, the gap this paper addresses>
**Additional:** <≤40 words, supporting context>
**Audio script:** <one paragraph>

## Motivation
...

## Contribution
...

## Method
...
**Key equation:** `$<core formula(s) as clean LaTeX>$`  <!-- 1–3 max: the objective / loss / governing equation that defines the method; transcribe symbols faithfully from text.txt, never fabricate; omit this subfield only if the paper genuinely has no formula -->

## Dataset / Benchmark
...

## Key Result
...

## Ablation Study
...

## Headline Numbers
...

## Takeaway
...
```

Section-by-section guidance:

1. **Problem** — 1–2 sentences naming the gap. `Additional` for context.
2. **Motivation** — 1–2 sentences for *why now*. `Additional` for the failure pattern of prior work.
3. **Contribution** — 1–3 sentences listing what this paper actually contributes. May be omitted by downstream renderers; still write it here.
4. **Method** — 2–4 sentences describing the proposed approach, in the paper's own vocabulary. **Add a `**Key equation:**` subfield** transcribing the paper's 1–3 core formulas (objective, loss, or governing equation) as clean inline LaTeX (`$…$`) — this is the single biggest gap downstream posters have versus author ground-truth. Copy symbols faithfully from `text.txt`; never invent. Omit the subfield only for genuinely formula-free papers (pure systems / empirical).
5. **Dataset / Benchmark** — describes the data the paper introduces OR uses standard benchmarks (renderers decide whether to render this section).
6. **Key Result** — the headline experimental finding in 1–3 sentences with the actual numbers.
7. **Ablation Study** — 1–3 sentences naming the most informative ablation rows. Omit if the paper has no ablations.
8. **Headline Numbers** — 1–4 metrics that summarize impact. Quantitative, traceable to text.txt — NEVER invented.
9. **Takeaway** — 1–2 sentences a passerby could repeat after one read.

`Audio script` subfields are full-sentence spoken paragraphs (3–6 sentences each) suitable for TTS. They are part of the spec because audio narration of *any* downstream rendering should be derivable from this single source.

### Step 5 — Clean ALL figure images (mandatory on the crop path — SKIPPED when source figures were used)

> **Skip this entire step** if Step 2 sourced the ORIGINAL figures via `source_figures.py` (arXiv source bundle or provided image links) — those graphics are already clean. Step 5 runs ONLY on the crop-path fallback (figures cropped from the rendered PDF).

Step 2 produces raw figure rasters that often carry:
- A 1–10 px **chrome residue** at the top edge (the bottom of a page rule line / banner / running title that the extractor's column-aware boundary couldn't perfectly avoid).
- A **baked-in caption strip** at the bottom (rare — `extract_pdf.py` already clamps to `cap_full.y0 - 1`, but a few papers have caption text fused into the figure raster).
- A uniform **white margin** of arbitrary thickness around the cleaned content (a side effect of the 50 px symmetric pad in Step 2 + caption-clamped tight tops).

Downstream renderers should receive **cleaned** figures, not raw extracts, so we run the deterministic cleanup pipeline on every figure here — independent of which figures any downstream actually picks. Cost is sub-second per figure × 3 commands × N figures = negligible. **Skip this entire step when the figures were pre-supplied** (Step 2's "already supplied?" branch): original source graphics carry none of the chrome / caption-strip / margin defects below.

**For each `figures/<file>.png`, run 5a → 5b → 5c in this exact order:**

**5a. `top-check` — strip top chrome residue.**

```bash
python ~/.claude/skills/paper2assets/scripts/crop_figure.py top-check <outdir>/assets/figures/<file>.png
```

Pattern-matches the chrome signature (1–15 px non-clean prefix + ≥3 px clean gutter + sustained figure content below). On `TOP-CHROME DETECTED — ... cut at y=Z`, re-run with `--apply` to strip. On `TOP clean — ...`, skip to 5b.

**5b. `decaption` — strip baked-in bottom caption strip (when present).**

```bash
python ~/.claude/skills/paper2assets/scripts/crop_figure.py decaption <outdir>/assets/figures/<file>.png
```

Fires only when there's a 1–3 line text band at the bottom separated from the figure body by a clear horizontal whitespace gap. Most figures won't trigger. On `DETECTED bottom caption band`, re-run with `--apply`. Otherwise skip to 5c.

**5c. `autotrim` — strip remaining uniform white margins (always last).**

```bash
python ~/.claude/skills/paper2assets/scripts/crop_figure.py autotrim <outdir>/assets/figures/<file>.png
```

Strips border rows/cols that are 100% near-white, keeping a `--pad 4` margin. Safe — never touches content pixels. **Must come AFTER 5a/5b** — `autotrim` stops at the first dark row, so any uncut chrome/caption traps a thick whitespace band that `autotrim` cannot reach.

All three modes write `figures/_debug/<file>.png.bak` (one-shot, never clobbered on re-runs) and update `figures.json` width/height. The top-level `figures/` directory keeps only the in-progress clean PNG — backups and other debug artifacts live in the hidden `_debug/` subdir so downstream consumers see a clean listing.

**5d. Visual AI cropping review (mandatory, runs on every figure).** The deterministic chain in 5a-5c handles uniform white margins, the chrome-residue pattern at the top edge, and the baked-in caption-strip pattern at the bottom edge. It does NOT handle:

- **Surrounding column body text leaked into the bbox** — when `extract_pdf.py`'s figure-region detection over-reaches into the paper's prose (a vertical strip of column text running alongside the figure, or a few lines of body paragraph above the figure). This is the most common defect, and it's *invisible* to autotrim/decaption: that text isn't a uniform white margin and isn't a thin caption sliver — it's *real ink* that paints similarly to figure content.
- **Caption text not caught by `decaption`'s thin-strip pattern** — captions that are tightly butted against the figure body, or captions that span 4+ lines (decaption refuses on caption blocks taller than ~15% of figure height to avoid amputating real figure content).
- **Adjacent-figure bleed** on multi-figure pages — a vertical strip of the neighboring panel.

These defects need *visual* judgment to identify and cut, but **eyeballing alone is too coarse** — visual estimates routinely miss small panel titles ("mAP", "AP_50"), under-include axis labels by ~50 px, and over-trust gaps that turn out to be content boundaries. So 5d's workflow grounds the visual judgment in two deterministic tools that turn "where exactly is this figure?" into a falsifiable, pixel-level question.

paper2assets owns this responsibility because:
1. Downstream renderers (paper2poster, paper2blog, paper2audio, paper2video) all want figures with **only the figure's own visual content** — surrounding paper text and captions are noise for every renderer.
2. Doing it once here is cheaper than each downstream re-doing it on its picks.
3. **The MAIN "Figure N: …" caption is NEVER part of the figure raster.** Its text is already in `<outdir>/assets/meta/captions.json` as structured data; baking those pixels into the PNG duplicates content and visually collides when downstream HTML/blog renderers add their own `<figcaption>`. **Panel sub-captions** like "(a) Pipeline overview" / "(b) Loss curves" are different — they label individual sub-panels, are part of the figure's visual content, and they STAY INSIDE the raster. Rule of thumb: if cutting it would leave the panels unlabeled, KEEP IT; if cutting it just removes a "Figure N: …" prose sentence already in `captions.json`, CUT IT.

**Workflow per figure (after 5a-5c have run):** the four steps below — analyze → judge → mark → verify → crop — exist as one loop so the bbox decision is committed only after a deterministic-grounded check AND a visual recheck both pass. Skipping the mark step (going straight from judge → crop) is the loop's most common failure mode: visual estimates from a downsampled Read are coarse, and a mis-estimated bbox commits a destructive crop in one shot. Mark first; commit only when the red box visibly encloses what you want.

**Process figures STRICTLY sequentially, ONE figure at a time end-to-end (hard rule).** Do not batch — do not run round-1 on all figures and then round-2 on all figures, do not invoke multiple sub-agent verifiers in parallel, do not Read figure A while reasoning about figure B's bbox. For each figure: complete every step (5d.i analyze → 5d.ii judge → 5d.iii mark → 5d.iv self-check + sub-agent verify ≥2 cycles → 5d.v commit), THEN move to the next figure. Cross-figure batching introduces two failure modes — sub-agent prompts can pick up the wrong figure's marked PNG (cross-context bleed), and your own per-edge reasoning can hallucinate elements from a sibling figure into the figure under judgment (cross-figure attention contamination). The cost of strict serial processing is real (no parallelism), but the verifier ambiguity it eliminates is worth it for correctness on every figure.

   **Step 5d.i — Analyze (deterministic, grounds the bbox decision in pixels):**
   ```bash
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py blocks <outdir>/assets/figures/<file>.png
   ```

   Prints the figure's ROW + COL ink-block structure (every dense band, every gap between bands, in pixel coordinates) plus heuristic hints flagging narrow blocks adjacent to the main body as "INCLUDE in bbox" (axis labels / legend / rotated y-title) versus blocks separated by a wide (>50 px) gap as "EXCLUDE unless visual recheck confirms it's figure content" (likely body-text column or adjacent figure). This output tells you exactly where each structural part of the figure sits in pixel space — no eyeballing dimensions.

   **Step 5d.ii — Judge a tight bbox** `(X0, Y0, X1, Y1)` (PIL convention: top-left origin, x1/y1 exclusive). Apply these rules of inclusion ↔ exclusion:

   | Pattern in `blocks` output | Decision |
   |---|---|
   | Narrow LEFT/RIGHT col block with ≤30 px gap to main body | KEEP — almost always axis labels, a rotated y-axis title ("Accuracy (%)"), or a legend |
   | LEFT/RIGHT col block with >50 px gap to main body | CUT — paper text column (left page-margin) or an adjacent figure bleed |
   | TOP row block separated from the main figure body by a clean gutter, ≤6 px thick | CUT — likely chrome residue (5a should have caught it; this is a backup) |
   | TOP row block separated by a clean gutter, larger | INVESTIGATE — could be a banner ("Published as a conference paper at ICLR 2025") OR could be the figure's actual top legend / panel-title row |
   | TOP small-text region with no clear gutter into the body | INVESTIGATE — could be body-text fragment from above the figure OR could be small panel titles ("mAP", "AP_50") that didn't hit the dense threshold |
   | BOTTOM row block matching "Figure N: ..." pattern (1–3 short rows after a clear gutter) | CUT — main figure caption, already in `captions.json` |
   | BOTTOM small row blocks matching "(a) <description>" / "(b) <description>" / "(c) <description>" pattern positioned right below each subplot | KEEP — sub-captions label the panels and belong with the figure |
   | Wide ROW gap (>200 px) at the top with no ink above it | The figure body starts where the first ink begins — pad `y0` up by 20–30 px to catch small panel titles that fall below the 5% dense threshold |
   | Any visual element straddling an edge (a column, row, panel, legend item, label cluster, sub-caption, bar in a chart) | NEVER a fractional capture. The element must be ENTIRELY inside or ENTIRELY outside the bbox. A half-included element is worse than full exclusion — it shows a confusing partial thing instead of a clean omission. If the rightmost column is "mostly" in but the right edge cuts the last 10% of it, extend the right edge to capture all of it OR pull the right edge in further to exclude it cleanly. |

   The three single most-common mistakes are (a) cutting the axis-label / rotated-title col block on the LEFT because it looks like a separate structure, (b) setting `y0` exactly at the first dense row, which lands inside the panel-title text instead of above it (fix: pad y0 up 20–30 px), and (c) capturing a fractional element at the right or bottom edge — usually a multi-column diagram's last column shows only its header but the right edge cuts the body, or a 4-row stat grid shows only the first 3 rows with the 4th half-visible.

   **Step 5d.iii — Mark + Preview (verification gate, never destructive):**
   ```bash
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py mark    <outdir>/assets/figures/<file>.png --box X0 Y0 X1 Y1
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py preview <outdir>/assets/figures/<file>.png --box X0 Y0 X1 Y1
   ```

   Run BOTH commands per round — they produce a paired set:
   - `figures/_debug/<stem>.marked-<NN>.png` — the ORIGINAL raster with a red rectangle overlay showing the proposed bbox. Used by your own per-edge sanity check (Step 5d.iv) because the red line shows where the cut WOULD happen.
   - `figures/_debug/<stem>.preview-<NN>.png` — the cropped image (i.e. what the final figure WOULD look like if this bbox is committed). Used by the sub-agent verifier (Step 5d.v) because there's no geometry to interpret — the preview IS the proposed result.

   Both files rotate suffix (`-01`, `-02`, ...) in lockstep so round-N's mark and preview pair together. The original PNG is untouched by either command.

   **Step 5d.iv — Re-Read the marked image and verify per-edge.** Look at the latest `figures/_debug/<stem>.marked-<NN>.png` and answer four explicit yes/no questions — one per edge. The red box is outside the bbox, so what's INSIDE the box (the content you'll keep) is unobstructed:

   - TOP edge: is everything above the red line truly noise (banner, body-text, top chrome)? Are any panel titles ("mAP", legend) sitting just below the line that you mean to keep?
   - BOTTOM edge: is everything below the line a "Figure N: …" caption or paper text? Are any sub-captions "(a) …" / "(b) …" / "(c) …" sitting below the line that should be inside the box?
   - LEFT edge: is everything left of the line a body-text column from the paper? Are any axis labels / rotated y-axis title / legend column sitting outside the line that should be inside?
   - RIGHT edge: same — body-text vs in-figure (legend on the right of a chart, color bar, etc.).

   If any answer flips (something you meant to keep is outside the box, or something you meant to cut is inside), **adjust the bbox and re-mark**.

   **Conditional iteration: round 2+ only when round 1 verifier wasn't a clean PASS.** Round 1 is always mandatory (mark + preview + sub-agent verify). For round 2+:

   - If round 1's verifier returned a **clean PASS** (all of R1–R7 OK, each citing STEP A justification, no ambiguity), **commit and stop** — running a forced second round when the first attempt is already correct invites the agent to "fix" something not broken, which often introduces a regression (e.g. shifting the box to include a caption it had cleanly excluded).
   - If round 1 returned **FAIL** OR had any rule answered ambiguously (e.g. "OK probably", missing STEP A citation, suggesting a correction even on a stated PASS), **adjust the bbox per the verifier's suggestion** (single-edge extend / single-edge contract / R7 translation shift), produce a fresh mark + preview pair (`-02`), and re-invoke the sub-agent verifier on the new preview. Iterate until clean PASS.

   Why conditional rather than always-≥2: forced second rounds on already-correct first attempts are net-negative (regression risk > confirmation value). Conditional iteration keeps quality on the table only when needed.

   Cap at 5 cycles per figure for genuinely hard cases. Mark + preview are cheap (pure file I/O, no API cost); the sub-agent call is the actual cost driver.

   **MANDATORY independent verification by a sub-agent (hard rule, not a suggestion).**

   Your own per-edge check above is biased: you just decided the bbox seconds ago, so your verification is anchored on that decision. You can't reliably catch over-crops (cutting into figure content) or under-crops (leaving noise) by self-review alone — the verifier and the decider need to be different.

   So after `marked-01` and your own per-edge check, **invoke an independent verification sub-agent via the Task tool** to recheck the bbox. The sub-agent runs in a fresh context — no anchoring on your bbox decision, no prior beliefs about which edges "should" be where. It is the only check that can catch what your own re-Read systematically misses.

   ```
   Task(
     subagent_type="general-purpose",
     description="Verify figure crop bbox",
     prompt="""You are an independent figure-crop verifier. The caller has produced
   a proposed crop of a paper figure raster. Your job is to judge whether the proposed
   crop is correct — by direct visual comparison of two images.

   IMAGE 1 (the ORIGINAL, uncropped extract):
     <outdir>/assets/figures/<stem>.png

   IMAGE 2 (the PREVIEW — what the figure WOULD look like if this bbox is committed;
   this is just IMAGE 1 cropped to the proposed bbox, no annotations):
     <outdir>/assets/figures/_debug/<stem>.preview-<NN>.png

   Read BOTH images. The judgement is a direct comparison: 'is IMAGE 2 a clean,
   complete version of the figure in IMAGE 1?' There is no red rectangle to
   interpret, no inside/outside geometry to puzzle over. You see what the
   caller proposes to keep (IMAGE 2) alongside the original (IMAGE 1), and you
   judge the difference.

   STEP 0 — Grounding (mandatory; never skip). Before any rule check, plainly state:
     - IMAGE 1 dimensions: W₁ × H₁ px. What it contains overall (one sentence).
     - IMAGE 2 dimensions: W₂ × H₂ px. What it contains overall (one sentence).
     - The visible difference: what content does IMAGE 1 contain that IMAGE 2
       has cut away? (e.g. 'IMAGE 1's top ~110 px (a page banner) is absent
       from IMAGE 2', 'IMAGE 1's right ~430 px (an adjacent Figure 2 column)
       is absent from IMAGE 2', 'IMAGE 1's bottom ~50 px ("Figure 1:" caption)
       is absent from IMAGE 2'). Be quantitative — name approximate pixel
       widths of each cut.
   This grounding step anchors you on what the proposed crop actually changes
   before any rule-based reasoning.

   The figure SHOULD include (these elements MUST be present in IMAGE 2):
   - all panels / sub-panels / chart bodies that visually compose the figure
   - axis labels, legends, colorbars, in-figure annotations
   - sub-captions like '(a) ...', '(b) ...' that sit BELOW each subplot and label it
   - decorative borders / frames that are part of the figure's artwork

   The figure should NOT include (these MUST be cut away — present in IMAGE 1,
   absent from IMAGE 2):
   - body-text paragraphs from the surrounding paper column
   - the main 'Figure N: ...' caption sitting below the figure body
   - page banner / running title / arxiv stamp at the top
   - vertical strips of an ADJACENT figure (when two figures share a page row)

   CRITICAL — no fractional captures: every visual element (column, row,
   panel, legend item, label cluster, sub-caption, bar in a chart, axis tick
   set, stat tile) must be either ENTIRELY in IMAGE 2 (kept whole) or
   ENTIRELY absent from IMAGE 2 (cut whole). A half-included element at any
   edge of IMAGE 2 (e.g. 'IMAGE 2's right edge shows the orange panel
   background ending mid-element', 'the rightmost "G" in "118 GB" is
   half-cut at IMAGE 2's right edge', 'only 3 of 4 stat tiles are fully in
   IMAGE 2 with the 4th half-visible') is the most common failure mode —
   flag it as FAIL even if everything else looks right.

   STEP A — Per-edge forced description (mandatory; no verdict allowed
   before completing this). For EACH of the four edges of IMAGE 2, describe
   in concrete words:
     (i) what content sits in the ~50 px strip just inside that edge of
         IMAGE 2 (does it end cleanly, or is it cut?), AND
     (ii) what content sits in the corresponding ~50 px strip of IMAGE 1
          that IMAGE 2 has dropped (is it noise that should be dropped,
          or figure content that should have been kept?).

     TOP edge:
       [IMAGE 2 top ~50 px]: ...
       [IMAGE 1 strip dropped just above IMAGE 2's top]: ...
     BOTTOM edge:
       [IMAGE 2 bottom ~50 px]: ...
       [IMAGE 1 strip dropped just below IMAGE 2's bottom]: ...
     LEFT edge:
       [IMAGE 2 left ~50 px]: ...
       [IMAGE 1 strip dropped just left of IMAGE 2's left]: ...
     RIGHT edge:
       [IMAGE 2 right ~50 px]: ...
       [IMAGE 1 strip dropped just right of IMAGE 2's right]: ...

   Be physical and specific — name actual elements, give approximate pixel
   distances, commit to whether each element ENDS within IMAGE 2 or CROSSES
   the edge.

   STEP B — Per-rule check (mandatory; one line per rule). For each rule
   below, answer VIOLATED or OK, and if VIOLATED quote the exact line from
   STEP A that shows the violation. Do NOT skip rules — answer all in order,
   even when obvious:

     R1 (no body-text paragraphs inside IMAGE 2): ___
     R2 (no main 'Figure N: ...' caption inside IMAGE 2): ___
     R3 (no page banner / running title / arxiv stamp inside IMAGE 2): ___
     R4 (no vertical strip of an adjacent figure inside IMAGE 2): ___
     R5 (no fractional capture at any edge of IMAGE 2 — every edge-adjacent
         element ENTIRELY in or ENTIRELY out): ___
     R6 (all figure-content elements present in IMAGE 2 — panels, axes,
         legends, sub-captions, colorbars; nothing critical was dropped
         when going from IMAGE 1 → IMAGE 2): ___
     R7 (no TRANSLATION error — the bbox is positioned correctly, not
         shifted off-center. Symptom: IMAGE 2 has significant white margin
         on ONE side AND content clipped at the OPPOSITE side. If left
         margin is wide and right edge cuts content, the box has the right
         width but is shifted too far LEFT — same with top-vs-bottom): ___

   The per-rule answers MUST cite the STEP A descriptions. 'R5 OK because
   the figure looks complete' is invalid — only 'R5 OK because STEP A right
   line says the orange panel background ends ~10 px before IMAGE 2's right
   edge with clean white margin' is a valid answer. 'R6 OK because IMAGE 2
   looks like a complete figure' is invalid — only 'R6 OK because IMAGE 1's
   right-strip drop contains only adjacent-figure content per STEP A right
   line, so nothing critical was dropped' is valid. 'R7 OK because the box
   is centered' is invalid — only 'R7 OK because STEP A shows the left
   ~50 px contains the leftmost panel's edge with ≤10 px margin, and the
   right ~50 px contains the rightmost panel's edge with ≤10 px margin,
   so the box is positioned correctly, not shifted' is valid.

   STEP C — Verdict. Based on STEP B:
   1. PASS (every rule OK) or FAIL (at least one VIOLATED).
   2. If FAIL, name the rule(s) violated and quote the relevant STEP A line(s).
   3. If FAIL, suggest a corrected bbox as concrete pixel deltas relative to
      the current one. Pick the right shape of correction:
      - **Single-edge extend** when an element is missing only on one side:
        'extend x1 by ~30 px to recover the rest of the orange panel
        background per R5'.
      - **Single-edge contract** when noise is leaking in on one side:
        'reduce y1 by ~50 px to drop the "Figure 1:" caption text per R2'.
      - **Translation shift** when R7 fired — when one side has slack
        whitespace and the opposite side cuts content. Apply equal-magnitude
        opposite-direction edits to BOTH edges of that axis, NOT a single-edge
        edit. Example: 'shift box right by ~80 px: x0 += 80 AND x1 += 80
        (per R7 — left has ~80 px white margin, right cuts the orange panel
        mid-element)'. Same pattern for top/bottom: 'shift box down: y0 += N
        AND y1 += N'. A single-edge fix on a translation error makes the
        problem worse, not better — flagging the shift explicitly is the
        only way the caller knows to act on it correctly.

   A response without all three steps (description → per-rule check →
   verdict) is invalid. The caller will reject any verdict that skips
   STEP A or B.

   Be specific and concise. The figure caller will act on your verdict directly."""
   )
   ```

   **Log the verifier's response immediately after every Task call.** Write the sub-agent's verbatim verdict (PASS/FAIL + the specific feedback) to `<outdir>/assets/figures/_debug/<stem>.verify-<NN>.txt`, where `<NN>` matches the `marked-<NN>.png` round it judged (so `marked-01.png` ↔ `verify-01.txt`, `marked-02.png` ↔ `verify-02.txt`, ...). This is the only auditable trace of what the verifier said and how each round's bbox decision was justified — without it, when a figure's crop trends worse across rounds, there's no way to tell whether the verifier gave bad advice or you misapplied good advice. Use the Write tool — keep the file plain text, include the round number and the bbox the verifier was judging at the top so the file reads standalone.

   Wait for the sub-agent's response. Two outcomes:

   - **PASS** → commit the bbox (Step 5d.v).
   - **FAIL** → apply the sub-agent's suggested correction, run `mark` again (producing `marked-02.png`), and re-invoke the sub-agent verifier on the new mark. Iterate.

   Cap at 5 verifier rounds per figure (the verifier disagreement should converge fast on a sane figure; if it doesn't after 5, accept your best attempt and note the residual in `figures.json` via a `"note"` field).

   The sub-agent is more expensive than self-check (one extra API call per figure × ~7-20 figures per paper ≈ tens of seconds added). The cost buys catching the over-crop / under-crop class of errors that self-review systematically misses.

   **Step 5d.v — Commit the crop** only after the mark passes verification:
   ```bash
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py box <outdir>/assets/figures/<file>.png --box X0 Y0 X1 Y1
   ```

   Overwrites the PNG (preserving the existing `figures/_debug/<file>.png.bak` from 5a-5c — `crop_figure.py` only writes `.bak` once, never clobbered on re-runs) and updates `figures.json` width/height. **All `figures/_debug/<stem>.marked-<NN>.png` overlays from this figure's mark iterations remain in place** as the auditable history of the bbox decision (paper2assets does NOT include them in its output contract; downstream renderers ignore `_debug/`, and `figures.json` doesn't list it). The hidden `_debug/` subdir is purely a debugging breadcrumb — keeps the top-level `figures/` listing clean while preserving full traceability.

   **Step 5d.vi — Split when the raster packs two independent figures.** Some papers compact two unrelated figures side-by-side onto one row to save page space. The extractor pulls them as a single raster, but they are NOT one figure and should not be cropped as one. Signature patterns to recognize:

   - LEFT image has its own "Figure N: …" caption text directly below it; RIGHT image extends taller than the LEFT image + its caption (the LEFT caption does NOT extend under the RIGHT image).
   - Two distinct sub-captions like "(a) Pipeline overview" / "(b) Loss curves" each pinned under its own panel with a clear vertical gutter separating them at the same column position.
   - `blocks` output shows TWO wide COL blocks separated by a clean gutter (≥30 px), each roughly half the image width, with their own internal structure (each has its own legend / axis labels / sub-caption).

   When you spot this pattern, **decide one bbox per child figure** (each tight per the 5d.ii rules above), `mark` each, verify each, then commit as a split:

   ```bash
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py split \
       <outdir>/assets/figures/<file>.png \
       --box X0a Y0a X1a Y1a --suffix a \
       --box X0b Y0b X1b Y1b --suffix b
   ```

   This produces `<stem>_a.png` + `<stem>_b.png`, removes the original PNG, and replaces the original's entry in `figures.json` with two new entries (inheriting `page` and `layout`; new `file`/`width`/`height` per child). The shared `.bak` of the original raster is preserved as the recovery source for both children.

   Downstream renderers see two figures and can pick them independently.

   **If the visual recheck reveals a structurally impossible crop** (e.g. the figure's y-axis labels share an x-range with a body-text column, so any rectangle that includes the labels also includes the body text), accept the best rectangular crop — the trade-off here is "lose axis labels" vs "include some body text"; the lesser evil depends on which is more visually offensive for downstream renderers. Note the residue in a brief `"note"` field on the figure's entry in `figures.json` so downstream is aware.

**Why this step is mandatory and runs on every figure, not just on picked ones:** paper2assets is the single owner of figure cleanup. Downstream renderers shouldn't re-discover surrounding-column-text or baked-in caption artifacts that the upstream stage left in. The cost (one `blocks` call + 1–3 `mark`/Read iterations + 1 `box` per figure, ~7–20 figures per paper) is paid once here instead of N times across renderers.

The `inspect` mode is helpful for quickly probing a figure's outer dimensions and pure-white border before deciding a bbox:
```bash
python ~/.claude/skills/paper2assets/scripts/crop_figure.py inspect <outdir>/assets/figures/<file>.png
```

### Step 5e — Final autotrim pass (mandatory, runs on every figure)

**For each `figures/<file>.png`, after 5d has committed its box crop, run autotrim one more time:**

```bash
python ~/.claude/skills/paper2assets/scripts/crop_figure.py autotrim <outdir>/assets/figures/<file>.png
```

Why this exists as a separate trailing step (not just re-using 5c): 5d's `box` crop is committed from a hand-picked rectangle that the verifier signed off on visually. Visual judgment is coarse at the pixel level — even a tight-looking bbox routinely leaves 2–10 px of pure-white margin on one or more edges (the verifier's eye smooths over thin uniform-white borders the same way it smooths over the top-chrome residue that motivated 5a). `autotrim` is the cheap, safe, deterministic mop-up that strips those residues so the saved PNG's dimensions match the figure's actual content extent.

Idempotent + safe:
- If 5d cropped tight (no whitespace left), `autotrim` prints `no border whitespace to trim — left untouched` and exits 0 without re-saving. Cost ≈ 50 ms per figure (just a numpy pass over the array).
- If 5d's bbox left a margin, `autotrim` strips it, keeps the standard `--pad 4` margin, writes the `.bak` (only if 5a/5b/5c didn't already — the one-shot guard protects the original raw extract), and updates `figures.json` width/height so downstream layout math stays consistent.
- Never touches content pixels — `--tol 8` means only rows/cols that are within 8 of pure white from all three RGB channels qualify as "border".

This is the **last image-processing step** before the figures leave paper2assets. Downstream renderers (paper2poster, paper2blog, etc.) receive content-tight PNGs and don't need to redo edge-trim work.

### Step 6 — Fetch institute logos + conference logo + URL QR codes

> ⚠️ **CRITICAL: copy the exact commands below verbatim.** The flag names
> here are trap-prone — a subtle mistake silently drops every logo. Do not
> hand-edit these commands.

```bash
python ~/.claude/skills/paper2assets/scripts/fetch_logos.py     --from-spec     <outdir>/assets/meta/paper_spec.md --outdir <outdir>
python ~/.claude/skills/paper2assets/scripts/fetch_conf_logo.py --from-metadata <outdir>/assets/meta/metadata.json --outdir <outdir>
python ~/.claude/skills/paper2assets/scripts/make_qr.py         --from-metadata <outdir>/assets/meta/metadata.json --outdir <outdir>
```

> ⚠️ **Flag traps for ALL THREE scripts — DO NOT alter:**
>
> 1. **`--from-spec` / `--from-metadata`** (NOT `--spec` / `--metadata`).
>    argparse rejects the short forms with usage error. We accept
>    `--spec` / `--metadata` as compat aliases now, but the canonical
>    flag names are the `--from-*` forms.
> 2. **`--outdir <outdir>`** is the **poster outdir** — NOT a `/logos`
>    or `/qr` subdir. The scripts append `assets/logos/` and `assets/qr/`
>    themselves. Passing `--outdir <outdir>/assets/logos` (or `/qr`) makes
>    the scripts land files at `<outdir>/assets/logos/logos/<slug>.png`
>    (nested-dir bug) — downstream paper2poster looks at
>    `<outdir>/assets/logos/<slug>.png` and finds nothing. The scripts now
>    auto-strip a trailing `/logos`, `/qr`, or `/assets/{logos,qr}` with a warning, but pass
>    the poster outdir cleanly as shown above.

`make_qr.py` is best-effort (classifies + de-duplicates the paper/project/code URLs into ≤2 QR slots — see the deliverable table). `fetch_conf_logo.py` and `fetch_logos.py` are **checklist-driven with a MANDATORY web-search fallback** — do NOT treat a first-pass miss as final:

#### 6a. Institute logos — checklist, then fallback (logos must NOT be left missing)

The deterministic Wikimedia pass gets the easy ones; obscure / non-English / newly-founded institutes routinely miss it. **You MUST close the gap** rather than shipping a logo-less header:

1. Run `fetch_logos.py` (command above). It prints a **✓/✗ CHECKLIST** to stderr and a JSON object `{"logos": [...], "missing": ["Institute A", ...]}` to stdout.
2. **Read the `"missing"` array.** For **EVERY** name in it, run the web-search fallback — this is required, not optional:
   - `WebSearch` `"<institute> official logo png"` (try `svg`, or the institute's English name / acronym expansion if the raw string is a department or non-English name).
   - Pick the **official** mark from the institute's own site / brand-resources page, Wikipedia/Wikimedia, or an official social profile — **skip** stock-photo aggregators, third-party redraws, photos, campus/building shots, and flags. `WebFetch` the page if you need to locate the direct image URL.
   - Download it through the SAME pipeline (autotrim + canonical slug) so it matches the other tiles:
     ```bash
     python ~/.claude/skills/paper2assets/scripts/fetch_logos.py --outdir <outdir> \
       --add-logo "<Institute Name>=<direct image URL>"
     ```
     Repeat `--add-logo "Name=URL"` for each missing institute (the flag is repeatable).
3. Only after a genuine web search comes up empty for a given institute do you leave it out. Re-run the checklist mentally: every institute now either has a `assets/logos/<slug>.png` file or was truly unfindable. **A logo missing because you skipped the fallback is a defect.**

#### 6b. Conference / venue logo — preprints get NONE (never an arXiv mark)

`fetch_conf_logo.py` fetches the conference's generic mark to `assets/logos/_venue.png`, best-effort, skipping on any miss (the header then falls back to its text VENUE/YEAR badge).

- **If the paper is a preprint with no accepted venue** — i.e. `metadata.json` `venue` is empty (an arXiv paper where no conference/journal could be found, per Step 3's venue rule) — there is **NO venue logo and NO venue badge**. Do **NOT** fetch, download, or fabricate an "arXiv" / "Preprint" mark to fill the slot; leave `_venue.png` absent so the header simply omits the venue entirely. arXiv is a host, not a venue.
- When `venue` IS a real conference/journal, `fetch_conf_logo.py` supplies its mark; if that misses, the text badge stands in (no fallback logo hunt needed for the venue).

Downstream renderers still defensively handle a missing logo / missing `qr/code.png`, but with the fallback above the institute logos should rarely be missing.

### Step 7 — Build the cross-skill canonical package (sections.json + narration.json + manifest.json)

paper2assets is the single source of truth for ALL paper-rendering skills downstream — not just paper2poster. Skills like paper2blog, paper2video, and paper2reel consume the same `<outdir>/` and rely on three additional canonical files that paper2poster doesn't need but they do:

- `manifest.json` — package inventory (file paths + counts + source PDF sha256). Lets downstream verify the package shape without re-walking the directory.
- `sections.json` — `paper_spec.md` parsed into structured per-section JSON with stable ids (`problem`, `motivation`, `method`, `key-result`, ...), the per-section `necessary` / `additional` / `audio_script` fields, and an empty `figures: []` per section (downstream joins with `figures.json` by id).
- `narration.json` — TTS clip list extracted from `**Audio script:**` markers, in document order. The title clip comes from the YAML frontmatter's `title_audio_script` field.

paper2poster ignores these three files (it reads `paper_spec.md` directly), so this step is **additive** — generating them does not change anything paper2poster sees.

**For each completed `<outdir>/`, run this exact sequence after Step 6:**

```bash
python ~/.claude/skills/paper2assets/scripts/build_package.py <pdf> \
    --outdir <outdir> \
    --skip-extract \
    --paper-spec <outdir>/assets/meta/paper_spec.md
```

Builds the 3 canonical JSON files from `paper_spec.md` + the already-extracted `text.txt` / `captions.json` / `figures.json` / `metadata.json`.

`build_package.py` notes:

- `--skip-extract` is mandatory in this step (extraction is already done by Step 2; without `--skip-extract` the script would re-invoke `extract_pdf.py` and overwrite our cleaned figures).
- Parses the paper2assets YAML frontmatter format (`---\ntitle: ...\nauthors: ...\n---`) for top-level metadata, and the `## Heading` + `**Necessary:** / **Additional:** / **Audio script:**` body sections for per-section content. This matches what Step 2 + Step 4 produce, end-to-end.

**Output (added to `<outdir>/`):**
- `manifest.json`
- `sections.json`
- `narration.json`

These are **canonical for all downstream paper-rendering skills**.

### Audio is NOT synthesized here — only the script

paper2assets stops at the narration **script** (`narration.json`, Step 7) and the `**Audio script:**` fields in `paper_spec.md`. It does **not** run TTS and produces **no `audio/` directory**. Each downstream renderer synthesizes its own audio from its own source:
- **paper2poster** runs its `scripts/generate_audio.py` on `<outdir>/assets/meta/narration.json` → `<outdir>/assets/audio/<id>.mp3` for its Listen buttons (see paper2poster's Step 5).
- **paper2video** synthesizes per-slide audio in its own stage from the deck's speaker notes (a separate narration source).

## Final deliverable check

Before declaring done, verify `<outdir>/` contains the required files:

```bash
# Step 2 outputs (extraction)
ls <outdir>/assets/meta/text.txt <outdir>/assets/meta/captions.json <outdir>/assets/meta/figures.json \
   <outdir>/assets/meta/metadata.json <outdir>/assets/meta/paper_spec.md
ls <outdir>/assets/figures/*.png

# Step 7 outputs (cross-skill canonical package)
ls <outdir>/manifest.json <outdir>/assets/meta/sections.json <outdir>/assets/meta/narration.json
```

The optional `logos/` and `qr/` directories may be empty or absent (best-effort fetch); a downstream renderer is responsible for handling that gracefully.

Print the absolute outdir path on the last line of your reply so the caller (poster_pipeline.sh, batch_titles.sh, or another driver) can pick it up.

## Tools

```
scripts/
├── extract_pdf.py        ← CLI: pdf → assets/meta/{text.txt,captions.json,figures.json} + assets/figures/
├── crop_figure.py        ← CLI: inspect / autotrim / box / decaption / top-check
├── fetch_logos.py        ← CLI: spec → assets/logos/*.{png,svg} (Wikimedia Commons)
├── make_qr.py            ← CLI: metadata → assets/qr/{paper,code}.png
└── build_package.py      ← CLI: assets/meta/paper_spec.md → manifest.json + assets/meta/{sections.json,narration.json}
                            (cross-skill canonical package for downstream renderers)
```

## Key rules

- **Step 5 runs on every figure, not just suspected ones.** Cost is trivial; missing chrome / trapped margins / surrounding paper text downstream is expensive.
- **Step 5 ordering is non-negotiable.** top-check → decaption → autotrim → visual AI review (5d) → final autotrim mop-up (5e). 5d sits in the middle because the deterministic chain in 5a-5c handles the easy patterns first; 5d catches what the patterns can't (column body text leakage, asymmetric noise, captions outside decaption's thin-strip pattern). 5e closes the loop by re-running the cheap autotrim after 5d's visually-judged bbox commits — visual judgment leaves pixel-level whitespace residues even when the bbox looks tight, and 5e is the safe deterministic mop-up that ensures saved PNG dimensions match figure content extent.
- **Main caption out, sub-captions in.** The paper's "Figure N: …" caption is already in `captions.json` as structured text — if you see that line at the bottom of a figure raster, CUT IT in 5d. **Panel sub-captions** like "(a) Pipeline overview" / "(b) Loss curves" stay — they label the sub-panels and are part of the figure's visual content; cutting them strips the figure of its own labels. Rule of thumb at the bottom edge: 1–3 short prose rows starting with "Figure N:" → CUT; short "(a)/(b)/(c) <label>" rows pinned right under each sub-panel → KEEP.
- **Surrounding column body text never lives inside the figure raster either.** A vertical strip of paper prose alongside the figure, or a few lines of body paragraph above/below — all noise. 5d's per-edge check catches them; act on what you can describe in words.
- **paper_spec.md is the single source of truth** for any downstream prose / narration. NEVER invent numbers — pull from `text.txt`.
- **Best-effort steps (logos/QR) do not abort the workflow.** Document the omission; downstream renderers handle missing inputs.
- **Cache friendliness:** re-running paper2assets on an existing outdir should be safe and incremental. The deterministic crop pipeline (5a/5b/5c) is idempotent — `.bak` is the original raw extract; re-runs operate on the already-cleaned `.png` and won't double-cut (autotrim refuses if there's nothing to trim; top-check returns "clean" if no chrome). 5d's visual review is also idempotent on a clean figure: the per-edge yes/no answers will be all "no" and no `box` invocation fires. 5e's trailing autotrim is by construction a no-op on an already-tight figure (it returns "no border whitespace to trim — left untouched"), so re-runs add a constant per-figure numpy scan with no I/O.
