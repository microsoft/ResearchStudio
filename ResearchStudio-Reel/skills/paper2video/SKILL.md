---
name: paper2video
description: >
  Turn a research paper, a paper2assets package, or an existing PPT deck into a
  narrated MP4 video. Prefer the shared paper2assets package when present so
  paper2poster, paper2blog, paper2slides, and paper2video use the same section
  order and narration. Preserve the advanced deck route by delegating slide
  authoring to the external `hugohe3/ppt-master` project, then synthesize audio
  with `skills/paper2poster/scripts/generate_audio.py`, render with
  `skills/paper2video/scripts/render_video.py`, and burn final subtitles with
  `skills/paper2video/scripts/add_subtitles.py`.
---

# paper2video - paper/assets/deck -> narrated MP4

`paper2video` is an orchestrator. It does not try to replace poster extraction,
deck authoring, TTS, or ffmpeg compositing. It wires the current best pieces
together:

```text
paper.pdf
  -> skills/paper2assets/scripts/build_package.py
  -> assets/meta/sections.json + assets/meta/narration.json
  -> deck source (ppt-master / paper2slides / existing PPTX)
  -> assets/audio/*.mp3 from skills/paper2poster/scripts/generate_audio.py
  -> raw MP4 from skills/paper2video/scripts/render_video.py
  -> timeline.json from skills/paper2video/scripts/build_timeline.py
  -> video.mp4 with burned-in subtitles from add_subtitles.py
```

The important branch-level contract is this: when a `paper2assets` package is
available, `narration.json` is the canonical narration order. Use it for TTS,
video frame/audio pairing, and subtitle timing. This keeps paper2poster,
paper2blog, paper2slides, and paper2video aligned.

## Paths

Run commands from the AutoResearch repo root unless noted.

```bash
PAPER2POSTER=skills/paper2poster
PAPER2VIDEO=skills/paper2video
PAPER2ASSETS=skills/paper2assets
```

`ppt-master` is an external dependency, not a path that every agent has:

```bash
git clone https://github.com/hugohe3/ppt-master /path/to/ppt-master
PPT_MASTER_DIR=/path/to/ppt-master
```

Do not hard-code `~/.claude/skills/...`. Users may run this repo from Codex,
Claude Code, a shell, or another agent.

## Output Contract

Follow the shared paper2assets v2 layout. The paper2video bundle top level holds
only deliverable files plus `manifest.json`; all audio, captions, slide decks,
clips, rendered frames, reports, and timeline/cue metadata live under `assets/`:

```text
<video_outdir>/
  video.mp4                  # required, burned-in subtitles with translucent caption box
  video_no_subtitles.mp4     # required, raw/pre-subtitle playback copy for paper2reel
  video.pptx                 # required, for follow-up editing
  manifest.json
  assets/
    audio/                         # script.json, *.mp3, word timings, TTS manifests
    captions/                      # video.srt, video.vtt
    slides/                        # slides.pptx, rendered slide frames, ppt-master export copy
    clips/                         # raw render and optional segment clips
    meta/                          # duration reports, timeline, visual cues, QA reports
```

Initialize it before running the route:

**Pick `<video_outdir>` (resolve BEFORE any file writes).** The bundle directory is shared across every paper2* skill — when paper2assets, paper2poster, paper2blog, and paper2video target the same root, the video's slides/audio/clips sit next to the poster's HTML, the blog's `.docx`, and the shared narration script in one self-contained package. Resolve deterministically:

1. **An explicit `<video_outdir>` argument from the caller wins** — honor it verbatim. The defaults below only fire when no path was passed.
2. **A `paper2assets` package already exists** → reuse its folder verbatim as `<video_outdir>`. The canonical detection signal is `<dir>/assets/meta/paper_spec.md` (the cross-skill source of truth produced by `paper2assets` Step 4); `<dir>/manifest.json` with `"layout": "v2-assets"` is a confirming hint when present. Writing into the same bundle means Route A reads `assets/meta/narration.json` from the same root it writes `assets/audio/*.mp3` into, with no path swap — and downstream tools that walk `manifest.json` see the video MP4s alongside everything else.
3. **Otherwise (a bare PDF is the only input)** → default to **`<input_pdf_dir>/<pdf_stem>/`** — the directory containing the input PDF, then a subfolder named after the PDF basename (no extension). Example: `papers/8008_Ink3D_Sculpting.pdf` → `<video_outdir> = papers/8008_Ink3D_Sculpting/`. This matches the `paper2assets` default convention, so if Route A invokes `paper2assets`'s `build_package.py` below it lands in the same bundle without a later move.

`$VIDEO_OUT` and `$PAPER_ASSETS` are the SAME directory under this rule. The two variable names persist below for readability — `$PAPER_ASSETS` is used where the snippet emphasizes "I'm reading paper2assets meta", `$VIDEO_OUT` where it emphasizes "I'm writing the video bundle" — but in practice they always point at one root.

```bash
# 1. Resolve $VIDEO_OUT per the rule above. $PAPER_ASSETS aliases the same path.
if [[ -n "$video_outdir_arg" ]]; then
  VIDEO_OUT="$video_outdir_arg"                                  # explicit caller arg wins
elif [[ -f "$paper2assets_dir/assets/meta/paper_spec.md" ]]; then
  VIDEO_OUT="$paper2assets_dir"                                  # reuse the paper2assets bundle
else
  VIDEO_OUT="$(dirname "$paper_pdf")/$(basename "$paper_pdf" .pdf)"
fi
PAPER_ASSETS="$VIDEO_OUT"  # one bundle root — Route A reads paper2assets meta from here

# 2. Create the assets/ scaffolding under that root
VIDEO_ASSETS=$VIDEO_OUT/assets
VIDEO_AUDIO=$VIDEO_ASSETS/audio
VIDEO_CAPTIONS=$VIDEO_ASSETS/captions
VIDEO_SLIDES=$VIDEO_ASSETS/slides
VIDEO_CLIPS=$VIDEO_ASSETS/clips
VIDEO_META=$VIDEO_ASSETS/meta
mkdir -p "$VIDEO_AUDIO" "$VIDEO_CAPTIONS" "$VIDEO_SLIDES" "$VIDEO_CLIPS" "$VIDEO_META/reports"
```

