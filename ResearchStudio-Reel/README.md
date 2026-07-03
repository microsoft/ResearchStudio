# ResearchStudio - <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel-wordmark.png" alt="Reel" height="28">

> From paper to poster, video, blog, and reel — Automating the Last Mile of Research Dissemination.

**ResearchStudio** streamlines the final steps of a research project — the materials a paper needs *after* the writing is done. Drop in one PDF and get back the artifacts that turn a paper into a conference submission and a public release: a structured asset bundle, a print-ready poster, a narrated walkthrough video, a bilingual blog post ready for an editor, and an interactive reel viewer.

<!-- Hero strip: two demos, stacked one per row. Top: a real Paper2Poster build. Bottom: the Paper2Reel interactive reel walkthrough. -->
<p align="center">
  <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_landscape/poster.pdf"><img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/poster_demo.gif" alt="Paper2Poster — building a conference poster from one PDF" width="60%"></a>
  <br>
  <sub><b>Paper2Poster</b> — building a poster from one PDF.</sub>
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel_demo.gif" alt="Paper2Reel — interactive reel feature demo" width="60%">
  <br>
  <sub><b>Paper2Reel</b> — presenting an interactive reel.</sub>
</p>

---

## The five skills

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/researchstudio-reel-pipeline.png" alt="ResearchStudio pipeline — one paper PDF fans out through Paper2Assets into Paper2Poster, Paper2Video, and Paper2Blog, then converges into Paper2Reel">
</p>

| Skill | Input | Output | Built for |
|---|---|---|---|
| **Paper2Assets** | paper PDF or Link   | intermediate artifacts (TXT, JSON)                                                      | the **upstream extraction stage** every downstream renderer reuses |
| **Paper2Poster** | paper PDF or assets | a narrated poster (HTML + MP3 + PDF + PNG + PPTX) | poster sessions at different venues |
| **Paper2Video**  | paper PDF or assets | a video (MP4 + PPTX) | lightning talks, virtual conference recordings, social promotion |
| **Paper2Blog**   | paper PDF or assets | two blogs (DOCX) | publicity push after acceptance — bilingual outreach in one pass     |
| **Paper2Reel**   | poster + deck artifacts | an interactive reel viewer (HTML) | one scrollable view that aligns the poster with slide / video frames |

Each skill is shipped as a [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex) **skill**.

---

## Usage

Let's consider Claude Code as an example. Open a Claude Code session and ask for the artifact you want — the agent picks up the matching skill and runs it end-to-end, writing every output to a working `<outdir>/`. To produce the whole bundle (poster + editable PPTX, blog, narrated video, and reel viewer) from one PDF in a single headless run:

```bash
CLAUDE_EFFORT=high CLAUDE_CONFIG_DIR="$PWD/.claude" \
  claude -p --model claude-opus-4-8 \
  "Run the full pipeline on ./my_paper.pdf: /paper2assets to extract the shared package, then /paper2poster (poster.html/pdf/png + editable poster.pptx), /paper2blog, /paper2video, and finally /paper2reel. Reuse the one paper2assets package across every stage and keep all intermediate HTML."
```

All five stages share one `paper2assets` extraction, so nothing is re-parsed. Each skill is detailed below.

<!-- 
### 🧱 Paper2Assets

Extract a paper PDF into a single poster-agnostic `<outdir>/` reusable by every downstream renderer. Runs once per paper; iterating on poster style or blog copy afterwards does **not** re-extract.

**Invoke**

```text
> /paper2assets my_paper.pdf
```

**Outputs** — one self-contained, movable bundle under `<outdir>/` (default `./my_paper/`). The top level holds only `manifest.json`; every figure, asset, and build intermediate lives under `assets/`:

```text
my_paper/
├── manifest.json                  # package index: paths, counts, source-PDF sha256
└── assets/
    ├── figures/*.png              # cleaned figure rasters (~432 dpi); raw .bak backups under figures/_debug/
    ├── logos/*.{png,svg}          # one logo per institute (best-effort)
    ├── qr/{paper,code}.png        # QR codes for the paper / code URLs
    └── meta/
        ├── paper_spec.md          # 9-section structured summary (Problem … Takeaway) + audio scripts
        ├── metadata.json          # title, authors, institutes, venue, paper / code URLs
        ├── text.txt               # full PDF text — authoritative source for any cited number
        ├── figures.json           # per-figure manifest (file, size, page, source-column layout)
        ├── captions.json          # detected "Figure N: …" captions
        ├── sections.json          # paper_spec parsed into per-section JSON
        └── narration.json         # TTS script only — no audio; each renderer synthesizes its own
```

