# Staged-fill loop reference

How to grow content from a lean initial render into a poster that exactly fills the 60×36in canvas. Read this when you reach **Step 8 — Stage-by-stage fill** in `SKILL.md`.

The goal is concrete: **every section's card must be filled to between roughly 80% and 100% of the card (padding included), without any section overflowing.** The initial render is deliberately lean (only `Necessary` from the six core sections; no `Additional`; no Contribution / Ablation Study).

The fill is an **iterative loop, not a fixed sequence of stages**. Each iteration: measure, read the per-section verdicts, then pick the **one or two modification methods** best matched to the current defects, apply them, and re-measure to review. There is no mandatory order — the methods below form a flat catalog, and which one helps most depends entirely on what the current measurement says. The only fixed rule is the exit condition: stop when every section is `FULL` and there are zero `FIG/NARROW` warnings (or, if a section overshoots, shave it back first). When several methods could apply, prefer the highest-value content (real numbers, the Method figure, named contributions) over filler prose.

## The measurement command

The loop is driven by `scripts/check_poster.py slack`, which print-emulates the HTML in headless Chromium and measures **per-section** geometry from real browser layout: each section's card box, padding box, and the union bbox of its content (excluding the Listen button). From these it computes a per-section `fullRatio = (content_bottom - card_top) / card_h` (denominator includes the card's own padding — what the eye sees) and assigns one of five verdicts:

| Verdict | fullRatio | Meaning | What to do |
|---|---|---|---|
| `OVERFLOW` | > 1.10 | content visibly past the card border | **remove** Additional text or **remove** the optional section |
| `SPILLAGE` | 1.00–1.10 | content just past the card border | **polish** to reduce content (tighten prose so it fits the card) |
| `FULL`     | 0.90–1.00 | fills the card; ideal | leave alone |
| `SPARSE`   | 0.70–0.90 | visible underfill | **polish** to enhance content (pad prose to fill the card) |
| `EMPTY`    | < 0.70 | clearly underfilled | **add** Additional text or **add** the optional section |

`fillRatio = content_h / padding_box_h` is still emitted for inspection but no longer drives the verdict — `fullRatio` is what the eye reads ("does the content reach the bottom of the card?"). Sections with `flex: 1 1 auto` (the bottom-most `.grow` card in each column) are classified by the same thresholds as every other section; a grown card that ends up `SPARSE` / `EMPTY` is still under-filled to the eye, not "deliberate breathing room".