The MP4 produced directly by `render_video.py` is the raw no-subtitle render.
Keep an audit copy under `$VIDEO_CLIPS/video_raw.mp4`, and also copy it to
`$VIDEO_OUT/video_no_subtitles.mp4` as a required deliverable. The default
playback deliverable with burned-in subtitles is `$VIDEO_OUT/video.mp4`.

## Two Supported Routes

### Route A - paper2assets-aligned paper video

Use this when we want the video content to match paper2poster/paper2blog.

1. Build or reuse the shared package:

```bash
python skills/paper2assets/scripts/build_package.py <paper.pdf> --outdir "$PAPER_ASSETS"
```

If `paper_spec.md` already exists, sync structured claims and narration:

```bash
python skills/paper2assets/scripts/build_package.py <paper.pdf> \
  --outdir "$PAPER_ASSETS" \
  --skip-extract \
  --paper-spec "$PAPER_ASSETS/assets/meta/paper_spec.md"
```

2. Export video narration inputs from the shared package:

```bash
python skills/paper2video/scripts/assets_to_script.py "$PAPER_ASSETS" \
  --out "$VIDEO_AUDIO/script.json" \
  --notes-dir "$VIDEO_META/notes"
```

For meeting-style duration targets, shape narration before TTS:

```bash
python skills/paper2video/scripts/assets_to_script.py "$PAPER_ASSETS" \
  --target-minutes 3 \
  --duration-tolerance-seconds 30 \
  --out "$VIDEO_AUDIO/script.json" \
  --notes-dir "$VIDEO_META/notes" \
  --duration-plan-out "$VIDEO_META/duration_plan.json" \
  --duration-rewrite-request-out "$VIDEO_META/duration_rewrite_request.json"
```

When the current narration already fits the target estimate, this writes:

```text
$VIDEO_AUDIO/script.json         # generate_audio.py-compatible script
$VIDEO_META/notes/<id>.md        # subtitle-friendly notes, same ids/order
$VIDEO_META/duration_plan.json   # when --target-minutes is used
```

When semantic rewriting is required, it writes `duration_plan.json` and
`duration_rewrite_request.json` instead of a final `script.json`. Fill the
request with rewritten prose, then rerun:

```bash
python skills/paper2video/scripts/assets_to_script.py "$PAPER_ASSETS" \
  --target-minutes 3 \
  --duration-rewrite-in "$VIDEO_META/duration_rewrites.json" \
  --out "$VIDEO_AUDIO/script.json" \
  --notes-dir "$VIDEO_META/notes" \
  --duration-plan-out "$VIDEO_META/duration_plan.json"
```

Duration control is a two-stage contract:

1. Plan narration against `--target-minutes` before TTS. If the current script
   is clearly too long or too short, the helper writes
   `duration_rewrite_request.json` and stops. The agent must rewrite each
   requested section as a complete narration within its word budget; do not
   truncate by keeping only the first sentences.
2. After the first audio/video render, run `plan_tts_rate.py` against the real
   duration report. Use the generated rate plan only for small residual timing
   errors. If the plan says `needs_script_rewrite`, regenerate the script
   instead of forcing an unnatural speech rate.

```bash
python skills/paper2video/scripts/plan_tts_rate.py \
  --duration-plan "$VIDEO_META/duration_plan.json" \
  --duration-report "$VIDEO_META/video_duration_report.json" \
  --target-minutes 3 \
  --out "$VIDEO_AUDIO/tts_rate_plan.json"

python skills/paper2video/scripts/generate_edge_audio.py \
  "$VIDEO_AUDIO/script.json" \
  --outdir "$VIDEO_AUDIO" \
  --rate-plan "$VIDEO_AUDIO/tts_rate_plan.json" \
  --timings-out "$VIDEO_AUDIO/word_timings.json"
```

If the video deck has fewer slides than `narration.json`, pass an explicit
comma-separated order:

```bash
python skills/paper2video/scripts/assets_to_script.py "$PAPER_ASSETS" \
  --ids title,problem,motivation,method,key-result,takeaway \
  --out "$VIDEO_AUDIO/script.json" \
  --notes-dir "$VIDEO_META/notes"
```

3. Create or provide a PPTX whose slide order matches the script sections.
This can come from `ppt-master`, a future `paper2slides`, or a user-provided
deck. The video compositor only requires a PPTX plus matching MP3s, but the
default high-quality route is `ppt-master`.

`ppt-master` discipline:

- An existing `ppt-master/examples/<topic>` project is optional reuse, not a
  prerequisite. If no suitable example exists, start a fresh ppt-master project
  from the paper/PDF or paper2assets materials and run the full ppt-master
  skill workflow.
- Do not replace ppt-master with handwritten SVG, a local simplified generator,
  or a copied example deck whose content does not come from the paper.
- Before running ppt-master, read the external
  `$PPT_MASTER_DIR/skills/ppt-master/SKILL.md` and follow its gates: source
  conversion, project init/import, Strategist Eight Confirmations, optional
  image acquisition, sequential page-by-page SVG authoring by the main agent,
  `svg_quality_checker.py`, `total_md_split.py`, `finalize_svg.py`, and
  `svg_to_pptx.py`.
