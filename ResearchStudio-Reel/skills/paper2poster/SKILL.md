---
name: paper2poster
description: Render a pre-extracted paper's structured 9-section spec (`paper_spec.md`) into a single-page HTML academic poster, fit the layout to the page via an iterative measured-fill loop, and export it to print-ready PDF + PNG thumbnail. Requires the upstream `paper2assets` skill to have produced the input `<outdir>/` package (`manifest.json` at the root + an `assets/` folder holding `meta/paper_spec.md`, `meta/text.txt`, `meta/figures.json`, `meta/metadata.json`, `figures/*.png`, `logos/`, `qr/`) first. Use when the user wants an HTML poster, PDF/PNG export, or PPTX from a paper they already have extracted assets for — e.g., "render the poster", "make the poster from this spec", "export poster to PDF", "paper2poster". The three skills paper2assets → paper2poster → html2pptx run in sequence, each invokable on its own.
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, AskUserQuestion, WebFetch, WebSearch
---

# paper2poster — paper_spec.md → HTML poster → PDF/PNG + editable PPTX

This skill is the **rendering stage** of a 3-skill pipeline. It assumes `paper2assets` has already produced the input `<outdir>/`. Given that outdir, it picks figures, renders an HTML poster, iteratively fills the layout to fit a fixed page (60×36in landscape or 33.1×46.8in A0 portrait), generates per-section narration audio, hands the HTML to the bundled **html2pptx** sub-skill (vendored at `html2pptx/`) for an editable `.pptx`, and exports PDF + PNG. The html2pptx handoff is a **standard final step**, not optional — one run yields `poster.{html,pptx,pdf,png}`, because users want the editable deck in the same pass and won't call html2pptx separately.

```
   <outdir>/                              (produced by paper2assets)
     manifest.json   assets/figures/   assets/logos/   assets/qr/   assets/meta/{paper_spec.md, text.txt, figures.json, metadata.json}
     │
     ▼  Step 1 — verify prerequisites
     ▼  Step 2 — pick figures (Method / optional Motivation / optional Secondary)
     ▼  Step 2.5 — optional per-figure visual box cut (asymmetric noise the
     │             paper2assets deterministic chain couldn't catch — most
     │             figures need no further work here)
     │
     ▼  Step 3 — compose (layout × style × header) + substitute  (references/compose_poster.py → poster.html)
     │         → <outdir>/poster.html (lean: 6 core sections, Necessary only)
     │
     ▼  Step 4 — iterative fill loop (check_poster.py slack + polish)
     │         → <outdir>/poster.html (every section FULL, every figure ≥90% on one axis)
     │
     ▼  Step 5 — generate_audio.py → <outdir>/assets/audio/<id>.mp3   (free Edge TTS, from <outdir>/assets/meta/narration.json)
     │         → the Listen buttons + Full Listen play these clips by id
     │
     ▼  Step 5.9 — fit_logos.py → pack the header institution logos to fill their zone
     │             (browser-measure + greedy shape-pack; baked into poster.html)
     │
     ▼  Step 6 — render_poster.py → <outdir>/poster.pdf + <outdir>/poster.png   (applies + bakes the expand into poster.html)
     │
     ▼  Step 7 — html2pptx skill → <outdir>/poster.pptx   (reads the baked poster.html; users want the editable pptx in one run)
     │         (render FIRST — bakes the expand into poster.html; html2pptx then reads it, isolated under assets/_pptx_build/)
     │         then check_poster.py verify-final
     │
     ▼  Step 7.5 — check_poster.py deliverables (MANDATORY final gate)
     │
     └─→  Step 8 — Report absolute paths (html + pptx + pdf + png)
```

The canvas is fixed per orientation (landscape 60×36in 5:3 / portrait A0 33.1×46.8in 0.708) in the templates; do not change it.

## Mandatory finishing gates (NEVER ship outside these bands)

Two hard requirements gate the final poster. They are NOT warnings, NOT advisory, NOT "polish for next iteration" — a poster that violates either MUST be re-iterated before you call the task done:

1. **Every card figure fills 90–100% of its section on at least one axis (width OR height).** `check_poster.py polish` reports this as `FIG/NARROW`. A figure painting under 90% on *both* axes is a small stamp marooned in its card — a visible defect. Stated as one number: `fillRatio = max(w_fig / w_section, h_fig / h_section)` MUST land in `[0.90, 1.00]`. The fix order (cap tune → tighten the figure-section's prose → shorten the figcaption → rebalance the column) is in `references/staged_fill.md`. Do not exit the staged-fill loop with any figure below 90%.

2. **Every section reads `FULL` (fullRatio 0.90–1.00).** `check_poster.py slack` reports this. `OVERFLOW` (>1.10), `SPILLAGE` (1.00–1.10), `SPARSE` (0.70–0.90), and `EMPTY` (<0.70) are all unacceptable finishing states.

Both gates compose: an edit that fixes one but breaks the other must be rolled back. Loop until `slack` shows every section `FULL` AND `polish` reports zero `FIG/NARROW` warnings — then render PDF/PNG and run `verify-final` + `deliverables`.

## When to consult which reference

| Step | When you hit it, read |
|---|---|
| Step 3 — compose the template | `references/compose_poster.py` (assemble layout × style × header → self-contained `poster.html`; landscape only) |
| Step 3 — substitute placeholders | `references/template_substitution.md` (placeholder map, theme color randomization, per-section accents, vertical-sizing rule, lean-render policy) |
| Step 3 — content patterns | `references/content_patterns.md` (catalog of 16 reusable CSS widgets — callouts, key-stat, vs-compare, numbered-steps, timeline ×4 variants, chips, definition, highlight-table, pullquote, bento, equation, banner — to break up wall-of-text monotony in section bodies) |
| Step 3 — polish | `references/visual_polish.md` (typography, color/contrast, inline emphasis rules, stat grid, figure cap, callouts, arch banners, print hygiene) |
| Step 4 — staged fill | `references/staged_fill.md` (slack command, the iterative measure→select→apply→review loop, the modification-method catalog, shave-back rules) |
| Step 5.9 — pack header logos | `references/fit_logos.py` (browser-measure each logo zone + greedy shape-pack so the marks fill it; bakes rows into poster.html — run after the fill loop, before render) |
| Step 5 — audio (generate) | `scripts/generate_audio.py` synthesizes `<outdir>/assets/audio/<id>.mp3` from the `<outdir>/assets/meta/narration.json` script (produced upstream by paper2assets; free Edge TTS) for the Listen buttons. See `references/audio_narration.md`. |

## Workflow

### Parallel-safety (READ FIRST — never violate)

This skill is frequently run on MANY papers at once — a batch driver
launches one `claude -p` session per paper, each with its own separate
`<outdir>` (e.g. `papers/foo_portrait/`, `papers/bar_portrait/`, …
running concurrently). Therefore:

- **NEVER run `ps`, `pkill`, `kill`, `killall`, or otherwise inspect or
  terminate other processes.** Any other `claude` / `python` /
  `chromium` / `soffice` processes you see belong to SIBLING poster jobs
  on DIFFERENT papers. They are NOT duplicates of you and NOT competing
  for your files. Killing them corrupts other papers' runs.
- **Only ever read/write files inside YOUR given `<outdir>`.** Never
  touch another paper's directory or the shared template/config dirs.
- **If `<outdir>/poster.html` appears to have "changed unexpectedly"
  between a Read and an Edit, it changed because of YOUR OWN prior tool
  call** (a Write, a substitution script you ran, a prior Edit) — NOT a
  competing process. Re-Read the file and continue. Do not investigate
  "who else is modifying it" — nobody else is.
- The shared template at `<config>/skills/paper2poster/assets/*.html`
  is READ-ONLY input — copy it into your `<outdir>`, never edit it
  in place.

Violating any of the above is the single most common cause of a
fast-fail (~400s) where the agent rabbit-holes on phantom "process
conflicts" instead of building the poster.

### Step 0 — Cache check (do this FIRST, before any other work)

Rendering a poster runs Stage 2's iterative staged-fill loop (~15-30
min of Claude tokens) and overwrites `<outdir>/poster.html` —
destroying any inline edits, manual figure swaps, or layout tweaks the
user may have made. Before starting, **check whether the deliverables
already exist**:

```bash
if [[ -f "$outdir/poster.html" \
      && -f "$outdir/poster.pdf" \
      && -f "$outdir/poster.png" ]]; then
  echo "[paper2poster] CACHED in $outdir — poster from prior run, reusing."
  echo "  poster.html  $(stat -c%s "$outdir/poster.html") bytes"
  echo "  poster.pdf   $(stat -c%s "$outdir/poster.pdf") bytes"
  echo "  poster.png   $(stat -c%s "$outdir/poster.png") bytes"
  # Report any extras
  [[ -f "$outdir/poster.pptx" ]] && echo "  poster.pptx  (html2pptx output present)"
  [[ -d "$outdir/assets/audio" ]] && echo "  assets/audio/       (narration present)"
  exit 0
fi
```

If all three core deliverables are present, REPORT and STOP.

Re-render ONLY when:
- one of `poster.{html,pdf,png}` is missing → resume from the
  appropriate step (`poster.html` missing → start from Step 2 fill loop;
  only `poster.pdf` / `poster.png` missing → just run Step 6 render)
