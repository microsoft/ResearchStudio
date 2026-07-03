# Innovation patterns — overview

The 15 induced ideation patterns (built on 1,891 of 1,947 papers in the corpus). The table lists official name + plain-language alias; each pattern's full card is in this directory. Every pattern's **definition + operational signature + when-to-apply** is inlined below so Phase 2.1 can read overview.md alone without opening individual cards.

| ID | Name | Plain alias | n_papers |
| --- | --- | --- | --- |
| `assumption_audit_and_pivot` | Audit and Pivot an Assumption | _Audit the load-bearing assumption and pivot_ | 181 |
| `architectural_operator_substitution` | Substitute the Operator or Representation | _Substitute the operator or representation_ | 109 |
| `generative_process_redesign` | Liberate a Fixed Generative Component | _Liberate a fixed generative component_ | 94 |
| `controlled_diagnostic_design` | Design a Confound-Isolating Diagnostic | _Design a confound-isolating diagnostic_ | 86 |
| `unify_into_shared_representation` | Unify Heterogeneous Inputs into One Space | _Unify heterogeneous inputs in one space_ | 82 |
| `reframe_as_solvable_object` | Reframe as a Solvable Object | _Reformulate the unsolved as a solvable object_ | 79 |
| `self_supervised_signal_engineering` | Manufacture the Supervisory Signal | _Manufacture the supervisory signal_ | 66 |
| `structural_prior_encoding` | Encode Structure by Construction | _Encode structure by construction_ | 61 |
| `algebraic_equivalence_unification` | Prove Equivalence to Unify | _Prove equivalence to unify methods_ | 59 |
| `heterogeneous_decomposition` | Decompose for Differentiated Treatment | _Decompose heterogeneity for differentiated treatment_ | 47 |
| `decompose_and_delegate` | Decompose and Delegate to Solvers | _Decompose and delegate to solvers_ | 42 |
| `relax_discrete_search_to_continuous` | Relax Discrete Search to Continuous | _Relax discrete search to continuous_ | 35 |
| `adapt_via_conditioning` | Adapt by Conditioning, Not Retraining | _Adapt by conditioning, not retraining_ | 18 |
| `characterize_limit_then_surpass` | Characterize a Limit, Then Surpass It | _Characterize the limit, then surpass it_ | 15 |
| `targeted_self_supervised_objective` | Design a Property-Targeting Pretext Objective | _Design a property-targeting pretext objective_ | 15 |

## Use
Phase 2.1 composition selection: read this file (table + inlined sections below). Phase 2.2 candidate generation: read the per-pattern card files for the 1–3 patterns in the winning composition. Phase 3.2 audit: load only the patterns referenced in the candidate.

---

### Audit and Pivot an Assumption (`assumption_audit_and_pivot`) — _Audit the load-bearing assumption and pivot_

**Definition**. Locate the load-bearing implicit assumption a result, guarantee, or defense rests on, then pivot on it: relax it to a weaker condition and re-prove (extending the guarantee), or violate it with a constructed counterexample/exploit (breaking the system or unlocking new behavior).

**Operational signature**. identify the implicit assumption a result or defense rests on → relax it (weaker condition) or violate it (counterexample/exploit) → re-derive the guarantee or demonstrate the new behavior

**When to apply**. When a result's strength or a system's safety hinges on an assumption that real settings can weaken or that an adversary can violate.

---

### Substitute the Operator or Representation (`architectural_operator_substitution`) — _Substitute the operator or representation_

**Definition**. Replace or relocate a costly computational operator, primitive, or intermediate representation with a cheaper surrogate that provably preserves the essential property (expressivity, sensitivity bound, curvature spectrum), breaking a complexity or cost bottleneck.

**Operational signature**. identify an expensive operator or representation → substitute a cheaper surrogate → prove it preserves the essential property (expressivity, sensitivity, curvature)

**When to apply**. When a cost/complexity bottleneck comes from an operator or representation that can be cheaply approximated without losing what matters.

---

### Liberate a Fixed Generative Component (`generative_process_redesign`) — _Liberate a fixed generative component_

**Definition**. Recognize a conventionally-fixed component of an iterative or staged generative procedure (the uninformative prior, fixed endpoints, unimodal step distribution, latent space, intermediate representation, or conditioning granularity) as a free design variable, and redesign it for quality or efficiency.

**Operational signature**. identify a conventionally-fixed component of an iterative/staged procedure → treat it as a free design variable → redesign it to gain quality or efficiency

**When to apply**. When an iterative or generative pipeline inherits a default design choice that was never the actual constraint.

---

### Design a Confound-Isolating Diagnostic (`controlled_diagnostic_design`) — _Design a confound-isolating diagnostic_

**Definition**. Build an evaluation instrument that holds confounds fixed (source capability, retrieval shortcuts, surface form) or systematically varies a hidden axis, isolating it so the measurement reflects the true property rather than an artifact.

**Operational signature**. identify a confound inflating a measurement → construct controlled instances that isolate it → measure the true property versus the artifact

**When to apply**. When reported performance may reflect a confound or shortcut rather than the capability you intend to measure.

---

### Unify Heterogeneous Inputs into One Space (`unify_into_shared_representation`) — _Unify heterogeneous inputs in one space_

**Definition**. Map heterogeneous modalities or tasks into a single shared representation space, vocabulary, or generative objective, replacing bespoke per-modality pipelines with one uniform model.

**Operational signature**. identify heterogeneous inputs/tasks → map them into one shared representation/vocabulary/objective → process them with a single uniform model