- If ppt-master reaches a blocking confirmation gate and the user has not
  already approved defaults, stop and ask the user. Do not mark the route as
  unavailable merely because the deck does not already exist.
- If a machine dependency is missing, record the concrete missing dependency and
  stop. Do not silently degrade to a different slide-generation method.

When using `ppt-master`, prepare title-slide utility assets before invoking the
deck workflow:

```bash
python skills/paper2assets/scripts/fetch_logos.py \
  --outdir "$PAPER_ASSETS" --from-spec "$PAPER_ASSETS/assets/meta/paper_spec.md" || true
python skills/paper2assets/scripts/make_qr.py \
  --outdir "$PAPER_ASSETS" --from-metadata "$PAPER_ASSETS/assets/meta/metadata.json" || true
```

If `assets/meta/paper_spec.md` is not available yet, skip `fetch_logos.py`; do
not invent logos. `make_qr.py` is best-effort and only uses `paper_url`,
`code_url`, or the documented `arxiv_id` paper fallback from
`assets/meta/metadata.json`.

Add this requirement block to the prompt given to `ppt-master`:

```text
Title slide assets:
- Use the local institute logo files under <paper2assets_outdir>/assets/logos/ when present.
- Use <paper2assets_outdir>/assets/qr/code.png as a labeled "Code" QR tile when present. If
  <paper2assets_outdir>/assets/qr/paper.png is present, it may appear as a smaller labeled
  "Paper" tile. Never fabricate a missing code URL or QR.
- Place these assets as a restrained utility cluster on slide 1, preferably in
  the right-side title area or lower-right safe zone. Keep the paper title and
  main visual hierarchy dominant; logos and QR tiles should be crisp, aligned,
  readable at 1080p video size, and visually integrated with the deck palette.
- Omit unavailable assets cleanly. Do not leave broken image placeholders,
  literal file paths, or empty boxes.
```

When the final video will use highlight/cursor attention, also generate cue
anchor requirements before invoking ppt-master:

```bash
python skills/paper2video/scripts/generate_cue_requirements.py \
  "$VIDEO_AUDIO/script.json" \
  --out "$VIDEO_META/visual_cue_requirements.json" \
  --contract-out "$VIDEO_META/visual_anchor_contract.json" \
  --markdown-out "$VIDEO_META/visual_cue_requirements.md"
```

Add the generated `visual_cue_requirements.md` to the ppt-master prompt. It
asks the slide authoring pass to place stable semantic anchors in PPTX shape
name/alt text and, when SVG/HTML is produced, in SVG IDs, `<title>`, `<desc>`,
or `data-cue-label` attributes. Those anchors make the post-hoc cue matcher
verify exact contract alignment instead of guessing the intended target from
generic shapes.

Anchor contract for ppt-master:

- Add only a few anchors per slide, normally 2-5, focused on visible content
  that narration actually discusses.
- Prefer stable PPTX/SVG ids that start with `cue_`, for example
  `cue_s08_c2_multi_head_attention`.
- Put the same id and narration keywords in PPTX shape name/alt text and in SVG
  `<title>`, `<desc>`, or `data-cue-label`; with `--anchor-contract`, the cue
  matcher requires exact `anchor_id` matches.
- Anchor a specific diagram/card/chart/formula/row, not a whole slide, header,
  caption, logo, QR tile, or decorative background.
- If strict cue generation fails with low confidence, repair the slide source
  by adding or tightening anchors before rendering highlighted video.
- Prefer anchors that survive in both `svg_final` and the exported PPTX. The
  video raster frames are rendered from `svg_final` when available, while the
  PPTX remains the editable deliverable and geometry audit source.

4. Generate audio:

```bash
python skills/paper2poster/scripts/generate_audio.py \
  "$VIDEO_AUDIO/script.json" \
  --outdir "$VIDEO_AUDIO"
```

5. For highlighted video, generate PPTX-backed visual cues before rendering.

Run one cue-planning pass to locate the authored SVG anchors, inject those
boxes into PPTX shape metadata, then run the final strict pass that requires
PPTX anchors:

```bash
python skills/paper2video/scripts/generate_visual_cues.py <ppt_master_project> \
  --script-json "$VIDEO_AUDIO/script.json" \
  --audio-dir "$VIDEO_AUDIO" \
  --pptx <deck.pptx> \
  --anchor-contract "$VIDEO_META/visual_anchor_contract.json" \
  --timings-json "$VIDEO_AUDIO/word_timings.json" \
  --strict-gate \
  --require-timestamps \
  --out "$VIDEO_META/visual_cues.pre_pptx.json" \
  --geometry-report-out "$VIDEO_META/geometry_resolution.pre_pptx.json" \
  --candidate-review-out "$VIDEO_META/cue_candidate_review.pre_pptx.html" \
  --cue-plan-out "$VIDEO_META/visual_cue_plan.pre_pptx.json"

python skills/paper2video/scripts/inject_pptx_anchors.py \
  --pptx <deck.pptx> \
  --cue-plan "$VIDEO_META/visual_cue_plan.pre_pptx.json" \
  --out <deck.pptx> \
  --report "$VIDEO_META/reports/pptx_anchor_injection.json"

python skills/paper2video/scripts/generate_visual_cues.py <ppt_master_project> \
  --script-json "$VIDEO_AUDIO/script.json" \
  --audio-dir "$VIDEO_AUDIO" \
  --pptx <deck.pptx> \
  --anchor-contract "$VIDEO_META/visual_anchor_contract.json" \
  --require-pptx-anchors \
  --timings-json "$VIDEO_AUDIO/word_timings.json" \
  --strict-gate \
  --require-timestamps \
  --out "$VIDEO_META/visual_cues.json" \
  --geometry-report-out "$VIDEO_META/geometry_resolution.json" \
  --candidate-review-out "$VIDEO_META/cue_candidate_review.html" \
  --cue-plan-out "$VIDEO_META/visual_cue_plan.json"
```