**Scan-to-Read suppression (a DELETE verdict, orthogonal to the five fill bands).** Besides the fill bands, the slack report carries one extra signal aimed only at the bottom **Scan-to-Read** QR section: when that section renders **wide and flat** — its OWN width ≥ `POSTER_SCAN_SUPPRESS_WH` (default **3.8**) times its OWN height — it holds a lone small QR marooned in horizontal empty space, a visible defect (poster #8: a grid column blown out to ~2× width left the QR filling ~15% of a 2542px-wide band). The report flags it in three places: `verdict.suppressSections: ["scan-to-read"]`, the section entry's `"suppress": true` + `"aspectWH"`, and a loud `^ SUPPRESS:` line under that section. **When you see it, DELETE the whole `scan-to-read` section block** (lift its verbatim source from the `EDIT TARGETS` block) and keep filling — the column's other sections immediately read `SPARSE`, and you grow them into the freed space with **real content** (a bigger figure, more bullets, a promoted `Additional`). This flag is `--strict`-blocking, so it is resolved *inside* the loop where the freed column gets real content — not left to `render_poster.py`'s render-time backstop, which can only hide the section into redistributed whitespace. A scan section measuring **below** the threshold is fine — leave it. After the delete, the poster carries no QR (the same trade the `3col` layout already makes), which is the right call when the only alternative is a QR adrift in empty space.

**`.grow` cards are gated, not exempted.** Flexbox will happily stretch a `.grow` card to absorb leftover column space, which can leave it with a fat band of trailing whitespace below the last line even though its column has zero `slackRatio`. This reads as an "unfinished" card to a passerby. When a `.grow` card falls below `FULL` (fullRatio < 0.90), treat it the same as any other under-filled section:

1. First try filling the `.grow` card itself — promote a paragraph from its **Additional** in the spec, add a bullet, or upgrade prose to a callout/stat-grid.
2. If the card has nothing more to say, grow a sibling instead — promote `Additional` into the non-grow section above it so less vertical space spills down into the `.grow` card.
3. Only if both fail, consider a column-width nudge (the *column-width* method below) to shrink the column's vertical budget.

Never accept a `.grow` card stuck in `SPARSE`/`EMPTY` as "done". The `polish` gate's `CARD/TRAILING` warning catches exactly this failure mode after the fact; the staged-fill loop should prevent it.

The gate is **per-section**: the loop is done when every section is `FULL`. No more guessing which section in a sparse column to grow — the report names them.

**The loop has a second mandatory exit condition: zero `FIG/NARROW` warnings.** Every card figure MUST fill **90–100%** of its section on at least one axis (width OR height) — a figure that paints as a small stamp in its card is a defect, not a soft nit. So the loop is only done when **both** hold: (a) `check_poster.py slack` shows every section `FULL`, and (b) `check_poster.py polish` reports **0** `FIG/NARROW` warnings. A figure that's still narrow after the columns are all `FULL` is usually *height-bound* — the fit script hands it only the vertical room left after its section's text, so a wide banner caps its width below 90%. Fix it with the **Method figure max-height** method first (raise the figure's `max-height` cap to enlarge the figure box), and when the columns have **0 slack** and the cap can't grow, with the **targeted prose polish** method (tighten the prose in that figure's own section so its bullets wrap shorter, freeing vertical room the figure box grows into). Re-run `check_poster.py slack --with-polish` after every such edit; keep it only if figure warnings drop without pushing any section into overflow/spillage, else roll back. The only exemption is a deliberate image-left/text-right card marked `data-fig-layout="beside-text"`.

```bash
python ~/.claude/skills/paper2poster/scripts/check_poster.py slack \
    <outdir>/poster.html --with-polish
```

`--with-polish` folds the visual-polish pass (`FIG/NARROW` and the other Gate A–G warnings) into this same measurement on **one** rendered page, so each round is a single browser launch instead of running `slack` then `polish` separately. Drop the flag if you want the bare fill report.

This replaces the older Node-based `measure_layout.js` estimator. The Python+Chromium version reads the actual rendered layout (including MathJax, image aspect-driven sizing, and the visual-polish components), so what the fill loop sees matches what the print PDF will produce. The script temporarily neutralizes the templates' `flex-grow` / `space-between` stretching during measurement so each section reports its natural content height — otherwise grown sections would always report 100% full and underfill of *other* sections would mask itself.

Prerequisite (same as `render_poster.py`): `playwright` + Chromium. If the first run prints `ImportError`, run the install commands it shows and re-run.

Report shape:

```json
{
  "page": { "width": 5760, "height": 3456, "contentHeight": 2704 },
  "columns": [
    {
      "index": 0, "width": 1147, "used": 2704, "slack": 0, "slackRatio": 0.0,
      "sections": [
        { "id": "problem",
          "card":         { "x": 73.3, "y": 679.2, "w": 1147.4, "h": 508.7 },
          "padding_box":  { "x": 116.0, "y": 721.8, "w": 1062.0, "h": 423.4 },
          "content_bbox": { "x": 121.0, "y": 722.8, "w": 1056.0, "h": 486.2 },
          "fillRatio":    1.149,
          "verdict":      "OVERFLOW",
          "isGrow":       false,
          "used":         509
        }, ...
      ]
    }
  ],
  "verdict": {
    "overflowSections": ["problem", "motivation", "contribution"],
    "sparseSections":    [],
    "emptySections":    [],
    "sparseColumns":    [],
    "sparseSections":   []
  }
}
```

Read `verdict.overflowSections` / `sparseSections` / `emptySections` for the action list. `columns[].slackRatio` is still emitted for continuity but is no longer the primary gate — a column can read slackRatio = 0% yet still have three overflowing sections (flex compression hides per-section overflow inside a fully-packed column), which is exactly the case the per-section gate catches.

## Preflight (cheap static lint first)

Before opening a browser, run the bundled HTML linter to catch LaTeX residue, raw `<` inside math, missing local images, and a missing root marker:

```bash
python ~/.claude/skills/paper2poster/scripts/check_poster.py preflight <outdir>/poster.html
```

The script tolerates paper2poster's class-based markup (`class="poster"`, `.col`, `.section`) — no `data-measure-role` attributes needed. Fix every reported `FAIL` (hard errors that would break the PDF) before going further. `WARN`s are informational. If preflight passes, continue.

## The fill loop

Each iteration of the loop is the same four steps:

1. **Measure** — first run `check_poster.py autofit <outdir>/poster.html` (deterministically closes the continuous-lever gaps a machine can size exactly: every `.grow`-card row-gap gap AND the scan-to-read QR height, each within the column budget, and prints what still needs YOU), then run `check_poster.py slack --with-polish` and read `verdict.overflowSections` / `sparseSections` / `emptySections` / `suppressSections`, plus the folded-in polish `FIG/NARROW` warnings (one browser launch covers both). Don't hand-type `margin`/`row-gap`/`.qr-img height` px the report already sized — `autofit` did it; you edit only the residual content/figure sections it lists.
2. **Select** — from the catalog of modification methods below, pick the **one or two** best matched to the current defects. There is no fixed order; the measurement tells you what's wrong, and you choose the method(s) that address it. When two methods are independent (e.g. tune the Method figure cap in the middle column *and* append an `Additional` paragraph in the left column) you may apply both in one iteration; when they touch the same column, apply one at a time so the rollback decision stays unambiguous.
3. **Apply** — make the edit(s) with the `Edit` tool (surgical, partial). **Never re-`Write` the whole `poster.html`** — it's ~100 KB and a full-file write blows the per-turn output-token cap (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`, default 32000), aborting the loop.
4. **Review** — re-measure. Keep the edit if it moved sections toward `FULL` without creating a new `OVERFLOW`; otherwise **rollback** that edit and try a different method next iteration.

**Stop the loop as soon as `verdict.overflowSections`, `spillageSections`, `sparseSections`, `emptySections`, and `suppressSections` are all empty AND `polish` reports zero `FIG/NARROW` warnings** — i.e., every section is `FULL`, every figure fills its box, and no scan section is flagged for deletion. `spillageSections` (fullRatio 1.00–1.10) is mild overflow — content already past the card border — so it is *not* an acceptable finishing state any more than `overflowSections` is; a passerby sees text colliding with the next card's border either way. If at any point a section appears in `overflowSections` **or `spillageSections`**, prefer to fix it (see "Shave back when overflowing") in that same iteration before growing anything else.

**Prefer the highest-value content.** When several methods could fill the same gap, reach for real numbers (Key Result table rows, stat tiles), the Method figure, and named contributions before generic `Additional` prose. The page should fill with the content a passerby most wants to read.

### Column-pack pre-check — run ONCE before the loop (kills the figure-vs-text deadlock up front)

The instant the initial poster renders — **before the first fill round** — run:

```
python3 scripts/check_poster.py pack <outdir>/poster.html
```

It computes, per outer column, `slack = columnHeight − Σ(figure floor heights) − Σ(text minimum heights)`, where a figure's *floor* is the smallest it can be while still clearing the 90% gate (`0.90 × sectionWidth / AR`). A column with **negative slack is INFEASIBLE**: its rigid figure floors plus minimum text already exceed the column height, so **no fill can make every section FULL** — the loop will *oscillate there for dozens of rounds* (a real opus run burned ~15 min on one such column, the single biggest time-sink measured). `pack` exits 3 and names the column.

When `pack` flags an INFEASIBLE column, **re-pack it now, not via 20 fill rounds**:
- **Move a text section to a looser column** (one with positive slack).
- **Move/swap the figure to a wider column or a half-layout** — a wider column means a *smaller* floor (floor = 0.90 × width / AR).
- If **TOTAL slack is negative** (content exceeds the whole canvas), re-packing alone can't fit it — **drop an optional section or cut a text block** (figures are immovable: never shrink one below its `FIG_MIN_RATIO` fill floor).

Enter the staged-fill loop only once every column's `pack` slack is ≥ 0. This turns the worst case (a figure-vs-text packing deadlock) from ~20 measured rounds into one pre-loop calculation.

**Then, during the loop: follow the per-column `budget` on every `slack` report.** Each `slack` call now prints `budget=±Npx` per column — the same capacity headroom, recomputed live every round (this is the *incremental* version of the pre-check: instead of betting on one up-front plan, the budget recalibrates each pass). Use it to steer **where** content goes so no column is ever pushed into the tight-oscillation zone:
- **`(room to add)`** — grow content HERE first (optional sections, `Additional` paragraphs).
- **`TIGHT`** — **stop adding to this column.** It's near capacity; aim its sections at the FULL band's *lower* edge (~0.94, comfortably full) rather than 0.99 (crammed), and route any further content to a looser column.
- **`OVER-PACKED`** (negative budget) — move a section out or cut content; it cannot be made FULL without spilling.

The point: fill toward a **comfortable** page (every section ~0.94–0.96) instead of cramming every column to 0.99 and oscillating. A poster that is comfortably full reads better than one crammed to the pixel — and it converges in a fraction of the rounds because no column sits on the knife-edge.

### Convergence protocol (READ FIRST — this is what stops the loop from oscillating)

Weaker / smaller models stall here, and the reason is structural: the FULL band is only **0.05 wide (`fullRatio` ∈ [0.94, 0.99))**, but a discrete text edit ("add/remove a line") moves ~50px ≈ 0.05 — one edit jumps the *whole* band, so the section ping-pongs `SPARSE`↔`SPILLAGE` forever. Six rules keep the loop converging in a handful of rounds instead of dozens:

**1. Edit by the number, at the located element — use `needPx` + the per-element slack.** Every off-band section in the `slack` report carries a signed **`needPx`** (and a safe **`needPxRange`**) — e.g. `problem  SPARSE  grow +51px [+21..+81]`, `ablation  OVERFLOW  shrink −243px`. That is the exact px the section's content bottom must move to land centered in the band: `+N` = grow (push the bottom DOWN ~N px), `−N` = shrink (pull UP ~N px). Choose an edit whose expected effect is ≈ `needPx` (or anywhere inside `needPxRange`). **Do not** apply an edit whose effect is several × `needPx` — that is exactly the overshoot that causes the ping-pong.

   The report also **localizes the slack to one element**: under each under-filled section it prints **`slack Npx below [k] <tag> "…"`** — the growable element the whitespace actually sits below, and whether it is the figure or a text element. *This ends the figure-vs-text guessing.* A section with a figure is no longer one opaque blob: the report tells you the gap is below the `<p>`/`<ul>`/callout (a **text** lever → grow that element: add a line, promote `Additional`, upgrade prose to a callout/stat-grid) **or** below the `<figure>` (a **figure** lever → raise its `max-height` so the image grows into the gap). Pull only the matching lever on the named element — never grow text to fix a small figure, or shrink a figure to fix short text. (Headings are excluded from the localization — you never "grow the title".)

**2. Near the band, switch from a discrete text line to a continuous lever.** When `|needPx|` is small (≲ one text line, ~50px), a text edit *will* overshoot. Use a **continuous CSS lever sized to `needPx`** instead:
- **grow `+N`px:** add `margin-bottom` / `padding-bottom: N px` to the section's bottom-most element, open the gap between the text block and its figure (`gap` / `margin` on the `<figure>`), or raise the Method figure `max-height` cap.
- **shrink `−N`px:** reduce the bottom element's `margin-bottom`/`padding`, shrink the column's `.col { gap }` a few pt, or tighten one prose line.
- **painted SPILLAGE (`needPx` present but `needPxRange` is null):** a callout/table/tile is poking past the card padding — pull it back inside by that many px (trim its bottom padding/margin), or better, **end the section with a plain `<p>`** (its own bottom margin sits the content cleanly inside the card) rather than a painted callout/table.

**3. Anti-oscillation — never repeat a tried edit on the same section.** Remember the last ~3 measurements per section. If a section **crosses the band** after an edit (`SPARSE`→`SPILLAGE` or back), or **2 edits in a row** don't move its `fullRatio` monotonically toward the band, you are oscillating: **stop using that lever**, halve the step (or switch to a continuous lever per rule 2), and never re-apply an edit you already tried on that section. Add-then-remove the same line is the classic stall — recognize it and change levers.

**4. Break a structural deadlock early — never text-balance a coupled pair.** Two patterns waste dozens of rounds because *no text edit can satisfy both sides*; spot them by the 2nd repeat and switch to a structural fix at once:
- **Shared-box mirror (`.mid-sub`).** The two sections stacked in a `.mid-wide` block's `.mid-sub` share a *fixed* vertical budget — grow one and the other shrinks. If one is intrinsically content-light (a standard-benchmark Dataset card, a one-line Contribution) and its sibling is content-heavy (Key Results), they flip `A SPARSE ⟺ B SPILLAGE` forever, and the agent burns ~20 rounds discovering it. The instant that mirror repeats, **stop balancing with text**: replace the light card with a **figure** (a figure auto-fills its box and permanently ends the mirror — e.g. swap a thin standard-Dataset card for the secondary-results figure), or promote a fuller section into the slot, or move content from the heavy sibling into Method. Better still, **don't create the mirror** — see the `.mid-sub` note in `template_substitution.md`.
- **Discrete element coarser than the band.** When a section's only size lever is a discrete element (one table row, one bullet, one clause) whose add/remove moves `fullRatio` by *more than* the 0.05 band (~50px), that element can never land the section in-band — it overshoots every time. Freeze the discrete content and size that section with **continuous levers only** (`min-height` on the card, `margin-bottom`, `font-size`, `.col { gap }`). `min-height` is the canonical decoupler — it pins a card's height regardless of a poking sibling (e.g. a tall `headline-numbers` hero that pushes past its box).
- **Column-stack coupling (rigid `headline-numbers` ⟷ `.grow` absorber).** A landscape column often stacks the *rigid* `headline-numbers` card — its big `.hero-val` is a fixed-pt block (160pt) that pokes past the card padding when the column is tight — above `ablation` and a `.grow` `takeaway`. Micro-shrinking the hero pt (160→140→120…) is whack-a-mole: every change re-disturbs the column's other cards, so you ping-pong for dozens of rounds. Instead, **lock the rigid card ONCE**: give `headline-numbers` a `min-height` ≈ its natural hero height (so the grid can't crush it), drop the hero to a single fitting pt, then **never touch it again** — let the column's `.grow` section absorb all remaining slack. If it still paints past the card, end it with a plain `<p>` (a real caption/footnote) so a text bottom-margin seats the content inside.
- **Column-width nudges are GLOBAL — set them once, never inside the fill loop.** Resizing one outer-grid column re-flows *every* column, so a "shift width col3→col2" fix throws col2 off and you ping-pong col2⟷col3 forever (this is a distinct oscillation source from the per-section levers). Pick the column widths at render time; inside the loop, balance a section ONLY with *in-column* continuous levers (margin / `min-height` / font-size / content), never by resizing the outer columns.

**5. Hard circuit breaker — the loop is bounded, and the script enforces it.** Aim to converge within **~12 measure→edit rounds OR ~20 minutes**. That is the *soft target*; the *hard backstop* is built into `check_poster.py slack` itself. Every `slack` call that measures the poster and finds it **not yet converged** increments a persistent counter in `<poster_dir>/assets/meta/.fill_budget.json` and, once it passes `--max-iterations` (**default 80**), `slack` prints a `CIRCUIT BREAKER` banner and **exits 3** instead of its normal verdict. The counter lives on disk, so it **survives context compaction** — you cannot reset it by losing your in-prompt round count (the exact failure mode that lets a loop grind to 100 measurements). It counts **consecutive** non-converged rounds: a measurement where every section is FULL and every figure OK clears it (and, under `--with-polish --strict`, only if the polish gates passed too — a poster that is FULL everywhere but keeps failing e.g. `ORPHAN` is still a loop the breaker must bound), so a later touch-up on an already-converged poster starts from a clean budget rather than inheriting the debt of the rounds that got it there. A call that never produced geometry (nav timeout, MathJax settle failure, no columns found) is an environment problem and does not count against you, and a counter left idle for over 15 minutes is treated as a previous session and dropped. When you see **exit 3 / the breaker banner**, stop immediately: **render the best-measured state** (fewest off-band sections / smallest total `|needPx|`), record the stage as **DEGRADED** with the residual off-band section ids in the stage note, and **move on**. A poster that is 95% there in 12 rounds beats one that burns 90 minutes chasing the last 1px. The exit gate itself stays strict (`--strict` is unchanged) — this breaker bounds only the *iteration count*, never the quality target. (For a genuine fresh re-render of the same `poster_dir`, pass `--reset-budget` once to zero the counter; set `--max-iterations 0` only to disable the backstop deliberately.)

**6. Context discipline — do NOT re-`Read` the whole `poster.html` each round.** It's ~100 KB (~25–30k tokens); pulling it into context every round floods a smaller model's window and triggers **auto-compaction**, which wipes your precise per-section fill state — so the loop forgets what it already tried and **thrashes without ever converging** (measured: a 200 K-window model auto-compacted twice and never converged on papers a large-window model finished compaction-free). Each round needs only the **`slack` report**, which is now self-sufficient: besides each section's verdict + `needPx`, it prints an **`EDIT TARGETS`** block carrying the **verbatim source of every off-band section**. Lift your `Edit` `old_string` straight from that block — a short, unique sub-snippet (a bullet's words, a stat value, a `margin-bottom`) — and grow/shrink the section by `needPx` without ever opening `poster.html`. If you somehow need markup the report didn't surface, `Read` a **narrow `offset`/`limit` slice** or `grep` for it — never the whole file. Beyond the one initial orientation read, re-reading the full `poster.html` is the single biggest avoidable context cost in this loop; on a small-context model it is the difference between converging and thrashing.

### Gate mechanics you must NOT rediscover (each one below cost a real opus run rounds it shouldn't have)

These are *how* `slack`/`polish` actually measure. They are not visible in the templates, so an agent that hasn't read them re-derives each by trial-and-error — one real run burned ~7 rounds reverse-engineering the painted gate and ~17 on a narrow-column seesaw. Read them once and act on them directly.

**Verdict bands (exact, so you don't read the script).** `fullRatio = content_bottom / card_h`. **EMPTY** < 0.70 · **SPARSE** [0.70, 0.94) · **FULL** [0.94, 0.99) · **SPILLAGE** [0.99, 1.10) · **OVERFLOW** ≥ 1.10. The FULL band is only 0.05 wide (rule 1).

**Painted-bottom gate — the #1 time-sink.** A section whose **bottom-most *painted* element** — a `.callout`/`.callout-soft` bar, the `.headline-hero` block, a `.stat-strip` / `stat-mini` / `.stat` grid, `p-vs` / `p-chips` / `p-table` widgets, a `.conclusion` border, a callout pill — reaches into the card's ~32pt bottom-padding zone is **downgraded FULL→SPILLAGE regardless of `fullRatio`** (tolerance is **1px**; any poke trips it). In the report this is the SPILLAGE with **`needPxRange: null`** (also surfaced as `needPx` from the painted-overshoot). Do **not** chase it with `padding-bottom` micro-tweaks — shrinking padding shrinks the *card*, not the no-paint zone, and usually makes it worse. The reliable fix every time: **end the section with a plain `<p>`** (a real caption / footnote / sentence) so a text bottom-margin seats the painted widget back inside the card. This is *why* rule 2 says "end with a plain `<p>`."

**Figure-bearing column, two regimes (post hard-floor).** `fit()` pins every figure between a HARD floor (>= `FIG_MIN_RATIO` fill, never smaller) and its `max-height` cap. **Underfill** (whitespace below a figure sitting under its cap): raise the figure's `max-height` cap so the image grows into the gap — adding/trimming text barely moves the column here, so pull the cap lever. **Overflow** (column content past the bottom): the figure will NOT shrink below its floor to absorb it, so the ONLY fix is to **trim text or drop an optional section** — never shrink the figure. (Pre-floor this column was a pure height-invariant and prose edits were a no-op; with the hard floor, prose IS the overflow lever.)

**Image-bound rigid figure deadlocks a narrow column.** A thin figure sized by its *intrinsic image height* (e.g. a ~190px motivation teaser) can neither shrink (to free room for a sibling) nor grow (to absorb slack), so a narrow column holding `figure + text section` seesaws forever. Fix: **convert that figure to text widgets** (drop it — ≥2 figures elsewhere already satisfy the figure target), or swap it for content that flexes.

**Narrow-column amplification.** In a narrow outer (1fr) column, one text line ≈ one *or more* band-widths (a clause wraps to 2–3 lines), so discrete text edits there ALWAYS overshoot — rule 4's "discrete coarser than the band" at its worst. In a narrow column, prefer continuous levers (figure cap / `padding` / `min-height`) and accept that content there moves in ~1-line quanta.

**Widow fixes must be length-neutral, and run them LAST.** `polish` flags a widow when a paragraph's last line is < ~20% of the column width. Rewording/reordering a bullet to clear a widow **changes its line count → disturbs already-FULL slack** (one run ping-ponged slack↔polish for 5 rounds doing exactly this). So: get `slack --strict` green FIRST, then fix widows by **reflowing the tail to the SAME length** (reorder words; don't add or remove lines). A widow fix that changes length is a slack regression.

### Modification methods (a flat catalog — pick by fit, not by order)

The first iteration is usually just a measurement: if every section already reads `FULL` and no figure is narrow, you're done — skip to the audio step. This is rare for full-length papers but common for short workshop papers with terse `Necessary` text. Otherwise, select from the methods below.

Every method follows the same **propose → re-measure → keep-or-rollback** discipline described in the four steps above. Never apply an edit and continue without re-measuring; the whole point of the per-section gate is that the browser tells you whether the edit actually helped. If an edit *creates* an overflow elsewhere (very common — adding text to one column pushes a different column past the budget when the grid re-balances), rollback to the pre-edit state and try a different method.

### Method — Method figure max-height tune (column-level)

**Scope:** the Method figure's `.method-figure { max-height: <X>cqh }` rule. Question to answer: *is the Method figure already filling 80–99% of its available column-vertical room on at least one axis (width or height), or is the cap leaving headroom on the table?*

Why this method matters early. The Method figure is the single largest visual on the poster, and the image-fit script (see template footer) makes the figure box shrink-to-AR around the image — so the **only** knob that controls how big the image gets is the figure's own `max-height` cap. Setting the cap too low (the safe default) leaves a small image and burns vertical space that a sibling card (Key Results) ends up needing. Setting it too high pushes Key Results into `OVERFLOW`. The right cap is paper-specific: a square architecture diagram wants a tall cap; a wide pipeline diagram wants a shorter one. It's worth tuning this before deciding to add an optional section, because adding Contribution / Ablation later changes the column's vertical budget — this method picks the cap that makes Method as large as it can be while leaving room for the rest.

**Budget floor (already enforced by the template, mentioned here so you don't double-correct).** Both templates' fit() scripts enforce `budgetH >= 0.24 * canvasH` (~830px on the 5760x3456 canvas) **specifically for Method-section figures**. This means a wide Method figure (e.g. 5:1 architecture banner like 904x181) at full column width is guaranteed to land at >=14% canvas height even when its section doesn't carry `.grow` and a sibling absorbs the column slack. So you should **never** see a Method figure painting under 90% width with the default cap. If you do, the floor regressed — check that `.method-body > figure { min-height: 14cqh }` is still present in the template's `<style>` and that the fit() script's `MIN_METHOD_FIG_BUDGET` block fires when the closest section's `data-section === 'method'`. The cap tune below still applies to figures that are **already** filling >=90% on one axis but could grow larger; the floor only prevents the catastrophic small-stamp failure mode.

**Note on orientation (full template).** The `orientMethod` script auto-picks the Method body's layout: a figure stacks (bullets above, full-width figure below) unless it is **portrait** (`w_fig/h_fig < 1`) **and** narrower than its stacked slot **and** the bullets' ~42% row share clears the readable-width floor (`min-width: 22em`), in which case it flips to `.method-horizontal` (bullets ~42% beside figure ~58%). Landscape figures always stack; a portrait-and-narrow figure in a **too-narrow column** also stays stacked because the floor vetoes the flip (starved 2–3-word-per-line bullets read worse than a stacked figure). This matters for the cap tune and especially the column-width nudge: a width nudge that narrows the Method column can drop it below the floor and *change the orientation*, so re-read the slack report after any Method-column width change. This method tunes the same `max-height` cap regardless of orientation — the fill helper below reads the figure's rendered rect, which already reflects whichever layout was chosen, and `max(wPct, hPct)` is the right metric for both (a stacked figure binds on width, a side-by-side portrait figure binds on height). You don't set the orientation; just tune the cap and let the script orient.

**Range:** `max-height: Xcqh` where `X` ∈ `[30, 60]` (full template) or `[40, 80]` (half template — half-width figures get more vertical room because they're not stacked above Key Results). Target the largest `X` at which **(a)** the rendered image fills **80–99%** of its figure box on at least one axis (width **or** height — a tall figure that fills the box height to ~100% counts even if it's narrow), AND **(b)** no sibling in the same column is in `verdict.overflowSections`. The 80–99% band leaves a single-percent visual breathing margin while still pushing the figure to the visual maximum.

**Propose.** Binary-search on `X`:

1. Start from the template default (full = `42cqh`, half: no explicit cap → use `60cqh` as the explicit starting point so this method has a knob to turn).
2. Re-measure with `check_poster.py slack`. Read **figure-fill** via the helper:
   ```bash
   python -c "from playwright.sync_api import sync_playwright; from pathlib import Path
   url=Path('<outdir>/poster.html').resolve().as_uri()
   with sync_playwright() as p:
     b=p.chromium.launch(); pg=b.new_page(viewport={'width':5760,'height':3456})
     pg.emulate_media(media='print'); pg.goto(url,wait_until='networkidle'); pg.wait_for_timeout(2000)
     print(pg.evaluate('''() => {
       const f=document.querySelector(\".method-figure\"); if(!f) return null;
       const i=f.querySelector(\"img\"); const fr=f.getBoundingClientRect(); const ir=i.getBoundingClientRect();
       const wPct=Math.round(100*ir.width/fr.width), hPct=Math.round(100*ir.height/fr.height);
       return {wPct, hPct, fillPct: Math.max(wPct, hPct)};
     }'''))
     b.close()"
   ```
   `fillPct` is the **per-axis maximum** (the larger of width-fill and height-fill) — that's what the width-or-height policy gates on. (Or read `image` vs `figure` rects directly with the same query.)
3. If image fillPct < 90 **and** no sibling overflows → **raise** `X` by 6cqh and re-measure.
4. If any sibling section overflows → **lower** `X` by 4cqh and re-measure. Smaller decrements on the shave-back direction because flexbox propagates the freed space directly to the OVERFLOW sibling, so each cqh down has outsized effect.
5. Stop when fillPct is in `[70, 99]` AND no sibling overflows. The cap that achieved this is the right value.

If no `X` in range satisfies both conditions, the figure box is too constrained by its section's text — **do not settle for a sub-90% figure.** Free vertical room so the figure can grow into the 90–100% band: tighten the bullets in the figure's own section (height-bound case — see the targeted-prose-polish method), shave a sibling card in the same column, or nudge column width to give the figure's column more room. Iterate until some `X` lands `fillPct` in `[90, 99]` with no sibling overflowing. A figure under 90% on both axes is a `FIG/NARROW` defect and is **not** an acceptable finishing state.

**Keep or rollback.**
- Image now fills 80–99% of figure box on at least one axis, no sibling overflows → **keep** the tuned `X` value.
- The best `X` still leaves Key Results in `overflowSections` → don't lower further; instead jump to "Shave back when overflowing" to trim Key Results' content, then return here with a tuned `X`.
- Half-template: if the Method figure section is its column's only Method card and there's no Key Results below it, the cap can stretch up to `80cqh` without risk — the only sibling competing for vertical space is the next column-grow card.

This method never adds or removes a section; it only resizes one CSS rule. Keep it focused on the Method figure.

### Method — Method-driven arrangement re-pick (method-driven layout only, column-level)

**Scope:** the `methoddriven` layout's `.mid-wide` block. Applies ONLY when `--layout methoddriven`. Question to answer: *given the priority Method figure, is the current subsection-card arrangement filling the room the figure left, with every `.msub` FULL?*

The Method figure is the priority: it fills the column width (and clears the 90% figure gate on width), bounded by `--method-fig-max` (default `42cqh`). The subsection cards below adapt to whatever height remains, and their arrangement is **not fixed** — `.msubs` is a span-composable grid you retag per-paper:
- `.msub.wide` → full-width long row (first card = top row, last card = bottom row)
- `.msub.tall` → tall card spanning 2 rows (the two normal cards flow the other column)
- `cols-3` on `.msubs` → a 3-up equal-column row

**Propose.** Read the per-`.msub` slack verdicts (`data-section="method-1"…"method-N"`), then:
- One card is long / carries a `.msteps` row or a small table while the others are short → make the long one `.msub.wide` (own full-width row) and pair the short ones side-by-side.
- One card is content-heavy and the other two are light → make the heavy one `.msub.tall` (left or right) and stack the two light ones in the other column.
- All cards are balanced and short → leave them all-normal (packs 2×2), or use `.cols-3` for three.
- Cards are cramped / a column reads INFEASIBLE in `pack` → raise `--method-fig-max` down a notch (smaller figure → more card room) OR cut a card / shorten prose, and re-pick the arrangement — do NOT just pad prose into an over-tight grid.

**Keep or rollback.** Re-run `pack` + `slack` + `polish`. Keep only if every `.msub` is FULL, no OVERFLOW/SPILLAGE, the Method figure still clears 90% on width, and the multi-card rows are content-balanced (no CARD-TRAILING blank). Otherwise revert the retag and try a different arrangement. Prioritize the figure first, then fit the cards into the remainder.

### Method — Add or rollback an optional **section** (column-level)

**Scope:** the whole column. Question to answer: *does this column have room for an extra section card?*

**Propose.** Walk the columns. For each column whose sections include at least one `SPARSE` / `EMPTY` verdict AND which doesn't yet have its optional section, choose the *highest-value* filler in this order:

1. **Inject the secondary figure** (if Step 5 picked one and it hasn't been placed yet) into its target Key Result / Ablation / Qualitative card. A figure inside an existing card delivers more reader value per inch than any new prose section and is the preferred way to fill column slack.
2. **Re-insert Ablation Study** (`{{ABLATION_1..2}}` from Ablation `Necessary`, `{{ABLATION_CONCLUSION}}` from its `Audio script`) if the right column has slack AND the spec has real ablation rows (skip if "no ablations reported"). Re-add `"ablation-study"` to `PLAYLIST`.
3. **Inject a paper-specific custom section** (Step 4's menu — Task Formulation, Qualitative Results, Failure Modes, etc.) into its insertion-point column if one was recorded in the spec.
4. **Re-insert Dataset / Benchmark** if the paper introduces one and it was withheld at lean-render.
5. **Re-insert Contribution** — LAST RESORT, only when (a) every other filler above has been tried, AND (b) the paper's headline novelty IS its contribution list (per Step 4's policy). For typical method-and-results papers, leave Contribution dropped — a sparse column that can only be filled by Contribution prose is a signal to grow the Method figure or extend `Additional` text instead. When kept, re-insert as `{{CONTRIBUTION_1..3}}` derived from Contribution `Necessary` only, split into ≤3 short bullets, and re-add `"contribution"` to `PLAYLIST`.

Per the vertical-sizing rule (see `template_substitution.md`), move the `grow` class onto the new bottom-most section so each column has exactly one growing child.

**Re-measure** with `check_poster.py slack`.

**Keep or rollback.**
- Every section in the touched column now `FULL` → **keep**. Move on.
- The touched column now has any section in `overflowSections` → **rollback the whole optional section** (remove the card, drop the `PLAYLIST` id, re-assign `grow`). The column doesn't have room; the per-section `Additional` append method is the right tool instead. Don't try to "fix" the overflow by trimming the optional you just added — it shouldn't have been added.
- The touched column still has `SPARSE` / `EMPTY` sections but no overflows → keep the optional and, next iteration, consider a paper-specific custom section or growing individual sections.

### Method — Add or rollback a paper-specific **custom section** (column-level)

**Scope:** any column still showing `SPARSE` / `EMPTY` sections after the canonical optionals have been considered. Question to answer: *did the spec carry a paper-specific custom section that fits this column, and does the column have room for it?*

The canonical 9 sections plus the 3 canonical optionals (Contribution, Dataset / Benchmark, Ablation Study) cover most papers. For papers that carry a substantial chunk on a topic the canonical vocabulary doesn't name, Step 4 of `SKILL.md` lets the synthesizer record **0–3 paper-specific custom sections** in `paper_spec.md` (Task Formulation, Theoretical Analysis, Efficiency / Complexity, Training Recipe, Scaling Behavior, Qualitative Results, Failure Modes / Limitations, Released Artifacts). These are never rendered in the lean initial pass; this method decides whether to inject them.

**Propose.** Read `paper_spec.md`. Walk every `##` heading whose name is **not** one of the canonical 9. For each such custom section:

1. Look up its target neighbor in the SKILL.md custom-section table (e.g., "Failure Modes / Limitations" → after Ablation Study).
2. Find the column that target neighbor lives in.
3. If that column has at least one `SPARSE` / `EMPTY` section in the latest measurement, inject the custom section into `poster.html` **immediately after** the target neighbor's `.section` block. Use the custom section's `Necessary` only (no `Additional` yet). Set `data-section="<kebab-case-name>"` (e.g., `failure-modes`, `task-formulation`, `released-artifacts`). Custom sections use the canonical theme `--accent` for border and heading; for the Listen button accent, use neutral slate `#475569` — custom sections don't get their own named color in the palette.
4. Re-assign the `grow` class so the new bottom-most section in that column carries it.
5. Add the kebab-case id to `PLAYLIST` so its TTS clip is generated.

**One custom section per re-measure cycle.** If the spec carries multiple custom sections, inject the highest-priority one first. Priority order (passersby and reviewers read these first): Failure Modes / Limitations > Task Formulation > Qualitative Results > Efficiency / Complexity > Released Artifacts > Training Recipe > Scaling Behavior > Theoretical Analysis.

**Re-measure** with `check_poster.py slack`.

**Keep or rollback.**
- Every section in the touched column now `FULL` → **keep**. Move on, considering the next custom section for any column still sparse.
- The touched column has any section in `overflowSections` → **rollback the custom section entirely** (remove the card, drop the `PLAYLIST` id, re-assign `grow`). Custom sections are fillers; if they don't fit, they don't go in. Don't try to trim the custom section to fit — the canonical sections own the column budget.
- The column still has `SPARSE` / `EMPTY` after the custom section is in → **keep** the custom section and, next iteration, grow `Additional` paragraphs.

**Hard rule.** A custom section that overflows shouldn't have been added (same rule as canonical optionals). Custom sections never edit the canonical sections' content to make room — if the column is already at budget after canonical optionals, skip the custom section entirely.

**Released Artifacts auto-suggest from `metadata.json`.** When `<outdir>/assets/meta/metadata.json` has a non-empty `code_url`, `project_url`, or `paper_url` AND the spec didn't already record a Released Artifacts custom section, the custom-section method may synthesize one on the fly:

- Inject after Takeaway (per the SKILL.md custom-section table).
- `Necessary` reads as a short link list, e.g., `Code: github.com/user/repo · Paper: arxiv.org/pdf/1706.03762 · Project: project.io`. Strip the `https://` prefix for compactness; render each as a `<a href="...">` link.
- Only include the fields that are non-empty in `metadata.json`. Never fabricate URLs.
- Treat as the **lowest-priority** custom section (lower than Theoretical Analysis) — only inject if a column is still `SPARSE` / `EMPTY` after all spec-recorded custom sections have been considered.
- Use `data-section="released-artifacts"` and add `"released-artifacts"` to `PLAYLIST` only if a script can be auto-synthesized (otherwise omit from PLAYLIST).

### Method — Append or rollback optional **text** (section-level)

**Scope:** one section at a time. Question to answer: *does this specific section have room for its `Additional` paragraph?*

**Propose.** Walk `verdict.sparseSections` ∪ `verdict.emptySections` in document order. For the first named section, look up its `**Additional:**` line in `<outdir>/assets/meta/paper_spec.md` and append as a second `<p>` (or continuation bullets if the section uses `<ul>`).

For the middle column (Method + Key Result), this method also covers appending Method's `Additional` and — when Key Result is `SPARSE` / `EMPTY` — applying the **Key Result growth ladder** below. Never add a whole extra section to the middle column.

#### Key Result growth ladder (Key Result only)

Key Result is the most number-dense card on the poster; when it reads `SPARSE` or `EMPTY` the right fix is **more numbers**, not more prose. A passerby reads table cells and stat tiles roughly 3× faster than sentences, so visual density beats word count. Apply these tactics **in order**, one per re-measure cycle, until the card lands `FULL`:

1. **Grow the results table.** The lean render shows a 2-row Baseline-vs-Ours comparison. Expand `<table class="results">` to **3–6 rows** using the full results table the synthesizer captured in the spec's Key Result `Additional`. Add 1–3 stronger or more recent baselines and, if the paper reports multiple model sizes, both the base and big variants of the proposed method. Keep numbers **verbatim** from the source table; never round, average, or invent.
2. **Add a second metric column.** If the source table reports two metrics on the same axis (e.g., EN-DE BLEU + EN-FR BLEU, top-1 + top-5 accuracy, accuracy + latency), widen the table from 2 columns to 3. Mark the best-performing row with `<tr class="best">`. Information-density gain is large for small visual cost.
3. **Append a `.callout` headline delta.** If the lean render didn't carry `{{HEADLINE_DELTA}}`, add it now: a single-sentence pill summarizing the strongest comparison (e.g., "+2.0 BLEU over prior best; ¼× the training cost"). All numbers must come from the spec.
4. **Append a `.conclusion` "so-what" line.** Pull from Key Result `Audio script` (≤22 words) and render under the table/callout. This is the "what the numbers mean" sentence.
5. **Append a mini `.stat-grid` below the table.** Still `SPARSE` after steps 1–4? Render a 2-cell stat-grid of supporting numbers (training-cost FLOPs, parameter count, throughput, latency, dataset size) drawn from the spec's `Additional` or `Headline Numbers`. Use only when the source paper has ≥2 supporting numbers **not** already in the table or the Headline Numbers card. Don't duplicate stats across cards.
6. **Last resort — append Key Result `Additional` as a `<p>`.** Prose paragraph. Use only when the visual tactics above ran out of source material.

If the lean render *replaced* `<table class="results">` with a `<p>` (because the spec had no clean baseline-vs-ours comparison), step 1 here is "swap the `<p>` back to a table by reading the source paper's results section and picking 3 honest rows." Key Result is the **one** section where the staged-fill loop is allowed to re-introduce structured markup that the initial render simplified away — the cost of an under-filled Key Result card on the most-read column is too high to accept.

**Hard rule — no fabricated numbers.** Every cell, callout delta, and stat-grid value must trace to `text.txt` or `captions.json`. If the spec ran out of real numbers, stop the ladder and accept `SPARSE`; never pad with made-up rows. Padding Key Result with invented numbers is the worst possible failure mode for this skill.

If the spec's Key Result `Additional` is itself thin (the extractor only found 2 baselines), the right fix isn't here — it's upstream. Re-read `text.txt` around the Results section and `captions.json` for Table 1/2, pull more baseline rows into the spec, then come back to step 1. The spec is the contract; if it's thin, fix it.

**Re-measure.**

**Keep or rollback.**
- The touched section is now `FULL` and no *other* section has flipped to `OVERFLOW` → **keep**. Move to the next still-sparse section.
- The touched section flipped to `OVERFLOW`, or pushed a sibling in its column to `OVERFLOW` → **rollback the appended paragraph**, then try **polishing instead**: tighten the spec's `Additional` by 10–20 words (cut filler — "In particular,", "It is worth noting that…" — preserve every number and named entity), re-append the shortened version, re-measure. If it still overflows after one polish pass, rollback for good and leave that section `SPARSE`.
- The touched section is still `SPARSE` after appending the full `Additional` → it's as full as the spec allows; move on. The column-width nudge or targeted prose polish methods may close the gap.

Only one append per re-measure cycle for a given column. Appending to three sections in the same column in a row without measuring between them makes the rollback decision ambiguous — you won't know which append caused the cascade.

### Method — Rebalance adjacent sections within a column (column-level)

**Scope:** one column whose sections are *individually* off-band but whose column as a whole is at budget (`slackRatio` ≈ 0). Question to answer: *the column has no free space, but is it distributed wrong — one card SPARSE while its siblings sit FULL?*

This is the method for the case the others can't touch. When a column has zero slack, you can't grow a SPARSE card by *adding* content (it pushes a sibling into OVERFLOW), and you can't shrink it by *removing* content (it's already underfilled). The pixels exist in the column — they're just sitting in the wrong card. Paper1's left column is the canonical example: `problem` reads SPARSE (~0.88) while `motivation` and `contribution` are both FULL, and the column's `slackRatio` is 0. Nothing is missing; the height budget is mis-apportioned. Two levers move the budget between siblings without changing the column's total:

- **`.grow` reassignment (pure layout, try first — it invents no text).** Exactly one section per column carries `.grow` (`flex: 1 1 auto`), and it absorbs all leftover column slack; every other `.section` sizes to its content (`flex: 0 1 auto`). Normally `.grow` lives on the bottom-most card. If a *non-bottom* card is the one reading SPARSE and the current `.grow` card is comfortably FULL, the slack is pooling in the wrong place. You usually can't simply move `.grow` upward (the templates expect it bottom-most so the column's visual baseline stays flush), but you **can** even out the distribution by promoting a reserved line into the SPARSE card *and simultaneously* trimming an equivalent line from a FULL sibling — a net-zero content swap that the next lever describes.

- **Net-zero content swap between siblings (semantically gated).** Move a *reserved* sentence or bullet from a FULL sibling into the SPARSE card — but **only when that content genuinely belongs to the destination section's topic.** The right source is usually a line the synthesizer parked in the FULL sibling's `**Additional:**` that actually reads as the SPARSE section's concern (a Problem-flavored caveat sitting in Motivation's Additional, say). Pull it into the SPARSE card and, if the donor sibling tips toward SPILLAGE as a result, trim its longest bullet by a clause. The column's total content is unchanged; only its distribution shifts toward even.

