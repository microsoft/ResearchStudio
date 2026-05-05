# Diagnose Then Surgically Fix
_id: `root_cause_surgical_remediation` · confidence: **high** · O28/H40/R27 · meta cov O19/28, H30/40, R26/27_

**Plain alias**. _Find the failure point and patch only that_

**Definition**. Empirically or theoretically localize the precise mechanism driving a failure mode (a single loss term, a numerical singularity, a bottleneck component, a pathological training signal) and apply the minimal targeted intervention that addresses exactly that mechanism, without broad architectural or data-level redesign.

**Operational signature**. observe failure F → isolate causal component C via analysis/ablation → propose minimal edit E to C → verify F is resolved while unrelated behavior is preserved

**When to apply**. When a pipeline mostly works but exhibits a specific, reproducible pathology, and when broad redesign would be wasteful relative to a targeted fix at the identified site.

**Sample note**. Sample sizes are healthy (n_oral=28, n_reject=27, n_hc=40) and meta-review coverage is strong on the Reject side (96%) and adequate on the Oral side (68%); a few Oral papers (e.g., several ICML 2023 Orals) lack meta-reviews so reviewer-voice claims lean on the ICLR/NeurIPS subset.

## Step-by-Step
1. Observe a specific, reproducible failure F: characterize precisely which input regime, metric, or behavior collapses.
2. Isolate the causal component C via analysis or controlled ablation; formal analysis (a theorem about which step introduces the pathology) beats empirical localization.
3. Propose a minimal edit E targeting only C — one line of the loss, one layer, one training-phase rule, one estimator step.
4. Prove or empirically verify a preservation guarantee: everything that worked before continues to work; the edit does not propagate side effects.
5. Validate that F is resolved by E specifically, not by capacity / data / optimization confounds — ablate the edit against close alternatives.
6. Position the contribution as the formal localization, not the patch — the edit demonstrates the localization, but the localization is the result.

