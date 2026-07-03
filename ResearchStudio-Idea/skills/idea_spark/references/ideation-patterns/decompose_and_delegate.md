# Decompose and Delegate to Solvers
_id: `decompose_and_delegate`_

**Plain alias**. _Decompose and delegate to solvers_

**Definition**. Split a monolithic task into sub-problems and route each to the best-suited solver — delegating structured/symbolic reasoning to sound external solvers while the learned model handles extraction, enrichment, and interfacing via structured intermediate artifacts.

**Operational signature**. identify a monolithic task → decompose it into sub-problems → route each to the best-suited (learned or symbolic/external) solver via structured intermediate artifacts

**When to apply**. When part of a task is better handled by a sound external/symbolic solver than by an end-to-end learned model.

## Success conditions (from Oral)
- **The boundary between learned and solver components is drawn at the seam where solver competence actually changes — the learned model is confined to extraction, structuring, and enrichment while a sound external mechanism owns verifiable combinatorial search or precise computation.**
  - rationale: Separating responsibilities along their comparative-advantage seam makes each sub-result correct-by-construction or independently checkable, so the composed system inherits the solver's soundness instead of the learned model's unreliability on the sub-task it cannot do well.
- **Each inter-component handoff carries a typed, externally verifiable intermediate artifact (a formal spec, an executable state, a candidate checkable by tests or a verifier) rather than free-form natural language.**
  - rationale: Verifiable artifacts break the error-propagation chain: a flawed intermediate is detected and corrected before it reaches downstream stages, which is precisely what lets multi-step composed pipelines stay coherent rather than degrading as length grows.
- **A single load-bearing mechanism is isolated and shown, via ablation, to collapse the method back to a known baseline when removed.**
  - rationale: Pinning the contribution to one removable mechanism lets gains be attributed precisely and separates the work from a mere assembly of existing parts; without such a pivot the decomposition is structurally indistinguishable from prior pipelines.
- **The baseline failure is named as a structural cause — incentive misalignment, error propagation across a fixed hierarchy, notation entanglement, or unreliable self-evaluation — and the mechanism is aimed directly at that cause.**
  - rationale: A structural diagnosis converts the method from a heuristic into a directed fix, and lets reviewers verify that the proposed mechanism addresses the stated root cause rather than an unrelated symptom.
- **Intermediate by-products are accumulated or abstracted into reusable, transfer-preserving capital — growing verified libraries, refined specifications, or abstract-then-concretize scaffolds — rather than discarded after one instance.**
  - rationale: Reuse turns per-instance solution effort into cumulative capability and forces the learned signal to carry transferable structure, which is what enables generalization to novel compositions instead of instance-level memorization.
- **The closed feedback loop is driven by signals the system can actually obtain — execution traces, verifier output, inter-candidate behavioral agreement — rather than assuming privileged external supervision.**
  - rationale: Grounding correction in obtainable signals makes the loop deployable without oracles or large labeled demonstration sets, and several accepted methods show a sufficiently capable model's own structured outputs become a usable corrective signal once surfaced explicitly.

## Failure modes (from Reject)
- **The decomposition is an assembly of off-the-shelf agents or prompts in which no component's removal would distinguish the system from prior decomposition work.**
  - rationale: When the routing structure is not itself novel and no single mechanism is shown to be responsible for the gains, reviewers judge the system as 'similar to prior work' and treat the contribution as a recombination of established parts.
- **The routing, templates, or prompts are hand-tailored to one narrow benchmark with no evidence of transfer to other domains or real-world conditions.**
  - rationale: Domain-specific scaffolding reads as an engineering hack rather than a transferable methodology, so reviewers discount single-benchmark numbers and demand the cross-domain or real-world validation that is conspicuously absent.
- **The cost the delegated solver imposes — NP-complete search, materialized intermediate structures, or a multiplied number of model calls — is left unmeasured.**
  - rationale: Offloading to a sound solver can trade unreliability for intractable cost; without a latency or efficiency analysis reviewers cannot judge practicality and treat the omission as an unaddressed critical limitation.
- **No ablation isolates the proposed mechanism from confounds such as additional data, longer training, or a stronger backbone model.**
  - rationale: If the gains could equally be explained by smuggled-in compute or data, the central claim becomes unfalsifiable and reviewers cannot attribute improvement to the decomposition itself.
- **Self-improvement or data-generation loops rely on external models without validating the intermediate supervision or analyzing error propagation across iterations.**
  - rationale: Unfiltered synthetic intermediates let errors compound through repeated self-training rounds, and reviewers flag both the missing quality gate and the unanalyzed risk of degradation as a reliability gap.
- **The decomposed system only marginally outperforms a simpler unified end-to-end baseline.**
  - rationale: When a monolithic model nearly matches the pipeline, the added complexity is unjustified and the premise that delegation was necessary collapses, eliminating the motivation for the method.

## Oral vs Reject gap
Accepted executions identify one load-bearing mechanism and demonstrate with ablation that removing it collapses the method to a specifically named prior baseline, with the drop quantified; rejected executions present a multi-stage pipeline of pre-existing agents and cannot point to any component whose removal would separate them from earlier decomposition work. Accepted papers ground every handoff in a typed, verifiable intermediate artifact that a sound mechanism can check, whereas rejected papers tend to pass unstructured outputs and leave error propagation unanalyzed. Accepted work diagnoses the baseline failure as a concrete structural cause (incentive misalignment, error propagation across a hierarchy, notation entanglement, unreliable self-evaluation) and aims the mechanism at that cause; rejected work imposes decomposition by intuition and often tailors its routing and prompts to a single benchmark. Accepted papers also report the cost of the added structure and show transfer across domains, while rejected ones omit efficiency analysis and offer only single-dataset numbers. Finally, accepted methods clear a fair comparison against unified end-to-end baselines, whereas several rejected ones beat that baseline only marginally, undercutting the premise that delegation was needed at all.

