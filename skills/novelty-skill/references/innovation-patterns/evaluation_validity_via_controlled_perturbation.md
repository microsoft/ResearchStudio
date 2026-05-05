# Audit Evaluation via Controlled Perturbation
_id: `evaluation_validity_via_controlled_perturbation` · confidence: **high** · O46/H25/R22 · meta cov O36/46, H20/25, R22/22_

**Plain alias**. _Stress-test the benchmark_

**Definition**. Expose hidden confounds or spurious signals in existing benchmarks by redesigning evaluation with parameterized templates, matched pairs, frozen harnesses, or semantically-irrelevant perturbations that isolate the claimed capability from artifacts.

**Operational signature**. suspect confound C in benchmark B → construct controlled variants of B that vary target capability while holding C fixed (or vice versa) → re-evaluate and reattribute performance

**When to apply**. When progress on a benchmark is suspected to reflect shortcut learning, memorization, or measurement artifacts rather than the capability the benchmark was designed to test.

**Sample note**. Sample is well-powered for both directions (n_oral=46, n_reject=22, full reject meta coverage); Oral meta-coverage at 36/46 (78%) is adequate but several Oral ICML 2023/2024 papers lack meta-reviews, which slightly weakens the reviewer-voice signal for the success side.

## Step-by-Step
1. Suspect a confound C in benchmark B — shortcut, leakage, memorization, measurement artifact — name C precisely, not vaguely.
2. Construct controlled variants of B: vary the target capability while holding C fixed, OR vary C while holding the target capability fixed.
3. Equalize confounders the variants don't address (capacity, hyperparameter search, dataset scale) — without equalization, 'controlled' perturbations are not controlled.
4. Re-evaluate methods on the variants; reattribute the apparent capability gap to either the target or the confound.
5. Validate the controlled-perturbation move on a real-data bridge — synthetic-only audits without showing the perturbation tracks natural confounds die in review.
6. State what changes in the field's understanding: a published consensus reverses, a benchmark is invalidated, a measurement primitive is retired. The audit's payoff is the reattribution.

## Success conditions (from Oral)
- **Run a direct ablation that toggles the suspected confound on/off while holding everything else fixed, then report the effect size of the confound itself rather than just the relative ranking change.**
  - evidence: `NeurIPS_2024_1168`, `NeurIPS_2025_1888`, `NeurIPS_2024_1248`, `ICLR_2025_1630`
  - Cambrian-1 freezes the LLM and varies only vision encoders; ImageNet-trained CNNs paper independently suppresses each cue rather than letting them compete; LLM Evaluators watermark generations to manipulate self-recognition; Training on the Test Task fine-tunes base models on task format and shows it absorbs most of the apparent progress. In each case the methodology is a one-factor-at-a-time intervention with a measured magnitude, not just a rank flip.
- **Re-run a classic, named diagnostic test or community-accepted protocol on modern systems and use the replication itself as the contribution, rather than designing a new metric.**
  - evidence: `ICLR_2025_1339`, `ICLR_2024_0985`, `ICLR_2025_1404`, `ICLR_2024_0915`
  - A Decade's Battle directly replicates Torralba & Efros (2011) at modern scale; Unprocessing re-evaluates 7 years of fairness papers under one harness; Conformity ports the Asch experiment; PPBench imports validated psychometric instruments. Reviewers explicitly praise the move of carrying an external/older protocol into a saturated subfield because the protocol's prior validation buys credibility for the negative findings.
- **Build a parameterized template or generator that produces semantically-matched variants and report how performance degrades along a single perturbation axis (irrelevant clause, value substitution, frame switch, syntactic transform).**
  - evidence: `ICLR_2025_1443`, `ICML_2025_1747`, `ICLR_2025_1412`, `ICLR_2025_1407`
  - GSM-Symbolic, LLM-SRBench, VLB, and COMFORT all share the structure: define a template, generate matched variants that vary one capability-relevant dimension while preserving difficulty/semantics, then plot degradation. The template move converts an ambiguous benchmark complaint into a continuous, replottable signal that reviewers can interrogate.
