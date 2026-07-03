# Encode Structure by Construction
_id: `structural_prior_encoding`_

**Plain alias**. _Encode structure by construction_

**Definition**. Bake a known invariant or structure of the problem — a symmetry group, relational topology, geometric manifold, or physical forward model — directly into the model's operators or representation so it is satisfied by construction rather than relearned from data.

**Operational signature**. identify a known invariant/structure of the problem → encode it directly into the operator or representation → guarantee it is satisfied by construction

**When to apply**. When the problem carries a known symmetry, topology, or physical law that a generic model would have to relearn from data.

## Success conditions (from Oral)
- **A proven entailment links the encoded construction to the claimed property, rather than empirical evidence that the property usually holds.**
  - rationale: What makes 'satisfied by construction' credible is a formal guarantee — that equivariant transitions induce an invariant distribution, that a frame's own symmetry yields exact compliance, that a conjugation action is an automorphism. Without the theorem, the construction is just another inductive bias that can silently fail off-distribution, and reviewers treat it as heuristic.
- **The symmetry or equivalence group is characterized completely, including any continuous, coupled, or operator-specific components, not just the obvious discrete part.**
  - rationale: Partial characterizations leave a residual gap that the construction provably cannot close: when only a subset of the true equivalence class is enforced, the unhandled symmetries reintroduce exactly the barrier the method set out to remove. Completing the group is repeatedly the difference between a near-result and a clean one.
- **The prior is enforced through structure-respecting operators acting on the raw, native representation rather than through precomputed invariant scalar features.**
  - rationale: Projecting to invariants before processing is lossy: relative orientation, direction, and higher-order structure vanish and cannot be reconstructed downstream. Shifting the burden from representation choice to operator design preserves the information the task actually depends on.
- **An exact guarantee is paired with a tractable computation — a small structured proxy, a geometry-native basis, a cached statistic, or an algebraic shortcut that avoids the expensive canonical route.**
  - rationale: Exactness alone is not adoptable if it costs exhaustive group averaging, per-query substructure enumeration, or full spectral decomposition. The accepted work finds the structured object that delivers the same guarantee cheaply, collapsing a trade-off the field had accepted as unavoidable.
- **The structural mechanism is shown to be general — validated across multiple domains, dimensions, or task types from a single framework.**
  - rationale: A structural prior earns its keep as reusable machinery, not a one-off trick. Demonstrating that the same construction transfers across point clouds, dynamics, weight spaces, or arbitrary dimension signals that the encoded structure is fundamental rather than dataset-specific engineering.
- **Identifying the structural object that carries the result is presented as the genuine load-bearing insight, with everything else following from it.**
  - rationale: The strongest entries reframe an apparent obstacle (non-convex landscapes, intractable invariance, instability) as an artifact of an unrecognized structure, so that surfacing that structure does the explanatory work. This focuses the contribution and makes the ablation that removes it decisive.

## Failure modes (from Reject)
- **Composing existing structure-aware modules into one pipeline with no single load-bearing mechanism whose removal breaks the result.**
  - rationale: When a method stitches together a global aggregator, a local aggregator, and a fusion block all borrowed from prior work, there is no new structural guarantee to credit; reviewers consistently read this as incremental assembly and ask which component is actually novel, a question the paper cannot answer.
- **Encoding a correct domain structure that delivers only marginal improvement over the baseline it extends, or whose contribution is never isolated.**
  - rationale: If the structural prior yields gains indistinguishable from the incumbent, or if a stronger backbone could equally explain the numbers, the structure cannot be shown to be the cause of any advantage — and an unisolated mechanism is treated as unproven regardless of how principled it sounds.
- **A rigorous structural theorem whose scope or applicability is too narrow to matter.**
  - rationale: Correctness is necessary but not sufficient: results confined to a heavily restricted architecture, accompanied by a single toy experiment, fail on magnitude and breadth. Reviewers weigh how widely the structural result applies, and a beautiful theorem with no reachable application is judged out of scope.
- **Wrapping or extending an existing structural result to a new regime without unlocking new identifying structure, and landing inferior to the method it aimed to replace.**
  - rationale: Generalizing a known construction to higher dimensions or a new modality is not itself a contribution when the result underperforms the established baseline; the structural move becomes dressing on top of an existing identifiability or symmetry result rather than a new source of capability.
- **Relaxing or partially characterizing the symmetry group without proving the resulting operator class is complete.**
  - rationale: Relaxing a global constraint to a data-inherent subgroup, or claiming a tractable operator family, invites the objection that some valid structure-preserving maps are missing. Absent a completeness proof, the construction may be a special case of a more general class, and reviewers withhold credit for the guarantee.
- **Bespoke per-instance structure that requires manual engineering for each new problem and offers no uniqueness or correctness guarantee.**
  - rationale: When the prior must be hand-derived separately for every problem type, generality collapses and the method reads as engineering rather than a transferable principle; the absence of any guarantee that the encoded structure is the right or unique one further undermines the claim.

## Oral vs Reject gap
The decisive difference is the presence of a single, provable, load-bearing structural step versus a bundle of plausible ones. Accepted executions state and prove an entailment — that the construction forces the property (equivariant operators ⇒ invariant distribution, frame symmetry ⇒ exact compliance, full-group factoring ⇒ collapsed basins) — and then show empirically that deleting that one step collapses the result; rejected executions instead concatenate borrowed structure-aware modules and cannot point to one mechanism whose removal breaks everything. Accepted work characterizes the *complete* symmetry or equivalence group and operates on the raw representation with structure-respecting operators; rejected work either enforces only a partial/canonical subset (leaving a residual barrier) or pre-projects to lossy invariant scalars. Accepted work pairs the guarantee with a tractable route (a small frame, a native basis, a cached summary) and validates across multiple domains; rejected work often confines a correct result to one restricted architecture or one toy experiment. Most concretely, accepted work isolates the structural prior with an ablation against simpler and incumbent baselines, whereas rejected work repeatedly fails to rule out that a stronger backbone or the extended baseline already accounts for the gains.

