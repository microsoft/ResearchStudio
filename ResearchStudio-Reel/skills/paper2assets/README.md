# paper2assets

> Extract one paper PDF into a single, reusable bundle of poster-agnostic assets — full text, cleaned figures, a structured 9-section summary, metadata, logos, and QR codes — that every downstream renderer shares.

`paper2assets` is the **upstream extraction stage** of the ResearchStudio pipeline. It runs **once per paper**; `paper2poster`, `paper2blog`, `paper2video`, and `paper2reel` all read the same `<outdir>/` it produces, so a paper is never parsed twice.

```
paper.pdf  ──▶  paper2assets  ──▶  <outdir>/  ──▶  paper2poster / paper2blog / paper2video / paper2reel
```

## Input

A single paper PDF (born-digital / vector text; scanned-image PDFs degrade figure cropping and number extraction).

## Output

One self-contained bundle that **defines the on-disk layout every `paper2*` skill follows**: deliverables at the top level, everything else under one `assets/` folder. Downstream skills drop their own deliverables (`poster.*`, `blog_*.docx`, …) next to `manifest.json` and never touch `assets/`.

```
my_paper/
├── manifest.json                  # package index (paths, counts, source-PDF sha256)
└── assets/
    ├── figures/*.png              # cleaned figure rasters (~432 dpi); _debug/ keeps raw .bak backups
    ├── logos/*.{png,svg}          # one logo per institute (best-effort, Wikimedia Commons)
    ├── qr/{paper,code}.png        # QR codes for the paper / code URLs
    └── meta/
        ├── paper_spec.md          # 9-section structured summary + audio scripts
        ├── metadata.json          # title, authors, institutes, venue, paper / code URLs
        ├── text.txt               # full PDF text — authoritative source for any cited number
        ├── figures.json           # per-figure manifest (file, size, page, source-column layout)
        ├── captions.json          # detected "Figure N: …" captions
        ├── sections.json          # paper_spec parsed into per-section JSON
        └── narration.json         # TTS script only — no audio; each renderer synthesizes its own
```

Deliverables reference assets by **root-relative** paths (`assets/figures/…`), so the bundle stays self-contained and movable.

## Usage

```text
> /paper2assets my_paper.pdf
```

Outputs land in `<outdir>/`, defaulting to `<input_pdf_dir>/<pdf_stem>/`. Pass an explicit second path to override.

## How it works

1. **Extract** text + figure rasters + captions from the PDF (`pdftotext` + a column-aware figure crop).
2. **Parse metadata** — title, authors, institute index map, venue, paper/code URLs.
3. **Synthesize `paper_spec.md`** — a 9-section summary (Problem · Motivation · Contribution · Method · Dataset/Benchmark · Key Result · Ablation · Headline Numbers · Takeaway), each with `Necessary` / `Additional` / `Audio script` fields.
4. **Clean every figure** — a deterministic chain (`top-check → decaption → autotrim`) plus an LLM-driven per-figure visual crop review, so downstream renderers get content-tight rasters with no page chrome, baked-in captions, or neighbouring-column bleed.
5. **Fetch logos + QR codes** — one institute logo each (Wikimedia, best-effort) and QR codes for the paper/code links.
6. **Build the canonical package** — `sections.json` + `narration.json` + `manifest.json` for the downstream skills.

> No audio is synthesized here — paper2assets stops at the narration **script** (`narration.json`); each renderer makes its own mp3s.

## Cache-friendly & idempotent

Re-running on an existing `<outdir>/` is safe: a Step-0 cache check reports and reuses an already-extracted paper instead of re-grinding, the figure-cleanup chain never double-cuts, and `.bak` backups of every raw extract are kept under `assets/figures/_debug/`.

## Scripts

```
scripts/
├── extract_pdf.py     # pdf → assets/meta/{text,captions,figures}.json + assets/figures/
├── crop_figure.py     # inspect / top-check / decaption / autotrim / box / split — figure cleanup
├── fetch_logos.py     # spec → assets/logos/*.{png,svg} (Wikimedia Commons)
├── make_qr.py         # metadata → assets/qr/{paper,code}.png
└── build_package.py   # paper_spec.md → manifest.json + assets/meta/{sections,narration}.json
```

## Requirements

- Python ≥ 3.10, `pymupdf`, `pillow`, `qrcode`
- Poppler (`pdftotext`, `pdftoppm`) for text extraction + vector-figure rasterization

## More detail

[`SKILL.md`](SKILL.md) is the authoritative, agent-facing spec: the full Output Contract, the per-step extraction workflow, the figure-cleanup pipeline (including the mandatory visual crop-review loop), and every CLI flag trap.
