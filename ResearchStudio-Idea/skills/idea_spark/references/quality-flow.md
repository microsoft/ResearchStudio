# Quality flow: interfaces, gates and states

This is a research-proposal workflow, not a certificate of novelty, efficacy or
mathematical truth.

## Commands and artifacts

A run starts in an empty directory:

```text
run.py next --dir ABSOLUTE_NEW_RUN
run.py quality_init --dir ABSOLUTE_NEW_RUN
run.py next --dir ABSOLUTE_NEW_RUN --query "direction"
```

Follow each complete emitted action. next does not create directories, edit candidates,
re-seal artifacts or issue model/network calls. Phase 0/1 retain their retrieval runbook.

| Interface | Contract |
|---|---|
| run_contract.json | contract_version=2, immutable run identity, attempt counter, proposal boundary |
| .quality/STAGE/request.json | UUID request_id; exact inputs/prompts/output paths; content hashes before call; canonical JSON digests |
| .quality/STAGE/result.json | request_id plus artifacts mapping from exact requested relative path to JSON object |
| quality_record | rejects wrong/stale requests, changed inputs/prompts, concurrent output changes, extra/missing outputs or non-object payloads |
| .quality/STAGE/receipt.json | input/prompt hashes plus output hashes; written last as commit marker |
| quality_materialize | explicit deterministic coherence/revision/skeleton/technical/final derivation; records hashes of inputs and implementation |
| quality_collision | existing dual-channel retrieval wrapper; records completed retrieval; never called by offline tests |
| quality_retry | audited abandon/redesign only; archives failed attempt recoverably; reuses information-gain and cycle caps |
| quality_publish | re-evaluates all gates, then validators, then rendering; --no-pdf records skipped status |

Phase 4 layout: `phase4/` holds only the deliverables (idea.std.en/zh .md and .pdf,
idea.detail.en.md). Every intermediate — skeleton, mechanism_record, fill_map,
technical_expansion, implementability, technical_repairs, repaired_technical, technical_review,
cost_assessment(_revised), derive_map, phase4_expansion, fidelity files, render_status, and the
.tex/.aux/.log build files — lives in `phase4/work/`. The std cards carry Title, Motivation and
Method (module headings from `module_title`); the detail card adds research status, main
contribution, falsification, resources and open questions.

Record handshake, two additions. (1) A large artifact may be written in parts —
`.quality/STAGE/result.parts/NN.json`, each `{"artifacts": {path: {some top-level fields}}}` —
and `quality_record` merges them in name order into result.json (a single 88 KB write stalled the
author twice; four smaller writes did not). (2) `quality_record` REJECTS a result that breaks a rule
the author can fix in the result itself, without a needs_work: the request stays open, `next`
re-emits the same step with the findings, and the fixed result is recorded against the same
request_id. The third result on one request is committed with the findings kept as warns. Rules:
plain_derive — the Chinese word-order rule (no more than 18 characters before 的 without a break);
generation — every Phase 1 collateral family is queried by an alias term or named in
`composition_note` as unreachable.

Prior requests/results/outputs remain recoverable in stage histories. Multi-output
recording validates the batch first; an I/O interruption can leave provisional files
but never a receipt or publishable candidate. Fresh preparation is required after such
an interruption. This is a local provenance ledger, not a tamper-proof security boundary.

## Selection and candidate additions

selected_gaps has one anchor and zero to two siblings. Each present sibling or companion
has sibling_dependency / companion_dependency:

```json
{"object":"O","producer":"operation that creates O","consumer":"operation that uses O",
 "removal_effect":"capability lost","usage":"training | inference | proof | evaluation_only"}
```

The program checks declaration completeness. For method + evaluation_only it warns and
the semantic audit decides whether a contribution component must move to evaluation.
Both empirical_reveal (existing enum) and the prose spelling empirical-reveal refer to
diagnostic discovery. Theory dependencies may be definitions, lemmas or proof objects.
Historical companions never impose an allowlist and draw no warning.
HARD RULE: on a `method` anchor, `controlled_diagnostic_design` as a sibling or companion, or
any component declaring usage = evaluation_only, is a `fail` (`measurement_component`),
whatever `usage` was declared. The measurement belongs in falsification_prediction. The
generation stage gets ONE bounded `REGENERATE` (`quality_materialize --operation
generation_retry`): the failed round is archived, the findings are written to
phase2_generate/selection_findings.json as an input, and the second rejection is terminal.
Evidence: 228/793 archive selections; paired A/B where the soft object/producer/consumer test
left the diagnostic in 3/5 selections, each self-declared "training"/"inference".
No pattern minimum is imposed.