- **Construct an adversarial 'minimal counterexample' or null baseline whose success on the benchmark logically implies the benchmark is invalid, not merely weak.**
  - evidence: `ICLR_2025_1371`, `NeurIPS_2024_1161`, `ICML_2024_1066`, `ICML_2025_1684`
  - Cheating Automatic Benchmarks shows a constant null-model response wins; Are We on the Right Way runs vision benchmarks text-only and shows large fractions remain solvable; MLLM-as-Judge constructs cases where known biases would dominate; EMMA designs tasks that admit no single-modality shortcut by construction. The argument has the form of a proof-by-counterexample, which is qualitatively stronger than 'the benchmark is noisy'.
- **Pair the audit with a constructive remedy or design rule (filtered benchmark, calibrated harness, escalation protocol, intermediate criterion) so the paper is not purely a takedown.**
  - evidence: `ICLR_2025_1633`, `ICML_2025_1740`, `ICLR_2024_0985`, `ICLR_2025_1551`
  - Trust or Escalate provides a selective-prediction framework with provable agreement; eSEN proposes energy-conservation as an intermediate filter that predicts utility; Unprocessing offers a unified comparison protocol; Counterfactual Feedback proposes both new metrics and a training fix. Reviewers in this set repeatedly note that the constructive contribution prevents the work from reading as 'just a critique'.
- **Validate the audit across many models/configurations and report the consistency of the effect, not a single dramatic point estimate.**
  - evidence: `NeurIPS_2024_1325`, `ICLR_2025_1339`, `ICLR_2025_1383`, `ICLR_2024_0985`
  - Reasoning Boundary spans 25 models and 4 tasks; Decade's Battle sweeps architectures and dataset configurations; Context-Parametric Inversion tests multiple model families and IFT datasets; Unprocessing evaluates thousands of configurations. Meta-reviews credit acceptance specifically to this breadth, contrasted with rejected papers that show the effect on one model or one dataset.

## Failure modes (from Reject)
- **The controlled environment is fully synthetic with no demonstrated transfer to realistic data, so reviewers cannot tell whether the diagnosed confound matters in deployment.**
  - evidence: `ICLR_2023_0374`, `ICLR_2024_0958`
  - Blindspot Discovery's SpotCheck is synthetic-only and reviewers explicitly flag uncertainty about whether artificially-induced blindspots track natural ones; SynBench builds a class-conditional Gaussian proxy and reviewers reject the claim that it predicts behavior on real downstream tasks. Both papers are technically clean controlled-perturbation work, but the absence of a real-data anchor sinks them.
- **The audited methodology overlaps too closely with existing critique papers, so the controlled-perturbation move reads as a re-skinning rather than a new audit.**
  - evidence: `ICLR_2024_0873`, `ICLR_2024_0869`, `ICLR_2025_1402`
  - Are LLMs Strong Abstract Reasoners is rejected for not diverging enough from existing reasoning critiques; Compositional Decision Making is treated as a variant of prior compositionality benchmarks; Direct Judgment Preference Optimization overlaps with concurrent judge-training work. The signal: reviewers ask 'what does this audit show that prior audits did not?' and accepted papers have a sharp answer.
- **The proposed alternative metric or benchmark relies on a subjective ground-truth pipeline (LLM-as-judge, in-house annotation) without showing that the new ground truth is itself less biased than the one being criticized.**
  - evidence: `NeurIPS_2024_1276`, `ICLR_2024_0956`, `NeurIPS_2025_1851`
  - PiCO uses peer LLMs as judges but reviewers question the consistency assumptions; Style Over Substance evaluates only 40 GPT-4 generations with the same model; the Visual Emotion paper bootstraps labels from MLLM majority-vote while simultaneously claiming MLLMs are unreliable on this task. The audit collapses because the new measurement instrument inherits or amplifies the very pathology being diagnosed.
- **The confound is named and a fix is proposed but neither is convincingly isolated — the proposed correction is entangled with other moving parts, so reviewers cannot attribute improvements to the fix.**
  - evidence: `NeurIPS_2024_1291`, `ICML_2025_1783`, `ICLR_2024_0914`
  - Removing Length Bias proposes prompt-template bias calibration but cannot disentangle it from length effects; Reliable Image Quality proposes DQA guidance but reviewers find the disparity signal entangled with feature-extractor pretraining; Provable Benefits of Preferences argues bias is the cause but the ablation logic does not cleanly rule out alternative explanations. The methodology lives or dies on isolation, and partial isolation does not pass.
