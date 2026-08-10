# Author Notes animations in Paper2Video

Paper2Video uses PowerPoint animation metadata as an authoring contract. The
production editable route renders the current PPTX itself; the legacy/source
authoring route can still render equivalent SVG groups. Neither route records a
PowerPoint playback window.

## Ownership and timing

| Layer | Owner | What it stores |
|---|---|---|
| Editable object animation | PPT Master / PPTX OOXML | Shape target, native effect, pane order, duration, trigger |
| Optional authoring overrides | `animations.json` in PPT Master | Per-slide/group effect, order, delay, duration, trigger |
| Named narration mapping | PowerPoint Author Notes | Stable handle, supported MP4 effect name, marker position, transcript block |
| Video timing | `animation_manifest.json` | Stable handle, PPTX shape id or SVG locator, and Edge word-aligned start/duration |
| Render evidence | `animation_render_report.json` | Strategy, global MP4 time, layer bbox, pixel sample times |
| Subtitle timing | SRT/VTT | Caption cues on the same audio clock |

`svg_to_pptx.py -a auto` writes native object animations into the PPTX. The
optional `animations.json` controls that export but is not a subtitle or video
script. PPT Master's native animation schedule is presentation-oriented; it
does not by itself align every object entrance to a spoken word.

The Author Notes bridge supplies that missing link. Marker position identifies
the corresponding transcript block and `word_timings.json` supplies Edge TTS
word boundaries. The renderer reconciles Notes blocks with Animation Pane
targets, then writes compact Alt Text containing only the first-line `[handle]`
and `Script:`. The accepted script hash and generated ordering provenance live
in the shape's `p2v:scriptBaseline` OOXML extension, while native animation
target, effect, trigger, delay, and grouping remain in PowerPoint's `p:timing`
tree. Subtitles, spotlight/laser cues, and animations therefore share the same
audio clock without exposing generated metadata in Alt Text or borrowing
timestamps from one another.

Spotlight has two marker forms:

| Form | Spoken/captioned text | Video duration |
|---|---|---|
| `[[Spotlight]]` | Text after the marker | Native emphasis duration or 2.4 s default |
| `[[Spotlight] spoken phrase]` | The enclosed phrase | First enclosed Edge word start through last enclosed Edge word end |

The spoken-span form is preferred when a human editor wants direct duration
control without editing JSON. Its enclosed phrase remains ordinary narration
and subtitle text. It is valid only for `Spotlight`; empty scopes, partial-word
boundaries, and sequence-gated scopes that end before their resolved start fail
closed. The manifest and cue plan record `duration_source: script_scope`, the
scope text, and its resolved word range. Point markers remain backward
compatible.

For an ordinary user-added animated target that has only plain pre-protocol Alt
Text, normalization promotes that sentence to the target's initial narration
and writes it back as managed `Script:` plus canonical Notes. This gives the
block a real speech window, so the following sequential target cannot begin
after only the short entrance transition.

After Notes markers are word-aligned, editable rendering recomputes all native
dependencies on that final clock. Each Notes block releases the next `On Click`
or `After Previous` row only after both its narration and effects finish.
`With Previous` remains the explicit overlap control. The pipeline pads the
fresh audio tail when the resolved sequence ends after spoken narration, and
strict QA rejects a sequential effect that starts before its block gate.

When canonical Notes cover only part of a slide, a user-added native animated
target that is absent from Notes is inserted at its Animation Pane position
relative to the Notes-owned native targets. Explicit Notes blocks still keep
their relative order when Notes and Pane conflict. A new first Pane row
therefore remains first instead of being appended after all existing Notes
blocks. Only scripted targets outside the Animation Pane use top-to-bottom,
left-to-right geometry fallback.

Author Notes are authoritative for handles, narration, supported MP4 entrance
names, marker positions, and `Spotlight` intent. The Animation Pane is
authoritative for target shapes, target order, and entrance/emphasis row kind.
A supported Notes entrance name may override a different recognized native
entrance name; the protocol report records both. Counts, order, and row kind
remain strict and fail when they cannot be reconciled safely.

## Support matrix

PPT Master currently registers 22 native entrance effects. Paper2Video renders
the following strict subset into MP4 pixels:

| PPT Master key | Author Notes name | PPTX preset | MP4 strategy | Default duration |
|---|---|---|---|---:|
| `appear` | `Appear` | `1 / 0` | instant reveal | 0.12 s |
| `fade` | `Fade In` | `10 / 0` | alpha fade | 0.48 s |
| `fly` | `Fly In` | `2 / 4` | left-to-right motion and fade | 0.56 s |
| `zoom` | `Zoom In` | `23 / 0` | center scale and fade | 0.48 s |
| `wipe` | `Wipe In` | `22 / 1` | left-to-right reveal | 0.52 s |
| `dissolve` | `Dissolve In` | `9 / 0` | alpha dissolve | 0.48 s |
| `circle` | `Circle In` | `6 / 0` | circular mask reveal | 0.52 s |
| `diamond` | `Diamond In` | `8 / 0` | diamond mask reveal | 0.52 s |