- the user explicitly requests it ("rebuild the poster", "regenerate",
  "fresh render", "from scratch", "redo the layout"). In that case,
  delete `<outdir>/poster.html` first so the cache check doesn't fire.

### Step 1 — Verify paper2assets prerequisites

Required argument: an `<outdir>/` path produced by the `paper2assets` skill, or a path to a source `*.pdf`. Verify the required files exist before doing any work:

```bash
ls <outdir>/assets/meta/paper_spec.md <outdir>/assets/meta/text.txt <outdir>/assets/meta/figures.json <outdir>/assets/meta/metadata.json
ls <outdir>/assets/figures/*.png
```

If any of the five required files is missing, automatically invoke the `paper2assets` skill on the source PDF to produce/populate the `<outdir>/`, then continue.

**Optional files `<outdir>/assets/logos/` and `<outdir>/assets/qr/` may be absent** — but **DO NOT silently delete the logo/QR HTML blocks** just because the directory is missing. Two common reasons the directory is missing are recoverable:

1. paper2assets's Step 6 was skipped, or
2. paper2assets's Step 6 was called with the wrong CLI flags (the `--spec` / `--outdir <outdir>/assets/logos` traps documented in paper2assets SKILL.md Step 6 caused most papers to land logos at `<outdir>/assets/logos/logos/<slug>.png` instead of `<outdir>/assets/logos/<slug>.png`).

**Recovery procedure when `<outdir>/assets/logos/` is missing or empty:**

```bash
# A. Auto-fix the nested-dir bug if present
if [ -d <outdir>/assets/logos/logos ]; then
  mv <outdir>/assets/logos/logos/* <outdir>/assets/logos/ 2>/dev/null
  rmdir <outdir>/assets/logos/logos
fi

# B. Retry fetch_logos.py from this skill (it's a paper2assets script
#    but safe to call from paper2poster as a recovery step).
python ~/.claude/skills/paper2assets/scripts/fetch_logos.py \
    --from-spec <outdir>/assets/meta/paper_spec.md --outdir <outdir>

# C. Same for qr/ if missing
python ~/.claude/skills/paper2assets/scripts/make_qr.py \
    --from-metadata <outdir>/assets/meta/metadata.json --outdir <outdir>
```