6. Render the video, pinning audio order to the script JSON:

```bash
python skills/paper2video/scripts/render_video.py "$VIDEO_OUT" \
  --pptx <deck.pptx> \
  --audio-dir "$VIDEO_AUDIO" \
  --script-json "$VIDEO_AUDIO/script.json" \
  --attention-mode highlight \
  --highlight-style spotlight_laser \
  --visual-cues "$VIDEO_META/visual_cues.json" \
  --target-minutes 3 \
  --duration-report-out "$VIDEO_META/video_duration_report.json" \
  --out "$VIDEO_CLIPS/video_raw.mp4" \
  --frames-out "$VIDEO_SLIDES/frames"
```

7. Burn final subtitles and place final video/deck in the normalized output.

```bash
python skills/paper2video/scripts/add_subtitles.py "$VIDEO_OUT" \
  --mp4 "$VIDEO_CLIPS/video_raw.mp4" \
  --audio-dir "$VIDEO_AUDIO" \
  --script-json "$VIDEO_AUDIO/script.json" \
  --srt-out "$VIDEO_CAPTIONS/video.srt" \
  --vtt-out "$VIDEO_CAPTIONS/video.vtt" \
  --out "$VIDEO_OUT/video.mp4"

The default burned-in subtitle render uses a translucent dark caption box so
narration text stays separate from dense PPT content. Use `--no-subtitle-box`
only for an explicitly approved legacy/plain-caption render. Use
`--subtitle-bar` to scale the complete slide above a solid black caption band
when captions must not overlap any PPT content.
Use `--no-subtitles` when the user disables captions. It still writes SRT/VTT
for timeline and QA, but stream-copies only video/audio into `video.mp4`.

cp "$VIDEO_CLIPS/video_raw.mp4" "$VIDEO_OUT/video_no_subtitles.mp4"
cp <deck.pptx> "$VIDEO_SLIDES/slides.pptx"
cp <deck.pptx> "$VIDEO_OUT/video.pptx"
```

`$VIDEO_OUT/video.mp4` is the default playback deliverable with burned-in
subtitles. `$VIDEO_OUT/video_no_subtitles.mp4` is also a required final
deliverable for paper2reel and downstream editing, where subtitles are controlled
by a separate VTT/CC toggle.

8. Build the unified timeline contract.

`timeline.json` is the canonical mapping between narration chunks, audio
windows, subtitle cues, and visual-highlight targets. Downstream
paper2reel must consume this file instead of guessing section start/end
times from the final MP4.

```bash
python skills/paper2video/scripts/build_timeline.py \
  --script-json "$VIDEO_AUDIO/script.json" \
  --duration-report "$VIDEO_META/video_duration_report.json" \
  --visual-cue-plan "$VIDEO_META/visual_cue_plan.json" \
  --visual-cues "$VIDEO_META/visual_cues.json" \
  --captions-vtt "$VIDEO_CAPTIONS/video.vtt" \
  --audio-dir "$VIDEO_AUDIO" \
  --video "$VIDEO_OUT/video_no_subtitles.mp4" \
  --section-map "$VIDEO_META/section_slide_map.json" \
  --out "$VIDEO_META/timeline.json"
```

`--section-map` is optional only when the script ids already are the canonical
paper2assets section ids. When a ppt-master deck uses slide-specific ids such
as `03_sequence_evolution`, pass an explicit map so poster sections, slides,
blog blocks, audio, subtitles, and visual cues share the same section ids.
Prefer the grouped form when poster sections overlap:

```json
{
  "problem": [2, 3, 4],
  "motivation": [3, 4],
  "headline-numbers": [2],
  "method": [5, 6, 7, 8, 9, 10, 11, 12]
}
```

### Route B - existing ppt-master deck video

Use this when ppt-master has already produced a complete project with
`notes/`, `svg_output/`, and `exports/*.pptx`.

```text
<project_path>/
  notes/<slide>.md
  svg_output/<slide>.svg
  exports/<name>.pptx
```

If `notes/*.md` is missing but `notes/total.md` exists, run the external
ppt-master splitter:

```bash
python "$PPT_MASTER_DIR/scripts/total_md_split.py" <project_path>
```

Build TTS script JSON from ppt-master notes:

```bash
python skills/paper2video/scripts/notes_to_script.py <project_path> \
  --voice alloy \
  --target-minutes 3 \
  --out <project_path>/audio/script.json
```

Generate audio:

```bash
python skills/paper2poster/scripts/generate_audio.py \
  <project_path>/audio/script.json \
  --outdir <project_path>/audio
```

Render:

```bash
python skills/paper2video/scripts/render_video.py <project_path> \
  --pptx <project_path>/exports/<name>.pptx \
  --audio-dir <project_path>/audio \
  --script-json <project_path>/audio/script.json \
  --attention-mode highlight \
  --highlight-style spotlight_laser \
  --visual-cues <project_path>/visual_cues.json \
  --target-minutes 3 \
  --duration-report-out "$VIDEO_META/video_duration_report.json" \
  --out "$VIDEO_CLIPS/video_raw.mp4" \
  --frames-out "$VIDEO_SLIDES/frames"
```

Burn final subtitles and copy the deck into the v2 assets bundle:

