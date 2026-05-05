# Localize via Causal Probing
_id: `mechanistic_probing_with_intervention` · confidence: **low** · O29/H4/R20 · meta cov O22/29, H4/4, R20/20_

**Plain alias**. _Probe the mechanism with targeted interventions_

**Definition**. Treat a trained system as an object of scientific inquiry: use probing, ablation, and causal interventions on internal components (neurons, heads, representations, parameter directions) to determine which sub-structures causally implement a behavior, then use that attribution for targeted editing, explanation, or defense.

**Operational signature**. hypothesize mechanism M inside model → design probe/intervention I targeting M → measure behavioral change under I → attribute M to specific components and exploit the attribution

**When to apply**. When a black-box system exhibits a capability or failure whose origin matters for editing, interpretation, safety, or security, and correlational analysis alone is insufficient.

**Sample note**. n_oral=29 and n_reject=20 with 76% and 100% meta coverage are robust, but HC n=4 falls below the <5 threshold needed for a reliable Oral-vs-HC contrast, so oral_hc_gap is deliberately left blank.

## Step-by-Step
1. Hypothesize an internal mechanism M: which component (layer, head, neuron, activation direction, circuit) is responsible for the observed capability or failure?
2. Pick the right unit (SAE feature, FFN value neuron, attention head, layer slice) — the level at which M can be intervened on cleanly.
3. Design a targeted intervention I (ablation, activation patching, weight surgery, controlled input perturbation, causal probing) — I must single out M, not bundled co-located components.
4. Predict the discriminating outcome BEFORE running I: what does the behavior look like if M is responsible vs. correlate? The prediction must be falsifiable.
5. Run I; measure the behavioral change; rule out spurious co-located effects with control conditions.
6. Exploit the attribution as an actionable artifact: targeted edit, capability transfer, bias removal, or interpretability tool — descriptive findings without exploitation invite the 'descriptive rather than explanatory' critique.

## Success conditions (from Oral)
- **Pair the probe with a causal intervention (activation patching, ablation, editing, injection) that flips or reproduces the behavior, never stopping at probe accuracy alone.**
  - evidence: `ICLR_2023_0227`, `ICLR_2025_1457`, `ICLR_2025_1489`, `ICLR_2025_1526`, `ICLR_2024_0836`, `ICLR_2025_1586`
  - Oral papers treat probe-predicted structure as a hypothesis; the paper is built around the intervention experiment that converts 'encoded' into 'used'. Reviewers explicitly praise this causal step (e.g., ICLR_2025_1489's 'causal interventions' and ICLR_2023_0227's 'interventional experiments').
- **Convert the localized mechanism into an actionable downstream artifact — a controllable knob, a targeted edit, a safety ablation, or a transferable vector — rather than ending with a descriptive finding.**
  - evidence: `ICML_2024_1051`, `ICML_2023_0430`, `ICLR_2025_1526`, `ICLR_2025_1405`, `ICLR_2024_0836`, `ICLR_2025_1586`
  - Each Oral paper exits with a concrete capability: value-neuron editing fixes arithmetic, SAHARA zeroes <0.006% of heads to break safety, SAE directions steer refusal, summed function vectors trigger behavior in unrelated contexts. The intervention is the product, not a diagnostic.
- **Ground the analysis in a controlled setting with known ground-truth structure (synthetic task, established continuous scale, simpler non-neural system) so the probe's claims are falsifiable.**
  - evidence: `ICLR_2023_0227`, `ICLR_2023_0397`, `ICLR_2024_0969`, `ICLR_2025_1489`, `ICML_2025_1703`, `ICLR_2024_0980`
  - Othello, linear-ICL, boolean ICL, modular arithmetic, and DW-NOMINATE ideology scales all provide external ground truth against which probe predictions and intervention effects can be cross-checked, eliminating the 'probe is just memorizing' escape hatch.
- **Triangulate with independent evidence streams — constructive proof, behavioral discrimination across competing hypotheses, and mechanistic decoding — rather than relying on a single probing technique.**
  - evidence: `ICLR_2023_0397`, `ICLR_2023_0402`, `ICLR_2024_0969`, `ICLR_2024_0836`, `NeurIPS_2024_1229`
  - Oral meta-reviews repeatedly praise combining 'theoretical foundation-laying and empirical experiments specifically designed to test the assumptions of those theories' (ICLR_2024_0969) and the design of discriminating experiments (ICLR_2023_0397/0402). Single-method probing is not enough at Oral bar.
- **Adopt an interpretable unit of analysis (SAE feature, concept-aligned neuron, routing weight, established scale) before running the circuit/attribution analysis, rather than analyzing raw polysemantic neurons or heads.**
  - evidence: `ICLR_2025_1586`, `ICLR_2025_1405`, `ICML_2025_1711`, `ICLR_2025_1489`
  - Reviewers for ICLR_2025_1586 explicitly reward the move from 'highly polysemantic' units to 'monosemantic features' as an atomic substrate. The same pattern drives the protein-SAE HC paper and the political-representation Oral: pick the right unit first.