gap_closure sub_pattern is either a real parent-consistent C## citation or null/empty
with sub_pattern_not_applicable_reason. Citation checking does not establish applicability.
composition_note is optional even for one pattern. Existing fields/file names remain.

## Patch schema

The patch contains contract_version=2, base_candidate_sha256 and applied_revisions.
Every operation uses target_id from critique.revision_targets and an explicit outcome:
applied, skipped_already_satisfied, skipped_requires_redesign, or skipped_invalid_request.
Skipped dispositions need delta_summary evidence. One target can have multiple operations.
Supported operations remain replace, append_sentence, append_items, swap_sub_pattern and
authorized rewrite_falsification. Invalid paths/targets, missing targets, protected edits
and contribution/pattern rebinding refuse the whole patch before final publication.

The raw patch is not back-written. merged_revision.json retains the merge-record
final_candidate, rewritten-falsification marker, changed-field scope and before/after
field word counts. No 15% length cap is used. Repeated exact sentences warn.

## Invalidation and independent review

| Change | Required recheck |
|---|---|
| Title/explanation wording | Presentation and contribution fidelity |
| Mechanism/reasoning/steps/gap closure/falsification | Dataflow, concrete dry run, degenerate cases, claim map, falsification, novelty (cost is arithmetic at implementability: `compute_budget` is immutable to revision, so a post-revision cost verdict could never be acted on) |
| Signature/alias terms or novelty delta | Reconfirm terms and relevant prior-art threats; refresh retrieval when confirmed terms differ |
| Authorized falsification rewrite | `falsification` check inside the post-revision review |
| Technical expansion | Implementation/technical review, plain derivative, fidelity, rendering |
| Prompts or recorded inputs | Their dependent stage receipts no longer apply |