Deliverables reference assets by root-relative path (`assets/figures/…`), so the bundle stays self-contained and movable. Re-running on an existing `<outdir>/` is safe and incremental. Full per-file field details live in the skill's `SKILL.md` (the Output Contract).
-->

### 🎨 Paper2Poster

Render a print-ready conference poster (HTML + PDF + PNG) from a `paper2assets` `<outdir>/`, with optional per-section narration audio. Two canvas presets are supported:

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/poster_showcase.png" alt="Paper2Poster — one paper rendered three ways: a landscape poster (NeurIPS / CVPR), the same content as an editable PPTX with native shapes, and a portrait variant (ACL / AAAI)" width="60%">
</p>
<p align="center">
  <sub>One paper, three deliverables — a landscape poster, the same content as an editable PPTX, and a portrait variant. Open the real examples below.</sub>
</p>

<div align="center">
<table align="center">
<tr><th>Deliverable</th><th>Open the real example</th></tr>
<tr><td>Landscape poster (e.g. NeurIPS / CVPR)</td><td><a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_landscape/poster.pdf">PDF</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_landscape/poster.png">PNG</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_landscape/poster.zip">HTML (zip)</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_landscape/poster.pptx">PPTX</a></td></tr>
<tr><td>Portrait poster (e.g. ACL / AAAI)</td><td><a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_portrait/poster.pdf">PDF</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_portrait/poster.png">PNG</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_portrait/poster.zip">HTML (zip)</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/latent_diffusion_portrait/poster.pptx">PPTX</a></td></tr>
</table>
</div>

> 🎧 **Easter egg — the poster talks back.** Open `poster.html` in a browser and press **`a`** to reveal per-section **Listen** pills; each plays an ~80-word narration MP3 for that block, and the titlebar's **Full Listen** stitches them into a guided audio tour. Free Microsoft Edge TTS by default — no API key required. (Bonus keys: **`s`** fullscreen, **`d`** debug overlay.)

**Invoke** via Claude Code — `/<skill>` activates the skill. `paper2poster` produces all four artifacts in one run; the editable PPTX is built in via the bundled `html2pptx` sub-skill, so you never call it separately:

```text
# point it at a paper2assets <outdir>/  →  poster.{html, pdf, png, pptx}
> /paper2poster ./my_paper/

# …or pass a natural-language request after the slash command
> /paper2poster Render a portrait poster for arxiv 2502.06434 in teal
```

**Outputs** — `poster.{html, pdf, png, pptx}` plus per-section `audio/*.mp3`, written to the same `<outdir>/`. For the full output details, the six templates, and the measured fill loop, see Paper2Poster's [`SKILL.md`](skills/paper2poster/SKILL.md).

### 🎬 Paper2Video

Turn a paper into a narrated walkthrough video: editable PPTX, subtitled MP4, no-subtitle MP4 for Paper2Reel, captions, slide frames, visual highlights, and timeline metadata. The recommended path reuses the same `paper2assets` `<outdir>/`, then delegates deck + speaker-note generation to the `ppt-master` skill.

<table align="center">
<tr>
<td align="center" valign="top" width="50%">
<div align="center"><b>Generated outputs and controls</b></div>
<br>
<img valign="center" src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2video_showcase.png" alt="Paper2Video — editable deck, narrated MP4, and controllable video options" width="100%">
</td>
<td align="center" valign="top" width="50%">
<video src="https://github.com/user-attachments/assets/17b62c7f-5d19-43a3-8868-233572e2bd95" controls width="100%"></video>
</td>
</tr>
</table>

<div align="center">
<table align="center">
<tr><th>Deliverable</th><th>Open the real example</th></tr>
<tr><td>Narrated video package</td><td><a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2video/video.mp4">MP4</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2video/video.pptx">PPTX</a></td></tr>
</table>
</div>

**Invoke** via Claude Code — point it at the shared bundle when available; starting from a PDF resolves the same `<pdf_stem>/` bundle root first:

```text
# point it at a paper2assets <outdir>/  →  video.mp4 + video_no_subtitles.mp4 + video.pptx
> /paper2video ./my_paper/

# …or start from the PDF
> /paper2video ./my_paper.pdf
```

