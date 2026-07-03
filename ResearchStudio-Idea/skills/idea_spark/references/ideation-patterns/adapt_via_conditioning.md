# Adapt by Conditioning, Not Retraining
_id: `adapt_via_conditioning`_

**Plain alias**. _Adapt by conditioning, not retraining_

**Definition**. Achieve task generalization by expressing each new task as conditioning — in-context examples, retrieved instances, goal specifications, or a unified task format — so the model solves it at inference without per-task parameter updates.

**Operational signature**. identify a new task → express it as conditioning (examples, retrieval, goals, unified format) → solve it at inference without parameter updates

**When to apply**. When you need broad task generalization but per-task training is costly or infeasible.

## Success conditions (from Oral)
- **The generalization claim is made falsifiable by structural holdout — excluding entire task or category clusters during adaptation, or stating the transfer hypothesis set-theoretically — so genuine cross-category transfer is distinguished from in-distribution memorization.**
  - rationale: Holding out instances of seen categories collapses the claim into ordinary in-distribution performance; only category-level exclusion forces the conditioning mechanism to demonstrate transfer to structurally novel targets, which is the capability actually being asserted.
- **The conditioning channel is trained as a first-class input modality, with the model explicitly taught to parse the unified format, retrieval-conditioned input, or structured layout.**
  - rationale: When conditioning is baked into training, the parameters acquire a context-interpretation skill that activates at inference; when it is attached post-hoc to a frozen model, the architecture reduces to a standard predictor that cannot leverage the target-setting signal.
- **A single structural quantity is isolated and shown to predict transfer efficacy — a shared-feature subset, a pre-adaptation distributional distance, a decomposed error term, or a coverage metric.**
  - rationale: Naming the load-bearing quantity makes the method diagnosable and the failure modes separable, converting a black-box result into a modular account that reviewers can interrogate and practitioners can reuse.
- **Parameters are decoupled from the target task by training on diverse, synthetic, or procedurally generated data so they encode context-interpretation rather than task-specific behavior.**
  - rationale: Context-conditioned prediction and direct behavior fitting place different demands on what parameters must memorize; learning only 'how to read context' lets the same frozen model absorb new tasks at inference without per-task data collection.
- **The method is shown to win precisely in the regime where the naive alternative breaks down, and that regime is explicitly characterized.**
  - rationale: Conditioning's advantage is regime-specific — sparse samples, low off-the-shelf accuracy, or small reference sets — and stating the boundary both explains the gain and immunizes the paper against the 'why not just use the simpler method' objection.
- **The empirical demonstration is paired with a mechanism-isolating ablation or a theoretical account explaining why conditioning suffices in place of retraining.**
  - rationale: Showing that conditioning works is weaker than showing why; an ablation toggling the conditioning signal, a characterization of optimization dynamics, or a finite-sample bound closes the attribution gap that otherwise leaves the result looking incidental.

## Failure modes (from Reject)
- **Claiming 'no adaptation needed' or 'true zero-shot' while the model has been trained on data from (or similar to) the evaluation domain, against baselines denied the same information.**
  - rationale: The improvement cannot be attributed to the conditioning mechanism versus the extra exposure, so reviewers read the headline comparison as unfair and discount the central claim regardless of its size.
- **Directly porting an established conditioning or retrieval technique to a new modality without grounding why the similarity metric or conditioning signal captures task-relevant structure there, and without testing the obvious cheaper baseline.**
  - rationale: Absent a reason the mechanism should transfer to the new setting, the work reads as under-theorized technique migration; the missing longer-context or nearest-neighbor comparison leaves the unique value of the conditioning unestablished.
- **A conditioning recipe that is not generic — it depends on a manual, task-specific search for the right auxiliary signal or format and is demonstrated on only a single task.**
  - rationale: If instantiating the method on a new problem requires bespoke search that the paper cannot systematize, reviewers conclude it is a one-off observation rather than a reusable methodology and apply the genericity bar.
- **Building a multi-component conditioning pipeline (e.g., graph plus fusion plus contrastive alignment) with ablations too shallow to justify each interacting module, often compounded by unclear formulation or technical errors.**
  - rationale: When the contribution of each component is unisolated, the real source of any gain is unknown, and the system's complexity becomes a liability that soundness and clarity concerns amplify.
- **A method that works only under idealized assumptions and decays under realistic conditions — larger data scale, common parameter-efficient adaptation, or imperfect conditioning-source coverage.**
  - rationale: Conditioning approaches whose performance hinges on exact-access or small-scale assumptions cannot support a general contribution claim, and reviewers extrapolate the observed decay to the deployment settings that matter.

## Oral vs Reject gap
Accepted executions construct the evaluation so the trivial explanation is structurally impossible: they hold out entire task categories rather than instances, audit train/eval contamination, and run an ablation that toggles the conditioning channel on and off to show the gain comes specifically from conditioning rather than from extra exposure or plain multitask training. Rejected executions leave that loophole open — training on evaluation-domain data while claiming 'no adaptation,' or comparing against baselines that were never given the same conditioning budget — so the improvement cannot be attributed to the mechanism. Accepted papers also name a single load-bearing structural quantity (a shared-feature subset, a pre-adaptation distributional distance, an error-decomposition term, a coverage-versus-ambiguity tradeoff) and show it predicts transfer, whereas rejected papers stack several interacting modules and supply ablations too shallow to isolate which one carries the effect. Finally, accepted work either demonstrates the conditioning recipe across many tasks and domains or precisely characterizes the regime where it beats retraining, while rejected work demonstrates on a single task or omits the obvious simpler comparison — longer context, nearest-neighbor lookup, or plain multitask — that would establish the conditioning's unique value.