**Hard semantic rule.** Never relocate a sentence across a section boundary just to balance pixels — a Motivation sentence stranded under the Problem heading reads worse to a passerby than a slightly-empty card, and it quietly corrupts the section's meaning (and its Listen-button narration, which still describes the original topic). If no reserved line in the column genuinely fits the SPARSE section, **do not force an off-topic relocation** — instead fill the SPARSE card the honest way: append *its own* `Additional` material, inject an on-topic custom section, or nudge column width so the card's own prose wraps to fill it. This method only ever *relocates* existing, on-topic content; it never invents filler. `SPARSE` is not a finishing state — keep applying methods until the card is `FULL`.

**Re-measure** with `check_poster.py slack` after each swap — a within-column move re-flows every card in that column.

**Keep or rollback.**
- The SPARSE card reached `FULL` and no sibling flipped to `SPILLAGE` / `OVERFLOW` → **keep**.
- A sibling tipped past the border and one clause-trim didn't recover it, or the only available content didn't truly fit the destination topic → **rollback the swap**, then fill the SPARSE card by an on-topic method instead (its own `Additional`, a custom section, or a width nudge). Do not stop while the card is still `SPARSE`.

This method is deliberately low-priority: reach for it only after the additive methods (append text, add optional/custom section) have been ruled out by a zero-slack column. It buys the last 5–10% of fit on a column that's *full but lopsided* — not one that's genuinely short of content.

