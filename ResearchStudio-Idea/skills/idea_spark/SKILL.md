---
name: idea-spark
description: Generate ONE reviewer-defensible, implementable research idea — with a concrete method and a falsification plan, calibrated against the patterns of Oral-accepted papers — from a user's research direction. Diagnoses the bottleneck against retrieved literature, selects 1-3 of 15 induced ideation patterns that structurally fit the bottleneck (with corpus-derived anti-pattern guard), generates a single candidate, runs collision check + critique, and expands into a structured idea card. **One-shot guarantee**: one user input produces one of three outputs — the rendered idea-card markdown (returned inline as the run's final response, with the LaTeX side artifact + per-phase JSON left under the run directory), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons) — never asking the user mid-flow. Use when the user asks for a research idea, novelty analysis, or paper-shape suggestion within a stated direction. Skip for code review, debugging, or pure brainstorming without research context.
---

# Idea Spark Skill

Convert an under-specified research direction into ONE reviewer-defensible Oral-level research proposal — grounded in 1947 ICLR/ICML/NeurIPS papers (2021-2025) — via a 5-phase workflow: retrieve recent literature, diagnose the bottleneck, select + generate a candidate using corpus-derived ideation pattern cards, run it through a quality gauntlet, expand into an idea card.

This file is the operational runbook. Design rationale (the 7 design principles, why each contract is shaped this way, removed-check history) lives in [references/design-notes.md](references/design-notes.md) — read it only when modifying or evaluating the skill, never needed to run it. First-time installation lives in [references/setup.md](references/setup.md).

## When to use

- "Give me a research idea in {area} I could pursue." / "What's the most impactful next step in this direction?"
- "Help me sharpen this vague direction into an Oral-level proposal."
- "What's the bottleneck of this problem?" / "Run a novelty audit on this idea."

## When NOT to use

- Code review, debugging, refactoring. Summarizing one paper. Cross-decade survey writing.
- Free-association brainstorming with no research context. Engineering integration tasks ("ship this feature in our system").
- Pure benchmark / dataset construction work — the 15-pattern vocabulary handles benchmark *audit* (controlled_diagnostic_design) but not benchmark *construction*.

## Setup (first use only)

Follow [references/setup.md](references/setup.md). Quick version — set two shell variables, install deps, verify:

```bash
SKILL_DIR=~/.claude/skills/idea-spark            # or wherever this folder lives
RUN_DIR="$PWD/idea_run" && mkdir -p "$RUN_DIR"   # ANY absolute output dir (Claude Code: reuse CLAUDE_PROJECT_DIR)
python3 -m pip install feedparser openreview-py beautifulsoup4 pymupdf
python3 "$SKILL_DIR/scripts/run.py" check_connectors   # from the SAME shell you'll run phases from
```

Credentials go in `.env` (OpenReview user/pass + Semantic Scholar key — see setup.md); the orchestrator auto-loads it. Optional: `xelatex`/`tectonic` for PDF cards.

---

## How to run: the `next` loop

The canonical way to drive a run is the **run-state navigator**:

```bash
python3 "$SKILL_DIR/scripts/run.py" next --dir "$RUN_DIR" --query "<user's research question>"
```

`next` inspects the artifacts already on disk and prints EXACTLY one next step — either a Bash command to run verbatim, or an LLM sub-agent spec (system-prompt path + input file paths + output path + the routing signal to report back). It is read-only and idempotent (safe to re-run anytime, including to resume an interrupted run). The host loop is:

1. Run `next`.
2. Do what it says (`bash` → run the command; `llm_subagent` → execute in an ISOLATED context per the Context discipline rules below).
3. Run `next` again. Repeat until it reports a terminal state (`DONE`, `do_not_generate`, or `phase_3_failed`).

`next` encodes the full phase graph — the mandatory full-text gate, the citation gate, the abandon-retry branch, the falsification re-audit branch, and the correct Phase 4 flags per path — so you do not need to memorize the reference tables below; they exist for deviation and debugging.

If your host exposes a task/todo tool (e.g., TodoWrite), seed it with this checklist and tick phases as `next` moves past them:

