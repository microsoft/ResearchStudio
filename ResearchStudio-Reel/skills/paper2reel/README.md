# paper2reel

> Turn the poster, blog, and video deliverables for one paper into an interactive `reel.html` viewer that aligns poster sections, slide thumbnails, video seek times, captions, and bilingual blog content.

`paper2reel` is the **convergence stage** of the ResearchStudio pipeline. It does not replace or mutate `paper2poster`, `paper2blog`, or `paper2video`; it reads their completed v2 outputs and builds a self-contained viewer on top.

```
paper2poster ─┐
paper2blog   ├──▶  paper2reel  ──▶  reel.html
paper2video  ┘       alignment       content_alignment.json
```

## Input

A complete shared v2 bundle containing:

- `poster.html`, `poster.pdf`, `poster.png`, `poster.pptx` from `paper2poster`;
- `blog_zh.docx`, `blog_en.docx` from `paper2blog`;
- `video.mp4`, `video_no_subtitles.mp4`, `video.pptx`, timeline, captions, and slide frames from `paper2video`;
- `manifest.json` and `assets/meta/sections.json` from `paper2assets`.

If the user invokes `paper2reel` with a PDF, arXiv/link input, or an incomplete bundle, the skill must inspect the bundle and complete the missing upstream stages through their full workflows before assembling the reel.

## Output

Written back into the same v2 bundle root:

| File | What it is |
|---|---|
| `reel.html` | Interactive viewer: poster-first home, section hover, modal video/blog view, top menu, downloads, shortcuts |
| `content_alignment.json` | Sidecar alignment map from poster sections to slides, video timestamps, captions, and blog blocks |
| `manifest.json` | Updated v2 package index with root-relative reel deliverables |
| `assets/poster/` | Poster HTML/PDF/PNG/PPTX copies used by the viewer and downloads |
| `assets/media/` | Video assets, section clips, VTT captions, and media metadata |
| `assets/slides/` | Slide thumbnails / frames used for timeline navigation |
| `assets/blog/` | HTML-rendered blog blocks and embedded blog images |
| `assets/meta/reel_downloads.json` | Structured All/Poster/Video/Blog source manifest |
| `assets/downloads/` | Persisted ZIPs in standalone `materialized` mode only |

`video_no_subtitles.mp4` is the playback source for the reel. The final subtitled `video.mp4` remains downloadable, but using it for in-reel playback would double-subtitle once the viewer CC toggle is enabled.

## Usage

From a Claude Code session:

```text
# preferred: point at a complete shared bundle
> /paper2reel ./my_paper/

# allowed: start from a PDF; missing stages are completed first
> /paper2reel ./my_paper.pdf
```

For local preview, use the Range-capable server:

```bash
python skills/paper2reel/scripts/serve_reel.py ./my_paper/ --port 8900
```

Open `http://127.0.0.1:8900/reel.html`. Do not use `python -m http.server` for validation; video seek requires HTTP Range support.
The same server handles `__download__/{all,poster,video,blog}` for
`on_demand` bundles and streams a temporary ZIP from
`assets/meta/reel_downloads.json` without saving it in the bundle.

The generated `reel.html` also supports direct local opening. You may double-click
`reel.html` or open it through `file://` as long as the whole v2 bundle folder is
kept together. Under `file://`, the viewer embeds the copied poster through
`iframe.srcdoc`, localizes poster render resources such as MathJax into
`assets/poster/`, and keeps the same poster hover, section modal, captions,
blog, thumbnails, and shortcuts. Standalone `materialized` bundles keep their
offline ZIP links; `on_demand` bundles hide those online-only links under
`file://`. The HTTP server remains the golden preview path for Range/206
validation; direct-open mode is validated by a separate file-browser gate.

## How it works

1. **Inspect the bundle** with `build_reel_from_paper.py --dry-run` and identify missing stages.
2. **Complete missing upstream outputs** through the full `paper2assets -> paper2poster -> paper2blog -> paper2video` workflows.
3. **Build the poster/slide base viewer** without mutating the original poster or deck deliverables.
4. **Attach timeline-backed media** from `paper2video` so slide thumbnails and direct video seeking use the same timestamp contract.
5. **Render blog content** into the modal's right pane, keeping images and headings from the DOCX/article outlines.
6. **Write `content_alignment.json`** so each canonical section id maps to poster area, slides, video clips, captions, and blog blocks.
7. **Run both browser gates** to prove the delivered viewer works over HTTP and when opened directly from disk, not just that files exist.

## Viewer contract

The default view is poster-first. Sections highlight on hover; double-clicking a poster section opens the section modal. The title region opens the full-paper modal. The modal places video on the left and blog on the right, with a draggable split, subtitle toggle, slide thumbnails that seek the video, and direct progress-bar seeking. Keyboard shortcuts include audio, help, and top-menu controls.

Downloads and the top menu are part of the delivered UI, not optional extras.
The explicit manifest field `delivery` selects `materialized` (default,
persisted ZIPs) or `on_demand` (dynamic endpoint, no persisted ZIPs). Portal
jobs must invoke `build_reel_from_paper.py --download-mode on_demand`; normal
standalone use remains backward-compatible.

## Scripts

```
scripts/
├── build_reel_from_paper.py          # inspect/complete bundle and assemble final reel
├── build_poster_slides_view.py       # poster + slides base viewer
├── build_section_media_from_timeline.py # section clips/captions from video timeline
├── check_reel_package.py             # browser-backed hard QA gate
├── reel_downloads.py                 # shared manifest/path/archive contract
└── serve_reel.py                     # Range-capable local preview server
```

## Requirements

- Python >= 3.10
- A complete v2 `paper2assets` bundle
- Completed `paper2poster`, `paper2blog`, and `paper2video` deliverables
- Playwright + Chromium for `check_reel_package.py --browser`
- Playwright + Chromium for `check_reel_package.py --file-browser`
- A local HTTP server with Range support, normally `serve_reel.py`

## More detail

[`SKILL.md`](SKILL.md) is the authoritative, agent-facing spec: the viewer UX contract, bootstrap rules for missing upstream stages, alignment rules, browser QA gate, and manifest requirements. `assets/section_modal_contract.json` is the golden UI contract used by the checker.