**Outputs** — top-level `video.mp4`, `video_no_subtitles.mp4`, and `video.pptx`, with audio, captions, slide frames, raw clips, visual cues, duration reports, timeline metadata, and QA reports under `assets/`. The default visual attention style is `spotlight_laser`: a feathered spotlight plus a small red laser-pointer dot aligned to narration cues.

For the full route details, duration-control loop, subtitle contract, visual-cue generation, and strict QA gate, see Paper2Video's [`README.md`](skills/paper2video/README.md) and [`SKILL.md`](skills/paper2video/SKILL.md).

### ✍️ Paper2Blog

Turn a paper into a **bilingual editorial package**: one Chinese WeChat public-account article and one English research-blog article, both `.docx`, sharing the same evidence map, figures, captions, numbers, and source links.

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2blog_showcase.png" alt="Paper2Blog — one paper rendered as English and Chinese DOCX articles, with layout gates for typography, figure fit, captions, and pagination" width="60%">
</p>
<p align="center">
  <sub>One paper, two editorial deliverables — an English research blog and a Chinese article, with layout gates for typography, figure fit, captions, and pagination.</sub>
</p>

<div align="center">
<table align="center">
<tr><th>Deliverable</th><th>Open the real example</th></tr>
<tr><td>Bilingual blog package</td><td><a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2blog/blog_en.docx">English DOCX</a>, <a href="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/examples/paper2blog/blog_zh.docx">Chinese DOCX</a></td></tr>
</table>
</div>

**Invoke** via Claude Code — use the shared `paper2assets` bundle when available; starting from a PDF initializes the same v2 bundle shape:

```text
# point it at a paper2assets <outdir>/  →  blog_zh.docx + blog_en.docx
> /paper2blog ./my_paper/

# …or start from the PDF
> /paper2blog ./my_paper.pdf
```

**Outputs** — top-level `blog_zh.docx` and `blog_en.docx`, with outlines, QA reports, previews, and shared cropped figures under `assets/`. The two articles are not literal translations: they agree on facts and figure choices, but `_zh` is written in a restrained WeChat register while `_en` is written as a neutral research blog.

For the full editorial workflow, image-selection rules, DOCX assembly contract, and bilingual QA gate, see Paper2Blog's [`README.md`](skills/paper2blog/README.md) and [`SKILL.md`](skills/paper2blog/SKILL.md).

### 🎞️ Paper2Reel

Assemble the completed poster, video, and blog outputs into an interactive `reel.html` viewer. The reel opens poster-first, highlights sections on hover, and lets readers double-click into a synchronized modal with video, slide thumbnails, captions, and bilingual blog content.

**Invoke** via Claude Code — point it at the complete shared bundle; starting from a PDF is allowed only because the skill first completes any missing upstream stages:

```text
# point it at a completed v2 bundle  →  reel.html + content_alignment.json
> /paper2reel ./my_paper/

# …or start from the PDF; missing paper2* stages are completed first
> /paper2reel ./my_paper.pdf
```

**Outputs** — top-level `reel.html` and `content_alignment.json`, with poster, video, slide, blog, caption, and download support assets under `assets/`. Paper2Reel uses `video_no_subtitles.mp4` for playback so its own CC toggle does not double-subtitle the video. Local validation must use `skills/paper2reel/scripts/serve_reel.py`, because video seeking needs HTTP Range support.

For the full bootstrap behavior, alignment map, section-modal UI contract, browser gate, and local serving requirements, see Paper2Reel's [`README.md`](skills/paper2reel/README.md) and [`SKILL.md`](skills/paper2reel/SKILL.md).

---

## Acknowledgements

- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex) — the agent runtime that drives every skill.
- [PyMuPDF](https://pymupdf.readthedocs.io/), [Poppler](https://poppler.freedesktop.org/), [Pillow](https://python-pillow.org/) — PDF + image processing.
- [Playwright](https://playwright.dev/) + Chromium — HTML → PDF / PNG rendering for posters.
- [LibreOffice](https://www.libreoffice.org/) + [FFmpeg](https://ffmpeg.org/) — slide rasterization and video muxing.
- [Inter](https://rsms.me/inter/) — the typeface bundled with the poster templates.
- [python-docx](https://python-docx.readthedocs.io/) — `.docx` assembly for Paper2Blog.
- [ppt-master](https://github.com/hugohe3/ppt-master) — AI generates natively editable PPTX.

## License

MIT — see [`LICENSE`](../LICENSE).

## Citation

If ResearchStudio - Reel helps your research workflow, please cite:

```bibtex
Placeholder
```