```bash
python skills/paper2video/scripts/add_subtitles.py <project_path> \
  --mp4 "$VIDEO_CLIPS/video_raw.mp4" \
  --audio-dir <project_path>/audio \
  --script-json <project_path>/audio/script.json \
  --srt-out "$VIDEO_CAPTIONS/video.srt" \
  --vtt-out "$VIDEO_CAPTIONS/video.vtt" \
  --out "$VIDEO_OUT/video.mp4"

The default burned-in subtitle render uses a translucent dark caption box so
narration text stays separate from dense PPT content. Use `--no-subtitle-box`
only for an explicitly approved legacy/plain-caption render. Use
`--subtitle-bar` to scale the complete slide above a solid black caption band
when captions must not overlap any PPT content.
Use `--no-subtitles` when the user disables captions. It still writes SRT/VTT
for timeline and QA, but stream-copies only video/audio into `video.mp4`.

cp "$VIDEO_CLIPS/video_raw.mp4" "$VIDEO_OUT/video_no_subtitles.mp4"
cp <project_path>/exports/<name>.pptx "$VIDEO_SLIDES/slides.pptx"
```

## Final QA Gate

Run the final hard QA gate for either route. This is not a smoke test; it checks
the exact slide frames archived by `render_video.py --frames-out`, probes
audio/video streams, checks PPTX geometry for text overflow/overlap and
undersized visuals, checks rendered-frame blank space/sparsity, verifies the
final MP4 duration, and rejects unsafe TTS rate plans when duration control is
requested.

```bash
python skills/paper2video/scripts/check_video_package.py "$VIDEO_OUT" \
  --pptx <deck.pptx> \
  --script-json "$VIDEO_AUDIO/script.json" \
  --audio-dir "$VIDEO_AUDIO" \
  --frames-dir "$VIDEO_SLIDES/frames" \
  --mp4 "$VIDEO_OUT/video.mp4" \
  --raw-mp4 "$VIDEO_OUT/video_no_subtitles.mp4" \
  --subtitle-file "$VIDEO_CAPTIONS/video.vtt" \
  --visual-cues "$VIDEO_META/visual_cues.json" \
  --cue-plan "$VIDEO_META/visual_cue_plan.json" \
  --timeline "$VIDEO_META/timeline.json" \
  --rate-plan "$VIDEO_AUDIO/tts_rate_plan.json" \
  --target-minutes 3 \
  --require-rate-plan \
  --require-subtitles \
  --require-visual-cues \
  --require-cue-plan \
  --require-timeline \
  --require-word-timings \
  --strict \
  --out "$VIDEO_META/reports/video_qa_report.json"
```

For stricter semantic-anchor enforcement, also require the anchor contract and
PPTX-backed anchors:

```bash
python skills/paper2video/scripts/check_video_package.py "$VIDEO_OUT" \
  --pptx <deck.pptx> \
  --script-json "$VIDEO_AUDIO/script.json" \
  --audio-dir "$VIDEO_AUDIO" \
  --frames-dir "$VIDEO_SLIDES/frames" \
  --mp4 "$VIDEO_OUT/video.mp4" \
  --raw-mp4 "$VIDEO_OUT/video_no_subtitles.mp4" \
  --subtitle-file "$VIDEO_CAPTIONS/video.vtt" \
  --visual-cues "$VIDEO_META/visual_cues.json" \
  --cue-plan "$VIDEO_META/visual_cue_plan.json" \
  --anchor-contract "$VIDEO_META/visual_anchor_contract.json" \
  --timeline "$VIDEO_META/timeline.json" \
  --rate-plan "$VIDEO_AUDIO/tts_rate_plan.json" \
  --target-minutes 3 \
  --strict \
  --strict-attention \
  --require-visual-cues \
  --require-cue-plan \
  --require-anchor-contract \
  --require-pptx-anchors \
  --require-timeline \
  --require-rate-plan \
  --require-subtitles \
  --require-word-timings \
  --out "$VIDEO_META/reports/video_qa_report.json"
```

The gate must pass before delivery. If it fails, fix the deck/script/audio/cues
and re-render; do not bypass strict mode for final output. Only pass
`--allow-missing-attention` for an explicitly user-approved degraded/debug run
with no highlight.

`audio_extra_files` remains visible in the QA report but is non-blocking: an
unreferenced MP3 does not change `script.json`, the timeline, or either final
MP4. Every other warning remains blocking under `--strict` or
`--fail-on-warning`, and every error is always blocking.

Write `$VIDEO_OUT/manifest.json` with `"layout": "v2-assets"` and root-relative
paths for both MP4 deliverables plus `assets/audio/`, `assets/captions/`,
`assets/slides/`, `assets/clips/`, and `assets/meta/reports/video_qa_report.json`.
If the QA gate exits non-zero, stop and fix the video package. Do not continue
with a simplified or unverified video unless the user explicitly approves a
named degraded path.

## Audio Providers

The current shared synthesizer is:

```bash
python skills/paper2poster/scripts/generate_audio.py <script.json> --outdir <audio_dir>
```

It consumes JSON with the same section contract used by
`paper2assets`'s `assets/meta/narration.json` and by paper2poster's Listen buttons:

```json
{
  "provider": "edge",
  "voice": null,
  "sections": [
    {"id": "problem", "heading": "Problem", "text": "..."}
  ]
}
```

`paper2assets` owns the narration text only. It does not synthesize audio.
`paper2poster/scripts/generate_audio.py` is the shared synthesizer:

- `edge` is the default free backend (`edge-tts`, no API key; default voice
  `en-US-AndrewNeural`).
- `azure` is opt-in and requires the Azure config/API key expected by
  paper2poster's script; Azure voices are `alloy`, `echo`, `fable`, `onyx`,
  `nova`, `shimmer`.

The compositor does not care which provider produced the MP3s. Future provider
support (edge-tts, OpenAI TTS, ElevenLabs, etc.) should only guarantee the same
contract: one `<id>.mp3` per script section under the chosen `audio/` directory.