## Oral vs HC gap
The HC sample here is moderate (roughly eight distinct papers, several of them strong applications), so this pattern is suggestive rather than definitive. HC papers tend to take an already-established structural-encoding idea and make it work decisively in one important place — porting an iterative corruption-reconstruction process to a new modality, anchoring a forward process at the observation, treating coordinates as recoverable pretraining targets, or enabling training-free editing from a pretrained model — and they earn their citations through immediate, reproducible practical utility and released artifacts. Oral papers instead introduce the *general* structural machinery that reframes a whole class of problems: a continuous-time formulation that exposes a parameter-free law, a complete symmetry characterization, a unifying algebraic duality, or a proof that a small structured subset suffices for exactness. In short, the HC paper instantiates a structural prior excellently in a high-value setting, while the Oral paper proves a foundational or unifying structural result whose reach spans domains or dimensions, so that others build their HC-style applications on top of it.

## Reviewer expectations
- **A formal proof that the construction enforces the claimed property — reviewers explicitly praise 'formal proof that equivariant kernels induce invariant distributions' and 'clean theoretical guarantees of exact invariance' rather than heuristic invariance handling.** _(source: oral_reviews)_
- **Demonstration that the structural prior is general — validated across multiple tasks, domains, or arbitrary dimension from one framework, not a single benchmark.** _(source: oral_reviews)_
- **An ablation that isolates the structural mechanism's contribution; reviewers repeatedly fault papers for not separating the proposed structure from a stronger backbone or for leaving the key design choice un-ablated against alternatives.** _(source: reject_reviews)_
- **Comparison against the relevant state-of-the-art, including the simpler incumbent the method extends — missing or outdated baselines, or failing to beat the prior method, is a recurring rejection trigger.** _(source: reject_reviews)_
- **Clear delineation of what is novel relative to prior structural methods — reviewers reject work whose components are 'directly inherited from prior work' or where it is 'unclear which components are novel.'** _(source: reject_reviews)_
- **Sufficient magnitude and breadth of applicability for a theory contribution — even undisputed, correct results are rejected when their scope is judged too narrow for the venue.** _(source: reject_reviews)_

## Cognitive barriers
- The tacit belief that invariance must be obtained by first projecting the raw representation onto invariant scalar features, treated as a lossless safe simplification; the leap is recognizing that equivariant operators acting on a non-invariant raw representation can preserve the invariant property while keeping the directional structure that featurization throws away.
- Working entirely inside an established framing — a discrete ladder, an ordered factorization, a flat-geometry basis, a per-pair substructure — so completely that the latent structure is invisible and the assumption can never be empirically falsified, because virtually all prior work lives in the same paradigm.
- Mistaking a partial, 'canonical' symmetry set for the complete one: assuming discrete reordering or a single fixed reference axis exhausts the equivalence class, when continuous, coupled, or operator-specific symmetries also exist and silently reintroduce the very barrier the construction was meant to remove.
- Treating a well-understood structural tool — a standard decomposition, an algebraic duality, a classical combinatorial bound — as a fixed computational convenience rather than a manipulable prior that can be embedded into operators, because architecture design and domain structure are habitually handled as separate concerns.

## Examples
### Oral lessons
- Reformulating a discrete, step-wise procedure as its continuous-time limit can expose a single parameter-free law that the discrete framing hid, unlocking exact density evaluation and flexible integration that were structurally impossible before.
- A tiny structured subset that itself satisfies the symmetry property delivers exact compliance at the cost of the subset, collapsing the tractability-versus-exactness trade-off the field had accepted as unavoidable.
- Enforce invariance through equivariant operators on the raw representation, not by pre-projecting to invariant scalars — directional signal discarded at the input cannot be recovered downstream.
- When independently trained solutions look like distinct optima, the apparent non-convexity may be a symmetry artifact: factor out the full equivalence group and the separate basins collapse into one.
- Substituting the geometry-native eigenbasis for a flat-geometry one makes every learned filter commute with the true symmetry group by construction and suppresses artifacts that only surface under long iterative rollouts.
- A decades-old algebraic duality can index all structure-preserving operators directly in the original basis, letting you skip the expensive irreducible-decomposition detour the field treated as mandatory.

### Reject lessons
- Composing several existing structure-aware modules into one pipeline, with no single mechanism that provably fails when removed, reads to reviewers as assembly rather than contribution.
- Encoding a correct domain structure that yields only marginal gains over the baseline it extends invites the verdict that the structure was never the source of any advantage.
- Extending a known structural result to a new regime without unlocking new identifying structure — and landing inferior to the incumbent it aimed to replace — is methodological dressing.
- A rigorous structural theorem that applies only to a narrow, restricted architecture and ships with one toy experiment fails on magnitude and breadth, not on correctness.
- Relaxing a global constraint to a data-inherent subgroup without proving the relaxed operator class is complete leaves reviewers doubting the construction captures all valid maps.
- When a stronger backbone alone could explain the gains, failing to ablate the proposed structural mechanism against that backbone makes the contribution impossible to credit.

_(corpus support: 61 papers under cluster-level primary)_