Core change requires novelty judgment even when terms match. Post-revision review also
checks target_resolution; it cannot silently clear a reviser's disputed repair request.
Review report: verdict=pass|needs_work|redesign, checks keyed by required scope; each has
status=pass|conditional|n_a|fail and concrete evidence. Conditional claims are explicitly
conditional, not proved; n_a needs a reason. A failed required check blocks publication; a
verdict of needs_work with no failing check is recorded as a warning, not a block (the
reviewer's own pass definition is "satisfied or appropriately conditional").

Candidate cycles remain bounded to three under one framing, with at most one further
bottleneck retry. Source-omission repair is one pass. Failed semantic/fidelity reviews
preserve needs_work and identify the exact change needed; they never launch open-ended
rewriting. A new user-authorized correction re-enters gates on changed inputs.

## The gate reports; the author writes

The coherence gate never edits the candidate. Its wording and definition fixes (an unbound
parameter, a step text that mismatches its formula, a claim graded overclaim) are
`suggested_repairs[]`, materialized as W1, W2, ... next to the blocking B# findings; a report that
carries `applied_revisions` is refused. The author's formula-repair round applies each W# or keeps
the text with its premise stated (`skipped_author_keeps`). A round with W# only writes
`refined_candidate.json` (receipt `wording_materialize`) and does not re-run the trace; a round with
B# writes `repaired_candidate.json` and the trace re-executes. T5 runs BOTH the tracer's own naive
(decides the verdict) and the candidate's declared naive (reported beside it), so a verdict that
depends on which naive was built is visible. `structural_requirement` carries executed facts and
salvage only — never capability requirements for the next candidate.

## Impossibility, regime, and what T5 may decide

A blocking coherence finding is kept only as `impossibility` — the written procedure cannot compute
what it claims on any legal input — with its derivation. `regime` findings (the procedure computes
but degrades on a constructed input family) are recorded in `blocking_findings.json.regime`, carried
into `mechanism_record.regime_notes` and the card's limitations, and may become a revise target;
they never block. T5 `equivalent_to_naive` blocks only when the tracer's naive is an ABLATION of
the mechanism with bit-identical executed output ("component X is inert"); against a constructed
alternative design it is a `t5_notes` entry (its verdict flipped in 4 of 6 consecutive traces of
one candidate). Each candidate declares its `intervention_object` (acts_on, operator,
decision_variables); a retry whose acts_on and operator repeat an archived cycle is refused by the
generation gate before any call is spent. Abandon reasons and `structural_requirement` carry
executed facts and salvage only, never directives for the next candidate.

## Formula repair loop

An executed blocking finding from the coherence gate no longer decides the run at first sight.
The gate's dry run executes the candidate's OWN rules (estimator, composition rule, test, update,
budget arithmetic) with the candidate's constants on synthetic inputs; it never simulates a learned
component (no toy backbones, no training loops) — whatever needs a model to decide is a premise for
the falsification experiment. A blocking entry is kept only when the tracer tags it `structural` and
supplies a `derivation` (the materializer enforces this; the rest become `demoted_to_notes`).

Wording suggestions alone (W#, no blocking finding) never buy a call: they are handed to the revision
stage as advisory input (`blocking_findings.json` `suggested_repairs`), where the reviser applies each
or states the premise that keeps the text. Blocking findings go to the AUTHOR (`formula_repair.txt`, stage `formula_repair`): repair the
formula — definition, normalisation, index, initial condition, unit — with target_id = finding id,
and attach the tracer's script re-run against the repaired rule (`rerun.script` + `rerun.output`).
The merger (`quality_materialize --operation formula_repair`) applies the patch to
`phase2_coherence/repaired_candidate.json`, archives the round under `phase2_coherence/round_<n>/`
and `repair_rounds.json`, and a FRESH coherence trace re-executes the repaired candidate. The loop
ends when the findings clear; when a repaired finding PERSISTS in the re-trace (the trace receives the
prior round's finding ids in `previous_findings.json` and reports each `resolved | persists`; the count
rule is the fallback); when the author declares `changes_object` / `stop: object` (the only fix replaces
the intervention object — a new idea, not a repair; `.formula_repair_stop`); or at
`IDEASPARK_REPAIR_ROUNDS` (default 3). A patch that removes a claim or touches a kill-switch field
is refused; a patch that breaks the contract gets one REREPAIR. What survives goes to the audit with
`repair_rounds.json` as an input, and the hard floor fires only on findings that survived the rounds
or were declared object-level. Each round costs two reasoning-tier calls (repair + trace).

## Phase 4 falsification revision, and the failed-validation card

Two exits that used to be dead ends.

(1) The technical review may find that the DECLARED experiment is infeasible under corrected arithmetic
(a cell, sample size, window or threshold the falsification paragraph names cannot deliver the verdict it
promises) while a bounded change of the experiment — same minimal experiment, metric and load-bearing
variable — would make it feasible. It then sets `route: falsification_revision` with `revision_targets`
(scope falsification). The flow (`quality_materialize --operation phase4_revision`, once per run) hands
those targets to the audited revision transaction as `phase3_revise/post_revision_findings.json` with
source `technical_review` (the merger accepts a `rewrite_falsification` authorized this way), archives
the Phase 4 stages under `.quality/phase4_revision_history/` and keeps the technical text under
`phase4/work/before_falsification_revision/` as reference for the next fill. Post-revision review runs
with the `falsification` check (this fresh transaction carries its own single re-revision), then Phase 4 re-runs on the revised candidate. Cost: revision,
post-revision review, fill, implementability, and repair/review as needed. A mechanism defect never
takes this route; that is needs_work.

(2) A run whose validation ends in failure — `phase_3_failed` (audit abandons to the cap or without
information gain) or a Phase 4 needs_work (technical review, second fidelity failure, publish
validation) — still prints its LAST candidate as a card that says so (`IDEASPARK_FAILED_CARD=off`
restores the refusal). `quality_materialize --operation failed_card` records where and why in
`phase4/work/failed_card.json` (the last candidate: final_candidate when a revision merged, else the
canonical one), and `next` drives the card stages the candidate has not run yet (fill,
implementability, plain derivation) with every gate a no-op and no new repair/review call. The
expansion carries `proposal_status: FAILED VALIDATION (stage) — reason` and `validation_failures`; the
std cards show a Status line under the title, the detail card lists the failures under Research
status; publish records validator fails instead of refusing. An execution-contract needs_work (a
broken record, a merge error) stays terminal: it is a host problem, not a validation verdict.

## Depth: idea (default) and experiment

`run_contract.json` records `depth` at init from `IDEASPARK_DEPTH` (`idea` unless `experiment`); a contract
without the field was audited in full and reads `experiment`. Depth never changes midway.

In BOTH depths the candidate states named VARIABLES with a selection rule or admissible range, not
constants: a default value, sample size, window, threshold, grid cell or budget arithmetic is not
required and is not audited. Auditors instantiate variables with their own illustrative values. A finding
that holds only for particular values, while some admissible assignment lets the rule compute and the
claim hold, is tagged `parameter`: `blocking_findings.json` `parameter_notes`, never blocking, never a
revision target on its own; it reaches the card through the mechanism record's notes.
`impossibility` must hold for every admissible assignment.

`idea` audits what makes the idea an idea: the mechanism computes, measures what it claims, differs from
its ablation (coherence trace + repair loop), differs from prior work and has a structurally sound
falsification (collision, critique), and survives its own revision (post-revision review). Phase 4 is
fill → implementability as a hole list (execution optional; trace fails are `technical_trace_note`
warns) → plain derivation → publish. No technical repair, no technical review, no falsification-revision
route, cost as an order of magnitude; stopped steps and contradictions go on the detail card as open
questions. Idea-depth stage notes are appended by `spec()` so experiment-depth requests are unchanged.

`experiment` adds the executed implementability trace, the bounded technical repair, the technical
review and the falsification-revision route, for a reader who will run the minimal experiment.

## Re-revision base

The first revision transaction patches the canonical candidate. A RE-revision (`revision_retry`, or the
Phase 4 falsification route) patches `phase3_revise/revision_base.json`, a copy of the last accepted
text taken when the retry is issued: the base already carries every earlier target, the author issues
operations only for the review's own targets (P#/F#/TR#), `base_candidate_sha256` is the base's
digest, and the merger requires coverage of those targets only. Nothing accepted earlier is re-typed,
so nothing accepted earlier can be dropped. The review still diffs the final text against the canonical
candidate for its scope, and reads the base to see exactly what the retry changed.

## Three call-saving rules

1. Object-level abandon on the record. When every surviving blocking finding is one the author declared
   object-level (`object_declared` in repair_rounds.json) and the re-trace reports each persisting with
   nothing new (`object_level_survivors`), the audit's hard floor is already decided: `quality_materialize
   --operation object_abandon` writes the abandon (verdict abandon, layer hard_floor, upheld dispositions
   with the executed evidence, salvage facts; `source: object_abandon`, paper threat and falsification
   check marked not_checked) with a deterministic critique receipt, and the retry proceeds. No audit call.
2. Pool refresh before the review. When the merged revision changed the retrieval terms, the collision
   pool is refreshed for the candidate's own terms BEFORE the post-revision review, whose novelty check
   then reads the refreshed pool. The separate post-novelty call is spent only when the reviewer confirms
   terms the pool was not built on (`--post confirmed`).
3. Reviewer consistency patch. A post-revision review whose only remaining objections are field-level
   inconsistencies (a stale number, name or clause in another field) fixes them itself in
   `consistency_patch` (≤8 exact-substring replacements in core_mechanism / core_mechanism_reasoning /
   core_mechanism_steps / what_step_was_missed / gap_closure[i].how_closed / differentiation_from_lit[i].delta;
   never a kill-switch field or a term list) and passes. `quality_materialize --operation consistency_patch`
   applies them, keeps the pre-patch text as final_candidate.pre_consistency.json, records applied and
   skipped entries, and its receipt stands in for the post-revision and merge receipts it re-seals. No
   re-revision and no second review are spent on them.

## LLM calls, complete inventory

Every reasoning call the skill can ask a host for, with when it fires. Deterministic steps are not listed.

| # | Step | Fires | Count |
|---|---|---|---|
| 1 | Phase 0 queries | the host writes 4 queries itself | 0 (inline) |
| 2 | Phase 0.4 relevance partition | always | 1 (classification tier) |
| 3 | Phase 0 pattern tagging | always; shardable | 1–3 (classification tier) |
| 4 | Phase 0.5 coverage check | always | 1 |
| 5 | Phase 0.5 host-ref tagging | only when nominations were admitted | 0–1 (classification tier) |
| 6 | Phase 1 bottleneck | always | 1 |
| 7 | generation (select + generate) | once per candidate cycle; +1 REGENERATE when the deterministic gate fails (once) | 1–2 |
| 8 | coherence trace | once per cycle, +1 per repair round | 1 + rounds |
| 9 | formula repair | per round, ≤ IDEASPARK_REPAIR_ROUNDS (3); +1 REREPAIR on a contract violation (once) | 0–4 |
| 10 | critique | once per cycle; 0 when every surviving finding is author-declared object-level; +1 REAUDIT on a contract violation (once) | 0–2 |
| 11 | refutation recheck | only when the critique refutes an executed finding | 0–1 |
| 12 | revision | when the verdict is revise; +1 re-revision when the review's needs_work is more than clause-level (once per transaction) | 0–2 |
| 13 | post-revision review | one per revision transaction | 0–2 |
| 14 | post-novelty | only when the reviewer confirms terms the refreshed pool lacked | 0–1 |
| 15 | technical fill | once per Phase 4 pass | 1 |
| 16 | implementability audit + cost | once per Phase 4 pass | 1 |
| 17 | technical repair | only when a step stopped, a structural contradiction, or the cost exceeds the ceiling | 0–1 |
| 18 | technical review | only after a repair | 0–1 |
| 19 | plain derivation | once; +1 REDERIVE when the fidelity review (off by default) fails once | 1–2 |
| 20 | fidelity review | only with IDEASPARK_FIDELITY=on | 0–1 |

Depth: rows 17–18 and the falsification-revision route fire only at `IDEASPARK_DEPTH=experiment`; an idea-depth card is typically 8–11 calls.

Routes: an abandoned cycle costs its own 7–10 (no Phase 4); the Phase 4 falsification revision adds 12–13
once (+re-revision) and repeats 15–18; the failed-validation card adds only the card stages not yet run
(19; 15–16 after a Phase 3 failure). A clean advance with no repair round is 6 quality-flow calls
(7, 8, 10, 15, 16, 19); the observed range with revision, two repair rounds and a technical repair is
14–18.

## Technical source and resources

The implementability trace no longer ends a run on its own: a stopped step (source omission or an
undefined operation a claim depends on) or a structural contradiction goes to ONE bounded technical
repair with three operation kinds — transcribe (exact source quote), SPECIFY (`kind: specification`
with a rationale: a preregistered choice a careful implementer would make from the candidate alone,
never a new mechanism), reconcile — and the technical review's executed `implementability` check
decides. A specified step is recorded on the card as `specified_by_repair`, not as a hole. Once a
technical review with no executed failing check exists, a `fail` the audit's PRE-repair trace raised
(a structural contradiction included) is a warn at publish, `technical_trace_reviewed`: the review of the
repaired text is the decider, and publish does not re-judge the text the repair replaced. An executed
contradiction that still quotes a current claim is carried on the card as `trace_contradiction`. The cost
assessment records the parsed figures and the exact substrings they were parsed from.

mechanism_record.json includes candidate_sha256, verbatim mechanism/reasoning/steps/
gap_closure/falsification sources, coherence dataflow and claim mapping, and
`dataflow_status`: `current`, or `stale_since_revision` when the revision changed a mechanism
field after the coherence trace ran — then `sources` are the authority, the stale parts are
named in `revision_changed_fields`, and `post_revision_evidence` carries the reviewer's executed
checks of the revised mechanism. Authors and auditors are told never to trace from stale parts.

## One evidence rule

Anything the program can compute, the program computes; a reviewer's label is an input to a
computation, never a gate by itself. Three consequences, all in quality_contract.py:
- `trace_findings` reads a coherence-shaped trace (formalized_procedure with per-step
  `instantiated | stopped`, executed dry_run, claim_step_map, naive_comparison, negative_control):
  stopped + a claim depends on it → fail; stopped otherwise → open question; equivalent_to_naive
  and a negative control that leaves the outcome unchanged → fail; an executed structural
  anomaly whose `contradicts_claim` names a claim the candidate makes → fail (a structural
  anomaly tied to nothing → warn). A fail needs `execution.mode ==
  executed`; without it the same finding is unverified (warn). The same evaluator reads the
  candidate trace (coherence), the technical-step trace (implementation audit) and the removal
  tests (post-revision review).
- Cost status is arithmetic: the GPU-day figure in current_estimate against the ceiling in
  intake.compute (ranges → midpoint; hours → days). feasible ≤ 80% < tight ≤ ceiling < infeasible;
  no figure → unknown. The auditor's declared status is corrected, not trusted.
- A review check's `fail` blocks only with `executed: true` (an executed instance or a written
  derivation in the evidence); a fail by judgement is `unverified_fail` (warn). Conditionals never
  block. Novelty, fidelity and readability are therefore advisory by construction.

Retired: recipe_application_check (a card is vocabulary, not a checklist), pattern_saturation (never
read), and — after 29 audited cycles across two recorded comparisons — gap_closure_reject_check (10 lesson
matches, none deciding a verdict the executed evidence had not decided), anti_pattern_check (1 match,
no effect), the `unattested_companion` warn and the `title_anchor` word-list warn (priors about shape,
not evidence about the candidate). The standalone falsification re-audit call is folded into the
post-revision review (`falsification` becomes a required check when falsification_prediction changed;
2/2 standalone re-audits advanced). The plain-vs-technical fidelity review is off by default
(`IDEASPARK_FIDELITY=on` restores it): 0 executed fails in every recorded run, one reasoning-tier call each.
What remains in the audit is executed (trace, dry run, negative control, removal tests, cost
arithmetic), retrieved (threat, novelty), or a file contract.

Implementation audit is a TRACE over method_flow.steps (same schema as the coherence gate); its holes
are derived by `implementation_points`: stopped + source_present → source_omission (one bounded repair),
stopped + claim-dependent → mechanism_blocking, stopped otherwise → open_question, unbound default →
implementation_choice. It has contract_version=2,
reviewed_step_ids and no enriched_steps or protected replacement fields. Each point has
step_id, kind, hole and evidence. kind is source_omission, implementation_choice or
mechanism_blocking. A core hole blocks — and only a core hole: mechanism_blocking is reserved
for an operation of the candidate's own mechanism that a claim depends on; an underspecified
baseline / control / ablation arm or an evaluation-only procedure is implementation_choice
with a recommended spec (this stage has no bounded retry, so its terminal kind is narrow). A source repair uses existing fields and exact
canonical source quotes; the independent technical review judges whether it was faithful.

cost_assessment.json binds candidate_sha256 and retains user_budget=intake.compute and
original_estimate=candidate.compute_budget verbatim. It includes current_estimate, basis,
change_reason; status is computed from the figures (see One evidence rule) and the declared
label is only compared against it. Computed infeasible blocks publication; unknown stays unknown. Resource risk is surfaced,
not fixed by changing the method or ceiling. Technical consistency includes cost impact.

Final order: technical → implementation audit (report + cost_assessment.json in ONE call) →
bounded source repair, and only then a technical review of the repaired text → ordinary EN/ZH
derivation → (fidelity, when enabled) → shared-source rendering. A run with no source omission spends no
technical-review call: the archive's median run is ~65 min against a 120 min wall and every
reasoning-tier call costs ~10 min. Plain maps cannot
write technical fields. Every ordinary method step mirrors technical step ids and order.
All three cards include contribution, falsification, resources, unresolved issues.

## State meanings

- DONE: current mandatory checks valid, matching Markdown artifacts generated. Not real
  experimental validation; PDF availability/compilation/visual QA is separate render_status.
- needs_work: preserved draft and exact blocker; cannot present as passed output.
- REGENERATE: the deterministic selection gate rejected the generation (hard rule above or a
  candidate-contract fail) and its one bounded retry is unused.
- REAUDIT: a deterministic validator rejected the audit report (critique contract or
  threat_grounding — e.g. a paper id inside parametric_family_concern) and its one bounded retry is
  unused; `quality_materialize --operation critique_retry` archives the report and hands the
  findings to the re-run as phase3_critique/critique_findings.json. Observed live on the first
  full run: without it a formatting violation in the audit was a terminal needs_work.
- REREVISE also fires once when the post-revision reviewer's removal tests show a component the
  patch added is not load-bearing (`claims_unchanged: true`, executed): the reviser deletes it.
- REPAIR / REREPAIR: the coherence gate found executed structural defects; the author's formula repair
  is applied and the trace re-runs (REPAIR), or the patch broke its contract and is re-issued once (REREPAIR).
- REREVISE / REDERIVE: the post-revision review or the fidelity review returned needs_work
  and its one bounded recovery is unused — `quality_materialize --operation revision_retry|
  fidelity_retry` archives the failed round, writes the review's findings next to the stage
  that produced the reviewed text (phase3_revise/post_revision_findings.json,
  phase4/work/fidelity_findings.json) and marks the budget spent. The second needs_work is terminal.
- UNSUPPORTED_RUN_DIR: a directory with files but no `run_contract.json` is refused, never resumed.
  One run is one fresh directory.
- do_not_generate / phase_3_failed: preserved existing terminal outcomes. phase_3_failed.md is
  written deterministically from the archived cycles: each cycle's title, verdict and the executed
  or quoted evidence that ended it, then the BEST cycle in full (no hard floor, fewest upheld
  executed findings, latest) as an explicitly unaudited draft, also copied to
  phase_3_failed_best_candidate.json. With the failed-validation card enabled (default) the last
  candidate then goes through the card stages and is printed marked FAILED VALIDATION.

The run contract is only created in an empty directory. The delivery sections render
only for expansions that carry a run contract and, in the plain register, only from derived plain_* fields.