- **Close the loop by showing the intervention transfers or generalizes — across contexts, models, or tasks — not just within the identification set.**
  - evidence: `ICLR_2024_0836`, `ICLR_2025_1405`, `ICLR_2025_1489`, `ICML_2025_1703`
  - Function vectors injected into unrelated contexts, SAE directions transferred from base to chat model, grokking reproduced in RFM — these transfer demonstrations distinguish 'identified' from 'causally sufficient'. Meta-reviewers consistently cite these as strengths.

## Failure modes (from Reject)
- **Descriptive probing without a causal account — characterizing what is encoded internally and stopping there, leaving reviewers to call the work 'empirical characterization without a causal account of how the behavior emerges'.**
  - evidence: `ICML_2025_1819`, `NeurIPS_2024_1149`, `ICML_2025_1721`
  - Chess look-ahead probes quantified depth but had no mechanistic explanation; stochastic-parroting work used linear probes without mechanism; topological signatures were 'reporting of results ... not very well-motivated'. Meta-reviews diagnose this as descriptive, not explanatory.
- **Transplanting an existing attribution or probing method into a new architecture/domain with only engineering adaptation, producing 'limited novelty' and no domain-specific insight.**
  - evidence: `ICLR_2023_0230`, `ICLR_2023_0161`, `ICML_2025_1725`, `NeurIPS_2025_1940`
  - LRP→GNN-RL, saliency→medical imaging, Shapley→proteins, and explainer→heterogeneous graphs were all rejected with essentially the same complaint: the method was not rethought for the new setting and contributes no mechanistic claim reviewers could take home.
- **Relying on narrow or architecture-specific hooks (one normalization layer, one relation type, one dataset family) and failing to test generality, so reviewers question whether the finding is a property of the model or the probe.**
  - evidence: `ICLR_2023_0255`, `NeurIPS_2023_0670`, `NeurIPS_2023_0644`
  - Channel-awareness required CCBM, word2vec-style arithmetic only held on one-to-one relations, GOAt used too few datasets. Each meta-review flagged generality as the deciding weakness.
- **Formal or axiomatic critiques of an attribution method without a constructive replacement mechanism reviewers can use, leading to 'the title promises a bit more than is provided'.**
  - evidence: `NeurIPS_2023_0577`, `NeurIPS_2023_0692`, `ICLR_2023_0187`
  - Refutations of Shapley, formal-logic attribution, and Fourier-consistency attribution were rejected because the theory 'reiterates the definitions' or leaves practical guidance unclear. Critique alone, without a usable successor method, does not clear the bar.
- **Proposing a new probing/attribution recipe whose faithfulness is validated only by heuristic or subjective measures (heatmap quality, human preference) rather than against a downstream task with ground truth.**
  - evidence: `ICLR_2024_0802`, `ICLR_2024_0928`, `NeurIPS_2023_0648`
  - DAME's human study asked for subjective 'quality'; ProtoNMF lost discriminativeness; frequency-filtering attribution lacked formal grounding. Reviewers repeatedly demand an objective downstream evaluation.
- **Operationalizing a grand construct (self-awareness, parroting, general ideology) through a single, under-specified behavioral test without internal-mechanism evidence to back the claim.**
  - evidence: `NeurIPS_2024_1150`, `NeurIPS_2024_1149`
  - Both papers gesture at mechanistic/representational questions but deliver only a thin behavioral probe; meta-reviewers found the soundness and rigor of the central test insufficient.

## Oral vs Reject gap
> Oral papers always execute a probe–intervention–exploitation arc: the probe identifies candidate components, a causal intervention (activation patching, targeted ablation, editing, injection, or swap into a different context) either breaks or reproduces the behavior, and the work ends with an actionable artifact (an edit that fixes arithmetic, a head-set whose ablation jailbreaks safety, a transferable function vector, a controllable ideology axis). Reject papers stop at one of the earlier stages — they characterize internal structure, propose a new attribution recipe, or critique an existing one, but either do not run the intervention that would convert correlation into causation (ICML_2025_1819, NeurIPS_2024_1149) or propose a technique whose only validation is heatmap-quality or a subjective human rating (ICLR_2024_0802, NeurIPS_2023_0648). Oral work also insists on triangulation — constructive proof plus behavioral discrimination plus mechanistic decoding, or probe plus intervention plus transfer — whereas Reject submissions typically have a single evidence stream and rely on the method's theoretical pedigree (Shapley, LRP, persistent homology, Fourier) to carry plausibility. Finally, Oral papers pick their unit of analysis deliberately (SAE feature, routing weight, concept neuron tied to an external scale) before probing; Reject papers analyze polysemantic raw units or architecture-specific hooks and get hit on generality.

