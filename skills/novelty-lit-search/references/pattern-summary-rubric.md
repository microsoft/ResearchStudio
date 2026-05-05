# Pattern summary rubric — assigning innovation patterns to retrieved papers

Goal: for each paper in the merged top-30 of a map-mode result, assign 1-3 of the 13 induced innovation patterns that the paper executes (not just mentions). This drives `novelty_pattern_summary.md` and the saturation flag.

## The 13 innovation patterns (id → name)

1. `assumption_audit_and_relax` — Audit and Relax Implicit Assumption
2. `formal_reframing_via_equivalence` — Reframe via Alternative Formalism
3. `shared_latent_alignment` — Align Heterogeneous Sources in Shared Space
4. `invariance_as_architectural_constraint` — Encode Invariance as Hard Constraint
5. `root_cause_surgical_remediation` — Diagnose Then Surgically Fix
6. `evaluation_validity_via_controlled_perturbation` — Audit Evaluation via Controlled Perturbation
7. `analytic_refinement_of_loose_bounds` — Sharpen a Single Analytic Step
8. `redundancy_compression_and_distillation` — Exploit Redundancy via Compression
9. `decomposition_into_tractable_stages` — Decompose and Recombine
10. `auxiliary_signal_engineering` — Engineer Auxiliary Supervision Signal
11. `mechanistic_probing_with_intervention` — Localize via Causal Probing
12. `soft_probabilistic_relaxation` — Soft Probabilistic Relaxation
13. `candidate_aggregation_over_diversity` — Aggregate Over Diverse Candidates

Full operational signatures live in the parent skill's [innovation patterns overview](../../novelty-skill/references/innovation-patterns/overview.md). For pattern summary we use the short form below.

## Decision rule (for each paper)

Read the abstract and ask, in order:

1. Does the paper **prove a separation, identifiability, regret, or sample-complexity result under a relaxed assumption A'**? → `assumption_audit_and_relax`.
2. Does the paper **recast the problem in a different mathematical language** (variational, game-theoretic, optimal-transport, energy-based, etc.) and solve in that language? → `formal_reframing_via_equivalence`.
3. Does the paper **align heterogeneous modalities/tasks/datasets in a shared latent space** via projection, contrastive loss, joint embedding? → `shared_latent_alignment`.
4. Does the paper **bake a symmetry, equivariance, or invariance into the architecture** so it holds by construction? → `invariance_as_architectural_constraint`.
5. Does the paper **diagnose a specific failure mechanism and apply a minimal targeted fix** (one loss term, one regularizer, one numerical correction)? → `root_cause_surgical_remediation`.
6. Does the paper **redesign evaluation with controlled perturbations / matched pairs** to isolate the claimed capability? → `evaluation_validity_via_controlled_perturbation`.
7. Does the paper **sharpen an analytic step** (tighten a bound, eliminate a constant, replace an asymptotic with a finite-sample result)? → `analytic_refinement_of_loose_bounds`.
8. Does the paper **exploit redundancy or perform compression/distillation** to make a system smaller without losing quality? → `redundancy_compression_and_distillation`.
9. Does the paper **decompose a hard task into tractable stages and recompose** with explicit interfaces? → `decomposition_into_tractable_stages`.
10. Does the paper **engineer an auxiliary supervision signal** (pseudo-labels, weak supervision, self-supervised objectives) to substitute for missing labels? → `auxiliary_signal_engineering`.
11. Does the paper **localize a behavior to a specific component via causal probing or intervention**? → `mechanistic_probing_with_intervention`.
12. Does the paper **relax a hard constraint into a soft probabilistic version** and integrate over uncertainty? → `soft_probabilistic_relaxation`.
13. Does the paper **aggregate over diverse candidates** (ensembles, mixtures, voting) with a principled diversity argument? → `candidate_aggregation_over_diversity`.

If 2+ rules trigger, list the strongest 2-3. If none triggers cleanly, mark `outside_taxonomy`.

## Output

```json
{
  "papers": [
    {
      "paper_id": "...",
      "primary": "<methodology_id>",
      "supporting": ["<id>", ...]
      // resolves_problem field is OMITTED for the typical paper. Include it ONLY when
      // the paper genuinely closes a sub-part of the methodology's load-bearing problem
      // (high bar; ≤ 5% of papers — see decision rule below). Empty / missing field is
      // the common case and tells Phase 1 persistence check "this paper executes the
      // methodology but does not resolve it".
    },
    ...
  ]
  // distribution / saturated / under_used / narrative are NOT emitted here — Phase 1
  // Step 1.0 recomputes the methodology distribution and saturation flags from the
  // per-paper tags directly (aggregating by tag × time bucket). Don't duplicate.
}
```

When a paper DOES resolve part of a innovation pattern's load-bearing problem, append to its entry:

```json
"resolves_problem": [
  {"methodology_id": "<id>", "what_resolved": "<one sentence>"}
]
```

## `resolves_problem` decision rule (high bar)

For each paper assigned a innovation pattern in `primary` or `supporting`, ask separately: does this paper claim to **definitively close** a sub-part of the innovation pattern's load-bearing problem (the open problem the innovation pattern's historical Oral pattern addresses), or does it merely **execute** the innovation pattern by instantiating one more solution?

Most papers EXECUTE the innovation pattern and add to its open frontier — they do NOT resolve. The bar for `resolves_problem`:

- The paper proves an exhaustive characterization (e.g., "all relaxations of A under condition C reduce to one of these K forms")
- The paper provides a definitive impossibility / lower bound that closes the space
- The paper's abstract or claimed contribution explicitly says the work "closes", "settles", "characterizes", or "resolves" — not just "extends" or "improves"
- The paper is itself widely-cited as the reference work for that sub-problem

If the paper executes the innovation pattern but does not close the space, OMIT this paper from `resolves_problem`. Empty `resolves_problem: []` is the common case; expect ≤ 5% of retrieved papers to have a non-empty `resolves_problem`.

This field feeds Phase 1's persistence check in the parent skill: `current_live_status: closed` requires ≥ 2 papers ≤ 12mo with the relevant `methodology_id` in their `resolves_problem` — positive count, not absence inference. Pre-2024 papers are eligible too (the closure stands regardless of when it happened).

## Calibration

The rubric is intentionally narrow — most ML papers are best described by 1-3 of these innovation patterns. If you find that >30% of retrieved papers are `outside_taxonomy`, the user's query is in a niche the 13-innovation pattern vocabulary doesn't cover; in that case emit a `taxonomy_coverage_warning` and prefer `outside_taxonomy` to forced fits.
