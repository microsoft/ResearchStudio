# Editable PPTX local rerender contract

The editable route uses the delivered PowerPoint as the local authoring file.
The canvas owns visible pixels. Canonical Author Notes own handles. Narration
and marker positions are reconciled against the last system-synchronized script
hash, so a user edit made only in Notes or only in Alt Text is retained. Without
that baseline, Notes remain authoritative except for the documented plain Alt
Text migration. Explicit Notes order is preserved. System-generated Notes
blocks use row-aware canvas order, while Animation Pane supplies native effects,
triggers, delays, and grouping. Rerendering requires no LLM or ppt-master
checkout.

For compatibility with ordinary PowerPoint editing, a new animated target may
start with one plain Alt Text sentence instead of protocol metadata. When that
target has no Notes block or managed `Script:`, normalization promotes the
plain text to its initial narration, then writes canonical Notes and a managed
`Script:` field. Its sequence block therefore waits for that speech before the
next sequential animation starts.

## One-time bootstrap

An ordinary native animated deck can be converted to the protocol without an
LLM or a package-specific script:

```bash
python skills/paper2video/scripts/bootstrap_editable_pptx.py \
  <animated-source.pptx> \
  --script-json <narration-script.json> \
  --out <editable-video.pptx> \
  --report-out <bootstrap-report.json>
```

The bootstrap assigns stable handles to Animation Pane targets, writes concise
canonical named-marker Notes, and writes matching compact Alt Text containing
only the handle and script. It splits each slide narration
deterministically across targets in row-aware spatial order, validates the
result, and preserves the original native timing tree.

## One-command rerender

```bash
python skills/paper2video/scripts/render_edited_pptx.py \
  <edited.pptx> <output_bundle> \
  --ids-from-script <previous_bundle>/assets/audio/script.json
```

The command performs these deterministic stages:

1. Parse slides in `p:sldIdLst` presentation order.
2. Read native entrance and emphasis targets from each slide's `p:timing` tree.
3. Resolve Notes directly by stable shape handle, falling back to Animation
   Pane order only when a one-to-one compatibility mapping is safe.
4. Compare Notes and Alt Text with the stored baseline hash, accept the edited
   side, and refresh both surfaces from the accepted script.
5. Optionally apply an explicitly selected user-edited `script.json`.
6. Run Edge TTS and collect word boundaries.
7. Build a word-aligned animation manifest from normalized `video.pptx`.
8. Render cumulative reveal states from that exact PPTX with LibreOffice.
9. Align each subtitle cue to the actual first and last Edge word boundary.
10. Encode animation, optional spotlight, audio, and bottom-band subtitles.
11. Write measured duration, subtitle alignment evidence, and the media timeline.
12. Run strict media, timeline, protocol, source-hash, subtitle, and animation QA.

`--prebuilt-audio-dir` is an offline/test option. Its MP3 names and
`word_timings.json` must exactly match the newly extracted Notes script or the
manifest stage fails.

## Author Notes and Alt Text

Keep the human-authored Notes block concise:

```text
## [result-card] Main result card
[[Fade In]] Accuracy rises by [[Spotlight] twelve points].
```

The renderer writes compact Alt Text on the corresponding animated target:

```text
[result-card]
Script: [[Fade In]] Accuracy rises by [[Spotlight] twelve points].
```

Authority and validation rules:

- Notes handles are authoritative. Exact handles target shapes without relying
  on Animation Pane position. When an old deck lacks matching handles, pane
  order is used only for a complete one-to-one compatibility mapping.
- Explicit Notes blocks keep their relative narration order and may differ from
  Animation Pane. A system-generated block is inserted by visual geometry:
  rows run top-to-bottom, and elements that substantially overlap vertically
  run left-to-right. This makes small y alignment differences harmless.
- A supported Notes entrance name may differ from the native entrance name.
  The Notes name controls the MP4 strategy and the conflict report records both.
- A Notes marker can add an MP4-only entrance or spotlight without a native row.
  Non-conflicting native effects remain active.
- The last system-synchronized script hash is stored only in shape OOXML. A
  Notes-only edit or Alt-Text-only edit wins. If both
  changed to the same value, accept it. If both changed differently, Notes wins
  and `author_notes_authority.json` reports `conflict: true` with both hashes.