### Method — Column-width nudge ± prose micro-edit (cross-column rebalance)

**Scope:** the whole poster. Question to answer: *can a small width change move slack from a full column to a sparse one?*

Reach for this when the per-section and per-column methods have been tried and at least one section is still `SPARSE` / `EMPTY` / `OVERFLOW`.

**Propose.** Two complementary tools, usually applied together:

- **Column-width nudge.** Templates declare the grid via `grid-template-columns` on `.poster`. Shift width between an overflowing-column and a sparse-column by **±5% at a time, capped at ±10% total** from the template default. A narrower column makes the same prose wrap to more lines (raising its fillRatio) and frees vertical space in its neighbors. Concrete example: `1fr 2.4fr 1fr` → `1.25fr 2.15fr 1fr` moves ~5% width from the wide middle column into a too-tight left column, dropping its sections' fill ratios from ~115% back to ~95%.
- **Prose micro-edit.** Pad a `SPARSE` section's `Necessary` or `Additional` paragraph by 10–20 words drawn from the same source paragraph in the spec (never invent facts), or tighten an `OVERFLOW` section by 10–20 words preserving every number and named entity.

**Re-measure** after each nudge **and** after each prose edit — never batch them. A width change re-flows every column simultaneously and can easily turn one fix into three new overflows.