```
- [ ] Phase 0: Literature grounding → lit_table.md, then Phase 0+ full-text fetch (MANDATORY — Phase 1 hard-gates on it)
- [ ] Phase 1: Bottleneck identification → phase1_output.json (routing: proceed | do_not_generate)
- [ ] Phase 2: Gap×pattern selection + candidate generation (ONE isolated context, TWO output files) → citation gate
- [ ] Phase 3: Collision retrieval (signature@10mo + alias@48mo) → audit (5 checks) → [revise → merge → re-audit if falsification rewritten] | [abandon → 1 internal retry]
- [ ] Phase 4: skeleton → fill → assemble → implementability audit → validate → render → return 3 cards inline
```

Three outcomes per run: the rendered idea-card markdown returned inline (LaTeX + per-phase JSON left under `$RUN_DIR`), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons twice). **Never ask the user mid-flow** — missing intake fields are inferred; revision, falsification re-audit, and the single internal retry all run without user re-invocation.

### Invocation contract

**No `cd` is required.** `scripts/run.py` self-locates its skill root, so every orchestrator command can be invoked from ANY working directory by absolute script path: `python3 "$SKILL_DIR/scripts/run.py" <subcommand> --out "$RUN_DIR/<phase>/" ...`. The legacy form `cd "$SKILL_DIR" && python3 -m scripts.run <subcommand> ...` works identically. Do NOT use relative script or `--out` paths — CWD is not stable across host-LLM Bash invocations, and the orchestrator rejects a relative `--out` outright.

**Exit codes 10 and 11 are NOT errors — they are sentinel handshakes.** When the orchestrator can't call an LLM itself (no `NOVELTY_LLM_CLASSIFY_FAST_CMD`), it writes a sentinel JSON describing what the host LLM should do, then exits rc=10 (intent / pattern-summary) or rc=11 (signature_terms). Read the sentinel (`$RUN_DIR/<phase>/.<step>_pending`), read the file at its `rubric_file` field (absolute path), produce the expected output, re-invoke per its `re_invocation` field. Do not stop on these codes. (The default Phase 0 flow below avoids the rc=10 intent sentinel entirely by passing `--queries` up front.)

### Context discipline (read BEFORE running any LLM-driven phase)

A full run accumulates ~180-250k tokens of intermediate state. If the host LLM carries that in its own conversation context across phases, the Phase 1 / 2.2 / 4.fill calls routinely hit the backend request timeout (`[API Error · Request timed out · Retrying...]`) and the retry times out again. Apply ALL three rules on every run:

**Rule 1 — Run every LLM-driven phase in an ISOLATED context.** Phases 1 / 2 (2.1+2.2) / 3.2 / 3.3 / 4.fill / 4.1.5 each have file-path inputs and one JSON output; no phase needs the conversation that produced an earlier one. Use the FIRST isolation mechanism your harness supports:

- **(a) Subprocess LLM** — set `NOVELTY_LLM_REASONING_LARGE_CMD` / `NOVELTY_LLM_CLASSIFY_FAST_CMD` (see § Configuration); each phase runs as its own subprocess, fresh context by construction, on any harness.
- **(b) Sub-agent tool** (Claude Code `Agent` or equivalent) — spawn one per phase, passing ONLY the file paths the phase prompt lists — not conversation history, not file contents inline. The sub-agent reads from disk, `Write`s to disk, returns ≤ 250 words (output path + routing signal). Exception by design: Phase 2.1 and 2.2 run in ONE sub-agent writing both output files — both are generation-side; the adversarial separations (3.2 vs 3.3, 4.fill vs 4.1.5) must stay separate calls.
- **(c) Manual context reset** — run inline but clear/compact at the four points in Rule 3.

Whichever mechanism, the parent context stays ≤ ~30k tokens for the whole run because it never holds a phase's structured output.

**Rule 2 — `Write` every phase artifact directly to disk; never paraphrase it into chat.** Output convention: `$RUN_DIR/<phase>/<phase>_output.json`. Use the `Write` tool — no Bash heredocs (permission prompts + silent truncation), no `echo`, no pasting JSON into replies. Bound tool-result captures from large files to ≤ 4 KB (`head -c 4000` / `jq` / `sed`); never `Read` a >10 KB intermediate dump into the parent context — the dump gets cached into every subsequent turn (this exact anti-pattern caused prior timeout runs).

**Rule 3 — Compact between phases.** Natural compact points: after Phase 0+, after Phase 1, after Phase 2, after Phase 3.2. Every phase re-reads its disk inputs, so compacting loses nothing. With `/compact`, use it there; Rule 1 mechanisms (a)/(b) achieve the same on their own.

