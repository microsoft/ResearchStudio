---
name: novelty-skill
description: Generate ONE Oral-level research idea (top ~5% submission tier) from a user's research direction. Diagnoses the bottleneck against retrieved literature, selects 1-3 of 13 induced innovation patterns that structurally fit the bottleneck (with corpus-derived anti-pattern guard), generates a single candidate, runs collision check + critique, and expands into a structured idea card. **One-shot guarantee**: one user input produces one of three outputs — an idea-card PDF, a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons) — never asking the user mid-flow. Use when the user asks for a research idea, novelty analysis, or paper-shape suggestion within a stated direction. Skip for code review, debugging, or pure brainstorming without research context.
---

# novelty-skill

Convert an under-specified research direction into ONE reviewer-defensible Oral-level research proposal — grounded in 1947 ICLR/ICML/NeurIPS papers (2021-2025) — by running a 5-phase workflow that retrieves recent literature, diagnoses the bottleneck, selects + generates a candidate using corpus-derived innovation pattern cards, and runs it through a single quality gauntlet.

## Design principles

1. **Innovation Patterns are diagnostic vocabulary, not classification labels.** The 13 induced innovation patterns (assumption-audit, formal-reframing, analytic-refinement, surgical-fix, evaluation-validity-audit, mechanistic-probing, shared-latent-alignment, invariance-as-architecture, decomposition, auxiliary-signal, redundancy-compression, soft-relaxation, candidate-aggregation) are how the corpus describes productive research moves. Phase 2 reads the innovation pattern cards to ground candidate generation in corpus-validated lessons + anti-patterns; the cards aren't a forced taxonomy candidates must fit into.

2. **Novelty lives in the contribution, not in innovation pattern choice.** Two papers using the same innovation pattern composition on different problems can both be novel. Phase 2.1 selection picks the innovation pattern composition *structurally suited to the bottleneck*; Phase 2.2 generation enforces substantive novelty via `differentiation_from_lit` deltas (what we derive/claim/construct that closest_adjacent did not — not "we use a different innovation pattern").

3. **Theory + Engineering legs are both required, but signature-agnostic.** Both legs must be non-trivial. Each leg can be theorem OR observable regime OR scaling exponent OR measurement primitive OR architectural property — the audit doesn't prefer one Oral signature (theory + reframing-first) over others (scaling-law, empirical-reveal, surgical-fix, benchmark-validity). All Oral shapes the corpus contains can score 5.

4. **Mechanism-aware falsification.** Every candidate carries `failure_a_numerical` (metric doesn't move) distinct from `failure_b_mechanistic` (metric moves but mechanism wrong) plus a `mechanism_probe_proposal` that produces the differential outcome. `compute_budget` is **user-relative** (no absolute cap) — Phase 4 feasibility_validation compares to `intake.compute`.

5. **Anti-pattern is empirical negative knowledge.** The corpus identifies 3 reject-favored 2-way compositions (audit + auxiliary_signal at 30% Oral / audit + invariance at 39% / audit + surgical_fix at 44%); each has a specific required_mitigation. Phase 2.1 flags compositions matching these; Phase 2.2 forces the mitigation into core_mechanism; Phase 3.2 audit's anti_pattern_check verifies substantive delivery (not just keywords).

6. **Cheap kills first, expensive expansion last.** Phase 3 runs collision retrieval (real, ~30s, no LLM) before audit (single LLM call replacing earlier 4-attacker simulation). Heavy expansion of the candidate into motivation + method_flow + claims + abstract happens only in Phase 4, after the candidate clears the gauntlet.

7. **Phase 3.2 is judgment, not modification.** The audit reports what corpus evidence triggered which signals; it does NOT auto-revise the candidate. Auto-revise was removed because LLM tends to cherry-pick attacks it can already answer (self-answering bias). When revision is needed, the audit emits `revision_targets[]` and the user re-runs Phase 2.2 with that guidance.

## When to use

- "Give me a research idea in {area} I could pursue."
- "What's the most impactful next step in this direction?"
- "Help me sharpen this vague direction into an Oral-level proposal."
- "What's the bottleneck of this problem?"
- "Run a novelty audit on this idea."

## When NOT to use

- Code review, debugging, refactoring (use a coding skill).
- Summarizing one paper.
- Cross-decade survey writing.
- Free-association brainstorming with no research context.
- Engineering integration tasks ("ship this feature in our system").
- Pure benchmark / dataset construction work — current 13-innovation pattern vocabulary handles benchmark *audit* (lens 6) but not benchmark *construction*.

## The 5-phase workflow

```
Run progress:
- [ ] Phase 0: Literature grounding (sub-skill, role-based retrieval) → lit_table.md
- [ ] Phase 1: Bottleneck identification (single LLM call) → bottleneck statement + closest_adjacent
- [ ] Phase 2: Idea generation (2 LLM calls — innovation pattern selection + candidate generation w/ signature_terms)
- [ ] Phase 3: Quality gauntlet (retrieval + audit + revise-when-needed)
- [ ] Phase 4: Expansion + packaging (motivation + method_flow + claim matrix + abstract → PDF)
```

Three outcomes per run: an idea-card PDF (advance OR revise→3.3 path), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons). The user gets one of these three from one input — no mid-flow clarification. **One-shot guarantee preserved** even when audit triggers revise: Phase 3.3 mechanically applies the revision_targets and Phase 4 proceeds without user re-invocation.