**Keep or rollback.**
- All sections now in band → **keep**, done.
- Fewer sections out-of-band than before, no new overflows → **keep**, continue with another nudge or micro-edit.
- Same or more sections out-of-band, or any new overflow → **rollback that single edit** (revert the `grid-template-columns` line or the prose change) and try the opposite direction (nudge the other way, or pad/tighten a different section).
- After two failed nudge attempts in each direction → stop nudging *this* lever and switch methods. The width nudge is only one knob; a still-`SPARSE` card means you fall back to appending its `Additional`, injecting an on-topic custom section, or rebalancing siblings. `SPARSE` (fullRatio 0.70–0.90), `EMPTY`, and `OVERFLOW` are all non-finishing states — keep iterating until every section is `FULL`.

### Method — Fill a flex-inflated section with on-topic content (don't shrink it)

**Scope:** a `.grow` section that reports `SPARSE` because flex stretched it past its current content — most commonly **Method when its figure is sized at the wide-floor and the bullet count is too low to fill the flex-allocated height**. The figure box stops at its image+caption height (correctly — `fig.style.flex='0 0 auto'`), so the unused flex space lands as trailing whitespace inside the section card.

**The diagnostic.** Open in browser, press `d`, look at the green dashed content union. If it ends well above the card's bottom border AND the figure is already at its width-floor cap (`figure.style.maxWidth` near 75% of available), the void is real and slack will report it as SPARSE 85–92%.