**Diagnostic for "Request timed out" mid-phase:** inspect your harness's session log (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`, look for `isApiErrorMessage: true`); the prior tool call shows which prompt got too big. The fix is one of the three rules — usually Rule 1.

---

## Phase reference

`next` prints each of these steps at the right moment with concrete paths; the tables below are the full contract for deviation/debugging.

### Orchestrator entry points

| Phase | Entry point (`python3 "$SKILL_DIR/scripts/run.py" ...`, any CWD) |
|---|---|
| navigator | `next --dir "$RUN_DIR" [--query "..."]` |
| Phase 0 | `phase0 --query "<user text>" --queries "q1\|q2\|q3\|q4" --out $RUN_DIR/phase0/` |
| user-ref registration (title-named anchor papers; BEFORE phase0_fulltext) | `add_user_ref --out $RUN_DIR/phase0/ --title "<full title>" [--raw-match "<user phrasing>"] [--id <arxiv/DOI/URL>]` |
| Phase 0+ full-text (**mandatory**, the moment lit_table.md lands) | `phase0_fulltext --out $RUN_DIR/phase0/` |
| Phase 1 anchor top-up (optional, when the #1 closest_adjacent fell outside the fulltext pool) | `phase1_fulltext_topup --out $RUN_DIR/phase0/ --paper-id <anchor paper_id>` |
| Phase 3.1 collision | `phase3_collision --idea-json $RUN_DIR/phase2_generate/phase2_generate_output.json --out $RUN_DIR/phase3_collision/` |
| Phase 3.3 merger | `phase3_merge_revisions --phase2 <p2.2-output> --revisions <p3.3-patch> --critique <p3.2-report> --out $RUN_DIR/phase3_revise/` |
| Phase 4 skeleton | `phase4_skeleton --candidate <final_candidate-or-p2.2> --phase1 ... --phase2-select ... --phase3-critique ... [--phase3-revise ...] --phase0-dir $RUN_DIR/phase0/ [--collision ...] --out $RUN_DIR/phase4/` |
| Phase 4 assemble | `phase4_assemble --skeleton $RUN_DIR/phase4/phase4_skeleton.json --fill-map $RUN_DIR/phase4/fill_map.json --out $RUN_DIR/phase4/` |
| Phase 4 render | `phase4_render --expansion $RUN_DIR/phase4/phase4_expansion.json --out $RUN_DIR/phase4/` |
| Validators | `validate --phase2 ... [--phase3 ...] [--phase4 ...] [--phase4-impl ...]` |

The LLM-driven phases (1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.fill / 4.1.5 / falsification re-audit) have no orchestrator subcommand (a `cat prompt | llm` wrapper would add fragility without determinism): read the prompt at `references/system-prompts/<phase>.txt`, gather the inputs listed at its top, `Write` the JSON described under `Output:` to `$RUN_DIR/<phase>/<phase>_output.json`. Run each under the Context discipline rules — Phase 4.fill is the largest output and the most timeout-prone; never in the parent context.

### Phase 0 — Literature grounding

Phase 0 and 3.1 require **real external retrieval** via the bundled connector scripts (`scripts/search_*.py`) — never WebSearch or ad-hoc fetch (downstream phases reject unstructured output). Gate sentinel: `.lit_grounding_mode` = `real` vs `connector_failure` (halt with diagnostic; `--allow-webfallback` exists as a flagged, lower-confidence escape).

**Default flow (skips one sentinel round-trip):** BEFORE invoking `phase0`, read `references/intent-recognition.md` (Map mode) yourself and produce 4-6 search queries — including one ESCAPE-MECHANISM query phrased in solution vocabulary (recalls papers that already fixed the bottleneck and title themselves by their fix; problem-keyed queries miss exactly those). Also apply the OOD short-circuit (intake-routing.md triggers #1 Too-broad / #2 No-anchor → route to do_not_generate instead of retrieving). Then invoke with BOTH flags:

```bash
python3 "$SKILL_DIR/scripts/run.py" phase0 --query "<user's research question>" --queries "q1|q2|q3|q4" --out $RUN_DIR/phase0/
```

The rc=10 sentinel path still exists as fallback when `--queries` is omitted. The orchestrator: asserts a sane clock; probes 4 connectors and retrieves role-based (arxiv 0-6mo cap 10 / openalex 6-24mo cap 12 published-only / semanticscholar 6-24mo cap 13 published-only / openreview 0-6mo cap 10 in-review; ~40-45 papers; non-overlapping windows; SS-priority dedup); extracts URL/ID user-refs from the query into `phase0/user_refs.json`; emits `.pattern_summary_pending` for the host.

Retrieval takes 3-10 min (the openreview connector alone budgets 600s) — set your Bash timeout ≥ 600s or run it in the background.

**Pattern tagging (host step):** classify each `lit_results.json` paper per `references/pattern-summary-rubric.md` into 1-3 of the 15 patterns → write `lit_table.md` with columns `paper_id | year_month | venue | title | ideation pattern tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem | retrieved_via`. Pure classification — delegate to a CHEAP/FAST isolated context (Haiku-class model or effort=low), not the large reasoning model.

**Title-named user refs:** if the user query names anchor papers by TITLE ("based on the LoRA paper" — anything the URL/ID regex can't catch), register each BEFORE `phase0_fulltext` via `add_user_ref` (entry-point table). It does a deterministic dedup-merge into `user_refs.json` — do NOT hand-edit that file (the Write tool requires a prior Read on existing files, and a malformed edit silently drops the U fetch tier).

**Phase 0+ full-text fetch — MANDATORY.** The instant `lit_table.md` lands, run `phase0_fulltext` (entry-point table) before touching Phase 1. Pool = U (user refs, never capped) + T2 (top-10 published on-topic) + T3 (top-5 arxiv on-topic), ceiling 15 excluding U, method-first ordering, concurrent fetch (HTML path first, pymupdf PDF fallback; per-paper budget so one slow PDF can't stall the step). Output `fulltext_cache.json` keyed by paper_id (`{tier, intro, method, source_used, warning}`); fetch failures degrade to abstract + warning. Phase 1 **hard-gates** on this file (`error: fulltext_not_fetched`).

### Phase 1 — Bottleneck identification

One isolated LLM call. Prompt: [references/system-prompts/bottleneck_identify.txt](references/system-prompts/bottleneck_identify.txt). Inputs: user query + intake, `phase0/lit_table.md`, `phase0/fulltext_cache.json` (all-failed cache → continue with `fulltext_degraded: true`, abstract-level residue confidence), `phase0/lit_results.json`. Output `phase1/phase1_output.json`: `intake` (+`_inferred_fields[]` — missing fields are inferred, never asked), `bottleneck_statement` (≥2 paper_id cited inline), `closest_adjacent[]` (`{paper_id, summary_and_residue}`), `what_phase_0_did_not_address[]`, `state ∈ {proceed, do_not_generate}`.

Routing: **proceed** (literature-groundable, no OOD trigger) or **do_not_generate** (too-broad / no-anchor OOD, <5 truly-relevant papers, genuinely blank space, or benchmark/system construction) → write `do_not_generate.md` with concrete remedial steps — terminal.

### Phase 2 — Selection + generation (ONE isolated context, TWO outputs)

Run 2.1 and 2.2 back-to-back in one isolated context, writing BOTH output files (they are both generation-side; only adversarial pairs need separate calls):

**2.1** — prompt [references/system-prompts/ideate_select.txt](references/system-prompts/ideate_select.txt); inputs `phase1_output.json`, `references/ideation-patterns/overview.md` (all 15 patterns' Definition / Operational signature / When to apply — selection at WHAT/WHEN level), `references/ideation-patterns/companion-combos.md`, `lit_table.md`. Pick the anchor gap (type-bound to `intake.contribution_type`), sample 1-3 sibling gaps randomly + coherence-filter (non-cohering siblings → `deferred_gaps[]`), judge each pattern per gap; record saturation (transparency, not a filter). Output `phase2_select/phase2_select_output.json`: `selected_gaps[]` (index 0 = anchor) + `coherence_thread_type` + `pattern_saturation` + `deferred_gaps[]`. **Retry mode:** when `$RUN_DIR/attempt_1/` exists, the prompt's OPTIONAL retry input applies — the archived audit + selection become negative constraints.

**2.2** — prompt [references/system-prompts/ideate_generate.txt](references/system-prompts/ideate_generate.txt); inputs 2.1 output, `phase1_output.json`, `lit_results.json`, plus for each gap ONE picked sub-pattern card from `references/ideation-sub-patterns/` (compare `when_to_pick_this_one` + `differentiation_within_parent` via its overview.md; then read the picked card's `tactical_pattern` + Step-by-Step). Output `phase2_generate/phase2_generate_output.json` — ONE candidate, 12 flat fields: `title` / `hook` / `core_mechanism` / `core_mechanism_reasoning` / `core_mechanism_steps`; `gap_closure[]` (`{gap, main_pattern, sub_pattern: "C## (parent pattern name)", how_closed}`, mirrors selected_gaps one-for-one); `falsification_prediction` (single paragraph: minimal experiment + metric-with-direction + ONE named load-bearing variable + negative control on that variable predicting the DOWNSTREAM outcome metric returns to baseline — non-tautological); `compute_budget` (user-relative; default intake = 1×A100 × 3 months ≈ 90 A100-day); `differentiation_from_lit[]` (substantive deltas, not "different pattern"); `almost_prior_paper_id` + `what_step_was_missed`; `signature_terms[]` (own vocabulary — recent collision channel); `alias_terms[]` (other communities' names for the same mechanism, from parametric knowledge — multi-year alias collision channel). Both kill-switch fields (`falsification_prediction`, `compute_budget`) are locked from here on — see Phase 3 for the single audited exception.

**Citation gate (deterministic, MANDATORY before Phase 3):**

```bash
python3 "$SKILL_DIR/scripts/run.py" validate --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json
```

Any `fail` = a `sub_pattern` citation was guessed from the parent's gist, not read from `overview.md`. Fix against `references/ideation-sub-patterns/overview.md` (or regenerate 2.2 with the card open) and re-run until clean — the gate proves parent-consistency only; whether core_mechanism performs the cluster's actual tactic is Phase 3.2's `recipe_application_check`. (`next` runs this gate automatically.)

### Phase 3 — Quality gauntlet

**3.1 collision (orchestrator, no LLM):** entry-point table. TWO retrieval channels over all 4 connectors, merged into `collision_hits.json` with a per-hit `collision_channel` tag: **signature** — the candidate's `signature_terms[]` over a 10-month window (contemporaneous scoop risk); **alias** — the candidate's `alias_terms[]` (other communities' names for the same mechanism, produced from parametric knowledge at 2.2) over a 48-month window (renamed-ancestor risk — the "goal-conditioned success detector vs goal-image conditioned scorer" blind spot is lexical, not temporal, so widening the signature window alone cannot catch it). Missing `signature_terms[]` → rc=11 sentinel: produce BOTH term sets per intent-recognition.md Collision mode (terms 3-7 words each — long sentences break URL encoding), edit the candidate JSON, re-invoke. Missing only `alias_terms[]` → loud warning, alias channel skipped (add the field and re-run to close the blind spot).

**3.2 audit (one isolated LLM call):** prompt [references/system-prompts/critique.txt](references/system-prompts/critique.txt); inputs: candidate, 2.1 spec, `lit_table.md`, `collision_hits.json`, `references/anti-patterns.md`, and each cited sub-pattern card `references/ideation-sub-patterns/<C##>.md` (strip the leading code from `sub_pattern`; typically 1-3 cards, others NOT loaded). Five corpus-anchored checks:

| Check | Question |
|---|---|
| gap_closure_reject_check | does the candidate match a documented Reject lesson in each cited sub-pattern card (`## Tactical failure mode` + ALL `### Reject lessons` bullets)? |
| recipe_application_check | does `core_mechanism` actually perform the cited C## cluster's `## Tactical pattern` signature move, or only the parent's generic idea (`bypassed` — the leading cause of incremental output)? |
| anti_pattern_check | if the SET of `gap_closure[].main_pattern` matches a reject-favored composition, is the required mitigation substantively delivered (artifact, not keyword)? |
| paper_pointed_threat | most specific subsuming/competing paper in `lit_table ∪ collision_hits` (both channels; alias-channel threats are NOT discounted for age); `no_threat_found` is valid — fabricating a generic threat is forbidden. Side output `parametric_family_concern`: a named un-retrieved mechanism family from parametric knowledge (family name + query vocabulary, never specific paper cites) — soft signal only, flows to Phase 4 reviewer_concerns as a "scoop-check X first" flag |
| falsification_structure_check | does `falsification_prediction` name the minimal experiment, the outcome metric + direction, ONE load-bearing variable, and a NON-tautological negative control targeting the downstream metric? |

Verdict is two-layer. **Hard floor** (LLM cannot override) → `abandon`: triggered Reject lesson / unmitigatable anti-pattern / exact-mechanism collision. **Soft judgment** otherwise → `advance` (only trivial borderlines; concerns surface in Phase 4's reviewer_concerns) or `revise` with concrete `revision_targets[]` (scopes: `tactical` / `sub_pattern` / `falsification`). `verdict_rationale` must cite specific check findings. The audit judges only — it never modifies the candidate.

**Routing on verdict:**

- **advance** → Phase 4 reads the 2.2 candidate directly.
- **revise** → **3.3** (one isolated LLM call, prompt [references/system-prompts/revise.txt](references/system-prompts/revise.txt)): reads candidate + 2.1 spec + audit; emits patch-only `applied_revisions[]` — one entry per revision_target, ops `replace` / `append_sentence` / `append_items` / `swap_sub_pattern` / `rewrite_falsification`, never echoes the candidate, never re-judges the verdict. Then run the **merger** (entry-point table, WITH `--critique`) → writes `phase3_revise/final_candidate.json` + back-injects it into the patch file. Kill-switch fields are merger-refused with ONE audited exception: a `scope=falsification` target from `falsification_structure_check` is applied via the dedicated `rewrite_falsification` op (authorization verified against the audit report via `--critique`; same experiment/metric/claim, structure repaired; max one per run). When the merger prints `falsification_rewritten`, run the **falsification re-audit** (critique.txt § "Falsification re-audit mode": single check on `final_candidate.json` → `phase3_critique/falsification_reaudit.json`): `advance` → Phase 4; `abandon` → `phase_3_failed.md`. `compute_budget` has no revision route under any scope. No `composition` scope — gap-level changes route through the abandon-retry below, never through patches.
- **abandon** → **one internal retry** (the one-shot guarantee bars asking the user, not internal regeneration): if `$RUN_DIR/.retry_used` is absent, archive the attempt and regenerate —

  ```bash
  mkdir -p "$RUN_DIR/attempt_1" && \
  mv "$RUN_DIR/phase2_select" "$RUN_DIR/phase2_generate" "$RUN_DIR/phase3_collision" \
     "$RUN_DIR/phase3_critique" "$RUN_DIR/phase3_revise" "$RUN_DIR/attempt_1/" 2>/dev/null; \
  touch "$RUN_DIR/.retry_used"
  ```

  then re-run Phase 2 in retry mode (archived audit + selection = negative constraints), citation gate, 3.1, 3.2. Phase 0/1 artifacts are reused as-is. A second `abandon` → write `phase_3_failed.md` citing BOTH attempts' verdict_rationale + triggering checks + user-side options — terminal.

### Phase 4 — Expansion + packaging

Five steps in order (`next` emits each with the correct flags for the advance vs revise path — on the revise path `--candidate` is `final_candidate.json` and `--phase3-revise` is passed; on advance it's the 2.2 output and the flag is omitted):

1. **skeleton** (orchestrator): populates every mechanical field — kill-switch echoes (byte-identical from the candidate), `differentiation_from_lit` venue_years, `almost_prior_venue_year`, `why_prior_stopped[].paper_id/venue_year`, `domain_landscape` (pattern_distribution + candidate_uses), `literature_breakdown`, `reviewer_concerns_and_responses[].attack/severity/fields_changed_to_address` (lifted from audit + patch), `feasibility_validation.compute` (bucketed against `intake.compute`) — and marks every prose field `<TODO[path]: hint>`.
2. **fill** (one isolated LLM call, prompt [references/system-prompts/expand.txt](references/system-prompts/expand.txt)): author ONLY the TODO paths as one flat `{path: value}` map → `phase4/fill_map.json` (~12 prose fields, ~8k tokens vs ~30 fields/~20k without the skeleton). No calendar projections; no experiment matrix / ablation plan / baseline table — the skill produces IDEA + falsifiability + feasibility judgment, not experimental engineering.
3. **assemble** (orchestrator): merges fill_map into skeleton → `phase4_expansion.json`; validates every path resolves to a real TODO; refuses kill-switch roots; warns on unfilled TODOs (expansion_completeness will fail them).
4. **implementability audit (4.1.5, one isolated LLM call, default on):** prompt [references/system-prompts/implementability_audit.txt](references/system-prompts/implementability_audit.txt) — fresh skeptical-engineer persona (separate from the 4.fill author) rewrites each method step into a buildable spec: `enriched_steps[]` (one per step, same ids/order, `what_changes` + `what_to_do_en` + `what_to_do_zh`) + `underspecified_points[]` (`{step_id, hole, fill, severity: filled|open}` — unfillable holes stay honest as `open`). Compute-agnostic by design (resource feasibility is 4.1's job); never adds/removes/renames steps; never carries kill-switch fields. Output `phase4/phase4_implementability.json`.
5. **validate + render:** run the validators (below), then `phase4_render` — templating only, no model call; auto-detects the sibling implementability file and merges `enriched_steps` by step_id into the rendered Method (deterministic; no-op when absent). Writes `idea.std.zh.md` (plain Chinese, domain-newcomer register) + `idea.std.en.md` (plain English) + `idea.detail.en.md` (rigorous English — the novelty + validity defense) + `idea.std.{en,zh}.tex` (auto-compiled to PDF when xelatex/tectonic is on PATH; skipped with a hint otherwise).

**Final response:** read all three markdown cards and return them inline under headings 中文版 / English / Reviewer version. Other phase outputs stay on disk for inspection, not echoed.

## Validators

```bash
# advance path: --phase3 = phase3_critique_output.json; revise path: --phase3 = phase3_revise_output.json
python3 "$SKILL_DIR/scripts/run.py" validate \
  --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json \
  --phase3 <see comment> \
  --phase4 $RUN_DIR/phase4/phase4_expansion.json \
  --phase4-impl $RUN_DIR/phase4/phase4_implementability.json   # optional; enables implementability checks
```

| Validator | Check | Severity |
|---|---|---|
| **subpattern_citation_consistency** | each `gap_closure[].sub_pattern` resolves to a real C## cluster in overview.md whose true parent == the cited `main_pattern` and whose parenthetical == that cluster's parent display name. Primary use: the Phase 2.2 citation gate; re-runs harmlessly here. | fail (hard) |
| **kill_switch_integrity** | `falsification_prediction` + `compute_budget` byte-identical along Phase 2.2 → [3.3 final_candidate →] 4. After an audited falsification rewrite (`falsification_rewritten` marker + matching applied `rewrite_falsification` entry — disagreement fails), the anchor for `falsification_prediction` re-bases at the 3.3 final_candidate (3.3 → 4 must match); `compute_budget` stays full-chain always. | fail (hard) |
| **expansion_completeness** | motivation (≥2 `why_prior_stopped`), `method_flow.steps[]` (each with `linked_component` + `linked_falsification`), `feasibility_validation` (5 sub-verdicts + `overall`), non-empty `abstract_draft` + `core_claim` + `sub_claims[]` — missing sections would render as silent blanks. | fail (hard) |
| **implementability_completeness** | `enriched_steps[]` one-per-step (same ids/order, EN+ZH), `underspecified_points[]` present (`[]` allowed), NO kill-switch field in the file. | fail (hard) |
| **implementability_readability** | std-register fields: no `占位`/`placeholder` leak, no bare English jargon dropped into Chinese prose. | warn |

**Retry budget on `fail` (cap = 2).** Fix only the named contract, re-validate; still failing after the 2nd retry → stop revising, render as-is, and append a short note listing the failing validators (a flagged-imperfect card beats a watchdog-killed run with zero output). Never "fix" `kill_switch_integrity` or `subpattern_citation_consistency` by editing a guarded field — surface them as the headline caveat instead.

## Configuration

By default every model-driven phase runs on the host LLM. To route phases to a different backend (Gemini, open-weights, custom):

- `NOVELTY_LLM_REASONING_LARGE_CMD` — Phase 1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.fill (needs ≥ 200k context, JSON output)
- `NOVELTY_LLM_CLASSIFY_FAST_CMD` — Phase 0 intent extraction + per-paper pattern tagging (smaller context, JSON output)

Each is a CLI taking a stdin prompt (`<<SYSTEM>>...<<USER>>...`) and emitting JSON on stdout. When unset (default for Claude Code), the orchestrator emits sentinel files and the host LLM handles those steps natively.
