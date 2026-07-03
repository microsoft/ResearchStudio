# Companion-pattern combinations (attested co-occurrence)

When a gap_closure leg's chosen pattern is the right FRAMING move but cannot
itself produce the deliverable that `intake.contribution_type` commits to
(canonical case: an `assumption_audit_and_pivot` leg on a `method` problem —
the audit names and inverts an assumption, but its honest deliverable is a
theorem / identifiability claim, not the runnable or empirical artifact a
`method` paper must ship), the leg names a `companion_pattern` that DOES own
the missing deliverable. This file is the membership set of which companions
are empirically real rather than forced.

## How to use

Each pattern below lists the set of patterns it co-occurs with in the corpus.
The list is a MEMBERSHIP SET, not a ranking — it is read as a yes/no test, so
its internal order carries no priority and is never the basis of a choice.

1. **Attestation (membership test).** The companion MUST be in the chosen
   pattern's set below. A pairing absent here was never observed together in
   the corpus and is presumed forced; do not use it.

2. **Deliverable-fit (the actual choice).** Among the attested companions,
   take the ONE whose move owns the deliverable the primary pattern cannot
   produce for this `contribution_type`. This filter typically collapses the
   set to one or two: e.g. `controlled_diagnostic_design` owns a
   confound-isolating empirical separation; `architectural_operator_substitution`
   owns a runnable operator; `self_supervised_signal_engineering` owns a
   manufactured optimization signal. State the choice and its reason in
   `companion_rationale` (which missing deliverable, why this companion owns
   it) — the pick is anchored to that reason, never to list position.

The two checks are a conjunction: both must hold, and their order is
irrelevant. Counts are omitted by design — co-occurrence frequency here mostly
reflects how broad a framing pattern is, not how good a given pairing is, so
ranking by it would pull selection toward hub patterns instead of toward
deliverable-fit.

## Provenance

Edges = unordered main-pattern pairs co-occurring in >= 10 of the 1891
multi-label-tagged papers (HDBSCAN mcs=10 alignment). Source:
`data/clustering/multilabel/paper_multilabel_v2.json`. Rebuild with
`python3 -m scripts.build_companion_combos`. 15 patterns, 68 edges.

## Allow-list


### adapt_via_conditioning
architectural_operator_substitution · assumption_audit_and_pivot · decompose_and_delegate · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering · structural_prior_encoding · unify_into_shared_representation

### algebraic_equivalence_unification
architectural_operator_substitution · assumption_audit_and_pivot · characterize_limit_then_surpass · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · structural_prior_encoding

### architectural_operator_substitution
adapt_via_conditioning · algebraic_equivalence_unification · assumption_audit_and_pivot · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering · structural_prior_encoding · unify_into_shared_representation

### assumption_audit_and_pivot
adapt_via_conditioning · algebraic_equivalence_unification · architectural_operator_substitution · characterize_limit_then_surpass · controlled_diagnostic_design · decompose_and_delegate · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · relax_discrete_search_to_continuous · self_supervised_signal_engineering · structural_prior_encoding · targeted_self_supervised_objective · unify_into_shared_representation

### characterize_limit_then_surpass
algebraic_equivalence_unification · assumption_audit_and_pivot · heterogeneous_decomposition · reframe_as_solvable_object · structural_prior_encoding

### controlled_diagnostic_design
assumption_audit_and_pivot · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering

### decompose_and_delegate
adapt_via_conditioning · assumption_audit_and_pivot · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering

### generative_process_redesign
adapt_via_conditioning · algebraic_equivalence_unification · architectural_operator_substitution · assumption_audit_and_pivot · decompose_and_delegate · heterogeneous_decomposition · reframe_as_solvable_object · relax_discrete_search_to_continuous · self_supervised_signal_engineering · structural_prior_encoding · targeted_self_supervised_objective · unify_into_shared_representation

### heterogeneous_decomposition
adapt_via_conditioning · algebraic_equivalence_unification · architectural_operator_substitution · assumption_audit_and_pivot · characterize_limit_then_surpass · controlled_diagnostic_design · decompose_and_delegate · generative_process_redesign · reframe_as_solvable_object · self_supervised_signal_engineering · structural_prior_encoding · targeted_self_supervised_objective · unify_into_shared_representation

### reframe_as_solvable_object
adapt_via_conditioning · algebraic_equivalence_unification · architectural_operator_substitution · assumption_audit_and_pivot · characterize_limit_then_surpass · controlled_diagnostic_design · decompose_and_delegate · generative_process_redesign · heterogeneous_decomposition · relax_discrete_search_to_continuous · self_supervised_signal_engineering · structural_prior_encoding · targeted_self_supervised_objective · unify_into_shared_representation

### relax_discrete_search_to_continuous
assumption_audit_and_pivot · generative_process_redesign · reframe_as_solvable_object · structural_prior_encoding

### self_supervised_signal_engineering
adapt_via_conditioning · architectural_operator_substitution · assumption_audit_and_pivot · controlled_diagnostic_design · decompose_and_delegate · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · structural_prior_encoding · targeted_self_supervised_objective · unify_into_shared_representation

### structural_prior_encoding
adapt_via_conditioning · algebraic_equivalence_unification · architectural_operator_substitution · assumption_audit_and_pivot · characterize_limit_then_surpass · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · relax_discrete_search_to_continuous · self_supervised_signal_engineering · targeted_self_supervised_objective · unify_into_shared_representation

### targeted_self_supervised_objective
assumption_audit_and_pivot · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering · structural_prior_encoding · unify_into_shared_representation

### unify_into_shared_representation
adapt_via_conditioning · architectural_operator_substitution · assumption_audit_and_pivot · generative_process_redesign · heterogeneous_decomposition · reframe_as_solvable_object · self_supervised_signal_engineering · structural_prior_encoding · targeted_self_supervised_objective
