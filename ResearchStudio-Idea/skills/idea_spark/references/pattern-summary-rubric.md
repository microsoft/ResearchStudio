# Pattern summary rubric — assigning ideation patterns to retrieved papers

Goal: for each paper in the merged top-30 of a map-mode result, assign 1-3 of the 15 induced ideation patterns that the paper executes (not just mentions). These per-paper tags populate the `ideation pattern tags` column of `lit_table.md`; the parent skill's Phase 1 derives the distribution + saturation flags from that column directly.

## The 15 ideation patterns (id → name)

1. `assumption_audit_and_pivot` — Audit and Pivot an Assumption
2. `architectural_operator_substitution` — Substitute the Operator or Representation
3. `generative_process_redesign` — Liberate a Fixed Generative Component
4. `controlled_diagnostic_design` — Design a Confound-Isolating Diagnostic
5. `unify_into_shared_representation` — Unify Heterogeneous Inputs into One Space
6. `reframe_as_solvable_object` — Reframe as a Solvable Object
7. `self_supervised_signal_engineering` — Manufacture the Supervisory Signal
8. `structural_prior_encoding` — Encode Structure by Construction
9. `algebraic_equivalence_unification` — Prove Equivalence to Unify
10. `heterogeneous_decomposition` — Decompose for Differentiated Treatment
11. `decompose_and_delegate` — Decompose and Delegate to Solvers
12. `relax_discrete_search_to_continuous` — Relax Discrete Search to Continuous
13. `adapt_via_conditioning` — Adapt by Conditioning, Not Retraining
14. `characterize_limit_then_surpass` — Characterize a Limit, Then Surpass It
15. `targeted_self_supervised_objective` — Design a Property-Targeting Pretext Objective

Full operational signatures live in the parent skill's [ideation patterns overview](../../idea_spark/references/ideation-patterns/overview.md). For pattern summary we use the short form below. The `id` values above are the authoritative vocabulary — they must match the parent skill's `pattern_id` set exactly, since Phase 1 and Phase 2.1 join on these ids.

## Decision rule (for each paper)

Read the abstract and ask, in order:

1. Does the paper **identify an implicit assumption a result or defense rests on, then relax it to a weaker condition (and re-derive the guarantee) or violate it with a counterexample/exploit (and demonstrate the new behavior)**? → `assumption_audit_and_pivot`.
2. Does the paper **replace an expensive operator or representation with a cheaper surrogate and argue the surrogate preserves the essential property** (expressivity, sensitivity, curvature, function-space coverage)? → `architectural_operator_substitution`.
3. Does the paper **take a conventionally-fixed component of an iterative or staged procedure** (terminal prior, schedule, endpoints, latent code, conditioning interface) **and redesign it as a free design variable** to gain quality or efficiency? → `generative_process_redesign`.
4. Does the paper **diagnose a confound inflating a measurement and build controlled instances / matched pairs that isolate the true property from the artifact**? → `controlled_diagnostic_design`.
5. Does the paper **map heterogeneous inputs/tasks/modalities into one shared representation, vocabulary, or objective and process them with a single uniform model**? → `unify_into_shared_representation`.
6. Does the paper **recast an intractable problem as a well-studied object** (subset selection, game, constraint satisfaction, supervised relabeling, etc.) **and solve it with that object's existing machinery**? → `reframe_as_solvable_object`.
7. Does the paper **derive a supervisory signal from the model's own outputs / uncertainty / generated samples** (pseudo-labels, self-training, self-distillation) **to substitute for missing ground-truth labels**? → `self_supervised_signal_engineering`.
8. Does the paper **encode a known invariant, symmetry, or structure directly into the operator or representation so it holds by construction**? → `structural_prior_encoding`.
9. Does the paper **prove an algebraic equivalence between distinct procedures or objectives and collapse the stages or unify them into one principled form**? → `algebraic_equivalence_unification`.
10. Does the paper **partition a heterogeneous resource by a discriminating property and apply a tailored operation to each partition**? → `heterogeneous_decomposition`.
11. Does the paper **decompose a monolithic task into sub-problems and route each to the best-suited (learned or symbolic/external) solver via structured intermediate artifacts**? → `decompose_and_delegate`.
12. Does the paper **relax a discrete structural search into a differentiable or amortized form and jointly optimize the structure with the task objective**? → `relax_discrete_search_to_continuous`.
13. Does the paper **express a new task as conditioning** (in-context examples, retrieval, goals, unified input format) **and solve it at inference without parameter updates**? → `adapt_via_conditioning`.
14. Does the paper **formalize a method class's exact distinguishability or expressivity limit as a separation criterion and construct an augmented operator that provably exceeds it**? → `characterize_limit_then_surpass`.
15. Does the paper **design a label-free pretext objective that only a target structural property minimizes, training the representation to encode that property**? → `targeted_self_supervised_objective`.

If 2+ rules trigger, list the strongest 2-3. If none triggers cleanly, mark `outside_taxonomy`.

## Output

```json
{
  "papers": [
    {
      "paper_id": "...",
      "primary": "<pattern_id>",
      "supporting": ["<id>", ...]
      // resolves_problem field is OMITTED for the typical paper. Include it ONLY when
      // the paper genuinely closes a sub-part of the ideation pattern's load-bearing problem
      // (high bar; ≤ 5% of papers — see decision rule below). Empty / missing field is
      // the common case and tells Phase 1 persistence check "this paper executes the
      // pattern but does not resolve it".
    },
    ...
  ]
  // distribution / saturated / under_used / narrative are NOT emitted here — Phase 1
  // Step 1.0 recomputes the ideation pattern distribution and saturation flags from the
  // per-paper tags directly (aggregating by tag × time bucket). Don't duplicate.
}
```

When a paper DOES resolve part of an ideation pattern's load-bearing problem, append to its entry:

```json
"resolves_problem": [
  {"pattern_id": "<id>", "what_resolved": "<one sentence>"}
]
```

## `resolves_problem` decision rule (high bar)

For each paper assigned an ideation pattern in `primary` or `supporting`, ask separately: does this paper claim to **definitively close** a sub-part of the ideation pattern's load-bearing problem (the open problem the ideation pattern's historical Oral pattern addresses), or does it merely **execute** the ideation pattern by instantiating one more solution?

Most papers EXECUTE the ideation pattern and add to its open frontier — they do NOT resolve. The bar for `resolves_problem`:

- The paper proves an exhaustive characterization (e.g., "all relaxations of A under condition C reduce to one of these K forms")
- The paper provides a definitive impossibility / lower bound that closes the space
- The paper's abstract or claimed contribution explicitly says the work "closes", "settles", "characterizes", or "resolves" — not just "extends" or "improves"
- The paper is itself widely-cited as the reference work for that sub-problem

If the paper executes the ideation pattern but does not close the space, OMIT this paper from `resolves_problem`. Empty `resolves_problem: []` is the common case; expect ≤ 5% of retrieved papers to have a non-empty `resolves_problem`.

This field feeds Phase 1's persistence check in the parent skill: `current_live_status: closed` requires ≥ 2 papers ≤ 12mo with the relevant `pattern_id` in their `resolves_problem` — positive count, not absence inference. Pre-2024 papers are eligible too (the closure stands regardless of when it happened).

## Calibration

The rubric is intentionally narrow — most ML papers are best described by 1-3 of these ideation patterns. If you find that >30% of retrieved papers are `outside_taxonomy`, the user's query is in a niche the 15-ideation pattern vocabulary doesn't cover; in that case emit a `taxonomy_coverage_warning` and prefer `outside_taxonomy` to forced fits.