## Oral vs HC gap
> HC sample (n=4) too small for reliable contrast.

## Reviewer expectations
- _[oral_reviews]_ Demand an interventional experiment that demonstrates causal — not merely correlational — use of the identified representation; probe accuracy alone does not satisfy them.
- _[oral_reviews]_ Expect the paper to exit with a concrete downstream demonstration (edit, ablation effect, transfer, behavioral control) rather than a descriptive map.
- _[reject_reviews]_ Require evidence that the finding generalizes beyond one architecture, one dataset, or one relation type; narrow scope is the single most common rejection reason.
- _[reject_reviews]_ Reject papers that port a classic attribution/probing method to a new setting without rethinking what the new setting changes about the method's validity.
- _[oral_reviews]_ Praise work that pairs theoretical construction (proof, formal analysis, controlled synthetic domain) with empirical measurement specifically designed to test the theory's assumptions.
- _[reject_reviews]_ Refuse purely subjective evaluations of explanation quality; demand ground-truth or downstream-task metrics that falsify the attribution's faithfulness claims.

## Cognitive barriers
- Novelty bias: researchers frame an impressive model behavior as a new phenomenon and ask 'what new thing is it doing?' instead of the harder, more deflationary 'is it re-executing something we already understand?' (ICLR_2023_0402).
- The 'distributed is inevitable' assumption: capabilities in large models are presumed to be smeared across all components, which blocks the hypothesis that a minimal parameter subset could mediate them and makes targeted editing seem implausible (ICML_2024_1051, ICLR_2025_1526).
- Cross-community isolation: causal-intervention tools, sparse decompositions, unlearning, influence functions, and counterfactual reasoning each live in separate sub-literatures, so the composition that Oral papers rely on (e.g., SAE × circuit discovery, unlearning × baseline selection) is non-obvious without bridging two methodological traditions (ICLR_2025_1586, ICLR_2025_1639).
- False-confidence barrier: a method with strong theoretical guarantees in its home domain (Shapley, influence functions, LRP) inherits unearned trust when moved to interpretability, obscuring the need to re-examine whether its axioms still apply (ICML_2024_1114, NeurIPS_2023_0577).

## Representative examples
- **[Oral]** `ICLR_2023_0227` — Canonical demonstration of the probe→intervention→behavioral-change loop in a fully controlled synthetic task (Othello), giving reviewers ground-truth-backed causal evidence that a trained model uses — not merely encodes — its internal world state.
  - _Lesson_: The probe → intervention → behavioral-change loop in a fully controlled synthetic task gives ground-truth-backed causal evidence — a model uses (not merely encodes) its internal world state.
- **[Oral]** `ICLR_2025_1586` — Exemplifies the 'pick the right unit first' move by composing SAE decomposition with circuit discovery, then using the interpretable circuits for SHIFT-style bias ablation — turning interpretability into targeted control.
  - _Lesson_: Pick the right unit first via SAE decomposition, then compose with circuit discovery — turning interpretability into targeted control via SHIFT-style bias ablation.
- **[Oral]** `ICML_2024_1051` — Shows that arithmetic, widely assumed to be distributed, is stored in identifiable FFN value neurons and can be fixed by direct inference-time activation edits with no gradient training — the methodology's most striking 'actionable artifact' payoff.
  - _Lesson_: The most striking actionable-artifact payoff — what was widely assumed distributed is in fact stored in identifiable FFN value neurons and can be edited at inference time with no gradient training.
- **[Oral]** `ICLR_2025_1489` — Anchors probing to an established external continuous scale (DW-NOMINATE) and closes the loop with head-level ablation that causally steers political bias, a textbook three-step execution of the methodology.
  - _Lesson_: Anchor probing to an established external continuous scale — closing the loop with head-level ablation that causally steers political bias is a textbook three-step execution.
- **[Reject]** `ICML_2025_1819` — Extends prior probing infrastructure to quantify chess look-ahead depth but stops at characterization — reviewers explicitly call it 'descriptive rather than explanatory' because no mechanism is causally identified.
  - _Lesson_: Stopping at characterization is 'descriptive rather than explanatory' — the methodology demands a causal intervention identifying a mechanism, not a quantification.
- **[Reject]** `ICLR_2023_0230` — Transplants LRP onto a GNN-based RL policy with only engineering adaptation and no mechanistic claim, hitting the 'domain port without insight' failure mode head-on.
  - _Lesson_: Domain port without insight — transplanting probing infrastructure with only engineering adaptation hits the 'no mechanistic claim' failure head-on.
- **[Reject]** `ICML_2025_1721` — Proposes topological signatures of adversarial latent-space compression but lacks causal intervention and downstream task validation, so reviewers treat it as unmotivated reporting rather than mechanism discovery.
  - _Lesson_: Without causal intervention and downstream task validation, mechanism reporting is 'unmotivated' — observation is not discovery.