When strict visual-attention alignment is required and Edge TTS is acceptable,
use the bundled Edge helper because it can write word-boundary timings:

```bash
python skills/paper2video/scripts/generate_edge_audio.py \
  <project_path>/audio/script.json \
  --outdir <project_path>/audio \
  --timings-out <project_path>/audio/word_timings.json
```

Those timings let `generate_visual_cues.py --require-timestamps` and
`check_video_package.py --require-word-timings` reject highlight plans that only
use proportional/estimated timing.

## Rendering Details

`render_video.py` does:

1. Prefer `svg_final/*.svg` -> PNG frames via Playwright/Chrome. If no SVG deck
   exists, or `--frame-source pptx` is explicitly set, use the legacy PPTX ->
   PDF -> PNG path via LibreOffice and `pdftoppm`.
2. Copy the exact MP4 frames to `--frames-out` when provided; final QA should
   point `--frames-dir` at that same directory.
3. MP3 duration probing via `ffprobe` or the ffmpeg fallback.
4. One MP4 segment per slide.
5. ffmpeg concat into a final H.264/AAC MP4.

Audio ordering:

- Preferred: `--script-json <script.json>`.
- Auto-detected fallback: `<audio-dir>/script.json`, then `<project>/assets/meta/narration.json`, then `<project>/narration.json` for legacy bundles.
- Secondary fallback: `<audio-dir>/manifest.json`.
- Last resort: sorted `*.mp3` filenames.

This matters for `paper2assets`, whose ids are semantic (`problem`, `method`,
`key-result`) rather than numeric (`01-intro`, `02-method`).

ffmpeg selection:

- First honor `PAPER2VIDEO_FFMPEG` / `PAPER2VIDEO_FFPROBE` if set.
- Then prefer `imageio_ffmpeg`'s bundled static ffmpeg when installed.
- Then fall back to system `ffmpeg` / `ffprobe`.

This mirrors the ACL26 video prototype: its subtitle burn step used
`imageio_ffmpeg`'s ffmpeg 7.x because the system ffmpeg on this machine is
2.4.x and too old for reliable subtitles/audio filtering.

Useful flags:

| Flag | Purpose |
|---|---|
| `--resolution 720p|1080p|1440p|4k` | Output frame size (default 1080p) |
| `--frame-source auto|svg|pptx` | Slide raster source; `auto` prefers `svg_final` |
| `--svg-dir DIR` | Explicit SVG deck directory |
| `--frames-out DIR` | Persist the exact frames used by the MP4 for QA/review |
| `--fps N` | Frame rate (default 30) |
| `--pad-tail SECONDS` | Trailing silence after each slide (default 0.3) |
| `--start-pad SECONDS` | Leading silence before slide 1 (default 0.5) |
| `--target-minutes N` | Write a final duration report against an N-minute target |
| `--attention-mode none|highlight|cursor|both` | Burn positioned attention cues into slide segments (default `highlight`) |
| `--highlight-style box|spotlight|cursor|box_cursor|spotlight_cursor|laser|box_laser|spotlight_laser` | Presentation style for highlight cues; default `spotlight_laser` |
| `--visual-cues path.json` | Normalized per-slide highlight/cursor cue file |
| `--allow-missing-visual-cues` | Degraded/debug only; final output should not use it |
| `--frames-only` | Stop after slide-frame export |
| `--audio-only-check` | Verify frame/audio count and order |

## Duration Control

Use the duration target at script-generation time, before TTS:

```bash
python skills/paper2video/scripts/notes_to_script.py <project_path> \
  --target-minutes 3 \
  --duration-tolerance-seconds 30 \
  --out <project_path>/audio/script.json
```

or for paper2assets:

```bash
python skills/paper2video/scripts/assets_to_script.py "$PAPER_ASSETS" \
  --target-minutes 3 \
  --duration-tolerance-seconds 30 \
  --out "$VIDEO_AUDIO/script.json" \
  --notes-dir "$VIDEO_META/notes" \
  --duration-plan-out "$VIDEO_META/duration_plan.json"
```

The helper estimates TTS duration from word count and keeps the selected section
count by default. If the estimate is outside tolerance, it writes a
`duration_rewrite_request.json` with per-section target word budgets. The agent
must rewrite the whole narration for those sections, preserving all key ideas
within the budget, then rerun with `--duration-rewrite-in`. Pass
`--duration-section-mode auto` only when the deck can be regenerated to match a
shorter section list; existing PPTX decks should keep the default `keep` mode.
`--allow-extractive-duration-draft` is for experiments only and must not be used
for final deliverables.

Then pass the same target to `render_video.py`. Rendering writes
`<out_stem>_duration_report.json` with the real MP4 duration after audio exists.
Use that measured duration to produce a conservative TTS rate plan:

```bash
python skills/paper2video/scripts/plan_tts_rate.py \
  --duration-plan <project_path>/audio/duration_plan.json \
  --duration-report <project_path>/exports/video_duration_report.json \
  --target-minutes 3 \
  --out <project_path>/audio/tts_rate_plan.json
```

Only `within_tolerance`, `use_rate_adjustment`, or
`borderline_rate_adjustment` may be used for final generation. A
`needs_script_rewrite` plan is a hard instruction for the agent to go back to
`notes_to_script.py` or `assets_to_script.py`, generate/apply a semantic
duration rewrite, and then regenerate TTS, subtitles, video, and timeline. Do
not hide a large mismatch with speech-rate changes.

## Visual Attention Cues

To make static slides feel less inert, first create an explicit visual-anchor
contract from the final narration script. Give the Markdown to ppt-master while
authoring the deck so it labels the few key visual targets used by the video:

```bash
python skills/paper2video/scripts/generate_cue_requirements.py \
  <project_path>/audio/script.json \
  --out <project_path>/cue_requirements.json \
  --contract-out <project_path>/visual_anchor_contract.json \
  --markdown-out <project_path>/cue_requirements.md
```

ppt-master should write each `anchor_id` into the corresponding visible SVG and
PPTX element metadata: SVG `id`, `data-cue-label`, `<title>`, or `<desc>`, and
PPTX shape name, alt-text title, or alt-text description. SVG anchors remain
useful semantic labels, but final highlighted videos should prefer PPTX
geometry when it can be matched confidently. The cue generator records both:
`semantic_*` fields describe what narration target was selected, while
`geometry_*` fields describe the PPTX element or PPTX connected cluster whose
box is actually rendered.

Then build the cue plan from the deck, slide visuals, narration, word-boundary
timings, and the anchor contract. Use a two-pass flow when the deck was authored
through SVG: the first pass reads the SVG anchor boxes, `inject_pptx_anchors.py`
stores those boxes as invisible PPTX shapes with matching shape metadata, and
the second pass proves the editable PPTX carries the same semantic anchors.

```bash
python skills/paper2video/scripts/generate_visual_cues.py <project_path> \
  --script-json <project_path>/audio/script.json \
  --audio-dir <project_path>/audio \
  --pptx <project_path>/exports/<name>.pptx \
  --anchor-contract <project_path>/visual_anchor_contract.json \
  --timings-json <project_path>/audio/word_timings.json \
  --strict-gate \
  --require-timestamps \
  --out <project_path>/visual_cues.pre_pptx.json \
  --geometry-report-out <project_path>/geometry_resolution.pre_pptx.json \
  --candidate-review-out <project_path>/cue_candidate_review.pre_pptx.html \
  --cue-plan-out <project_path>/visual_cue_plan.pre_pptx.json \
  --audit-out <project_path>/cue_audit.pre_pptx.json \
  --html-audit-out <project_path>/cue_audit.pre_pptx.html \
  --repair-out <project_path>/cue_repair_requests.pre_pptx.json \
  --repair-md-out <project_path>/cue_repair_requests.pre_pptx.md

python skills/paper2video/scripts/inject_pptx_anchors.py \
  --pptx <project_path>/exports/<name>.pptx \
  --cue-plan <project_path>/visual_cue_plan.pre_pptx.json \
  --out <project_path>/exports/<name>.pptx \
  --report <project_path>/pptx_anchor_injection.json

python skills/paper2video/scripts/generate_visual_cues.py <project_path> \
  --script-json <project_path>/audio/script.json \
  --audio-dir <project_path>/audio \
  --pptx <project_path>/exports/<name>.pptx \
  --anchor-contract <project_path>/visual_anchor_contract.json \
  --require-pptx-anchors \
  --timings-json <project_path>/audio/word_timings.json \
  --strict-gate \
  --require-timestamps \
  --out <project_path>/visual_cues.json \
  --geometry-report-out <project_path>/geometry_resolution.json \
  --candidate-review-out <project_path>/cue_candidate_review.html \
  --cue-plan-out <project_path>/visual_cue_plan.json \
  --audit-out <project_path>/cue_audit.json \
  --html-audit-out <project_path>/cue_audit.html \
  --repair-out <project_path>/cue_repair_requests.json \
  --repair-md-out <project_path>/cue_repair_requests.md
```

Then pass positioned cues at render time:

```bash
python skills/paper2video/scripts/render_video.py <project_path> \
  --pptx <project_path>/exports/<name>.pptx \
  --audio-dir <project_path>/audio \
  --script-json <project_path>/audio/script.json \
  --attention-mode highlight \
  --highlight-style spotlight_laser \
  --visual-cues <project_path>/visual_cues.json \
  --duration-report-out "$VIDEO_META/video_duration_report.json" \
  --out "$VIDEO_CLIPS/video_raw.mp4"
```

`highlight` is the default final-delivery mode. If `--attention-mode` is not
`none`, `render_video.py` now requires `--visual-cues`; missing cues are a
blocking error unless the agent explicitly passes the degraded/debug-only
`--allow-missing-visual-cues`.

`visual_cues.json` uses normalized coordinates so it survives 720p/1080p/4K
renders:

```json
{
  "slides": [
    {
      "id": "07_fineweb_accuracy_lift",
      "cues": [
        {"start": 3.2, "end": 8.5, "type": "highlight", "box": [0.12, 0.28, 0.14, 0.21], "point": [0.19, 0.39]},
        {"start": 9.0, "duration": 4.0, "type": "cursor", "point": [0.52, 0.62]}
      ]
    }
  ]
}
```

`id` matches the audio/script section id. `index` may be used instead for
1-based slide numbers. `highlight` renders a translucent target box when a
normalized `box` is available; `point` remains as a compatibility center point
and point-only cues render as the older soft-dot fallback. For automatic cue
generation, the matcher reads semantic SVG/PPT regions and strongly prefers
explicit `cue_` anchors. It then resolves the visible geometry to PPTX when
possible: direct PPTX boxes first, small connected PPTX clusters second, and
semantic fallback only when PPTX geometry is low-confidence. Text-line targets
are promoted to their nearby module/group when that parent is still reasonably
bounded, so final highlights should point at cards, rows, formula blocks, or
figure panels rather than isolated words. Connected PPTX clusters are rejected
when the union box grows too large or crosses unrelated PPTX content. When
`--anchor-contract` is provided, anchors are no longer just a confidence bonus:
each contracted narration chunk must match its exact `anchor_id`, and
`--require-pptx-anchors` requires the match to come from PPTX geometry.