- **Audit is restricted to a narrow benchmark or single phenomenon whose flaws are already widely suspected, so the paper confirms folk knowledge rather than uncovering a hidden confound.**
  - evidence: `ICLR_2025_1653`, `NeurIPS_2025_1841`, `ICLR_2023_0387`
  - The LRA paper audits only Long Range Arena, whose local-bias problem was already well-known; Are We Using Motion shows benchmarks lack temporal demand but on a niche slice; Conceptual Consistency proposes a consistency metric whose insight reviewers find limited. When the audited target is too narrow or its problems pre-known, controlled perturbation does not produce a community-relevant update.
- **The benchmark or audit lacks scale (few items, few models, few seeds) so even a clean controlled-perturbation result cannot support the broad claim it makes.**
  - evidence: `ICLR_2024_0956`, `ICLR_2025_1422`, `NeurIPS_2024_1169`
  - Style Over Substance covers 40 questions and one generator; ERiC-UP^3 has expert annotation but limited scale and primarily text validation; the Hybrid Architectures ICL paper enumerates structural permutations but reviewers find the scope insufficient for the claimed conclusions. Reviewers explicitly tie rejection to 'cannot tell if the conclusion generalizes', which is a structural risk for any controlled-perturbation paper that has high methodological cost per data point.

## Oral vs Reject gap
> Oral papers couple the controlled perturbation to a falsifiable prior claim with a named owner — Torralba & Efros 2011 (ICLR_2025_1339), seven years of fairness papers (ICLR_2024_0985), CLIP's assumed superiority over captioners (NeurIPS_2023_0658), the texture-bias claim (NeurIPS_2025_1888) — and report the confound's effect size as a single headline number that reverses or substantially shrinks the prior conclusion. They run the audit across many models or configurations (25 models in NeurIPS_2024_1325, thousands of configs in ICLR_2024_0985) so reviewers can see consistency, and they offer a constructive remedy (a corrected protocol, calibrated harness, escalation framework). Reject papers, by contrast, target a vaguely-defined community practice rather than a named claim, run the perturbation on one model or a small set (40 prompts in ICLR_2024_0956, single-model evaluation in ICLR_2025_1474), and stop at 'we built a cleaner benchmark' without either falsifying a specific result or providing a usable replacement. The other recurring reject pattern is full-synthetic evaluation with no real-data bridge (ICLR_2023_0374, ICLR_2024_0958), where reviewers cannot rule out that the artificially-induced confound has no real-world counterpart.

## Oral vs HC gap
> HC papers (e.g., MMLU ICLR_2021_0043, GSM-Symbolic ICLR_2025_1443, LiveCodeBench ICLR_2025_1490, Chatbot Arena ICML_2024_1012) deliver a clean controlled-evaluation instrument that the community quickly adopts, but tend to stop at constructing the harness and reporting initial findings. Oral papers go one step further: they use the harness to overturn or sharply qualify a specific named result and articulate a methodological lesson the field is expected to internalize — Unprocessing reverses fairness-paper conclusions (ICLR_2024_0985), Decade's Battle falsifies the assumption that scale solved dataset bias (ICLR_2025_1339), Cheating Benchmarks shows null models top leaderboards (ICLR_2025_1371), the Texture-bias paper inverts a canonical finding (NeurIPS_2025_1888). The Oral graduation move is from 'here is a better measurement instrument' to 'here is what the field believed that turns out to be wrong, demonstrated with that instrument'.

## Reviewer expectations
- _[oral_reviews]_ Show that the proposed controlled protocol changes which method or claim wins, not just that scores shift in absolute terms.
- _[both]_ Run the audit across multiple model families, scales, and datasets so a single cherry-picked condition cannot explain the effect.
- _[oral_reviews]_ Provide a constructive output (corrected protocol, replacement metric, fine-tuning fix, or filter) rather than only a critique, so the field has something to adopt.
- _[reject_reviews]_ Anchor the audit to a real-world or ecologically valid distribution; if the diagnosis is run on synthetic data, demonstrate transfer to natural data.
- _[reject_reviews]_ When the audit relies on an automated judge or model annotator, validate that the judge itself does not inherit the bias being investigated.
- _[reject_reviews]_ Explicitly contrast the diagnosed confound with prior critiques in the same area and show what is uniquely revealed by this protocol.