Only AFTER the retry, if logos/ is still empty (institute names didn't resolve to any Wikipedia infobox — happens for "Anonymous Institution" submissions and obscure labs), then remove the unused `<img class="logo">` elements from the poster HTML as a final fallback. Same for missing QR codes.

### Step 2 — Pick figures

Read `figures.json` + `captions.json` + `paper_spec.md`. Pick:

- **Method figure** — the figure that visualizes the paper's proposed approach. Usually labeled "Figure 1" or "Figure 2" and described in the Method section's caption ("our pipeline", "overview", "architecture"). Record its `width`, `height`, and `layout` from `figures.json`.
- **Motivation figure (optional)** — a figure that motivates the problem (a "failure mode" plot, a side-by-side comparison with prior art, a teaser). Pick only when one of the early figures clearly carries motivational signal. **Disjoint from Method.** Always rendered as `{column=half}` — full-width motivation figures are not supported.
- **Secondary figure (optional but encouraged)** — a Key Result plot, ablation chart, or qualitative samples figure. **Disjoint from Method + Motivation.** **Target ≥2 figures per poster** — Method alone leaves the empirical side as a prose-and-numbers wall.
- **Figure-rich mode → 3-column layout.** If the paper carries **more than 3 high-signal figures** (multiple result plots, a qualitative-samples gallery, architecture + component diagrams), select them all (soft cap ~6) instead of stopping at 2 — and render with the **3-column layout** (`--layout 3col`, Step 3) whose wider columns hold bigger figures, the way most author-GT posters do. Distribute the figures across all three columns; the Method figure stays the anchor. Pick only genuinely informative figures — never pad to hit a count.

Cite each picked figure with its file path: `assets/figures/<page>_figure<n>.png`. Verify the file exists on disk before relying on it.

### Step 2.5 — Per-figure visual box cut (optional, for asymmetric noise the deterministic chain couldn't catch)

`paper2assets` already ran the deterministic cleanup pipeline (`top-check` → `decaption` → `autotrim`) on every figure. Most picked figures need no further work.

If a picked figure has **asymmetric noise** the deterministic chain couldn't catch — multi-figure-page bleed on a SIDE (a vertical strip of an adjacent panel), an obvious orphan caption line a tight `decaption` threshold missed, or a region of figure content you want excluded — do one visual `box` pass:

1. **Read** the figure with the Read tool.
2. **Decide** a tight pixel bbox `(X0, Y0, X1, Y1)`.
3. **Apply:**
   ```bash
   python ~/.claude/skills/paper2assets/scripts/crop_figure.py box <outdir>/assets/figures/<file>.png --box X0 Y0 X1 Y1
   ```
   This writes a one-time `<file>.png.bak` (or preserves the existing one from paper2assets' earlier work) and updates `figures.json`.
4. **Re-Read** the result. Cap at 3 attempts per figure; restore from `.bak` with `cp` if you over-cut.

For most papers this step is a no-op — skip when the picked figures look clean after paper2assets' deterministic pipeline.

### Step 3 — Render the HTML poster

**Pick THREE independent axes — layout × style × header — then COMPOSE.**

Landscape posters are now assembled from three orthogonal source axes under `assets/` (instead of one monolithic file per combination):

- `assets/layouts/{full,half,3col}.html` — **STRUCTURE** (column grid + `.section` cards + base CSS),
- `assets/styles/{solid,framed,simple}.css` — **VISUAL** style,
- `assets/headers/{v1,v2,v3,v4}.html` — the **TITLEBAR**.

`references/compose_poster.py` injects the chosen style at `{{STYLE_CSS}}` and the chosen header at `{{HEADER}}` into the chosen layout and writes ONE self-contained `poster.html` — structurally identical to the old monolithic templates, so `check_poster.py` / `render_poster.py` / the staged-fill loop all work UNCHANGED. Pick each axis independently — **four orthogonal axes** (layout × style × header × scan) composed from ~30 small source files, not an N×M×K×J explosion of monolithic templates.

**Portrait is now composed** (`--orientation portrait`, `assets/layouts_portrait/{full,half}.html`) — it takes the STYLE + COLOR + **HEADER** axes (all 11 styles + 8 themes + 5 A0 title formats `pv1`–`pv5`, light-default header). It has no Scan-to-Read section, so it composes those three axes only. Portrait sections must use the **content-pattern widgets** (`references/content_patterns.md`) with the same ≥5-distinct-types discipline as landscape — the narrow A0 columns make it *easier* to collapse to plain bullets/tables, so it needs the widget palette more.

**Axis 0 — orientation:**

1. **`landscape`** (default) — ICML / NeurIPS / CVPR standard 60×36 in, 5:3 aspect. 4-column outer grid. **Always use landscape unless the user has explicitly opted into portrait.**
2. **`portrait`** — ACL / NAACL / AAAI 2025 standard A0 portrait, 33.1×46.8 in, 0.708 aspect. 2-column outer grid. Use **ONLY** when the pipeline sets `POSTER_ORIENTATION=portrait`. **Do NOT auto-detect orientation from the Method figure aspect ratio** — figure shape drives the layout axis (full vs half) WITHIN an orientation, not the orientation itself. A tall Method figure in landscape goes in a `half` template's single column; it does not flip the whole poster to portrait.

If `POSTER_ORIENTATION` is unset (or set to `landscape`), use landscape templates. Period.

**Axis 1 — layout (driven by Method figure shape):**

1. **`full`** (landscape `--layout full`; portrait `layouts_portrait/full.html`) — use when the Method figure is **horizontally wide**: in landscape `AR ≥ 2.5`, in portrait `AR ≥ 1.2`. Also use when `{column=full}` in `figures.json`. In landscape, this picks a 4-col outer grid with the middle two columns merged into a `.mid-wide` block. In portrait, this picks a layout with the Method section in a full-width hero band (`.method-hero` — bullets-left + wide-figure-right side-by-side) above the 2-col body.

   **Portrait pseudo-section for bullets fill:** the hero band's LEFT bullets cell is wrapped in `<div class="section method-text" data-section="method-text">…</div>` — a visually-transparent pseudo-section that participates in the staged-fill loop. slack.py measures its fill ratio as `bullets_content_h / row_h`. When the figure stretches the row taller than the bullets need, the verdict surfaces `method-text SPARSE` and the LLM expands bullets until the cell fills. This is why the AR threshold can stay loose at 1.2 instead of the safer 1.8 — the pseudo-section absorbs medium-aspect-figure whitespace automatically.
2. **`half`** (landscape `--layout half`; portrait `layouts_portrait/half.html`) — default within the orientation. Use when Method figure AR is moderate or tall AND `{column=half}` in figures.json, OR when Method figure is `**Figure:** none`. In landscape, Method is a half-width card in 1 of 4 cols. In portrait, Method is a card in 1 of 2 cols.

Read the Method figure's `width` and `height` from `figures.json`, compute `AR = width / height`, then:
- Landscape: `full` if AR ≥ 2.5 OR `{column=full}`, else `half`.
- Portrait: `full` if AR ≥ 1.2 OR `{column=full}`, else `half`. (The hero band's bullets cell is a pseudo-section that auto-fills via the staged-fill loop; medium-aspect figures are safe.)

**Figure-rich override (landscape — takes precedence over full/half).** If Step 2 selected **more than 3 figures**, use the **3-column layout** (`--layout 3col`) regardless of the Method figure's AR — its 3 wide equal columns (`1fr 1fr 1fr`) hold bigger, more numerous figures, matching the dominant author-GT layout. The Method figure card stays prominent in the middle column; the other figures distribute across columns. Via composition, `3col` now combines with **any** style and **any** header (the old "solid-only" limit is gone). The full/half choice above applies only when the poster carries ≤ 3 figures.

**Method-driven override (OPT-IN — only when the user explicitly asks for a "method-driven" poster).** Use `--layout methoddriven`. The **Method owns the wide middle block** (`.mid-wide`, the merged centre columns): a **large priority Method figure** on top, then the method split into **solid rounded subsection cards** (`.section.msub`, `data-section="method-1"…"method-N"`) that organize its sub-parts; the benchmark-style filler cards are dropped (side columns carry Problem/Motivation left, Key-Results/Headline/Takeaway right). This is opt-in — `--layout random` never selects it, and every other layout/style is unchanged. Rules:
- **Colour** = `multi-accent` by default: same hue as the theme `--accent`, different **depth per card** (`.msub.d1…d4`, theme-derived — tracks the 8-theme axis). Opt into distinct hues by adding class `mhue` to `<body>`.
- **The Method figure is the priority** — it fills the column WIDTH (so a wide banner clears the 90% figure-fill gate on width; NO exemption needed) and is bounded only by a generous, fill-loop-tunable height guard `--method-fig-max` (default `42cqh`). Raise/lower `--method-fig-max` to trade figure size against card room. The `<figcaption>` flows below.
- **The subsection cards adapt to the figure — the fill loop chooses the arrangement per-paper** (no fixed 2×2). `.msubs` is a span-composable grid; tag individual cards + order them to compose the layout:
  - `.msub.wide` → full-width long **row** (first card = top row, last card = bottom row)
  - `.msub.tall` → **tall** card spanning 2 rows (the two normal cards flow the other column)
  - add `cols-3` to `.msubs` → a **3-up** equal-column row
  - Examples: **tall+2** (one `.tall` + two normal); **row-top/bottom+2** (a leading/trailing `.wide` + two normal); **2×2** (four normal); **3-up** (`.cols-3` + three normal). Add/remove cards freely.
- **Fit the cards into the room the figure left.** Run the `pack` pre-check; measure every `.msub` with `slack` (each must read FULL 0.90–1.00). If cards are SPARSE/OVERFLOW or unbalanced, **re-pick the arrangement** (add/remove a `.wide`/`.tall`, change card count, switch to `.cols-3`) or nudge `--method-fig-max`, rather than only padding prose. In any multi-card row, **balance the cards' content** or the shorter one trails blank (polish Gate C / CARD-TRAILING).

**Axis 2 — style (`POSTER_STYLE`, default randomize):**

The first three are **full themes** (they retheme the header + page background); styles 4–11 are **block-only** card treatments that ride the solid theme (accent header, flat white logo chips) and just change the section-card look.

1. **`solid`** — the *classic* look: solid-filled accent titlebar (accent bg, white text), section `h2` = colored accent text with a thin underline. Sections are quiet warm cards with a top accent stripe.
2. **`framed`** — the *editorial* look: outlined rounded titlebar frame (white bg, accent border + accent title), section `h2` = solid accent-filled banner edge-to-edge; white section cards with a neutral thin frame.
3. **`simple`** — the *minimal white* look: white header + a single thin rule beneath it, near-black plain headings, frameless section cards separated only by a hairline top rule.
4. **`left-bar`** — thick accent rail down the card's left edge; plain accent heading.
5. **`elevated`** — floating white card with a soft deep shadow, rounded corners.
6. **`neo-brutal`** — hard black border + offset accent drop-shadow; uppercase headings.
7. **`tag`** — heading rendered as an inline accent pill.
8. **`underline`** — bold accent rule hugging the heading.
9. **`tinted`** — faint accent-tinted card background.
10. **`double-rule`** — centered heading between two thin accent lines.
11. **`legend-frame`** — heavy accent border with the centered heading sitting on the top edge, breaking the border (fieldset/legend look).

**Default style policy:** for landscape, **randomize across all 11**. Pass **`--style random`** so `compose_poster.py` picks one DETERMINISTICALLY from a hash of the output path — a reproducible spread across a wave. Do NOT ask the model to "pick a random style" (it defaults to solid in headless); use the `random` keyword. Override a specific one via `POSTER_STYLE=<name>`. The block-only styles (4–11) ride the solid header theme. **Portrait now composes too** (`--orientation portrait`, reads `assets/layouts_portrait/`): it takes the STYLE + COLOR + HEADER axes, so all 11 styles + 8 themes + **5 A0 title formats** (`pv1`–`pv5`, `assets/headers_portrait/`) ride portrait, all on the light-default header. The portrait title formats: **pv1** centered-classic, **pv2** title-left, **pv3** banner masthead (centered title + rule, venue/logos row below), **pv4** logo-forward (marks left, title right), **pv5** centered stack.

**Axis 5 — color/theme (`POSTER_THEME`, default `random`):** 8 academic accent bundles (`blue` · `teal` · `green` · `burgundy` · `purple` · `rust` · `slate` · `plum`) — the palette the paper's gallery recolor used. Each swaps `{--accent, --accent-soft}` (and the audio `--play-highlight-blue`); the result-register `--callout` (crimson) stays fixed across all themes. With the landscape **light-default header** (`--tb-bg: var(--accent-soft)`, dark title) each theme paints a pale-tint header + colored `<h2>` text/underlines on white cards — the light look, not a dark filled band. `--theme random` hash-samples one theme from the output path — **truly random and reproducible**, replacing the old "model hand-edits `:root`" step. Defined once in `references/apply_theme.py` (`THEMES`); shared by landscape and portrait (both via `compose_poster.py`).

**Axis 3 — header (`POSTER_HEADER`, default randomize):**

1. **`v1`** — venue (left) · title (center) · institution logos (right). Symmetric 3-zone band.
2. **`v2`** — mirror of v1: institution logos (left) · title (center) · venue (right).
3. **`v3`** — title centered full-width with a single equal-height logo strip below (conference mark + institutions).
4. **`v4`** — title (left) · venue + institution logos stacked (right). A common GT layout.
5. **`v5`** — *classic*: venue **text** badge (left) · title (center) · institution logos **+ Paper/Code QR tiles** (right). The one header that carries the QR in the titlebar. **Opt-in only** (`POSTER_HEADER=v5`) — when chosen, suppress the standalone `scan-to-read` section (set both `{{QR_*}}` empty) so the QR is not duplicated.

v1–v4 each render the conference **logo** when `assets/logos/_venue.png` exists (Step 6 `fetch_conf_logo.py`), else a text venue/year fallback in the same chip; v5 uses a text venue badge by design. All work for **2–6 institutions** (empty `LOGO_n` slots auto-hide). Logos are sized to **fill** their zone (single venue logo + a 2-row institution grid), and the logo chips **theme to the chosen style** via `--tb-chip-bg` / `--tb-chip-shadow`: solid → flat white chip (no shadow) on the accent band; framed → flat white chip on the white card; **simple → transparent chip (no frame), logos sit directly on the white header**. Default: pass **`--header random`** — `compose_poster.py` picks one DETERMINISTICALLY (output-path hash) from **all five (v1–v5)**; v5 fills its own titlebar QR via `{{HDR_QR_*}}` (see the QR contract). Override via `POSTER_HEADER={v1|v2|v3|v4|v5}`.

**Default font policy:** the poster body font defaults to **Arial** — a cross-platform-safe family pre-installed on Mac + Windows PowerPoint, so the exported `.pptx` needs **no font embedding** and round-trips cleanly. To override, edit the chosen template's `--font-latin` CSS variable (in the `:root` block) to any of the 8 PPT-safe families: `Calibri | Aptos | Cambria | Arial | "Times New Roman" | Verdana | Georgia | "Trebuchet MS"`. The optional `POSTER_FONT` env var, when set, carries the same choice — but the default lives in the templates, not in any external script. To use **Inter** (the bundled webfont — more editorial, but not pre-installed), flip `--font-latin` back to `Inter, …` *and* run the html2pptx Inter embed step so the `.pptx` ships the font; the 4 Inter `@font-face` blocks stay defined (inert) in every template for exactly this one-line override.

**Composition catalog (landscape):**

| Axis | Choices | Source files | Pick via |
|------|---------|--------------|----------|
| layout | `full` · `half` · `3col` | `assets/layouts/<layout>.html` | Method-figure AR / figure count (Axis 1) → `--layout` |
| style | `solid` · `framed` · `simple` · `left-bar` · `elevated` · `neo-brutal` · `tag` · `underline` · `tinted` · `double-rule` · `legend-frame` (11) | `assets/styles/<style>.css` | `POSTER_STYLE` (default randomize all 11) → `--style` |
| header | landscape `v1`·`v2`·`v3`·`v4`·`v5`(opt-in) / portrait `pv1`·`pv2`·`pv3`·`pv4`·`pv5` | `assets/headers/<v>.html` · `assets/headers_portrait/<pv>.html` | `POSTER_HEADER` (default random) → `--header` |
| scan | `single` · `dual` (group keywords — recommended) · `aside`(default) · `hero` · `contact` · `directory` · `banner` · `twin` · `chips` | `assets/scan/<variant>.html` | code QR resolves → `--scan dual`, else `--scan single` (Axis 4) → `--scan` |
| color/theme | `blue` · `teal` · `green` · `burgundy` · `purple` · `rust` · `slate` · `plum` (8 accents) | `references/apply_theme.py` (`THEMES`) | `POSTER_THEME` (default `random`, deterministic per output-path) → `--theme`. Applies to landscape (via compose) **and portrait** (explicit `apply_theme.py` call). |

`compose_poster.py` validates each choice and, on a bad name, aborts listing the available options. The old monolithic `poster_*_{solid,framed}.html` / `poster_portrait_*.html` templates have been **retired** — `compose_poster.py` (layout × style × header × scan × color, `--orientation portrait` for A0) is the only path; the source now lives entirely in `assets/{layouts,layouts_portrait,styles,headers,headers_portrait,scan}/`.

**Generate `poster.html` WITHOUT ever emitting its full contents through your output channel — hard requirement.** The template is ~100 KB (≈ 30–40k tokens); writing it inline with the `Write` tool overflows the per-turn output-token cap (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`, default **32000**) and **kills the run** — and the measured-fill loop would re-pay that cost every round. Generate it *indirectly* so the bulk template never passes through your output:

1. **Compose the template** (disk-to-disk, zero output tokens — do NOT `Write` it):
   ```bash
   # landscape — assemble layout × style × header into ONE self-contained poster.html
   python references/compose_poster.py \
     --layout <full|half|3col> --style <solid|framed|simple|left-bar|elevated|neo-brutal|tag|underline|tinted|double-rule|legend-frame> --header <v1|v2|v3|v4|v5> \
     --scan <single|dual> --theme <random|blue|teal|green|burgundy|purple|rust|slate|plum> \
     --out <outdir>/poster.html
   # portrait — composed too (STYLE + COLOR + HEADER axes; 5 A0 title formats pv1-pv5,
   # no scan section): reads assets/layouts_portrait/ + assets/headers_portrait/
   python references/compose_poster.py --orientation portrait \
     --layout <full|half> --style <solid|framed|simple|left-bar|elevated|neo-brutal|tag|underline|tinted|double-rule|legend-frame> \
     --header <random|pv1|pv2|pv3|pv4|pv5> \
     --theme <random|blue|teal|green|burgundy|purple|rust|slate|plum> \
     --out <outdir>/poster.html
   ```
   `compose_poster.py` resolves the STRUCTURAL hooks (`{{STYLE_CSS}}`, `{{HEADER}}`, and landscape-only `{{SCAN_SECTION}}`) AND the COLOR axis (rewrites the `:root` accent vars to the resolved theme); every CONTENT `{{...}}` placeholder survives for the next step. **`--scan`:** pass the GROUP keyword `dual` only when `make_qr.py` emitted TWO QR slots (two genuinely distinct URLs survived de-duplication), else `single` — compose deterministically picks a fitting variant within the group (so a 2-QR layout never lands on a 1-link paper, whose paper/project/code URLs collapse to one QR); `--scan random` or an explicit variant name also work. **QR-count guard (belt-and-suspenders):** if you pass a single-QR context (`single`, or an explicit `hero`/`contact`/`banner`) but `metadata.json` actually carries **two** QR files on disk, `compose_poster.py` auto-upgrades to the `dual` group so the second (project/code) QR is never silently dropped — still pass `dual` explicitly when a code QR resolved. **`--theme`:** default `random` picks one of 8 academic themes DETERMINISTICALLY from the output-path hash (reproducible spread across a wave) — do NOT hand-edit `:root` colors; override a specific one with `--theme <name>` or `POSTER_THEME`. **`--header`:** default `random` (landscape v1-v5 / portrait pv1-pv5). **`--math`:** the math-typesetting engine, default **`katex`** (thinner glyphs, posterskill-like) — the ONE place to switch is `MATH_ENGINE_DEFAULT` in `compose_poster.py`, or per-run `--math mathjax` / `POSTER_MATH=mathjax`. Both engines are bundled offline (`assets/katex/`, `assets/mathjax/`) and intercepted by the renderer + html2pptx (whose math pass is engine-agnostic), so flipping it needs no template/pptx change. Injected at the `{{MATH_HEAD}}` hook in every layout (landscape + portrait).
2. **Substitute placeholders with the `Edit` tool**, one `{{...}}` token (or one section block) at a time — each `Edit` emits only the small placeholder plus your paper-specific content, never the surrounding template. **Never reconstruct and `Write` the whole file.**

Equivalent Opus-style alternative when you have many substitutions: **copy the ready skeleton at `references/build_poster.py`** (it carries the real placeholder names, a depth-aware optional-section drop for the lean render, and a leftover-`{{...}}` check), fill its `SUBS` dict with this paper's content, and run it on the composed `poster.html` — the template is read from disk at runtime and never enters your output. Either path is fine; the invariant is identical: **the full HTML must never appear in a tool call's output** (this is the single most common cause of a smaller model aborting on a large poster).

**Read `references/template_substitution.md` now** — it carries the full placeholder map, the code-driven theme color (1-of-5, applied by compose / `apply_theme.py` — do NOT hand-edit `:root`), per-section accent palette, vertical-sizing convention (`grow` on the bottom-most section only), and the **lean initial render policy**: only `Necessary` of the six core sections; all three optional sections (Contribution, Dataset / Benchmark, Ablation Study) and every `Additional` paragraph are deliberately withheld at this stage.

**Decoupled-header + QR placeholder contract (NEW — edge cases).** The composed headers (v1–v4) replace the old titlebar, so the placeholder set changed:
- **Venue:** the header uses `{{VENUE_NAME}}` + `{{VENUE_YEAR}}` (text) and an optional `{{VENUE_LOGO}}`. Set `VENUE_LOGO` to `assets/logos/_venue.png` **only if that file exists**, else `""` — when empty, the header paints the VENUE/YEAR text in the conference chip (and preflight won't flag a dead image). The old `{{VENUE}}` / `{{VENUE_LINK}}` / `{{VENUE_TAG}}` header fields are **gone**; don't emit them.
- **Institution logos:** `{{LOGO_1}}`…`{{LOGO_6}}` (up to six). Fill each present institution's path; set every **unused** slot to `""` (empty/unfilled chips auto-hide). Works for 2–6 institutions.
- **QR placement depends ONLY on the header — the QR appears in exactly ONE place, and NEVER in the Title Section except for `v5`:**
  - **Headers `v1` / `v2` / `v3` / `v4` →** the Title Section carries NO QR (these headers have no QR slot at all). ALWAYS fill the standalone **Scan to Read** `.section` (`data-section="scan-to-read"`, right after Takeaway) via `{{QR_PAPER}}` / `{{QR_CODE}}`, and set the header's `{{HDR_QR_PAPER}}` / `{{HDR_QR_CODE}}` to `""`. Institution count is **irrelevant** — the old "≤ 2 institutions → header QR" rule is **RETIRED**; the QR never joins the logo row. The section's **internal layout is the `--scan` axis** (Step 3): pass `--scan dual` when a code QR resolves, else `--scan single`, so a two-QR layout never lands on a one-QR paper. Beyond `{{QR_PAPER}}`/`{{QR_CODE}}`, the picked variant may also expose the display-URL placeholders `{{URL_PAPER}}` / `{{URL_CODE}}` / `{{URL_PROJECT}}` (short URL text from `metadata.json`, e.g. `arxiv.org/abs/2106.09711`) and `{{CONTACT}}` — fill whatever exists and leave the rest `""`; every one auto-hides when empty. **Exception — `--layout 3col`:** the standalone Scan-to-Read section is **suppressed** in the 3col layout (its 1/3-width column is too wide for the section's small content and reads as empty), so a 3col poster intentionally carries **NO QR**. When you compose with `--layout 3col`, leave `{{QR_PAPER}}` / `{{QR_CODE}}` (and the other scan content placeholders) empty — they would render into a hidden section anyway.
  - **Header `v5`** (classic) is the ONLY header with a titlebar QR — with `v5`, ALWAYS fill `{{HDR_QR_PAPER}}` / `{{HDR_QR_CODE}}` and leave the section `{{QR_*}}` empty, so the QR shows once (in the v5 header) and the `scan-to-read` section auto-hides.
  - **Render-time guarantee (CSS — belt-and-suspenders, you do NOT rely on the build filling the right one):** every layout hides `.section[data-section="scan-to-read"]` whenever the titlebar carries a FILLED QR (`body:has(.titlebar img.qr-img[filled]) , body:has(.titlebar .qr-tile .chip.qr img[filled]) -> [data-section="scan-to-read"]{display:none}`). So even if BOTH the header QR and the section QR get filled, the standalone Scan-to-Read section is suppressed at render time and the QR can never appear twice.
  - Every QR placeholder auto-hides when empty or when its `assets/qr/*.png` is absent — set a path only if the file exists.
- **Logo autotrim:** `fetch_logos.py` / `fetch_conf_logo.py` now rasterize (SVG→PNG) and crop the transparent/near-white border so chips hug the mark — automatic, best-effort, no action needed here.

After substitution, apply the visual polish layer — **read `references/visual_polish.md`** for typography, color, the inline-emphasis vocabulary (`<strong>` / `.hi` / `.num`), stat grid, figure cap, callout and arch components, and print hygiene (the canvas locks per orientation: landscape 60×36in / `cqw` / `aspect-ratio: 5 / 3`; portrait 33.1×46.8in / `cqw` / `aspect-ratio: 33.1 / 46.8` — **never edit**).

**Read `references/content_patterns.md` now and BREAK UP THE WALL-OF-TEXT.** This is not optional reference material — it is a hard requirement for visual quality. The 16-widget catalog (callouts, key-stat, vs-compare, numbered-steps, timeline ×4, chips, definition, highlight-table, pullquote, bento, equation, banner) exists specifically because plain `<p>` + `<ul>` across every section makes the poster read as undifferentiated text. **Rules:**

- **Every section body MUST contain at least ONE pattern widget.** Plain `<p>` + `<ul>` alone is a failure mode (verified empirically — without this rule, posters ship with only 1 widget across 9 sections).
- **Across the full poster, use at least 5 DISTINCT pattern types.** A poster that uses `.p-callout-soft` 9 times still reads as monotonous. Vary the widget across sections so adjacent sections look visually different.
- **Cap at 2 widgets per section** (so a section doesn't stack 3 callouts + a key-stat + a chips strip = different kind of clutter).
- **Match widget to content shape:** pick from the catalog's "Shape of content it suits" column — `key-stat` for sections dominated by one number, `vs-compare` for Theirs/Ours sections, `numbered-steps` for pipelines, `chips` for taxonomy/dataset/baseline lists, etc.

The figure/logo/QR assets live under `<outdir>/assets/{figures,logos,qr}/` (placed there by paper2assets), and `poster.html` references them with `src="assets/figures/…"`, `src="assets/logos/…"`, `src="assets/qr/…"`. The `path`/`file` values in `figures.json`, `fetch_logos.py`, and `make_qr.py` manifests already carry the `assets/` prefix, so dropping them verbatim into `src` makes the relative paths resolve from the poster's own location without further action.

### Step 4 — Iterative fill to exactly fit the page

**First, the column-pack pre-check (one calculation, before any fill round).** Run `python3 scripts/check_poster.py pack <outdir>/poster.html`. It flags any column whose figure floors + minimum text already exceed the column height — a **negative-slack column is INFEASIBLE**, and the fill loop would oscillate there for ~20 rounds (the single biggest time-sink measured: one opus run burned ~15 min on one such column). Re-pack a flagged column *before* filling — move a text section or the figure to a looser/wider column, or (if TOTAL slack is negative) drop/shrink a figure or cut text — and enter the loop only when every column's slack ≥ 0. Details: `references/staged_fill.md` → "Column-pack pre-check".

The lean initial render usually leaves some sections under-filled. Grow content with an **iterative loop** until every section reads `FULL` (`fullRatio` 90–100% of the card height, padding included). Each pass: **first run `check_poster.py autofit <outdir>/poster.html`** — it deterministically closes the continuous-lever gaps a machine can size exactly (every `.grow`-card row-gap gap AND the scan-to-read QR height, using the `needPx` the report already computes, bounded by the column budget) and prints the residual sections that still need YOUR content/figure edits — then measure with `check_poster.py slack --with-polish`, read the per-section verdicts, pick the **one or two modification methods** best matched to the current defects, apply them, then re-measure to review and keep-or-rollback. There is no fixed order of methods — the measurement tells you what's wrong and you choose the remedy. Each off-band verdict suggests its remedy:

- `EMPTY` (<70%) → **add** Additional text or **add** the optional section for that column.
- `SPARSE` (70–90%) → **polish to enhance** the existing prose (pad with material from the spec's `Additional`) so the card fills.
- `SPILLAGE` (100–110%) → **polish to reduce** content (tighten prose so it fits in fewer lines).
- `OVERFLOW` (>110%) → **remove** Additional text or **remove** the optional section to claw back vertical space.

When two methods are independent (different columns) you may apply both in one pass; when they touch the same column, apply one at a time so a rollback decision stays unambiguous. When several methods could fill the same gap, prefer the highest-value content (real numbers, the Method figure, named contributions) over filler prose.

**Machine-checked exit gate.** The loop is done only when this command exits `0`:

```bash
python ~/.claude/skills/paper2poster/scripts/check_poster.py slack \
    <outdir>/poster.html --with-polish --strict
```

`--with-polish` runs the fill gate (`slack`) and the visual-polish gate (`FIG/NARROW` etc.) on **one** rendered page — a single browser launch instead of two — and under `--strict` **both** must pass, so this one command replaces the old separate `slack` + `polish` calls. Do not stop iterating while it exits non-zero. `--strict` is the same measurement you read each pass, but with a hard exit code — there is no "acceptable SPARSE" or "figure too tight to fix" escape. Keep applying the modification methods (and, for a stubborn figure, the column-width nudge / vertical-room methods in `references/staged_fill.md`) until the gate passes.

**Converge fast, and bound the loop (critical for smaller models).** The `slack` report gives each off-band section a precise **`needPx`** delta — e.g. `key-result  SPARSE  grow +50px [+18..+83]`. Edit *by that number* with a continuous CSS lever (`margin-bottom` / `.col` gap / figure `max-height`), don't guess with whole text lines and overshoot the 0.05-wide FULL band. Track recent measurements and switch levers the instant a section ping-pongs `SPARSE`↔`SPILLAGE`. And the loop is **bounded**: if both gates aren't green after **~12 rounds / ~20 min**, render the best-measured state, mark the stage **DEGRADED** with the residual off-band section ids, and move on — never grind indefinitely. This is **script-enforced**: `slack` counts *consecutive non-converged* measurements in `<poster_dir>/assets/meta/.fill_budget.json` and **exits 3 with a `CIRCUIT BREAKER` banner** once it passes `--max-iterations` (default **80**) — an on-disk cap that survives context compaction, so a lost round-count can't make you grind. A converged measurement clears the count, and a call that produced no geometry at all (nav timeout, MathJax settle failure) doesn't count against it. Treat **exit 3 as a hard stop** (render best state, mark DEGRADED). The exit gate stays strict; only the iteration count is capped. Full rules: the **"Convergence protocol"** at the top of `references/staged_fill.md`.

**When the `.grow` section is persistently `EMPTY` or `SPARSE`** even after exhausting its own Additional/optional content, don't keep stretching that one section — instead **refine the content of the other (non-grow) sections in the same column**: lift their `Additional` paragraphs into the rendered card, promote bullets from concise to expanded form, or fold in a paper-specific custom section. The `.grow` section then absorbs the residual slack naturally instead of inflating a single card with filler.

**When a column is at budget (`slackRatio` ≈ 0) but *lopsided*** — one card `SPARSE` while its siblings read `FULL`, so neither adding nor removing content works — use the **rebalance-adjacent-sections** method: relocate a *reserved, on-topic* line from a FULL sibling into the SPARSE card (a net-zero swap that shifts the column's height budget without changing its total). This only moves content that genuinely belongs to the destination section.

**Read `references/staged_fill.md` now** — it carries the `check_poster.py slack` command, the JSON report shape, the measure→select→apply→review loop, the flat catalog of modification methods, and the shave-back order.

Run preflight first (`check_poster.py preflight`) to catch LaTeX residue / raw `<` in math / missing images before measuring.

**Debug aid.** When the fill loop misbehaves — slackRatio says one thing, your eyes see another — write `check_poster.py slack --json-out <outdir>/assets/meta/poster_debug.json` output, open `poster.html` in a browser, and press `d`. Every column/section/figure gets outlined; badges show actual rendered height alongside the estimator's prediction and the delta.

### Step 5 — Synthesize narration audio for the Listen buttons

paper2assets produced the narration **script** (`<outdir>/assets/meta/narration.json`); paper2poster turns it into the mp3s the Listen buttons play — paper2poster is where TTS happens (paper2assets does NOT):

```bash
python ~/.claude/skills/paper2poster/scripts/generate_audio.py \
    <outdir>/assets/meta/narration.json --outdir <outdir>/assets/audio
```

- **Backend = free Edge TTS by default** — Microsoft Edge online voices via the `edge-tts` package: no API key, no config file, just network. Default voice `en-US-AndrewNeural`; `narration.json` carries `"provider": "edge"`. Override per run with `--provider azure` (needs `~/.azure/speech.json` + `AZURE_API_KEY`) or `--voice <name>`. See `references/audio_narration.md`.
- **Graceful skip:** if `edge-tts` isn't installed or the network is down, the script exits with a clear message and writes nothing — the poster's HTML/PDF still render, only the Listen buttons stay silent. Surface that message; don't fabricate audio.
- **Keep `PLAYLIST` in sync:** the template's `PLAYLIST` (and the per-section `data-section` ids) must match the clip ids in `<outdir>/assets/audio/`. The Listen buttons + Full Listen play `assets/audio/<id>.mp3` by id; an id with no file flashes the highlight and falls silent. So if you drop a section at render time (e.g. `dataset-benchmark`) or inject a custom one, keep `PLAYLIST` in sync with the audio files present. If `<outdir>/assets/audio/` is absent entirely, the buttons gracefully no-op and the poster still works visually.

### Step 5.9 — Pack the header logos to fill their zone (fit_logos.py)

After the fill loop converges, BEFORE rendering, pack the header's institution logos so they FILL their zone regardless of count or shape:

```bash
python references/fit_logos.py --poster <outdir>/poster.html
```

`fit_logos.py` opens the poster headless at true canvas scale, measures each logo zone (`.logo-grid` / `.logo-block`), greedily searches row partitions to MAXIMISE the single **uniform height** shared by EVERY institution logo (they enlarge *together* — never some big, some small); logos are reorderable. It also (a) wires the venue logo **into the conference chip** (`.chip.conf`) when `assets/logos/_venue.png` exists, so the `:has(img)` CSS fires and the venue year-text auto-hides — it never duplicates the mark; and (b) for `v1`–`v4` headers, pulls any QR **out of the titlebar** and re-homes it in the standalone **Scan-to-Read** section (re-creating that section after Takeaway if an older render dropped it) — only `v5` keeps a titlebar QR. It rewrites the zone into rows — baked into `poster.html` **disk-to-disk** (it never emits the full HTML through your output channel). Every logo renders at the SAME height, as large as the zone allows (one logo fills it; many balance into rows of equal-height marks). The widest mark and the short header band cap that uniform height, so there is **no fixed fill target** — the packer maximises the shared height. **`render_poster.py` (Step 6) now auto-runs `fit_logos.py` for you** right before it renders (it was routinely skipped when manual), so the exported PDF/PNG always has packed logos; you may still run it standalone to preview.

### Step 6 — Render the poster to PDF + PNG (FIRST — applies + bakes the expand)

```bash
python ~/.claude/skills/paper2poster/scripts/render_poster.py <outdir>/poster.html
```

Run this **before Step 7 (html2pptx)** so the expand is baked into `poster.html` *before* html2pptx reads it — the editable `poster.pptx` then matches the PDF/PNG instead of shipping the pre-expand layout. The script reads `@page { size: <W> <H> }` from the HTML, mirrors the bundled Inter webfonts into `<outdir>/assets/fonts/` (so the poster.html + its `assets/fonts/` stay self-contained for sharing across platforms), opens Chromium with print emulation, waits for MathJax to settle, applies the render-time expand, **bakes that expand back into `poster.html`**, then writes `<outdir>/poster.pdf` and `<outdir>/poster.png` (0.35× scale by default).

**Render-time "expand" (automatic, on by default).** Right before writing the PDF/PNG, `render_poster.py` runs one render-time fill pass: for every under-filled card it grows the row-gaps *between* the card's inner rows until the content reaches `POSTER_EXPAND_THRESHOLD` (default **0.98**). This makes a poster that converged at the 0.90 FULL gate read as visually full — no trailing whitespace — *without* re-grinding the fill loop to a tighter, ~2× slower gate. It is safe by construction, on two guardrails: (1) **figures are never resized** — they stay `flex:0 0 auto`, so a card's `<img>` keeps its exact pixel dimensions and aspect ratio even when the card it lives in is filled; (2) **a card is reverted if filling it would change its column/container height** (parent-height guard) — so a flex `.grow` card absorbs the fill *inside* its column (column bottom unchanged → fills the trailing column-bottom whitespace), while a grid/content card that would push the fixed-canvas layout taller is left alone. A card also stops at its **bottom-padding ceiling** (never eats padding → column bottoms stay aligned), so smaller cards finish a bit under 0.98 — that ceiling, `1 − padBot/cardHeight`, is their real "full". The expand result is then **persisted into `poster.html`** as a single `<style id="poster-expand-baked">` block (one `row-gap` rule per expanded section), so the editable HTML, its `D` debug overlay, the PDF/PNG, and the downstream html2pptx read all show the *same* expanded layout — not the pre-expand one. This is responsive-safe (the templates use a fixed internal layout scaled by an outer `transform: scale()`, so an inline px `row-gap` renders identically at any view size) and idempotent (a re-render replaces the block). It is written **only at this final render**, after Step 4's fill loop — so `check_poster.py slack/polish` during the loop still measure the natural top-aligned layout and the 0.90 FULL gate stays correct.

**Two tuning knobs (env vars) — the only layout dials you normally touch:**

| Env var | Default | Controls |
|---|---|---|
| `POSTER_FULL_THRESHOLD` | **0.90** | The staged-fill loop's FULL gate (Step 4). The layout is optimized until every section's natural top-aligned fill reaches this. Raise (e.g. `0.94`) for a tighter pack at ~2× loop time; the per-element `slack` report keeps either threshold from oscillating. |
| `POSTER_EXPAND_THRESHOLD` | **0.98** | The render-time expand target (this step). Each card fills toward this, capped by its bottom-padding ceiling and the column-height guard. Set `0` to disable the expand and ship the natural top-aligned layout. |

The pairing is deliberate: **0.90 converges the layout fast**, then **0.98 makes the final deliverable read full** at render time for free. Both are read from the environment, so a one-off run can override either without editing code.


Useful flags (defaults usually fine):
- `--thumb-scale 0.5` for a larger thumbnail, `0.2` for smaller.
- `--mathjax-timeout-ms 15000` if the poster has heavy LaTeX.

**This is a SOFT path.** A blocked CDN, MathJax fetch failure, or slow web font produces a stderr warning and a PDF that may show raw `$...$` instead of typeset math. Surface warnings verbatim, but **do not re-run** the script in response — fix upstream.

**Prerequisites:** `playwright` + Chromium. If the script exits with `ImportError`, run the install commands it prints and re-run.

After rendering, run the final dimension gate:

```bash
python ~/.claude/skills/paper2poster/scripts/check_poster.py verify-final \
    <outdir>/poster.pdf --from-html <outdir>/poster.html
```

A `FAIL` means the upstream HTML or `render_poster.py` invocation is wrong (e.g., `@page` was edited out). Surface the error and stop — re-running without fixing the HTML produces the same failure.

### Step 7 — Convert poster.html → poster.pptx (html2pptx — STANDARD final handoff)

Users almost always want the editable PowerPoint in the **same run** — do NOT treat this as optional or wait for a separate request. Once Step 6 has rendered and **baked the expand into** `poster.html`, hand it to the bundled **html2pptx sub-skill** (vendored inside this skill at `html2pptx/`; no longer a separate git submodule). From a Claude session, say:

> "Use the html2pptx skill to convert `<outdir>/poster.html` into `<outdir>/poster.pptx`. The default poster font is **Arial**, pre-installed on Mac + Windows PowerPoint, so **no font embedding is needed** — skip the embed step. ONLY if this poster was rendered with the optional **Inter** override, also run the html2pptx Inter embed (its own `scripts/font_embedder.py`) so the .pptx ships the font."

The skill extracts the DOM via Playwright, builds a native `.pptx` (editable text + native shapes + images, NOT a PNG-in-slide), renders a soffice sanity PNG, and runs a Claude-vision fidelity audit (on by default). **Run it with `--outdir <outdir>/assets/_pptx_build/`** so every html2pptx artifact (DOM json, sanity PNGs, the soffice render) stays under `assets/`, then promote the deck to the deliverable top level: `cp <outdir>/assets/_pptx_build/poster.pptx <outdir>/poster.pptx`. Final deliverable: `<outdir>/poster.pptx` (bundle root); build artifacts isolated under `<outdir>/assets/_pptx_build/`. Because it reads the **already-baked** `poster.html` from Step 6, the pptx carries the same expanded layout as the PDF/PNG.

**Ordering.** html2pptx runs **after** Step 6's render+bake so it reads the expanded `poster.html`. Its soffice sanity render writes into `<outdir>/assets/_pptx_build/`, so it never clobbers the bundle-root `poster.pdf` / `poster.png` (which is what made this safe to run last).

**Non-fatal.** If html2pptx genuinely cannot run (e.g. `soffice` or a Python dep missing), record a clear **WARNING** and **CONTINUE** to Step 7.5 — a pptx failure must never block the core `poster.{html,pdf,png}`. Report the warning explicitly; never drop the pptx silently.

### Step 7.5 — Final deliverable check (MANDATORY before declaring done)

```bash
python ~/.claude/skills/paper2poster/scripts/check_poster.py deliverables <outdir>
```

Deterministic gate, not advisory. It exits `0` only when **all four** core artifacts exist in `<outdir>` and meet minimum size thresholds:

- `paper_spec.md` (from paper2assets)
- `poster.html` (from Step 3–4)
- `poster.pdf` (from Step 6)
- `poster.png` (from Step 6)

If exit is non-zero, the command prints which files are missing and the exact command to produce them — run those, then re-run this check. Loop until exit `0`. Then confirm `poster.pptx` (Step 7) is also present; if html2pptx warned out, say so in the report instead of silently dropping it.

**FAILURE MODE this gate catches** — models routinely exit after Step 4's fill loop passes its `slack`/`polish` hard gates and skip the render steps entirely, rationalizing "all gates passed = task done." This is wrong: the fill loop only verifies the HTML; it does NOT produce or verify the PPTX/PDF/PNG. The same Claude model, on the same paper, will sometimes run Steps 6–7 and sometimes skip them — there is no warning sign you can rely on internally. **Do not declare done without running this check.**

### Step 8 — Report

Tell the user the absolute paths of all artifacts:

- `<outdir>/assets/meta/paper_spec.md` (from paper2assets)
- `<outdir>/poster.html`
- `<outdir>/poster.pptx` (editable PowerPoint, from Step 7 — note it explicitly if html2pptx warned out)
- `<outdir>/poster.pdf`
- `<outdir>/poster.png`
- `<outdir>/assets/audio/` (generated here by Step 5's `generate_audio.py` from `narration.json`; absent if edge-tts/network unavailable — Listen buttons then no-op)

**Do not dump file contents into the chat** — the spec and HTML are long, and the PPTX/PDF/PNG are binaries. For the PNG, inline-display if the chat surface supports image attachments. Mention that the user can open `poster.html` directly in a browser; the poster auto-fits the browser window (no scrolling needed). Press `s` for fullscreen, `a` to toggle Listen buttons, `d` to toggle a debug overlay.

The full chain is `paper2assets` → `paper2poster` (which now ends by producing the editable `.pptx` via the bundled html2pptx); each skill is still invokable on its own from a Claude session against the previous stage's `<outdir>/`.

## Tools

```
scripts/
├── check_poster.py      ← CLI: slack / preflight / polish / verify-final / deliverables
├── render_poster.py     ← CLI: print-emulated PDF + scaled PNG thumbnail (mirrors bundled fonts)
├── generate_audio.py    ← CLI: narration.json → assets/audio/<id>.mp3 (free Edge TTS default; --provider azure)
└── utils/               ← internal modules (canvas parser, Playwright + settle, etc.)
```

`check_poster.py slack` and `render_poster.py` both read `@page { size: W H }` from the input HTML — the templates set this — so the canvas size doesn't need to be passed on the command line.

Note: figure-cropping tools (`crop_figure.py`, `extract_pdf.py`, `fetch_logos.py`, `make_qr.py`) live in the **paper2assets** skill. If you need a one-off visual `box` re-crop on a figure paper2assets' deterministic chain couldn't handle, invoke them via `~/.claude/skills/paper2assets/scripts/` (see Step 2.5).

## Templates

All templates live in `assets/`. They share placeholder tokens, audio markup, keybinding scripts, design tokens; only the canvas size + column grid differ across orientation/layout. Step 3 routes between them by orientation trigger (`POSTER_ORIENTATION=portrait` → portrait; else landscape — DO NOT auto-detect orientation from figure AR) and then Method-figure shape (landscape: AR ≥ 2.5 OR `{column=full}` → `full`, else `half`; portrait: AR ≥ 1.2 OR `{column=full}` → `full`, else `half`).

**Landscape (60×36in, 5:3):**
- `poster_half_<style>.html` — **4-column grid** for half-width Method figures. Default landscape layout; Method is a half-width card alongside the other sections.
- `poster_full_<style>.html` — **4-column outer grid with the middle two columns merged into `.mid-wide`** for wide / full-width Method figures (AR ≥ 2.5 OR `{column=full}`). The `.mid-wide` block spans grid columns 2–3 and stacks Method (full mid-width, with the wide-figure floor enforcing ≥ 75% of available width) above a 2-col `.mid-sub` carrying Dataset + Key Result.

**Portrait (33.1×46.8in A0, 0.708):**
- `layouts_portrait/half.html` — **2-column grid** for tall / moderate-AR Method figures. Default portrait layout; LEFT col carries Problem / Motivation / Method (with figure); RIGHT col carries Dataset / Key Results / Ablation / Headline Numbers / Takeaway.
- `layouts_portrait/full.html` — **5-band magazine sandwich layout** for wide Method figures (AR ≥ 1.2 OR `{column=full}`). Reading order: titlebar → Band 1 (Problem | Motivation, 2-col equal) → Band 2 (.method-hero centerpiece, full-width: vertical-rotated SIDE-TITLE on left + bullets + wide-figure on right — magazine editorial style) → Band 3 (Key Results 1.5fr | Ablation 1fr | Headline Numbers 1fr, asymmetric 3-col data band) → Band 4 (Takeaway full-width punchline). The Method centerpiece sits in the visual middle, not at the top — this matches poster narrative convention (Problem/Motivation set up the WHY, then Method delivers the HOW, then Results/Numbers pay off, then Takeaway lands the WIN). The bottom 3-col band is intentionally unbalanced (1.5/1/1) so the data display reads as hierarchy, not parallelism. Takeaway gets the full canvas width — the eye lands on it as the closing word. The bullets cell inside the method-hero is wrapped in a **pseudo-section** (`<div class="section method-text" data-section="method-text">`) that's invisible to viewers but measured by `slack.py` — when the figure stretches the row taller than the bullets need, the staged-fill loop sees `method-text SPARSE` and the LLM expands bullets until the cell fills, unbinding the "narrow bullets cell next to tall figure → whitespace" trap. Optional sections (Contribution, Dataset/Benchmark) are NOT in the default layout — see the inline-commented recipe at the bottom of the template body to paste them in only when the paper genuinely needs them.

If you add a template: keep it venue-neutral, preserve the `{{...}}` placeholder vocabulary, preserve `data-section` attributes and `PLAYLIST` markup, and keep the canvas / `cqw` / `aspect-ratio` lock intact for that orientation.

Bundled in `assets/fonts/`: Inter Regular / SemiBold / Bold / ExtraBold in both `.woff2` (web) and `.ttf` (pptx-embedding) formats — the HTML templates' `@font-face` rules use the relative `fonts/Inter-*.woff2` path, and `render_poster.py` mirrors them into each `<outdir>/fonts/` so the deliverable is self-contained.

## Content guidelines

- **Section semantics:**
  - **Problem** — the concrete gap or failure mode the paper addresses.
  - **Motivation** — why this matters now; what's broken about prior approaches.
  - **Contribution** — the paper's explicit contributions (usually the bulleted "we contribute" list from the intro): the new artifact, dataset, algorithm, theorem, or insight.
  - **Method** — how the proposed approach works (the technical realization of the contribution).
  - **Key equation / Formulation** — the paper's core formula(s): the objective, loss, governing equation, or the one expression that defines the method. **Include at least one key equation on every poster that has meaningful math** (most ML / theory papers do), rendered with the `equation` widget (MathJax typesets `$…$` / `$$…$$`). The model chooses placement — fold it into **Method**, or give it its own compact **Formulation** card when the math is central. Pull the LaTeX from `paper_spec.md` (Method's `Key equation` subfield, produced by paper2assets) / `text.txt`; never fabricate. Skip only for genuinely formula-free papers (pure systems / empirical).
  - **Dataset / Benchmark** — the datasets, splits, scale, and any new benchmark the paper introduces. If the paper just consumes standard public benchmarks without elaboration, this section is optional. If the paper *introduces* a dataset or benchmark, treat it as a first-class contribution.
  - **Key Result** — the headline experimental finding and qualitative takeaway.
  - **Ablation Study** — which components/design choices matter, quantified. Top 1–3 rows (hard cap 3). If the paper has no ablation, state so and omit numbers.
  - **Headline Numbers** — the 1–4 standout quantitative results. The numbers themselves are the visual; no figure. **MUST render as the template's hero+supporting layout** — a `<div class="headline-hero">` containing `.hero-val` + `.hero-label` + `.hero-note` AND a `<div class="supporting">` row holding **at minimum 2** `.stat-mini` tiles (each with `.val` + `.lbl`). Bullets here OR a solo hero without supporting tiles = poster failure mode (caught by polish gates HEADLINE/HERO and HEADLINE/SUPPORTING).
  - **Takeaway** — the one-sentence "so what".
- **Tables vs figures:** tables (from `captions.json`) are not eligible as Method figures (only PNGs in `figures/`). Their numbers flow into `Headline Numbers` and `Key Result` necessary text.
- **Every kept figure carries a one-line caption.** A `<figure>` (Method, Motivation, or any secondary figure injected during fill) must always have a non-empty `<figcaption>` drawn from `captions.json` — a bare, unlabeled figure is a defect (`check_poster.py preflight` warns on empty captions). If a figure has no caption source, either write a short factual one-liner from the paper text or drop the figure; never ship it caption-less.
- **Prefer 3+ column tables.** A two-column `Method | Metric` table stretched to the section width reads sparse (wide empty gutter). When the paper reports more than one metric, give the table a column per metric so it holds more and fills its width. See `content_patterns.md` P12.
- **No fabrication.** Every number, claim, and figure caption must trace to `text.txt` (produced by paper2assets) or `figures.json`. When uncertain, prefer omission to invention.

## Edge cases

| Situation | Action |
|---|---|
| `<outdir>/` missing or missing required paper2assets outputs | Automatically invoke the `paper2assets` skill on the source PDF to produce/populate the `<outdir>/`, then continue. |
| `figures.json` is empty | Proceed; Method's figure is `none`. |
| Selected figure file missing on disk | Treat as `none`. |
| Method figure `none` | Use `<orientation>_half_<style>.html`, remove the Method `<figure>` block. |
| `POSTER_ORIENTATION=portrait` set (the ONLY trigger — do not auto-flip on figure AR) | Use `layouts_portrait/{full,half}.html` — A0 portrait canvas (33.1×46.8 in), 2-col body. |
| Method figure AR ≥ 2.5 in landscape (horizontally wide) | Use `poster_full_<style>.html` — wide pipeline / architecture figures get the merged-middle layout regardless of source-column attribute. |
| Method figure AR ≥ 1.2 in portrait | Use `layouts_portrait/full.html` — 5-band magazine sandwich. Reading order: Problem\|Motivation (top 2-col) → `.method-hero` centerpiece (full-width, vertical-rotated SIDE-TITLE on left + bullets + wide figure on right) → Key Results\|Ablation\|Headline (asymmetric 3-col 1.5/1/1) → Takeaway full-width punchline. Bullets cell is a pseudo-section that auto-fills the row height. |
| Method figure `{column=full}` in landscape | Use `poster_full_<style>.html` (merged-middle layout). |
| Method figure `{column=full}` in portrait | Use `layouts_portrait/full.html` (5-band magazine sandwich, Method centerpiece in middle with vertical-rotated SIDE-TITLE). |
| Method figure `{column=half}` and AR < 2.5 in landscape | Use `poster_half_<style>.html`. |
| Method figure AR < 1.2 in portrait (tall) | Use `layouts_portrait/half.html` — figure in a single col with text above, no hero band. |
| `<outdir>/assets/logos/` empty | Remove any `<img class="logo">` element whose institute didn't resolve — don't leave a literal `{{LOGO_N}}` token in `src`. |
| `<outdir>/assets/qr/code.png` missing | Remove the code QR `<img>` from the title bar (paper QR alone is fine). |
| Fewer than 4 headline numbers | Remove unused `.stat` divs (keep the ≥2 supporting tile floor). |
| No clean baseline-vs-ours comparison | Replace `<table class="results">` with a `<p>` carrying Key Result **Necessary**. |
| `poster.html` already exists | Overwrite without prompting. |
| Paper has no ablation study | One-line `Necessary` noting no ablations; empty `Additional`; remove the Ablation Study `.section` block and drop `"ablation-study"` from `PLAYLIST`. |
| Paper just uses standard public benchmarks (no new dataset) | Dataset / Benchmark is optional. Default = omit the `.section` block at lean-render time; the staged-fill loop may add a one-line "Standard benchmarks: …" card if a column has slack. Drop `"dataset-benchmark"` from `PLAYLIST` if the block is omitted. |
| Paper *introduces* a new dataset or benchmark | Render the Dataset / Benchmark section in the initial pass (treat as first-class, like Method); keep `"dataset-benchmark"` in `PLAYLIST`. |

## Key rules

- **Never invent numbers.** Pull from `text.txt` (paper2assets' output). Every stat, delta, and table cell must trace back to the spec.
- **Never emit the full `poster.html` through your output channel.** It's ~100 KB; a full-file `Write` (or any inline emission of the whole template) overflows the per-turn output-token cap (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`, default 32000) and aborts the run — the single most common way a smaller model fails on a large poster. Generate it indirectly (shell `cp` the template + surgical `Edit`s for placeholders, or a `build_poster.py` generator — see Step 3), and keep every fill-loop change a partial `Edit`, never a full rewrite.
- **Never re-`Read` the whole `poster.html` during the fill loop (INPUT-context twin of the rule above).** At ~100 KB, re-reading it each round floods a smaller model's context window → **auto-compaction** → lost fill state → the loop thrashes and never converges. Work from the `slack` report — it now prints an `EDIT TARGETS` block with the verbatim source of every off-band section, so lift your `Edit` `old_string` straight from there and never re-read the whole file. See `staged_fill.md` rule 6.
- **Lean render first, measured fill second.** Don't guess at fit during placeholder substitution. Render the core sections' `Necessary` only — Problem, Motivation, Method (**with the key equation**), Key Result, Headline Numbers, Takeaway — then let `check_poster.py slack` decide what to add. **Contribution is dropped by default** (keep only when the paper's headline novelty IS its contribution list). **Ablation Study, Dataset / Benchmark, and a filler Takeaway are deprioritized** — render only when they carry real first-class content (Dataset only when the paper *introduces* one; Ablation only with real ablation rows). The fill loop reaches for the **key equation, real numbers, the Method figure, and secondary/qualitative figures** before Ablation, Dataset, or padded prose — and before resurrecting Contribution.
- **Target ≥2 figures per poster.** Method alone leaves the right-side empirical story as a prose-and-numbers wall. Step 2 picks a secondary figure whenever the paper has one — the eye needs at least one *empirical* visual beyond the Method diagram. 1-figure posters are acceptable only when no remaining figure carries real signal (rare).
- **Include the key equation.** Every poster for a paper with meaningful math MUST show at least one key equation/formula (objective, loss, or governing expression) via the `equation` widget — integrated into Method or as a compact Formulation card. Rendering zero equations for an equation-driven paper is a quality failure (the single most common gap vs author GT). Pull the LaTeX from the spec / `text.txt`; never invent symbols.
- **No contentless section.** A section that would render with no real content is **omitted, not shown empty** — never ship a heading over a placeholder or a lone "N/A". This is the flip side of the FULL fill gate: deprioritized sections (Ablation, a filler Takeaway, Dataset when not introduced) are dropped rather than padded. Every kept section must carry genuine, paper-specific content.
- **Strict per-section fit gate.** Stop the staged-fill loop only when **every** section is `FULL` (fullRatio 0.90–1.00) **and every card figure fills 90–100% of its box on at least one axis** (`polish` reports zero `FIG/NARROW`). There is **no per-column SPARSE allowance** — a `SPARSE` card is not done, it is a card you have not finished filling.
- **Fill-loop pass ≠ task done.** Passing the slack/polish gates means the HTML is well-laid-out — it does NOT mean the deliverables are produced. Step 6 (PDF/PNG render) and Step 7 (html2pptx) are separate steps and are routinely skipped by models who mistake "fill loop converged" for "task done." The `check_poster.py deliverables` gate in Step 7.5 is non-negotiable: run it before reporting, loop until exit 0.
- **`.grow` cards are gated, not exempted.** A `.grow` card stretched by flexbox to absorb leftover column space can read as FULL in old tooling yet still show a visible band of trailing whitespace. Apply the same fullRatio gate to it — fill it (Additional / extra bullet) or shift content from its non-grow siblings instead of leaving the whitespace.
- **Multi-tile content uniformity (RECURRING DEFECT — read carefully).** Whenever a section emits a horizontal row of small stat / number tiles, every tile in the row MUST share the same visual shape — same line count for the big number, same line count for the label. Mismatched heights look broken: one tile's value sits high while its neighbor sits low, or the labels show a 2-line / 3-line zig-zag baseline. Applies broadly — not just `.headline-hero .supporting` `.stat-mini` tiles, but also `.p-stat-strip` cells, any ad-hoc number-card row in `Motivation` / `Method` / `Key Results`, and any future tile widget.
  - **The template now structurally backstops this**: `.headline-hero .supporting` uses `align-items: flex-start` (all `.val` numbers top-align so they always sit at the same height regardless of label height) and `.stat-mini .lbl` carries `min-height: 2.4em` (every label reserves 2 lines, so a 1-line and a 2-line label occupy identical vertical space). This means a label that wraps can no longer shove its value up out of line. **But the CSS only reserves the slot — you must still keep every label ≤ 2 lines** or a 3-line label overflows the reserved 2-line slot and the row breaks again. Do NOT rely on the CSS as an excuse to write uneven labels.
  - **Big numbers**: either ALL tiles fit on one line OR ALL tiles wrap to two. Never mix 1-line and 2-line within the same row. Fix by shortening the longest tile's value (e.g. `−84% FLOPs Δ` → `−84%`), or by rephrasing short tiles to wrap too — usually the first option.
  - **Labels**: keep all tiles in a row to the SAME line count, **≤ 2 lines each** (the reserved slot is exactly 2 lines). Target either all-1-line (short tokens: `pts`, `params`, `mAP`) or all-2-line, never a mix that reads as a zig-zag. If one label naturally goes to 3 lines while siblings stay at 2, shorten the long one (drop adjectives, prefer abbreviations, use unit shortcuts like `M` / `B`, `acc` for accuracy) — do NOT pad the shorter ones.
  - **Check before declaring done.** Visually scan every multi-tile row in the rendered poster. If values are at different y-positions or labels show a stair-step baseline, the row fails uniformity — fix the content before signing off.
- **Do not edit the canvas lock.** The 60×36in / `cqw` / `aspect-ratio: 5 / 3` rules in both templates are what makes the browser preview, print PDF, and PNG thumbnail look like the same layout at different magnifications.
- **paper2assets owns the figure-cleanup pipeline (top-check → decaption → autotrim).** Don't re-run the deterministic chain here — it's already done. Step 2.5's visual `box` cut is for residual asymmetric noise only.
