# Decompose for Differentiated Treatment
_id: `heterogeneous_decomposition`_

**Plain alias**. _Decompose heterogeneity for differentiated treatment_

**Definition**. Partition a resource (parameters, error terms, conditioning signals, corruption modes) into components with systematically different properties, then apply a treatment tailored to each rather than a single uniform operation.

**Operational signature**. identify a resource with heterogeneous components → partition it by a discriminating property → apply a tailored operation to each partition

**When to apply**. When a uniform treatment is suboptimal because the resource's components have systematically different properties.

## Success conditions (from Oral)
- **The heterogeneity is empirically characterized and localized before any treatment is designed — the work names a concrete sub-population (a heavy-tailed minority of high-influence elements, a distinct extreme-value regime at specific operator boundaries) and shows its distribution.**
  - rationale: A named, measured property gives the partition a principled basis and lets reviewers verify the differentiated treatment is responding to real structure rather than an assumed one, which is what converts a plausible idea into a creditable one.
- **The partition is shown to be load-bearing, either through an ablation demonstrating that uniform treatment collapses or a matching lower bound proving the separately-handled term cannot be avoided.**
  - rationale: Demonstrating that removing the decomposition breaks the method isolates the decomposition as the causal source of the gain, separating it from incidental tuning and pre-empting the 'gains could come from anything' objection.
- **Two quantities the field had treated as one are decoupled into independently controllable axes (e.g., storage precision vs. computation precision, individual operator vs. composite operator pair, parameter count vs. intermediate-state memory).**
  - rationale: The conceptual inversion is the actual unlock: once the axes are separated, a tailored treatment on each becomes possible at no cost to the other, which is the move reviewers reward as non-obvious.
- **Each partition's treatment is derived from its measured property (a bin allocation produced by an entropy objective, a residual correction sized to the sensitive minority, a per-component format computed from that component's variance) rather than chosen heuristically.**
  - rationale: When the operation follows analytically from the property, the method generalizes and the design choices are defensible; arbitrary per-bucket assignments invite the charge that the treatment is interchangeable with simpler alternatives.
- **The method targets the genuinely binding constraint at the correct stage of the pipeline (attacking information loss at the compression step rather than patching it downstream, or attacking the dominant memory term rather than a secondary one).**
  - rationale: Correctly diagnosing which lever binds is what makes the differentiated treatment effective; treatments aimed at the wrong stage produce marginal gains regardless of how elegant the partition is.
- **A theoretical guarantee accompanies the construction — a contraction or generalization bound, an exact minimizer characterization, or a near-tight lower bound on the decomposed quantity.**
  - rationale: A guarantee elevates the decomposition from a useful heuristic to a principled result, and supplies the depth that distinguishes top-tier acceptance from a strong-but-engineering contribution.

## Failure modes (from Reject)
- **The partition or sensitivity criterion turns out to be a relabeling of a widely-known quantity — a standard normalization, a generic round-trip distortion, principal-component projection of activations.**
  - rationale: When the discriminating property reduces to an established tool under questioning, reviewers see rediscovery rather than new identifying structure, and the differentiated-treatment framing cannot rescue a criterion that adds nothing beyond prior art.
- **The differentiated treatment is assembled from off-the-shelf modules dropped onto each partition (classical distillation on one part, a known calibration on another) rather than derived from the components' properties.**
  - rationale: Stitching existing components together is read as methodological dressing; without a mechanism that the partition uniquely motivates, the contribution looks like integration work that any practitioner could replicate.
- **Heterogeneity is asserted as the premise but the distribution it depends on is never analyzed or shown.**
  - rationale: If the work does not characterize the property it claims to exploit, reviewers cannot judge whether differentiated treatment is warranted or whether a uniform operation would do as well, so the central justification stays unverified.
- **The practical payoff is reported only in proxy units (parameter count, FLOPs) while the constraint that actually binds — inference latency, wall-clock time, memory at deployment — is left unmeasured or is even made worse.**
  - rationale: A decomposition that wins on a proxy but loses on the real deployment metric (e.g., a storage reduction whose lookup tables blow the cache and kill throughput) fails its own motivation, and reviewers treat the missing measurement as a fundamental gap, not a minor omission.
- **The method is validated only in a regime where the motivating constraint does not actually bind, or in a scope the field has moved past.**
  - rationale: Demonstrating a storage-saving partition on models small enough that storage was never a problem, or an architecture-specific scheme after the community has shifted architectures, hollows out the stated need and leaves the contribution looking like a solution in search of a problem.
- **No ablation or baseline isolates the decomposition from generic effects, so the observed gain cannot be attributed to the differentiated treatment.**
  - rationale: When the comparison set omits the uniform-treatment baseline or the obvious competing methods, reviewers cannot tell whether the improvement comes from the partition itself or from added capacity, extra regularization, or more tuning — and unattributable gains do not clear a top-venue bar.

## Oral vs Reject gap
Oral papers empirically characterize and localize the heterogeneity before exploiting it — they name the specific sub-population (the small set of elements carrying outsized influence, a distinct extreme-value regime confined to particular positions) and exhibit its distribution — whereas rejected papers assert that components differ and apply a partition without ever measuring the property that justifies it. Oral papers prove the partition is load-bearing through an ablation in which uniform treatment collapses, or a matching lower bound showing the separately-handled term is unavoidable; rejected papers cannot attribute their gains to the decomposition because they omit the baseline that would isolate it from added capacity or generic regularization. Oral treatments are derived mechanistically from each component's measured property (a bin allocation from an entropy objective, a residual code sized to the sensitive minority, a per-stage format computed from variance), while rejected ones bolt a standard module — classical distillation, structured dropout, PCA-on-activations, a BatchNorm-like normalization — onto each bucket, which reviewers recognize as relabeled prior art. Finally, oral papers measure the real payoff in binding units (memory, wall-clock, inference steps) and confirm the targeted bottleneck actually constrains the system, whereas rejected papers report parameter-count or FLOP reductions that leave latency unmeasured or regressed, or validate in a regime where the motivating constraint never bites.