## Success conditions (from Oral)
- **The failure mechanism is formalized as a measurable quantity at a specific internal site (a loss term, a numerical constant, an estimator's bias) before any fix is proposed — diagnosis precedes and constrains the intervention.**
  - evidence: `ICLR_2024_0884`, `ICLR_2024_0855`, `ICML_2024_1011`, `ICLR_2025_1583`, `NeurIPS_2025_1905`
  - These Orals each produce a concrete object that pinpoints the pathology — Lipschitz singularity, MSE sensitivity in high-perturbation regions, Hessian/gradient-conflict patterns, gradient-statistic imbalance, an analytic decomposition of label-smoothing — and only then design the edit. Reviewer voice praises this as 'theoretical analysis of the limitations in previous approaches.'
- **The intervention is paired with a formal preservation guarantee (unbiasedness, equivalence under a degenerate parameter, convergence proof) that bounds collateral damage from the edit.**
  - evidence: `ICLR_2023_0282`, `ICLR_2024_0860`, `ICML_2025_1693`
  - Each pairs the surgical fix with a theorem: gradient-bias correction provably yields unbiased combined direction; InfoBatch's rescaling makes the gradient estimator unbiased in expectation; the non-parametric cost memory is bias-free by construction. The proof is what distinguishes 'surgical' from 'plausible patch.'
- **The fix is targeted at a single named component (one loss term, one normalization layer, one schedule, one numerical operation) rather than a broad architectural redesign — and its scope is explicitly bounded.**
  - evidence: `ICLR_2021_0046`, `ICLR_2023_0376`, `NeurIPS_2025_1905`, `ICLR_2024_0855`
  - Binaural replaces only the loss; SAR fixes only BN behavior plus a flat-minima regularizer; MaxSup edits only the penalized logit; iCT swaps only the metric and the schedule. The minimality of the edit is what makes 'unrelated behavior preserved' verifiable.
- **The fix simultaneously eliminates multiple symptoms or accumulated patches that the field had stacked around the same root cause, demonstrating that the diagnosis is structurally upstream of those symptoms.**
  - evidence: `ICML_2023_0465`, `ICLR_2024_0832`, `ICLR_2024_0860`
  - Hiera shows that fixing the learning objective lets a stack of architectural 'bells and whistles' be deleted; FSQ shows that one reformulation eliminates the entire heuristic stack around codebook collapse; InfoBatch's bias fix also removes the need for elaborate pruning-criterion machinery. This 'patch-collapse' signal is a strong reviewer marker for genuine root-cause.
- **The diagnosis is validated by directly measuring the targeted property after the fix (e.g., empirical Lipschitz constant, gradient-statistic distributions, covariance spectra) and not only by aggregate task metrics.**
  - evidence: `ICLR_2024_0884`, `ICLR_2025_1583`, `ICML_2024_1011`
  - Each paper presents a 'before/after' on the specific internal quantity it claimed was the failure source — this closes the diagnostic loop and is precisely what Reject papers typically omit.

## Failure modes (from Reject)
- **Diagnosis is plausible but no controlled ablation isolates the proposed fix as the dominant lever — reviewers cannot rule out that data quality, capacity, or a peripheral factor is the real driver.**
  - evidence: `ICLR_2025_1345`, `ICLR_2025_1369`, `ICLR_2025_1584`, `ICLR_2025_1604`
  - Multiple Reject meta-reviews explicitly say the structural-mismatch claim 'appears to be a theoretical impurity rather than a practical bottleneck' and that without isolating ablations the targeted correction's causal role is unverified.
- **Targeted fix is presented but its theoretical claims are internally inconsistent or formally wrong, undercutting the 'surgical correctness' that this methodology depends on.**
  - evidence: `ICLR_2025_1584`, `ICLR_2025_1604`, `ICML_2025_1794`
  - MoE Smoothness assumes Lipschitz continuity for known-discontinuous Top-K routers; the DP-GNN privacy analysis is judged simply incorrect; SemiDICE diagnosis is right but reviewers note prior papers already established the mechanism — a surgical fix only lands if the proof holds and is novel.
- **Fix is validated only on toy or narrow regimes, so the claim that the localized mechanism is 'the' root cause cannot be defended at scale or across distributions.**
  - evidence: `ICLR_2024_0765`, `ICLR_2024_0864`, `ICLR_2025_1504`, `ICLR_2025_1415`
  - Reject meta-reviews flag restricted dimensionality (≤4D for MetaGFN), narrow data-generating processes (Brownian/OU only for signature), or marginal gains on some datasets — the surgical fix may be real but its scope of applicability is left unestablished.
- **Failure to position the diagnosis against concurrent or prior work that already identified the same mechanism, so the 'we localized the root cause' contribution collapses.**
  - evidence: `NeurIPS_2023_0684`, `ICLR_2024_0894`, `ICML_2025_1794`, `ICLR_2025_1573`
  - Reviewers explicitly cite uncited adjacent papers (Spectral Feature Augmentation; PlanE; Dual RL/ODICE; DeepGCN). Surgical-remediation papers are penalized hard when the localized mechanism is presented as new but is independently known.
- **Claimed mechanism is asserted but the structural property it targets is never directly measured — reviewers see only aggregate accuracy and cannot confirm the diagnosis.**
  - evidence: `ICLR_2024_0829`, `ICLR_2025_1564`, `ICLR_2025_1594`
  - Feature-accentuation visualizations are not psychophysically validated; VQ restoration's discrete-bottleneck claim isn't probed with diagnostics that would expose hard-assignment failure; StoryAgent's cross-component consistency is not measured. The methodology demands 'F is resolved' be observable on the targeted variable, not just on aggregate metrics.

## Oral vs Reject gap
> Oral papers couple three moves that Reject papers almost always miss at least one of: (1) the failure mode is operationalized as a *measurable quantity* on the suspected internal site (gradient norm statistics, covariance log-determinant, Lipschitz constant near t=0, energy/phase decomposition of the loss) so the diagnosis is falsifiable; (2) the fix is paired with a *preservation guarantee* — a theorem of unbiasedness, equivalence under degenerate parameters, or proof that unrelated behavior is held constant — not just an empirical 'works as well or better'; (3) ablations explicitly isolate the surgical edit from confounding factors (capacity, data, schedule) so reviewers can see the targeted mechanism is the dominant lever. Reject papers typically supply (1) at the level of intuition only, skip (2) entirely, and offer aggregate-metric improvements without ablations that rule out alternative explanations — which is exactly the language Reject meta-reviews use ('without controlled ablations… it remains unclear whether the targeted metric is the dominant bottleneck').

## Oral vs HC gap
> Both Oral and HC papers execute the diagnose→localize→minimal-fix loop, but Oral papers more consistently anchor the localization in a *formal* object (a closed-form bias term, a proven Lipschitz singularity, a loss-landscape Hessian/conflict analysis, an analytic decomposition of a loss into named summands) and then prove that the fix preserves a precise property — unbiasedness in expectation, equivalence to full-gradient updates, convergence guarantees, or mathematical equivalence to a degenerate special case. HC papers more often perform the diagnosis empirically (ablation tables, controlled component swaps, measurement of internal statistics) and validate the fix by downstream metric recovery rather than by a theorem. The other Oral-distinctive move is breadth-of-recovery: Oral fixes are shown to simultaneously eliminate multiple downstream symptoms or accumulated patches (Hiera removes 'bells and whistles'; FSQ removes a stack of VQ heuristics; MaxSup fixes representation collapse and miscalibration with one swap), whereas HC papers typically resolve the single targeted symptom.

## Reviewer expectations
- _[oral_reviews]_ A formal characterization of the failure mechanism — a theorem, a closed-form bias expression, a proven singularity, or a decomposition of the loss into named terms — not just an intuitive narrative.
- _[oral_reviews]_ A preservation guarantee that the surgical fix leaves untouched behavior actually untouched (unbiasedness, equivalence to a known good case, convergence, no quality drop on adjacent tasks).
- _[reject_reviews]_ Ablations that isolate the proposed edit from capacity, data-quality, and hyperparameter confounds — Reject meta-reviews repeatedly demand this and reject when it is missing.
- _[reject_reviews]_ Explicit comparison against concurrent or prior work that may have already identified the same mechanism; failure to cite is treated as evidence the diagnosis is not novel.
- _[both]_ Direct measurement of the targeted internal property (the 'F' in the operational signature) before and after the fix, not just downstream task metrics — both Orals supply this and Rejects are penalized for omitting it.
- _[reject_reviews]_ Demonstration that the localized mechanism is the *dominant* limiting factor, not a peripheral one — reviewers consistently challenge whether the surgically targeted component is actually load-bearing in the regime of interest.

## Cognitive barriers
- Misattribution of root cause: practitioners default to blaming optimizer hyperparameters, capacity, or data quality, when the actual culprit is a specific term in a loss, a numerical singularity, or a normalization layer treated as 'neutral preprocessing' (e.g., BN in TTA, L2 in binaural, semi-gradient in DICE).
- Hidden failure modes that look like mild suboptimality rather than bugs: methods 'still converge, just suboptimally,' so the bias never crosses the visibility threshold that would prompt diagnosis (gradient bias in multi-objective, info-loss vs bias confusion in pruning).
- Component is treated as a fixed canonical primitive whose internals are off-limits for surgery; field-wide convention to patch around the component rather than open it up (label smoothing, MSE in CM training, fixed timestep schedule near singularities).
- Output-level vs mechanism-level framing: practitioners measure the failure at the output and propose architectural or data-level remedies, missing that a single internal site fully explains the symptom when probed with the right mathematical lens (loss-landscape geometry, Lipschitz analysis, covariance of hidden states).

## Representative examples
- **[Oral]** `ICLR_2024_0884` — Proves a Lipschitz singularity at t→0 as a theorem, measures it across architectures, then applies timestep truncation that removes only the singular region — a textbook diagnose→formalize→minimally-edit chain.
  - _Lesson_: A textbook diagnose → formalize as theorem → minimally edit chain. The truncation removes only the singular region; everything else is untouched.
- **[Oral]** `ICLR_2024_0860` — Identifies pruning-induced gradient bias (not information loss) as the failure mechanism and corrects it with a per-batch rescaling whose unbiasedness is proven in expectation, leaving the rest of training untouched.
  - _Lesson_: Reframing the failure as gradient bias (not information loss) localizes the cause to a correctable expectation — per-batch rescaling fixes it with a proof, not a heuristic.
- **[Oral]** `ICLR_2023_0282` — Reorders nonlinear-aggregation and stochastic-estimation steps so the resulting combined gradient is provably unbiased, with no extra sample-complexity cost — surgical move at exactly the algebraic site that introduced the bias.
  - _Lesson_: The surgical move is at the algebraic site that introduced the bias — reordering nonlinear-aggregation and stochastic-estimation produces an unbiased gradient with no extra sample-complexity cost.
- **[Oral]** `NeurIPS_2025_1905` — Analytically decomposes label smoothing to isolate the ground-truth-logit penalty as the term causing representation collapse, then surgically replaces only that term with a max-logit penalty.
  - _Lesson_: Analytically decompose a multi-term loss to isolate the offending term; then surgically replace only that term — preservation by construction.
- **[Reject]** `ICLR_2025_1584` — Targets a real mechanism (sparsity vs stability in MoE routing) but the central theorem assumes Lipschitz continuity for routers known to be discontinuous, so the formal localization step that this methodology requires collapses.
  - _Lesson_: If the formal localization step assumes a property the system doesn't have (Lipschitz on a discontinuous router), the central theorem collapses regardless of the empirical fix.
- **[Reject]** `ICML_2025_1794` — Correctly diagnoses that semi-gradient DICE estimates a different fixed point than full-gradient DICE, but fails to position the diagnosis against concurrent ICLR 2024 papers that established the same mechanism, undercutting the 'we localized it' contribution.
  - _Lesson_: The right diagnosis fails when concurrent papers established the same mechanism — surgical remediation without explicit positioning against close prior work erases the localization claim.
- **[Reject]** `ICLR_2025_1369` — Proposes a structure-aware substitution justified as a relaxed-assumption fix, but provides no ablations isolating the substituted component, leaving reviewers unable to confirm the structural mismatch is the dominant bottleneck.
  - _Lesson_: Without ablations isolating the substituted component, reviewers cannot confirm the structural mismatch was the dominant bottleneck — surgical attribution requires per-component evidence.