`generate_visual_cues.py` also writes `geometry_resolution.json`. Use it with
`cue_audit.html` and `cue_candidate_review.html` to inspect whether a cue
rendered from `pptx`, `pptx_cluster`, or a semantic fallback. The candidate
review page shows the narration chunk, word-timing match, selected semantic
target, final geometry target, and top rejected semantic/geometry alternatives.
`check_video_package.py --strict` reports geometry source counts and timing
source counts; it fails if `geometry_box` is malformed, does not match the
rendered cue `box`, lies outside the normalized slide canvas, or if required
word-timing alignment is low-confidence.

Highlight presentation styles:

- `spotlight_laser` is the production default: a feathered spotlight plus a
  small red laser-pointer dot at the accepted cue center.
- `box` renders a subtle slate fill plus border around the accepted box.
- `cursor` renders only a soft presentation pointer at the cue center.
- `box_cursor` combines the accepted box with the same pointer, useful for
  reviewer comparisons.
- `spotlight_cursor` combines the feathered spotlight with the same mouse
  pointer, useful when a visible arrow is preferred over the laser dot.
- `laser` renders only the small red laser-pointer dot at the cue center.
- Cursor styles render a mouse-pointer overlay and ease it between consecutive
  cue points on the same slide instead of teleporting at cue boundaries.
- Laser styles use the same eased movement between consecutive cue points as
  cursor styles.
- `spotlight`, `spotlight_cursor`, and `spotlight_laser` softly dim the
  surrounding slide with a continuous alpha-mask falloff around the accepted
  box while keeping the target at original brightness. They are tolerance modes
  and can be substantially slower on full-length videos because each cue adds
  an extra full-frame overlay mask.

Strict gate repair loop:

1. If `generate_visual_cues.py --strict-gate` exits non-zero, do not render a
   highlighted video yet.
2. Treat `cue_repair_requests.md`, `cue_audit.html`, `visual_cue_plan.json`,
   and `slide_regions.json` as agent debugging inputs, not user homework.
3. Open those files and fix the root cause in the deck or narration: add precise SVG cue labels,
   make a huge container into a smaller semantic group, retarget away from
   header/caption/chrome, or rewrite/split a narration chunk so it names the
   same concept as the slide. If the failure says `anchor_missing`, add the
   requested `anchor_id` to the intended PPTX shape metadata and rerun export.
4. Re-run ppt-master post-processing/export when SVGs changed, rerun the
   pre-PPTX cue pass, rerun `inject_pptx_anchors.py`, then rerun
   `generate_visual_cues.py --strict-gate --require-pptx-anchors`.
5. Attempt at least two concrete repair passes before reporting a blocking
   visual-cue ERROR, unless the failure is a missing dependency or a user
   decision is required.
6. While repairing, record a `REPAIRING` note in `$VIDEO_OUT/manifest.json` or
   `$VIDEO_META/reports/video_qa_report.json`; promote to final `ERROR` only
   after the agent has no viable repair path or needs user/external action.

`generate_visual_cues.py` writes the audit and repair files even when strict
mode fails, then exits non-zero. That is intentional: diagnostics exist for
repair, while downstream rendering is still blocked until the gate passes.

After a highlighted render, run `build_timeline.py` with the same
`visual_cue_plan.json`, `visual_cues.json`, `duration_report.json`, script, and
subtitle VTT. This is what binds every spoken chunk to its audio time, subtitle
cue, and visual target. Do not let downstream tools cut video by ad-hoc
timestamps that are not derived from the timeline.

For section-level playback in paper2reel, build section media from
complete slide clips and append a short silent freeze tail. This avoids abrupt
audio/video endings and avoids cutting a slide mid-sentence simply because the
section boundary falls inside a rendered MP4 timestamp. Use
`$VIDEO_OUT/video_no_subtitles.mp4` as the paper2reel video source, not
the burned-in subtitle deliverable at `$VIDEO_OUT/video.mp4`; otherwise
the viewer can show duplicate subtitles when CC is enabled.

## Subtitles

`add_subtitles.py` can use either notes files or script JSON:

- With `--script-json`, subtitle order and fallback text come from the JSON.
- Without it, the script preserves legacy ppt-master behavior: sorted
  `notes/*.md` paired with sorted `audio/*.mp3`.

Default mode burns subtitles into the video pixels with a translucent dark
caption box. Pass `--soft` to mux a toggleable `mov_text` track instead. Pass
`--srt-only` to produce just the SRT. Pass `--no-subtitle-box` only for a
user-approved legacy/plain-caption render. Pass `--subtitle-bar` to preserve
the complete slide above a solid black bottom band and burn white captions
inside that reserved band; this avoids covering dense PPT content.
Pass `--no-subtitles` to keep the public MP4 caption-free while still writing
the SRT/VTT timing sidecars required by the internal timeline and QA.

## Sanity Checks

Before calling the video done:

- PPTX slide count equals the number of selected script sections.
- Every selected section has `audio/<id>.mp3`.
- `render_video.py --audio-only-check` passes.
- `ffprobe` reports a positive duration for the final MP4.
- `check_video_package.py --strict` passes and writes `video_qa_report.json`.
- If visual attention is enabled, `check_video_package.py --strict-attention`
  passes with `--require-visual-cues --require-cue-plan --require-timeline
  --require-word-timings`.
- `timeline.json` exists and every chunk has the expected audio window,
  subtitle cues, and accepted visual cue before paper2reel consumes it.
- If subtitles are requested, `add_subtitles.py` uses the same `--start-pad`,
  `--pad-tail`, and `--script-json` as `render_video.py`.

## References

- `references/script_json_schema.md` - narration JSON shape and TTS gotchas.
- `references/render_video.md` - compositor internals and ffmpeg debugging.
- `references/visual_cues.md` - visual cue JSON schema and examples.