**When to apply**. When multiple modalities or tasks are handled by separate bespoke pipelines that a shared substrate could subsume.

---

### Reframe as a Solvable Object (`reframe_as_solvable_object`) — _Reformulate the unsolved as a solvable object_

**Definition**. Recast an intractable problem as a different, well-studied mathematical object — combinatorial selection, an optimization/constraint program, a game/equilibrium, or a supervised-relabeling problem — so that existing solvers and guarantees apply.

**Operational signature**. identify an intractable problem → recast it as a well-studied object (subset selection, game, constraint, supervised relabeling) → solve with that object's existing machinery

**When to apply**. When the native formulation is intractable but isomorphic to a problem class with mature solvers or guarantees.

---

### Manufacture the Supervisory Signal (`self_supervised_signal_engineering`) — _Manufacture the supervisory signal_

**Definition**. In the absence of ground-truth labels, derive the training or adaptation signal from the model itself — its output entropy/uncertainty, pseudo-labels, internal-state agreement, self-generated preferences, or generated-and-filtered synthetic samples.

**Operational signature**. identify missing ground-truth supervision → derive a signal from the model's own outputs/uncertainty/generated samples → train or adapt on that manufactured signal

**When to apply**. When ground-truth labels are scarce or unavailable but the model (or a generator) can produce a usable proxy signal.

---

### Encode Structure by Construction (`structural_prior_encoding`) — _Encode structure by construction_

**Definition**. Bake a known invariant or structure of the problem — a symmetry group, relational topology, geometric manifold, or physical forward model — directly into the model's operators or representation so it is satisfied by construction rather than relearned from data.

**Operational signature**. identify a known invariant/structure of the problem → encode it directly into the operator or representation → guarantee it is satisfied by construction

**When to apply**. When the problem carries a known symmetry, topology, or physical law that a generic model would have to relearn from data.

---

### Prove Equivalence to Unify (`algebraic_equivalence_unification`) — _Prove equivalence to unify methods_

**Definition**. Establish an algebraic equivalence showing that distinct procedures, or a family of seemingly different objectives, are the same thing — collapsing a multi-stage pipeline into one stage or unifying heuristics under a single principled form.

**Operational signature**. identify distinct procedures/objectives → prove an algebraic equivalence between them → collapse the stages or unify them into one principled form

**When to apply**. When two procedures or a family of heuristics look different but you suspect they optimize the same thing.

---

### Decompose for Differentiated Treatment (`heterogeneous_decomposition`) — _Decompose heterogeneity for differentiated treatment_

**Definition**. Partition a resource (parameters, error terms, conditioning signals, corruption modes) into components with systematically different properties, then apply a treatment tailored to each rather than a single uniform operation.

**Operational signature**. identify a resource with heterogeneous components → partition it by a discriminating property → apply a tailored operation to each partition

**When to apply**. When a uniform treatment is suboptimal because the resource's components have systematically different properties.

---

### Decompose and Delegate to Solvers (`decompose_and_delegate`) — _Decompose and delegate to solvers_

**Definition**. Split a monolithic task into sub-problems and route each to the best-suited solver — delegating structured/symbolic reasoning to sound external solvers while the learned model handles extraction, enrichment, and interfacing via structured intermediate artifacts.

**Operational signature**. identify a monolithic task → decompose it into sub-problems → route each to the best-suited (learned or symbolic/external) solver via structured intermediate artifacts

**When to apply**. When part of a task is better handled by a sound external/symbolic solver than by an end-to-end learned model.

---

### Relax Discrete Search to Continuous (`relax_discrete_search_to_continuous`) — _Relax discrete search to continuous_

**Definition**. Convert a combinatorial structural-search problem into a differentiable or amortized one — via continuous relaxation, learnable distributions over configurations, or learned configuration prediction — and optimize the structure jointly with the task objective.

**Operational signature**. identify a discrete structural search → relax it to a differentiable or amortized form → jointly optimize structure with the task objective

**When to apply**. When the design space is a combinatorial structure and exhaustive or nested search is prohibitively expensive.

---

### Adapt by Conditioning, Not Retraining (`adapt_via_conditioning`) — _Adapt by conditioning, not retraining_

**Definition**. Achieve task generalization by expressing each new task as conditioning — in-context examples, retrieved instances, goal specifications, or a unified task format — so the model solves it at inference without per-task parameter updates.

**Operational signature**. identify a new task → express it as conditioning (examples, retrieval, goals, unified format) → solve it at inference without parameter updates

**When to apply**. When you need broad task generalization but per-task training is costly or infeasible.

---

### Characterize a Limit, Then Surpass It (`characterize_limit_then_surpass`) — _Characterize the limit, then surpass it_

**Definition**. Formalize the exact distinguishability or expressivity limit of an established method class as a separation criterion, then construct an augmented operator proven to exceed that limit.

**Operational signature**. identify a method class's exact distinguishability/expressivity limit → formalize it as a separation criterion → construct an augmented operator that provably exceeds it

**When to apply**. When an established method class plateaus and you can pinpoint a structural property it provably cannot capture.

---

### Design a Property-Targeting Pretext Objective (`targeted_self_supervised_objective`) — _Design a property-targeting pretext objective_

**Definition**. Construct a label-free objective (e.g., continuous-label contrastive, hierarchical-ordering, masked prediction on normalized signals) whose minimization forces the representation to encode one specific targeted structural property rather than generic invariance.

**Operational signature**. identify a target structural property → design a label-free objective that only that property minimizes → train the representation to encode it

**When to apply**. When generic representation objectives fail to capture a specific attribute the downstream task depends on.

---
