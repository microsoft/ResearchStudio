# Methodologies — overview

The 13 induced methodologies. Each row shows the official name, a plain-language alias to surface in user-facing output, and the empirical sample sizes. Each methodology has a full 7-panel card in this directory.

| ID | Name | Plain alias | Confidence | n_Oral | n_HC | n_Reject |
| --- | --- | --- | --- | --- | --- | --- |
| `assumption_audit_and_relax` | Audit and Relax Implicit Assumption | _Find the hidden assumption and weaken it_ | high | 122 | 20 | 108 |
| `invariance_as_architectural_constraint` | Encode Invariance as Hard Constraint | _Bake the symmetry into the architecture_ | medium | 62 | 3 | 36 |
| `formal_reframing_via_equivalence` | Reframe via Alternative Formalism | _Change the mathematical lens_ | medium | 162 | 12 | 85 |
| `decomposition_into_tractable_stages` | Decompose and Recombine | _Break the hard task into stages with clear interfaces_ | high | 31 | 5 | 32 |
| `root_cause_surgical_remediation` | Diagnose Then Surgically Fix | _Find the failure point and patch only that_ | high | 28 | 40 | 27 |
| `soft_probabilistic_relaxation` | Soft Probabilistic Relaxation | _Replace hard rules with soft probability distributions_ | low | 3 | 0 | 12 |
| `redundancy_compression_and_distillation` | Exploit Redundancy via Compression | _Compress what is redundant_ | high | 31 | 9 | 29 |
| `auxiliary_signal_engineering` | Engineer Auxiliary Supervision Signal | _Add a training signal that exposes hidden structure_ | high | 23 | 8 | 23 |
| `shared_latent_alignment` | Align Heterogeneous Sources in Shared Space | _Put different signals into one shared representation_ | high | 45 | 18 | 52 |
| `candidate_aggregation_over_diversity` | Aggregate Over Diverse Candidates | _Combine many imperfect candidates instead of perfecting one_ | low | 6 | 2 | 3 |
| `mechanistic_probing_with_intervention` | Localize via Causal Probing | _Probe the mechanism with targeted interventions_ | low | 29 | 4 | 20 |
| `evaluation_validity_via_controlled_perturbation` | Audit Evaluation via Controlled Perturbation | _Stress-test the benchmark_ | high | 46 | 25 | 22 |
| `analytic_refinement_of_loose_bounds` | Sharpen a Single Analytic Step | _Tighten one proof bottleneck_ | medium | 60 | 0 | 33 |

## Use

In Phase 4 (audit), load the relevant methodology cards based on the candidate's composition.
In Phase 3 (ideate), the system prompt embeds short summaries; full cards are loaded only when audit needs them.