## Cognitive barriers
- Practitioners take rising aggregate scores as evidence the underlying capability is improving and never re-instantiate the original diagnostic test, so the field assumes the problem is being solved while the diagnostic has never actually been re-run (ICLR_2025_1339, ICLR_2025_1443).
- Implementation choices in evaluation protocols are inherited from early influential papers as defaults; questioning them feels like methodological pedantry rather than a research contribution, so the option of one-factor-at-a-time ablation across protocol parameters is invisible (ICLR_2024_0974, ICLR_2025_1630).
- Convenience metrics (single-turn, end-to-end, scalar preference, end-state correctness) are conflated with sufficient metrics; the gap between 'easier to measure' and 'enough to measure' is suppressed by the self-reinforcing incentive of clean leaderboards (ICLR_2024_0899, ICLR_2023_0264).
- Benchmarks claiming to test a capability are presumed to test it because they nominally include the relevant input modality or task structure, hiding the possibility that single-modality or single-frame shortcuts dominate the score (NeurIPS_2024_1161, ICML_2025_1684, NeurIPS_2025_1841).

## Representative examples
- **[Oral]** `ICLR_2024_0985` — Equalizes capacity and hyperparameter search across thousands of configurations from seven years of fairness papers and shows the simple thresholding baseline they all beat is in fact optimal — the textbook case of a unified harness reversing a field's published consensus.
  - _Lesson_: Equalize capacity and hyperparameter search across thousands of configurations from years of papers — show the simple thresholding baseline they all beat is in fact optimal. A unified harness can reverse a field's published consensus.
- **[Oral]** `ICLR_2025_1630` — Identifies test-task fine-tuning as a previously-unacknowledged confound, fine-tunes older base models on task-format data to ablate it, and shows the practice eats most of the apparent emergent-capability gap — a clean isolate-and-quantify-the-confound move.
  - _Lesson_: Identify a previously-unacknowledged confound, fine-tune older base models on task-format data to ablate it — most of the apparent emergent-capability gap dissolves.
- **[Oral]** `ICLR_2025_1371` — Constructs the minimal adversarial example — a constant null-model response — and shows it tops AlpacaEval-style leaderboards, using a single counterexample to invalidate the evaluation paradigm rather than a metric debate.
  - _Lesson_: A single counterexample (constant null response tops the leaderboard) invalidates an evaluation paradigm faster than a metric debate.
- **[Oral]** `NeurIPS_2025_1888` — Replaces the cue-conflict paradigm with independent suppression of shape, texture, and color, separating cue salience from feature reliance and overturning the canonical 'CNNs are texture-biased' finding through a cleaner experimental design.
  - _Lesson_: Replace cue-conflict with independent suppression — separating cue salience from feature reliance overturns canonical findings via cleaner experimental design.
- **[Reject]** `ICLR_2023_0374` — Builds a synthetic ground-truth blindspot benchmark with the right intent, but reviewers reject because the artificially-induced blindspots are never shown to track natural ones — the controlled-perturbation move dies without a real-data bridge.
  - _Lesson_: The controlled-perturbation move dies without a real-data bridge — synthetic blindspots must be shown to track natural blindspots, not just exist.
- **[Reject]** `ICLR_2024_0956` — Decomposes evaluator preferences along multiple style axes — methodologically the right idea — but runs the entire audit on 40 GPT-4 generations evaluated by GPT-4 and Claude-1, so reviewers cannot tell if the bias is real or a single-model artifact.
  - _Lesson_: Insufficient evaluation scope when the methodology's central claim is bias detection — single-model evaluators undermine the bias claim itself.
- **[Reject]** `ICLR_2025_1653` — Audits Long Range Arena and shows simple training tricks match specialized architectures, but the diagnosed pathology (LRA's local biases) was already widely suspected and the audit does not generalize beyond a single benchmark.
  - _Lesson_: If the diagnosed pathology was already widely suspected and the audit doesn't generalize beyond a single benchmark, the contribution reads as confirmatory rather than novel.