## Oral vs HC gap
The HC sample here is moderate (roughly ten distinct papers), so this should be read cautiously. Both groups deliver strong empirical Pareto frontiers and immediately usable artifacts; the separation is that Oral papers add a crisp conceptual inversion or a closed-form/asymptotic guarantee on top of the decomposition, while HC papers more often stop at a strong, well-engineered recipe. HC contributions are repeatedly flagged in their own reviews as reading like a 'technical report' or a 'known result made practical' — a valuable, widely-adopted tool whose conceptual core was already understood — whereas Oral papers reframe the resource itself, decoupling two axes the field had treated as one (storage vs. computation precision, individual operator vs. operator pair, parameter count vs. activation memory) and backing the reframing with theory such as a contraction proof, an exact-minimizer characterization, or a near-tight lower bound. Put concisely: HC is a decomposition that works and gets adopted; Oral is a decomposition that also changes how the community conceptualizes the resource and carries a guarantee that the differentiated treatment is principled rather than heuristic.

## Reviewer expectations
- **The partition or sensitivity criterion must be clearly differentiated from known techniques — reviewers reject when it collapses to PCA, structured dropout, or a standard normalization, and they praise orals specifically for surfacing a 'previously unaddressed' sub-structure or regime.** _(source: both)_
- **Real-world efficiency must be measured in deployment units (inference latency, wall-clock, memory at serving time); reporting parameter-count or FLOP reductions alone is treated as leaving the central claim unverified.** _(source: reject_reviews)_
- **Every component of the differentiated treatment should be justified by a motivation for that step and validated by an ablation isolating its individual contribution.** _(source: oral_reviews)_
- **The comparison set must include the baselines that isolate whether the decomposition itself — rather than added capacity or generic regularization — produces the gain, including the most directly competing methods.** _(source: reject_reviews)_
- **The distribution or heterogeneity being exploited must be empirically analyzed, not merely posited, so that the case for differentiated rather than uniform treatment is grounded in evidence.** _(source: reject_reviews)_
- **The motivating bottleneck must actually bind in the tested regime; validating on cases where the claimed constraint (e.g., storage cost) is trivial undercuts the contribution.** _(source: reject_reviews)_

## Cognitive barriers
- A tacit conflation of two quantities that are in fact independent — storage precision with computation precision, a centering step with a scaling step, compression error with the capacity meant to absorb it — so the very option of treating them differently never enters consideration.
- The default habit of treating a resource as a single homogeneous unit, applying one operation to every parameter, every operator, or every error term, which keeps the heterogeneous sub-structure invisible until someone thinks to measure its distribution.
- Inherited pipeline conventions mistaken for mathematical necessity — transform-then-assign, encode-then-store, reconstruct-the-input — leading researchers to optimize within the convention instead of asking whether the partition could be drawn somewhere else entirely.
- An assumption that the discriminating property must be estimated relative to a converged or objective-coupled state (sensitivity needs a task loss, initialization is incidental, the bottleneck is the obvious quantity like parameter count), which blocks the realization that the property can be measured independently or that the true binding constraint lies elsewhere.

## Examples
### Oral lessons
- Replacing a fidelity-to-input objective with a task- or behavior-defined distance can sever an unwanted coupling, making the learned representation structurally blind to variation that is irrelevant to the outcome.
- A per-component representation format derived from that component's own variance can absorb scale differences that a worst-case range argument insists require higher precision — distributional analysis beats worst-case analysis here.
- Storage precision and computation precision are independently controllable: hold a value in a compact lossy form but reconstruct it to full precision only at the exact arithmetic boundary, decoupling memory cost from numerical fidelity.
- The initialization of a correction module is a first-order design choice, not an incidental detail — seeding it from the structured (low-rank) part of the compression residual determines which optimization basin later adaptation converges to.
- Managing extreme-valued elements can be reframed as a spatial redistribution problem: equalize their variance across groups by norm-preserving rearrangement instead of suppressing them locally.
- Shifting the unit of decomposition — from individual operators to composite pairs, or from weight space to intermediate-state space — can expose a compressible dimension that is invisible at the original granularity.

### Reject lessons
- A new sensitivity or partition criterion that turns out to be a relabeling of a widely-known quantity (a round-trip distortion, a normalization, principal components of activations) reads as rediscovery, not as new identifying structure.
- Bolting standard modules onto a partition — classical distillation for one part, an off-the-shelf calibration for another — is methodological assembly, not a treatment tailored to the components' measured properties.
- Asserting that components are heterogeneous without ever characterizing the distribution being exploited leaves reviewers unable to credit the differentiated treatment over a uniform one.
- Claiming a storage or parameter-count win while leaving the real deployment bottleneck (inference latency, wall-clock) unmeasured — or making it worse — undermines the entire value proposition.
- Demonstrating the method only where the motivating constraint is trivial (small models for which storage was never a burden) hollows out the motivation regardless of the technique's elegance.
- Without an ablation that pits the decomposition against uniform treatment, gains cannot be separated from generic effects like extra capacity or regularization, so the contribution stays unattributable.

_(corpus support: 47 papers under cluster-level primary)_