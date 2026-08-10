---
name: ppt2video
description: Render any local PowerPoint PPTX into a fresh narrated video bundle with native or script-timed object animations, Notes-first and Alt-Text-fallback narration, optional user script overrides, spotlight cues, bottom-band subtitles, editable source delivery, timeline metadata, and strict QA. Use for ordinary presentations as well as Paper2Video decks, when a user has edited a PPTX, needs to rerender an animated deck without an LLM or ppt-master, or needs the Author Notes and Alt Text protocol.
---

# Convert an edited PPTX to video

This is a general-purpose PowerPoint-to-video tool embedded in `paper2video` so
both skills can share one deterministic rendering engine. It is not limited to
research papers or to a previously delivered `video.pptx`. Use any local PPTX
as the visual source. Prefer canonical Author Notes for precise narration and
marker timing. When canonical Notes are absent, read explicit Shape Alt Text
`Script:` fields. Do not reuse audio, video, or cache files from an older
bundle.

## Authoring contract

For precise control, write a Notes block whose handle matches a top-level shape
or group:

```text
## [latency-card] latency-card
[[Fly In]] A new latency card appears. [[Spotlight]] It reports lower latency.
```

Use the same bracketed handle as the first Alt Text line. Alt Text stays compact
so a PowerPoint user sees only the editable handle and script:

```text
[latency-card]
Script: [[Fly In]] A new latency card appears. [[Spotlight]] It reports lower latency.
```

The baseline hash and generated ordering provenance live inside the PPTX shape
OOXML. Native effect, target, trigger, and delay data stay in PowerPoint's
`p:timing` tree. They do not appear in Alt Text. Older verbose
`[Paper2Video]` blocks remain readable and migrate to this two-line form on the
next writeback. Keep Author Notes clean. Read
[../references/editable_pptx.md](../references/editable_pptx.md) for the
hidden provenance contract.

The stable handle resolves the target directly, so Notes order controls spoken
order and does not need to copy Animation Pane order. Marker positions determine
their Edge word-boundary times. A system-generated Notes block is inserted by
row-aware canvas order: top-to-bottom between rows and left-to-right within one
row. A Notes marker may add an MP4 effect even when the shape has no matching
native row.

For a PPT-native workflow without canonical Notes, put an explicit script in
the shape's Alt Text and use the native Animation Pane for effects:

```text
[latency-card]
Script: A new latency card appears and reports lower latency.
```

Read [../references/animations.md](../references/animations.md) before changing
effect names or resolving a protocol conflict.

## Authority and conflict rules

Apply this precedence:

1. An explicitly selected user `script.json` owns narration for that render.
2. Canonical Author Notes own handles. For narration, compare Notes and Alt Text
   with the last system-synchronized script hash stored in shape OOXML. A change
   on only one surface wins; if both changed differently, Notes wins and the
   authority report records the conflict.
3. Explicit Alt Text `Script:` fields provide narration when Notes are absent or
   when their script alone differs from the stored baseline.
   A new animated target with only plain pre-protocol Alt Text uses that text
   once as its initial script and is normalized to compact `Script:` metadata.
4. Explicit Author Notes order wins. System-generated Notes blocks follow
   row-aware spatial order, independent of Animation Pane order.
5. Animation Pane supplies native effects plus `On Click`, `With Previous`,
   `After Previous`, and
   delay relationships when an explicit Notes marker does not own timing. These
   dependencies are recomputed after Notes timing: sequential rows wait for the
   prior Notes block's narration and effects, while `With Previous` explicitly
   permits overlap.
6. Shape OOXML stores `orderSource` and canonical `orderIndex` beside the script
   hash. An explicit Notes reorder promotes the visible sequence to
   `author_notes`; otherwise generated blocks remain `geometry`.
7. The PowerPoint canvas owns all visible pixels and geometry.

When Notes and Alt Text both changed differently, Notes wins and the delivered
PPTX Alt Text is refreshed. When a Notes effect conflicts with a native effect
of the same kind, use the Notes name and time for MP4; preserve non-conflicting native effects.
Fail when a Notes handle cannot be resolved safely or an effect name is
unsupported.

## One-command render

```bash
python ResearchStudio-Reel/skills/paper2video/scripts/render_edited_pptx.py \
  path/to/edited.pptx \
  path/to/new_video_bundle \
  --resolution 1080p
```

Input and output may be arbitrary local paths. Add
`--script-json path/to/edited-script.json` only when a user-edited external
script should override PPTX narration. This command must:

1. Normalize compact Alt Text from authoritative Notes when present.
2. Generate handles and compact two-line Alt Text for new animation targets.
3. Backfill canonical Notes when the source has only Alt Text or native rows.
4. Extract narration using user script, Notes, then Alt Text precedence.
5. Generate fresh Edge TTS and word timings, or deterministic silent audio for
   a native-only silent slide.
6. Build Notes word timing and Animation Pane trigger/delay mappings.
7. Align every subtitle cue to its actual first and last Edge TTS word
   boundaries. Never use proportional timing in a final render.
8. Render PPTX pixels, animations, audio, spotlight, and bottom-band subtitles.
9. Write `timeline.json`, subtitle-alignment evidence, mapping reports, and
   strict QA evidence.

Do not pass `--prebuilt-audio-dir` for a final render. Do not pass `--no-qa`.

For a change-aware rerender, ordinary users choose whether to keep existing
narration or regenerate only changed elements. The latter requires a previous
PPTX baseline and an OpenAI API key:

```bash
python ResearchStudio-Reel/skills/paper2video/scripts/render_edited_pptx.py \
  edited.pptx new-bundle \
  --baseline-pptx previous-video.pptx \
  --narration-mode regenerate
```

Regenerated scripts are written back into both Author Notes and compact Alt
Text in the delivered PPTX. `script.json` remains an Advanced override, not the
normal editing surface.

## Ordinary animated PPTX

If the deck does not yet contain canonical Notes and Alt Text, bootstrap a copy
from an existing narration script, then edit that copy:

```bash
python ResearchStudio-Reel/skills/paper2video/scripts/bootstrap_editable_pptx.py \
  path/to/animated-source.pptx \
  --script-json path/to/script.json \
  --out path/to/editable-video.pptx \
  --report-out path/to/bootstrap-report.json
```

## Completion gate

Require these deliverables:

```text
new_video_bundle/
  video.mp4
  video_no_subtitles.mp4
  video.pptx
  manifest.json
  assets/audio/
  assets/captions/
  assets/meta/timeline.json
  assets/meta/reports/author_notes_authority.json
  assets/meta/reports/subtitle_timing_alignment.json
  assets/meta/reports/video_qa_report.json
```

Confirm the subtitle timing report has `status: word_aligned`, then confirm
`video_qa_report.json` has `passed: true`, `error: 0`, and `warning: 0`.
Do not claim completion until the strict renderer exits 0.