The remaining native presets are recognized but do not have an MP4 strategy:

| PPT Master key | PowerPoint name | PPTX preset |
|---|---|---|
| `cut` | `Cut In` | `42 / 8` |
| `split` | `Split In` | `16 / 21` |
| `blinds` | `Blinds In` | `3 / 10` |
| `checkerboard` | `Checkerboard In` | `5 / 6` |
| `random_bars` | `Random Bars In` | `14 / 10` |
| `peek` | `Peek In` | `12 / 4` |
| `wheel` | `Wheel In` | `21 / 0` |
| `box` | `Box In` | `4 / 0` |
| `plus` | `Plus In` | `13 / 0` |
| `strips` | `Strips In` | `18 / 12` |
| `wedge` | `Wedge In` | `20 / 0` |
| `stretch` | `Stretch In` | `17 / 0` |
| `expand` | `Expand In` | `50 / 0` |
| `swivel` | `Swivel In` | `19 / 0` |

An unknown native preset tuple fails during extraction. A recognized native
entrance without an MP4 strategy may be mapped only when Author Notes explicitly
choose one of the eight supported MP4 names; that override is recorded rather
than silently changed to Fade. An unsupported or misspelled Notes name fails.
PPT Master's seven page transitions (`fade`, `push`, `wipe`, `split`, `strips`,
`cover`, `random`) are a separate slide-level layer and are not part of the
object-animation manifest.

## Build and render

Editable PPTX route, recommended after a user changes the deck:

```bash
python skills/paper2video/scripts/build_animation_manifest.py \
  --pptx "$VIDEO_OUT/video.pptx" \
  --word-timings "$VIDEO_AUDIO/word_timings.json" \
  --protocol-report-out "$VIDEO_META/reports/editable_pptx_protocol.json" \
  --out "$VIDEO_META/animation_manifest.json"

python skills/paper2video/scripts/render_video.py "$VIDEO_OUT" \
  --pptx "$VIDEO_OUT/video.pptx" \
  --audio-dir "$VIDEO_AUDIO" \
  --script-json "$VIDEO_AUDIO/script.json" \
  --frame-source pptx \
  --animation-source pptx \
  --animation-manifest "$VIDEO_META/animation_manifest.json" \
  --animation-report-out "$VIDEO_META/reports/animation_render_report.json" \
  --require-animations \
  --out "$VIDEO_CLIPS/video_raw.mp4"
```

The renderer creates cumulative PPTX reveal states with LibreOffice and derives
each animation layer from adjacent pixel states. Text, color, position, image,
style, addition, and deletion edits therefore come from the current deck, not
from an earlier SVG export. The manifest records the PPTX SHA-256; rendering
and strict QA fail if the deck changes after the mapping is built.

SVG authoring route:

```bash
python skills/paper2video/scripts/build_animation_manifest.py \
  --author-notes-report "$VIDEO_META/reports/author_notes_report.json" \
  --word-timings "$VIDEO_AUDIO/word_timings.json" \
  --svg-dir "$PPT_MASTER_PROJECT/svg_final" \
  --out "$VIDEO_META/animation_manifest.json"

python skills/paper2video/scripts/render_video.py "$PPT_MASTER_PROJECT" \
  --pptx "$VIDEO_OUT/video.pptx" \
  --audio-dir "$VIDEO_AUDIO" \
  --script-json "$VIDEO_AUDIO/script.json" \
  --frame-source svg \
  --svg-dir "$PPT_MASTER_PROJECT/svg_final" \
  --animation-manifest "$VIDEO_META/animation_manifest.json" \
  --animation-report-out "$VIDEO_META/reports/animation_render_report.json" \
  --require-animations \
  --out "$VIDEO_CLIPS/video_raw.mp4"
```

Final QA must receive the same manifest and report plus the raw MP4:

```bash
python skills/paper2video/scripts/check_video_package.py "$VIDEO_OUT" \
  ... \
  --raw-mp4 "$VIDEO_OUT/video_no_subtitles.mp4" \
  --animation-manifest "$VIDEO_META/animation_manifest.json" \
  --animation-report "$VIDEO_META/reports/animation_render_report.json" \
  --require-animations \
  --strict
```

The strict animation gate checks exact slide/order/locator/name coverage,
Edge timing provenance, strategy mapping, valid layer bboxes, and transition
pixel changes inside every mapped bbox. For `source_kind: pptx`, it also checks
the delivered PPTX, manifest, and render report all carry the same SHA-256 and
shape ids.

## Is PPT Master required?

PPT Master is not a runtime dependency after the first native PPTX exists. It
remains the preferred upstream authoring tool because it gives each Group a real
Animation Pane effect. A user can then edit that PPTX and run
`render_edited_pptx.py` locally with no LLM and no ppt-master checkout. See
`editable_pptx.md` for the exact mutation contract.