- The authoritative provenance node is
  `ppt/slides/slideN.xml` →
  `p:cNvPr/a:extLst/a:ext/p2v:scriptBaseline`. Besides `sha256`, it stores
  `orderSource` and canonical `orderIndex`. Alt Text does not expose these
  generated fields. A user-reordered Notes sequence is promoted to `author_notes`;
  unchanged generated blocks remain `geometry` and follow current positions.
- For a legacy PPTX with no baseline, a plain Alt Text replacement on a
  Notes-owned animated shape is promoted once as the user-edited script. Other
  ambiguous legacy Notes/managed-Alt differences remain Notes-first and are
  reported rather than silently discarded.
- Marker position determines its Edge word-boundary start time. The preferred
  `[[Spotlight] spoken phrase]` form keeps the phrase in speech and subtitles,
  then uses the first and last enclosed Edge word boundaries as the exact cue
  interval. Legacy `[[Spotlight]]` remains a point marker with native or
  default duration.
- Native emphasis effects map to the deterministic `Spotlight` video cue.
- Unsupported Notes marker names, ambiguous handles, nested targets, and empty
  slide narration fail closed.
- Only top-level PowerPoint elements are supported as editable animation
  targets. Group related primitives first, then animate and identify the group.
- Older verbose `[Paper2Video]` blocks remain readable. Every writeback migrates
  Alt Text to exactly `[handle]` plus `Script:`; all generated details remain in
  OOXML or native `p:timing`.
- Final subtitle cues must use `edge_word_boundary` timing. A cue starts at its
  first spoken word and ends at its last spoken word. Punctuation attaches to
  those words. Missing or mismatched boundaries fail closed instead of falling
  back to character-proportional estimates.

## Add, delete, and modify

Modify an element:

1. Change text, image, color, style, size, or position on the PowerPoint canvas.
2. Edit the Notes transcript if the spoken narration should change.
3. Keep the Notes handle stable unless intentionally renaming it. If renamed,
   the next render refreshes the Alt Text handle and script.
4. Rerun the command. Both static and animated pixels come from the edited
   PPTX, so no SVG regeneration is needed.

Add an element:

1. Add a top-level shape or group.
2. Give it a stable first-line Alt Text handle such as `[new-result]`.
3. Optionally give it a native entrance effect.
4. Add `## [new-result] ...` in Notes at the desired narration position.
5. Add the exact supported video marker, such as `[[Zoom In]]`, inside its
   transcript. A first-line `[new-result]` Alt Text handle is useful while
   editing but optional; the renderer writes the compact Alt Text.

Delete an element:

1. Delete the shape from the slide. PowerPoint removes its native animation.
2. Delete the matching Author Notes block or Alt Text `Script:` field.
3. Rerun. An unresolved Notes handle fails instead of targeting another shape.

Reordering is also explicit. Reorder Notes blocks to change spoken order.
Reorder Animation Pane rows to change native trigger relationships. Move shapes
on the canvas to change system-generated order, or reorder Notes blocks to set
an explicit sequence that overrides geometry.

## Reproducibility evidence

`animation_manifest.json` records:

- `source_kind: "pptx"`;
- the exact PPTX SHA-256;
- stable slide IDs, section IDs, shape IDs, Alt Text handles, native order,
  native and Notes-selected effect names, conflict resolution, and Edge-aligned
  times.

`animation_render_report.json` repeats the source hash and records every layer
bbox and MP4 sample window. Strict QA verifies the delivered PPTX hash and
checks an early/late pixel pair for every mapped effect.

The automated regression suite edits a synthetic PowerPoint in sequence:

- red card to blue card, proving modification reaches encoded MP4 pixels;
- add a green card, proving manifest and video reveal count increase;
- delete the original card, proving its mapping and pixels disappear;
- stale an Alt Text handle, proving Notes wins and compact Alt Text is refreshed;
- omit Notes for a native target, proving silent native effects remain valid;
- add a native-only target between two existing cards, proving generated Notes
  use row-aware left-to-right geometry instead of Animation Pane order;
- reverse Notes versus Animation Pane order, proving Notes controls narration;
- use Alt Text scripts without Notes, proving spatial generation and writeback;
- add a Notes-only effect with no native row, proving script-timed effects;
- add a native emphasis plus `[[Spotlight]]`, proving local attention mapping.

Previously delivered decks using `[ID] result-card` remain readable for local
rerenders. Bootstrap and all newly rendered decks write `[result-card]` as the
first line and the matching `Script:` as the second line. The handle mirrors
`## [result-card]` in Notes.