**The fix is content, NOT structure.** Add real material that belongs in that section:
1. **Add a bullet.** The most direct fix — if the Method spec has more than 3 candidate bullets, promote one of the held-back ones into the rendered list. The bullet should be a genuine step in the method (Train, Validate, Inference) — not filler.
2. **Append a one-sentence paragraph below the figure.** Pull from the section's `Additional` field in `paper_spec.md`. Place AFTER the figure so it doesn't push the figure box smaller.
3. **Lengthen each existing bullet by 5–10 words.** Add concrete qualifiers ("on the full dataset (not a subset)", "with zero soft-label storage") that came from the source paper. **No invention** — every added word must trace back to the spec or source text.

After each edit, re-measure. The void shrinks toward zero, the SPARSE verdict climbs toward FULL, and the column bottoms stay aligned with neighbors (because the section's *card* height is still set by flex, not content).

**Do NOT drop `.grow` to shrink the section to its content.** That fixes the void but creates a worse problem: the section card becomes shorter than its sibling column's content, so the column bottoms misalign. The right column might end at 36 in while col-1's mid-wide ends at 32 in, leaving a 4-in white band at the bottom of one column only. A balanced poster has all columns reaching the same baseline — preserve that, even if it means working harder to find honest content.

**When content is genuinely exhausted** (spec has no more material, no Additional, source paragraph already fully extracted) — the spec was too thin. Go back to the spec-synthesis step (SKILL.md Step 4) and pull more from the paper's Method section; the spec under-extracted on the first pass.

### Method — Targeted prose polish (last-mile fine fit)

**Scope:** the specific sections still out-of-band after the other methods. Question to answer: *can I close the last 5–15% of fit by polishing the prose in the named SPARSE / EMPTY / OVERFLOW sections?*

Reach for this when the other methods have been tried and at least one section is still flagged. It's the most surgical method — most posters never need it, but it's the difference between "acceptable" and "publication-clean" for the awkward few.

**Propose — targeted prose polish for `SPARSE` / `EMPTY` / `OVERFLOW` sections.** Walk the named sections and rewrite the specific paragraph/bullet that's mis-sized. Discipline:

- **`OVERFLOW`**: tighten by 10–25%. Cut filler ("In particular,", "It is worth noting that…", "Notably,"). Replace clauses with appositives. Combine two short bullets into one. **Preserve every number, named entity, method name, and dataset name.** No semantic loss.
- **`SPARSE` / `EMPTY`**: pad by 10–25%. Pull material from the same paragraph in `paper_spec.md` (the spec's `Additional` or the source sentence the `Necessary` was distilled from). If the spec is dry too, add one concrete number or named entity that the source paragraph mentions. **Never invent facts.**
- **Inline emphasis check** (also `references/visual_polish.md` §"Inline emphasis"): every revised paragraph should re-balance its `<strong>` / `.hi` / `.num` budget. 2–5 `<strong>`s, at most one `.hi`, and `.num` on every standalone number. If the rewrite drops the section's only `.hi`, restore one on the most decisive sentence.

**Re-measure** after each single edit. This is the most surgical method in the loop — one paragraph polish per cycle.

**Keep or rollback.**
- Section landed in band, no sibling flipped to `OVERFLOW` → **keep**, continue with the next out-of-band section.
- Section moved in the right direction but is still out of band → **keep** and re-measure: a second polish pass on the same section is fine here (this method is explicitly the fine-tuning layer).
- Section went wrong direction or pushed a sibling to `OVERFLOW` → **rollback that single edit**, then try polishing a *different* paragraph (e.g., the sparse sibling instead of the overflowing one).
- After three rollbacks on the same section → switch methods rather than settling. Between `SPARSE` and `OVERFLOW`, prefer to leave the section `SPARSE` *for that iteration* (shave the overflow one more time per "Shave back when overflowing" below), but `SPARSE` is still not a finishing state: return to it next pass with a different lever (its own `Additional`, a custom section, sibling rebalance, or width nudge) until it reaches `FULL`.

### Why prose polish stays separate from the column-width nudge

The column-width nudge rebalances the whole poster (column widths, cross-column prose). The prose-polish method stays *inside* a single section's card and tweaks one knob only: the text of the named out-of-band paragraph. Direct figure-box sizing (the `max-height` cap) belongs to the Method-figure method — keeping the last-mile polish prose-only means a regression there always points at the one paragraph you just edited, not at an entangled image rescale. Prose is the cheapest knob to roll back and the most local, which is why it's usually the last method you reach for. Note that prose edits *indirectly* resize a figure when its section is **height-bound**: trimming the bullets in a figure's own section frees the vertical room the fit script then hands to the figure box, which is exactly how you clear a `FIG/NARROW` warning once the columns are at 0 slack and the figure cap can't grow. That coupling is intentional and still local — the edit and its effect both live in the one section you touched.

### Why measure-act-rollback rather than measure-act-act-act

Each edit shifts the layout in ways that are hard to predict from inspection alone: re-adding Contribution can push Motivation into overflow when the column re-balances, and a column-width nudge re-flows all three columns at once. Batching two edits *in the same column* and then measuring leaves you unable to tell which one caused a regression. (Two edits in *independent* columns are safe to batch — that's the "one or two methods per iteration" allowance.) The cost of one extra `check_poster.py slack` call (~3s) is much smaller than the cost of unwinding two intertwined edits by guess. When in doubt, measure.

## Shave back when overflowing

Any time the measurement names a section in `verdict.overflowSections` **or `verdict.spillageSections`**, fix it before continuing the loop. SPILLAGE (1.00–1.10) is the same defect as OVERFLOW (>1.10), just milder — content past the card border — so it gets the same shave-back treatment; the only difference is degree, and a one-line trim usually settles a SPILLAGE section where an OVERFLOW one may need a whole paragraph or optional-section removed.

**Watch for *systematic* spillage.** When most sections in the poster spill by a similar small margin at once (e.g. six sections all at fullRatio 1.03–1.06), the problem isn't any single card's content — it's that every column was grown a few percent too tall together. Don't trim six cards one at a time; instead apply a *uniform* reduction that re-flows the whole page: nudge the base font-size or line-height down a notch in the template's root rule, or widen the tightest column slightly so its prose wraps to fewer lines, then re-measure. One global edit clears all six far more cleanly than six local trims that each risk flipping a sibling.

Apply in order, stopping the moment the section lands in band:

1. **If the overflowing section is the column's optional** (Contribution / Ablation Study) — drop it entirely. Drop its id from `PLAYLIST`. **Hard rule: an optional section that overflows shouldn't have been added.**
2. **Strip an `Additional` paragraph** from the overflowing section if the append-text method added one to it.
3. **Trim the longest bullets** in the overflowing section by 20–30%. Preserve every named entity and number; cut filler only.
4. **If a sibling section in the same column is `SPARSE` / `EMPTY`**, the column is *balanced wrong*, not full — move text from the overflowing section into the sparse one (e.g., split a long bullet across two sections that share the topic), then re-measure.
5. **Re-assign `grow`** to the new bottom-most `.section` if you removed the previous bottom.

If a section with only its core `Necessary` paragraph *still* overflows, the `Necessary` text itself is too long — tighten it in `poster.html` (don't edit the spec) by 10–20 words, preserving every number and name. This is the only situation where shave-back edits `Necessary`.

### Why per-section overflow is sneakier than column overflow

Column-level slackRatio can read 0% (column "perfectly full") while three sections inside it overflow by 15–20% each — flex children with `min-height: 0` compress their cards while their text paints past the bottom border into the inter-card gap. The column accounting balances out, but the rendered poster shows text colliding with neighboring section borders. The per-section gate is the only way to catch this; the old column-only gate is silent.

## The asymmetry that matters

A section with too much content crowds the eye and feels cluttered; a section with too little reads as breathing room. Both are defects. *Within a single iteration*, if you must choose between leaving a card transiently `SPARSE` and letting one `OVERFLOW`, prefer the `SPARSE` — then fix it on the next pass. The end state is not "slightly empty is fine"; the end state is **every section `FULL`**. The loop grows content into a measured budget and keeps rebalancing until the whole poster sits in the `FULL` band with every figure at 90–100%.

## Why measurement and not eyeballing

Claude isn't actually rendering the page to look at it. `check_poster.py slack` gives a real bounding box per section from a real Chromium layout pass, which makes the fill decision deterministic and reproducible across runs. Prefer the script's verdict over your own guess.

## When to skip the loop entirely

- Every section already reads `FULL` on the first measurement (rare for full papers; common for short workshop papers).