## Oral vs HC gap
The high-cited-but-not-Oral sample here is moderate (roughly a dozen papers), enough to read a pattern. HC papers tend to win on timing and adoptability: they are the first to demonstrate that a delegation or self-correction pattern is possible, crystallize a paradigm, and ship a broadly reusable framework — yet their core machinery is frequently a combination of established parts, and reviewers explicitly call the underlying framework 'incremental' or 'limited in technical novelty' while still accepting it for filling a real gap. Oral papers add to the practical system a non-obvious mechanistic diagnosis of why prior decompositions fail plus a mechanism that provably or rigorously-measurably addresses it — often a formal result (an exponential representational-blowup proof, a transition-model equivalence, a by-construction validity guarantee) or a single sharply isolated mechanism backed by collapse-on-ablation evidence. In short, HC status rewards being first and immediately buildable; graduating to Oral additionally requires a depth move — a named structural insight and a targeted, validated mechanism — that makes the contribution defensible beyond its utility.

## Reviewer expectations
- **Report the cost of the added structure — token and API budget, number of model or solver calls, and solver latency — rather than only end-task accuracy.** _(source: both)_
- **Provide ablations that isolate each component's marginal contribution, and especially show the claimed load-bearing step is what drives the gains rather than extra data or compute.** _(source: both)_
- **Disclose the exact prompts and implementation details so the decomposed pipeline is reproducible and the results are not suspected prompt-engineering artifacts.** _(source: both)_
- **Demonstrate generalization beyond a single narrow benchmark or domain, ideally with cross-domain or real-world tasks rather than templates specific to one dataset.** _(source: both)_
- **Compare fairly against simpler unified or end-to-end baselines and against concurrent decomposition methods, clarifying precisely what is novel relative to them.** _(source: both)_
- **Justify that the decomposition targets a genuine structural bottleneck — ideally evidenced by an empirical diagnostic linking a sub-task to the final outcome — instead of imposing structure for its own sake.** _(source: both)_

## Cognitive barriers
- Two abilities are tacitly treated as one monolithic capability that must be improved together, hiding the fact that they are separable and only one half is actually broken — so the obvious move is to make the whole system better rather than to surgically replace the single failing sub-task with a sound solver.
- The intermediate representation is assumed to require a particular form (symbolic notation, a flat structure, an instance-specific trace), which conceals that decomposing in a different representational space — concrete states, behavioral predictions, or abstract scaffolds — would decouple the reusable reasoning from its domain-specific encoding.
- Pipeline modules are assumed to be fixed, decoupled stages that merely pass outputs along, blocking the realization that one component can be folded into another — a generator can score its own candidates, a transition model can absorb composite operations, or a planner can configure the solver it calls.
- Self-generated signals are dismissed as unreliable confabulation and static inputs (a curated library, fixed documentation, an externally supplied task distribution) are taken as exogenous givens, obscuring that a capable model's own structured outputs can both correct it and grow the resources it was assumed to merely consume.

## Examples
### Oral lessons
- Interleaving deliberation steps with external-lookup steps in a single trajectory — so each retrieved observation reshapes the next reasoning step — outperforms running either stream alone; the feedback loop, not the two capabilities, is the load-bearing design.
- Express sub-goals as concrete intermediate states that a forward executor can verify, not as symbolic descriptions of solution content, so learned sub-results recombine across compositions never seen in training.
- When a model's self-generated evaluations are measurably unreliable, replace them with behavioral consensus among independently sampled candidates as a more robust correctness proxy than self-critique.
- Reward measurable improvement between successive attempts rather than final-attempt quality, or reinforcement collapses to inflating the first attempt and emitting cosmetic edits afterward.
- Redirect a solver's intermediate by-products into a validated, growing reusable library, converting each individual solution attempt into permanent capital that lowers the cost of future problems at near-zero marginal effort.
- Strip notation from structured procedural artifacts and train on predicting their input-output behavior in natural language, isolating the transferable reasoning skeleton from domain-specific syntax.

### Reject lessons
- Chaining an enrichment agent to a parameter-extraction agent over an existing engine is a reasonable pipeline, but if every component is an off-the-shelf prompt there is no mechanism reviewers can credit as the novel contribution.
- A decomposition stitched together with domain-specific templates and prompts tuned to one benchmark reads as an ad-hoc engineering hack, not a transferable method, no matter how strong the single-dataset numbers are.
- Delegating a sub-problem to a sound solver is not free — an NP-complete constraint solve or a materialized intermediate structure that is never costed out invites rejection on practicality grounds alone.
- Without an ablation that isolates the proposed mechanism, reviewers cannot tell whether the gains come from the decomposition or from the extra data, epochs, or stronger model it quietly brings along.
- Generating intermediate-step supervision from external models without validating that data lets errors propagate through the self-improvement loop, and reviewers will flag the missing quality filter and the unanalyzed degradation risk.
- If the decomposed system only marginally beats a unified end-to-end baseline, the added complexity is unjustified and the very premise that delegation was necessary falls apart.

_(corpus support: 42 papers under cluster-level primary)_