### How phases run (orchestrator vs. host LLM)

Two phases need real external retrieval and run via `scripts/run.py`:

| Phase | Entry point | Why orchestrator |
|---|---|---|
| Phase 0 (literature grounding) | `python -m scripts.run phase0 ...` | probes 4 connectors, runs role-based retrieval, dedups |
| Phase 3.1 (collision check) | `python -m scripts.run phase3_collision ...` | re-uses connectors with the candidate's signature_terms |
| Phase 4.2 (PDF rendering) | `python -m scripts.run phase4_render ...` | templating, no model call |
| Validators | `python -m scripts.run validate ...` | static contract checks |

The remaining phases — **Phase 1 bottleneck identification, Phase 2.1 innovation pattern selection, Phase 2.2 candidate generation, Phase 3.2 critique-and-revise, Phase 4.1 expansion** — are LLM-driven and run *manually* by the host LLM (or user) reading the corresponding system prompt under `references/system-prompts/`, providing the listed inputs, and writing the JSON output to the conventional `outputs/<phase>/...` location. There is no orchestrator subcommand for these because adding one would just be a thin `cat <prompt> + <inputs> | llm` wrapper — no validation work happens between input assembly and the LLM call. Wrapping it in Bash would add fragility (env vars, CLI shape, JSON post-processing) without buying determinism.

The convention each manual phase follows: read the prompt at `references/system-prompts/<phase>.txt`, gather inputs listed at the top of the prompt, produce the JSON described under `Output:`, save it to `outputs/<phase>/<phase>_output.json`. Downstream phases read that filename.

### CRITICAL: Literature grounding mode

Phase 0 and Phase 3.1 collision require **real external retrieval** via the `novelty-lit-search` sub-skill. Two states (simplified from earlier 4-state design): `lit_grounding_mode = real` (any connector worked, including webfallback with per-paper retrieved_via tagging) vs `connector_failure` (no connector, no fallback flag — orchestrator halts with diagnostic). Without at least one working connector, the skill halts cleanly rather than degrading silently.

In Claude Code: install both `novelty-skill` and `novelty-lit-search` before invoking.

---

### Phase 0 — Literature Grounding

Phase 0 runs via a single Bash command — the orchestrator at `scripts/run.py`. This physically narrows tool choice to one path; alternative paths (WebSearch, ad-hoc fetch) produce unstructured output that downstream phases reject.

```bash
python -m scripts.run phase0 --query "<user's research question>" --out outputs/phase0/
```

**What the orchestrator does internally**:

1. Asserts system clock is sane (≥ 2024-01, ≤ 2027-01).
2. Intent extraction: turn the user's free-text query into 3-5 search queries. Without an external LLM CLI configured, emits `.intent_extraction_pending` sentinel and exits — the host LLM produces queries per `intent-recognition.md`, then re-invokes with `--queries "q1|q2|q3"`.
3. Probes 4 connectors (arXiv, DBLP, OpenAlex, OpenReview) and reports availability.
4. **Role-based retrieval** (each connector used where it's most informative):

   | Connector | Window | Cap | Role |
   |---|---|---|---|
   | arxiv | 0-4 mo | 10 | preprint pool — recent active work (sortBy=relevance) |
   | dblp | 4-24 mo | 15 | top-venue conference index (`--venues` configurable for non-ML/AI fields) |
   | openalex | 4-24 mo | 15 | published proceedings + journals (`--published-only`) |
   | openreview | 0-6 mo | 10 | in-review submissions (forward signal); venues runtime-derived from review cycles |

   Target: ~30-40 papers. Gracefully degrades to ~20-30 if openreview unavailable. Windows are non-overlapping (0-4mo arxiv vs 4-24mo dblp+openalex), so a paper that's both a recent preprint and an older published proceedings doesn't double-count.
5. Dedups across sources with file-order priority (dblp > openalex > openreview > arxiv).
6. **pattern_summary** (LLM step) tags each paper with innovation pattern + bottleneck + open_issue + retrieved_via, producing `lit_table.md`. Without an external LLM CLI, emits `.pattern_summary_pending` sentinel for the host LLM to fill.
7. Writes one gate sentinel: `.lit_grounding_mode = real`.

**Host-LLM handshake** (when `NOVELTY_LLM_CLASSIFY_FAST_CMD` is unset — typical when running inside a host LLM): the orchestrator emits sentinel files in a common schema rather than silently substituting model knowledge. Three sentinel sites in Phase 0 + 3.1:

| Sentinel | Trigger | Host LLM action |
|---|---|---|
| `.intent_extraction_pending` | rc=10, no `--queries` and no LLM env | Read intent-recognition.md (Map mode), produce queries, re-invoke `phase0 --queries "q1\|q2\|q3"` |
| `.pattern_summary_pending` | informational | Read pattern-summary-rubric.md, classify each paper into 1-3 of the 13 innovation patterns, write lit_table.md |
| `.signature_extraction_pending` | rc=11 in Phase 3.1 | Read intent-recognition.md (Collision mode), produce 3-5 signature_terms, re-invoke phase3_collision |
| `.collision_classify_pending` | informational | Read collision-rubric.md, classify hits into 7-class taxonomy, write collision_report.json |

`lit_table.md` schema (consumed by Phase 1):

```markdown
| paper_id | year_month | venue | title | innovation pattern tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem | retrieved_via |
```

---

### Phase 1 — Bottleneck Identification

Single LLM call. Use [references/system-prompts/bottleneck_identify.txt](references/system-prompts/bottleneck_identify.txt).

The earlier design ran 13 separate lens probes here, each scoring 0-3 sharpness with persistence × activity caps. That structure was removed because its mechanical complexity (rule + LLM hybrid scoring, cross-lens consistency Jaccard checks) added drift more than signal. Phase 1 now does one substantive thing: read user query + lit_table.md + intake, write a literature-grounded bottleneck statement plus the routing decision.

**Inputs**: user query, intake context, `outputs/phase0/lit_table.md`, `outputs/phase0/lit_results.json` (for abstract-level grounding when needed).

**Output schema**: see `bottleneck_identify.txt`. Key fields:
- `intake` (with `_inferred_fields[]` listing fields not stated by user)
- `bottleneck_statement` — one paragraph citing ≥ 2 paper_id from lit_table inline
- `closest_adjacent[]` — list of `{paper_id, what_they_did, where_they_stopped}`
- `what_phase_0_did_not_address[]`
- `state ∈ {proceed, do_not_generate}`

**No-ask guarantee**: missing intake fields are inferred from user query + Phase 0 retrieval; if hopelessly missing, route to `do_not_generate` with concrete remedial_steps rather than asking.

**Routing**:
- **proceed** — bottleneck is literature-groundable AND no OOD trigger fires
- **do_not_generate** — OOD (too broad / no anchor / engineering integration / no verifiable benchmark / venue-time mismatch / unobtainable resources) OR lit_table too sparse (< 5 truly-relevant papers) OR genuinely blank-space (no adjacent literature) OR benchmark/system construction (current vocab doesn't cover) → emit `do_not_generate.md` with redirect

---

### Phase 2 — Idea Generation (2 LLM calls)

#### Step 2.1 — Innovation Pattern selection

Use [references/system-prompts/ideate_select.txt](references/system-prompts/ideate_select.txt).

**Inputs**: Phase 1 output, `references/innovation-patterns/overview.md` (selection-friendly summaries of all 13 innovation patterns — when to apply / Oral signal / Reject warnings / anti-pattern flags), `references/anti-patterns.md` (3 corpus-validated reject-favored compositions with required_mitigations).

**Output**: ranked top 3 innovation pattern compositions, each with:
- `primary_methodology` + `secondary_methodologies[]` (1-3 of the 13 IDs)
- `structural_fit_rationale` — why this composition fits the bottleneck *structure*; NOT "closest_adjacent hasn't used it"
- `anti_pattern_check` — `{matches, matched_pattern, required_mitigation}`
- `delta_potential` — where the substantive novelty in Phase 2.2 will come from

Plus `winning_composition_rank` + `winning_rationale`.

**Selection is structural, not novelty-shopping.** Two papers can use the same innovation pattern composition on different problems and both be novel; this step picks composition by *fit to bottleneck structure*, not by "what closest_adjacent hasn't done". Novelty is checked at generation (substantive deltas) and critique (strongest reviewer attack).

#### Step 2.2 — Candidate generation

Use [references/system-prompts/ideate_generate.txt](references/system-prompts/ideate_generate.txt).

**Inputs**: winning composition from 2.1, **full innovation pattern card** for each innovation pattern in winning_composition (1-3 cards from `references/innovation-patterns/<id>.md`), **sub-pattern cards** under the primary pattern (3-4 cards from `references/innovation-sub-patterns/`), `closest_adjacent` abstracts from Phase 0 lit_results.json, anti-pattern required_mitigation if applicable.

**Output**: ONE candidate. Key fields:
- title / hook / problem
- pattern_composition (echo from winning_composition)
- sub_pattern_id + 3-field sub_pattern_rationale (or outside_taxonomy=true)
- core_mechanism (3-5 sentences; if anti-pattern matched, MUST include required_mitigation)
- theoretical_leg + engineering_leg
- differentiation_from_lit[] — each delta describes substantive contribution difference, NOT innovation pattern choice difference (≥ 1 paper_id from closest_adjacent)
- falsification_prediction (what_we_run / success / failure_a_numerical / failure_b_mechanistic / compute_budget / decision_rule)
- mechanism_probe_proposal (distinguishes failure_a from failure_b)
- R0_case (novelty_case + almost_prior — substantive forms accepted: theorem, observable regime, measurement primitive, architectural property, scaling exponent)
- is_reframing_contribution (descriptive flag)

**K=1, not K=2/3.** Earlier design generated K=3 then K=2 candidates with anchor diversity. Removed because the alternate candidates were never auto-selected on Phase 3 escalation (now removed) and K=N added LLM-call overhead without clear quality wins. Single candidate goes through critique.

---

### Phase 3 — Quality Gauntlet (1 retrieval + 1-2 LLM calls)

#### Step 3.1 — Mechanism-specific collision retrieval

Run via the orchestrator:

```bash
python -m scripts.run phase3_collision --idea-json outputs/phase2_generate/phase2_generate_output.json --out outputs/phase3_collision/
```

Orchestrator probes arXiv / OpenAlex / OpenReview (DBLP skipped — its 4-24mo window doesn't overlap collision's 0-6mo focus), runs each available connector with a 6-month window using the candidate's `signature_terms[]`, dedups across sources, writes `collision_hits.json`.

If candidate lacks `signature_terms[]`, orchestrator emits `.signature_extraction_pending` sentinel — host LLM produces 3-5 terms per intent-recognition.md Collision mode rubric, edits the candidate JSON, re-invokes. (After the Phase 2.2 schema added `signature_terms[]` natively, this sentinel rarely fires.)

**No 7-class classification step.** Earlier design ran a separate LLM call to classify each hit into 7 categories (exact / mechanism / claim / evaluation / terminology / weak-transfer / non-blocking) and emitted a collision_report.verdict {pass / regenerate / narrow_claim}. This was removed because Phase 3.2's paper-pointed threat search already does the substantive subsumption judgment over `lit_table.md ∪ collision_hits.json`. Pre-classifying duplicated that work and added a second verdict layer (collision_report.verdict vs critique.verdict) that produced noise without signal.

3.1's sole job now: **expand the paper pool that 3.2 will search** with mechanism-specific recent retrieval that Phase 0's broad-domain queries miss.

#### Step 3.2 — Audit-and-Verdict (3 corpus-anchored steps)

Single LLM call. Use [references/system-prompts/critique.txt](references/system-prompts/critique.txt).

Phase 3.2 produces an audit report with three corpus-anchored checks. It does **NOT** auto-revise the candidate — earlier design's automatic revision step was removed because LLM tends to cherry-pick attacks it can already answer (self-answering bias). Instead, when revision is needed, Phase 3.2 emits `revision_targets[]` and Phase 3.3 mechanically applies the fix.

The three checks each anchor on specific corpus content the LLM cannot fabricate:

| Step | Corpus anchor | Question |
|---|---|---|
| **1. composition_reject_check** | composition-scoped reads, one card per innovation pattern role: `innovation-sub-patterns/<candidate.sub_pattern_id>.md` for primary + `innovation-patterns/<id>.md` for each secondary. Total reads = composition_size. Other tactical cards and other innovation pattern cards are NOT loaded. | For each role in the composition, does the candidate fall into the Reject patterns documented at the role's granularity? Aggregate verdict is the worst across primary + all secondaries. |
| **2. anti_pattern_check** | `references/anti-patterns.md` — 3 reject-favored compositions with required mitigations | If the composition matches an anti-pattern, is the mitigation **substantively delivered** in core_mechanism / theoretical_leg (not just keyword-present)? |
| **3. paper_pointed_threat** | `lit_table.md ∪ collision_hits.json` (unified pool) | Most specific paper subsuming or competing with the candidate's claim. `no_threat_found` is a valid clearance signal — fabricating a generic threat is forbidden. |

(Earlier design had a 4th check `almost_prior_factcheck` cross-referencing `R0_case.almost_prior` against lit_table. Removed: low fire rate (almost_prior is generated by Phase 2.2 LLM that already has lit_table access), and refuted cases would also surface in paper_pointed_threat. Hallucinated paper_ids are now caught upstream by Phase 2.2 prompt rules.)

**Verdict is two-layer**: hard floor (mechanical, LLM cannot override) + soft judgment (LLM weighs within safe zone):

- **Layer 1 hard floor** — `abandon` if any of: composition_reject_check=triggered (documented Reject pattern matches) / anti_pattern unmitigated-and-uninsertable / exact-mechanism collision. These are corpus-anchored facts; LLM has no override authority.
- **Layer 2 soft judgment** — when hard floor didn't fire, LLM picks `advance` or `revise` by weighing how severe each borderline/partial finding is. Trivial borderlines (non-load-bearing fields) → advance with concern surfaced for Phase 4 to fold into reviewer_concerns_and_responses. Borderlines hitting load-bearing structural properties (e.g., a innovation pattern's success condition) → revise with concrete revision_targets[]. LLM can also demote clear→revise if holistic reading reveals a concern individual checks missed.

The `verdict_rationale` must cite specific check findings (lesson_quoted / failure_mode_quoted / sub-block verdict). "All checks pass" without naming which is a process error.

Why two-layer: pure mechanical aggregation over-triggers revise (treats 1 trivial borderline same as 3 severe). Pure LLM verdict introduces agreeable-bias and loses audit trail. Hard floor preserves non-negotiable corpus facts; soft layer uses context to distinguish "must fix" from "noted concern, advance".

Routing on verdict:
- **advance** → Phase 4 reads Phase 2.2 candidate directly.
- **revise** → Phase 3.3 (single LLM call) applies revision_targets[] → Phase 4 reads Phase 3.3 final_candidate.
- **abandon** → orchestrator emits `phase_3_failed.md` with verdict_rationale + triggering check. No automatic retry.

#### Step 3.3 — Apply Revision Targets (only when 3.2 verdict = revise)

Single LLM call. Use [references/system-prompts/revise.txt](references/system-prompts/revise.txt).

Phase 3.3 reads Phase 2.2 candidate + Phase 3.2's revision_targets[] and emits `final_candidate` with ONLY the named fields modified, kill-switch byte-identical preserved. It does not re-judge the audit's verdict and does not propose new attacks — it mechanically applies the corpus-grounded fix instructions.

This step is **structurally different from earlier auto-revise** (which was deleted for self-answering bias):
- Earlier auto-revise: same LLM call wrote attack AND fixed it (LLM picks attacks it can answer).
- Phase 3.3 revise: SEPARATE LLM call from 3.2 audit. Audit identifies issues from corpus checks, NOT LLM intuition. Revise applies them mechanically. No LLM is both proposing AND answering an attack.

**Output schema** (`outputs/phase3_revise/phase3_revise_output.json`):
```json
{
  "candidate_id": "...",
  "applied_revisions": [
    {"field": "theoretical_leg", "issue_addressed": "...", "fix_direction_quoted": "...",
     "what_changed": "...", "before_excerpt": "...", "after_excerpt": "...",
     "outcome": "applied | skipped_already_satisfied | skipped_anti_substitution | skipped_inapplicable"}
  ],
  "final_candidate": { /* full Phase 2.2 schema, only named fields modified */ }
}
```

**Hard rules** (enforced in revise.txt):
- Modify ONLY fields named in `revision_targets[].field`
- Kill-switch fields NEVER modified (V1 enforces)
- Apply fix_direction faithfully, do not re-interpret
- Do not re-judge audit verdict
- Out-of-scope rewrites (e.g. "change innovation pattern composition") → `outcome = skipped_inapplicable` (will route to re_select in a future iteration)

**Anti-substitution chain**: kill_switch_integrity validator handles both routings:
- 3.2=advance, no 3.3: Phase 2.2 → Phase 4 directly (Phase 3 passthrough)
- 3.2=revise, 3.3 ran: Phase 2.2 → Phase 3.3 final_candidate → Phase 4 (3-link chain). All three byte-identical for kill-switch fields.

---

### Phase 4 — Expansion + Packaging

#### Step 4.1 — Expansion

Single LLM call. Use [references/system-prompts/expand.txt](references/system-prompts/expand.txt).

**Inputs**: Phase 3.2 `final_candidate` (canonical source), Phase 3.2 `strongest_attack` + `revision_summary`, Phase 3.1 collision_report, Phase 1 bottleneck + closest_adjacent + intake, Phase 0 lit_table + lit_results (for citing in motivation.why_now and motivation.why_prior_stopped).

**Output**: Idea-card PDF content. Key blocks:
- `motivation` (problem_framing / why_now / why_prior_stopped[] / what_changes_when_gap_closes)
- `core_claim` + `sub_claims[]`
- `method_flow` (high_level_pipeline / numbered steps[] with linked_component + linked_falsification / preservation_argument)
- `theorem_or_algorithm_or_system_design`
- `theoretical_leg` + `engineering_leg` (echoed)
- `falsification_prediction` (echoed VERBATIM — anti-substitution)
- `mechanism_probe_proposal` (echoed VERBATIM — anti-substitution)
- `feasibility_validation` (5 sub-checks: compute / data / theoretical / engineering / falsification + overall, all user-relative)
- `differentiation_from_lit` (echoed)
- `reviewer_concerns_and_responses[]` — single entry from Phase 3.2 strongest_attack (not 4-attacker breakdown)

**Echo vs reference policy**: anti-substitution-guarded fields are echoed (kill-switch + theoretical_leg + engineering_leg + differentiation_from_lit). Other Phase 0 / 1 / 3 content is read directly by PDF templating (closest_adjacent, collision_report, lit_grounding_mode sentinel) — not duplicated into Phase 4 output.

**No calendar projections.** Sequencing in dependencies, not weeks. **No experiment matrix / ablation plan / baseline table / expected figures.** Skill produces IDEA + falsifiability + feasibility judgment; experimental engineering is the user's responsibility.

#### Step 4.2 — PDF rendering

Templating only, no model call. Idea-card template at `references/templates/idea_card.tex.j2` — earlier tiered fallback templates were removed when Phase 3 escalation was deleted (failure now → `phase_3_failed.md`, not a degraded PDF).

```bash
python -m scripts.run phase4_render \
  --expansion outputs/phase4/phase4_expansion.json \
  --out outputs/phase4/
```

Each successful run writes:
- `idea_<timestamp>.pdf` (compiled via tectonic)
- `idea_<timestamp>.tex` (intermediate, kept for diagnostics)

Failed runs write `do_not_generate.md` (Phase 1 OOD) or `phase_3_failed.md` (Phase 3 abandon) with concrete remedial steps.

---

## Validators

Run after Phase 4 to verify the contracts the prompts assert:

```bash
# When Phase 3.2 verdict = advance (no Phase 3.3 ran)
python -m scripts.run validate \
  --phase2 outputs/phase2_generate/phase2_generate_output.json \
  --phase3 outputs/phase3_critique/phase3_critique_output.json \
  --phase4 outputs/phase4/phase4_expansion.json

# When Phase 3.2 verdict = revise (Phase 3.3 produced final_candidate)
python -m scripts.run validate \
  --phase2 outputs/phase2_generate/phase2_generate_output.json \
  --phase3 outputs/phase3_revise/phase3_revise_output.json \
  --phase4 outputs/phase4/phase4_expansion.json
```

| Validator | Check | Severity |
|---|---|---|
| **kill_switch_integrity** | `falsification_prediction.what_we_run`, `falsification_prediction.compute_budget`, `mechanism_probe_proposal` byte-identical Phase 2.2 → Phase 4 (Phase 3.2 passthrough on advance path) or Phase 2.2 → Phase 3.3 final_candidate → Phase 4 (revise path). | fail (hard) |
| **expansion_completeness** | Phase 4 expansion has the structural sections downstream PDF rendering needs: motivation (with ≥ 2 `why_prior_stopped` entries), `method_flow.steps[]` (each with `linked_component` + `linked_falsification`), `feasibility_validation` (5 sub-verdicts + `overall`), non-empty `abstract_draft` + `core_claim` + `sub_claims[]`. | warn (soft — schema deviation flagged not blocked) |

Removed validators:
- `V_anti_pattern` (keyword detection for anti-pattern mitigation) — superseded by Phase 3.2 audit's `anti_pattern_check.mitigation_substantively_delivered` which judges at semantic not keyword level. Keyword version was redundant given the audit's deeper check.
- `V2` / `V3` / `V4` (composition primary / evidence chain / anchor diversity Jaccard) — Phase 2 schema simplifications rendered them trivially satisfied or directly enforced in prompts.

---

## Configuration

`config.yaml`:
- `default_backend: host_llm` — every model-driven phase uses the host LLM by default
- `profiles.{REASONING_LARGE, REASONING_FAST, CLASSIFY_FAST}.backend` — leave empty to inherit `host_llm`; specify only when overriding

The skill specifies *capability profiles*, not model names. Five profiles: `[REASONING_LARGE]` for Phase 1, 2.1, 2.2, 3.2, 4.1 (need ≥ 200k context, JSON output); `[CLASSIFY_FAST]` for sub-skill intent + classification; `[EMBEDDING]` for sub-skill collision-mode embedding cosine. The skill runs identically on Claude / GPT / Gemini / open-weights LLMs that expose JSON-mode.