## Oral vs HC gap
The HC sample here is thin — only two papers — so this contrast is suggestive rather than firm. Both high-cited-but-not-Oral papers were impactful, reproducible empirical demonstrations that a conditioning recipe works at surprising scale or sample efficiency, but reviewers flagged them as primarily empirical or dataset-curation-driven and left an attribution loophole open, such as the missing train/eval data-overlap analysis needed to defend a 'true zero-shot' claim. The Oral papers in the same family pair the empirical demonstration with a move that isolates why the conditioning works: an ablation that specifically toggles the conditioning signal against a matched non-conditioned multitask baseline, a characterization of the optimization dynamics that motivate the design, or a theoretical account with finite-sample bounds. In short, graduating to Oral appears to require closing the attribution gap — showing not just that conditioning generalizes but mechanistically what makes it generalize — rather than adding raw scale or more benchmarks.

## Reviewer expectations
- **Run an ablation that isolates the conditioning signal — comparing instruction, format, or retrieval conditioning against the same multitask training without it — to prove the gain comes from conditioning and not merely from broader exposure.** _(source: both)_
- **Provide a contamination or data-overlap analysis between the adaptation tasks and the held-out evaluation set before any genuine held-out or zero-shot generalization claim is accepted.** _(source: both)_
- **Compare against the obvious cheaper alternative — longer input context, nearest-neighbor lookup, or plain multitask fine-tuning — so the unique value of the conditioning or retrieval is established rather than assumed.** _(source: reject_reviews)_
- **Justify each component of a multi-module conditioning pipeline with ablations that isolate its contribution; shallow ablations over interacting components are treated as insufficient.** _(source: both)_
- **Demonstrate that the recipe is generic across multiple tasks or domains and explain how the conditioning signal is obtained without a manual, per-task search.** _(source: reject_reviews)_
- **Characterize sensitivity to the quality and coverage of the conditioning source — the demonstration or retrieval database — and to the distributional gap between that source and the test domain.** _(source: both)_

## Cognitive barriers
- The field defaults to the assumption that adaptation requires parameter updates, more capacity, or target-task data, so it is hard to imagine that expressing a task purely as conditioning could match or beat retraining — the prior even holds that targeted adaptation narrows a model toward its training distribution rather than broadening transfer.
- Practitioners instinctively diagnose the bottleneck as a shortage of data or capacity when it is actually distributional alignment or the format-parsing skill itself; recognizing that a handful of well-chosen conditioning signals can outweigh hundreds of thousands of generic annotations requires inverting the volume-is-the-constraint intuition.
- Several monotonicity and commitment assumptions stand in the way — that a more accurate source is always a better teacher, and that a surrogate prediction must commit to a single best label — and breaking them demands seeing how input-channel boundaries or coverage effects silently violate the default.
- Reaching the method requires noticing that 'how to read context' is a different and far cheaper learning target than 'what to do,' which means stepping outside the labeled-transfer problem formulation entirely rather than extending it incrementally — an uncomfortable reframing of what the parameters are even supposed to memorize.

## Examples
### Oral lessons
- When labeled samples are sparse, calibrate the estimated distribution by borrowing spread statistics from structurally similar, well-sampled categories rather than fixing the classifier — the regularity that similar categories share spread in learned representation space is the unlock.
- Holding out entire task categories, not just held-out instances, is what converts a 'generalization' claim from in-distribution performance into evidence of genuine cross-category transfer.
- The efficacy of cross-type transfer is governed by whether the source concentrates on features the target can also access, so a higher-performing source is not necessarily a better teacher.
- Treat a cross-domain gap as distributional rather than structural: aligning representation distributions before adaptation can replace bespoke architectural redesign and even predicts downstream performance.
- Train the model to read the conditioning channel as a first-class input — retrieval-conditioned or format-conditioned input baked into training — otherwise the architecture quietly reduces to an ordinary pretrained predictor.
- Parameters need only learn how to interpret context, not what to do, so a task-agnostic context-interpreter can be bootstrapped from cheap, procedurally generated synthetic data and still transfer to real tasks.

### Reject lessons
- Claiming 'no adaptation needed' while training on data drawn from the evaluation domain makes the comparison unfair and the generalization claim impossible to attribute to the mechanism.
- Porting a retrieval or conditioning technique to a new modality without explaining why its similarity metric captures task-relevant structure reads as under-theorized transfer, especially when the obvious cheaper baseline of simply extending the input context is never tested.
- A conditioning recipe that requires a manual, task-specific search for the right auxiliary signal — and is shown on only one task — fails the genericity bar reviewers apply to a proposed methodology.
- Stacking many interacting modules without ablations that isolate each component's contribution leaves the true source of the gain unjustified and turns complexity into a soundness liability.
- A method that works only under idealized access assumptions and decays under realistic conditions such as larger data or parameter-efficient adaptation cannot support a claim of general contribution.

_(corpus support: 18 papers under cluster-level primary)_