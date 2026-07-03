---
name: idea-quality
description: Score the QUALITY of a research idea at the idea stage — given a Markdown file with Title / Motivation / Method sections (no experiments needed), produce a per-axis quality assessment with cited evidence and an overall 0–100 score plus a verdict; or, given two such idea files, a blind head-to-head comparison. TRIGGER when the user asks "how good is this idea", "rate / score / grade this research idea or proposal", "review my idea .md before I write it up", "is this contribution strong enough to pursue", "which of these two idea files is stronger", or hands over an idea Markdown file (Title/Motivation/Method) and wants a quality judgment. Use this even when the user does not say the word "score" but clearly wants an assessment of how strong an idea is. DO NOT trigger for prior-art / overlap / "is this novel vs existing work" checks (that is a literature-collision task), for full reviews of finished papers that already have results, or for generating the idea itself.
---

# Idea Quality

Judge how strong a research idea is **at the idea stage** — before any experiments exist — and return a quality score with reasons a reviewer would recognize. This skill is self-contained: it judges from first principles on the three axes below. It consults no external corpus, dataset, or other skill, so its judgment is reproducible from the idea text alone.

## Input: an idea Markdown file

The idea is a `.md` file with three sections. Read the file, then map each section to what it feeds:

```markdown
# Title
<≤ ~15 words: the idea's handle>

## Motivation
<the bottleneck / gap the idea attacks, why it matters, and why it is still open>

## Method
<the proposed contribution as concrete numbered steps>
```

- **Title** → the handle.
- **Motivation** → feeds **Axis A** (is the problem worth attacking) and gives **Axis C** the "problem" half.
- **Method** → feeds **Axis B** (is the method good) and gives **Axis C** the "method" half.

If a section is missing or thin, infer the most reasonable reading from the rest and note the assumption in the report — do not stall asking for clarification. If the user passes two files (or one file with two ideas) and wants a comparison, run the **pairwise** track.

## Scope: what this judges, and what it deliberately does not

- **No experiments exist.** Every axis is a *reasoning-level* judgment — the kind a reviewer makes from an abstract before seeing results. **Never invent or assume experimental results to score with.** If a claim's truth would need an experiment, judge the *plausibility of its argument*, not an imagined outcome.
- **Not a prior-art check.** "Has someone already done this?" is a separate literature-collision task. Judge whether the idea is *good* (real gap, deep method, sound + on-target), NOT whether a near-duplicate exists. Judge the contribution's intrinsic ambition, not its novelty against a literature search.

A strong score means *the idea is strong*; it does not predict acceptance, which also turns on execution this skill cannot see.

## The three axes

Score on exactly these three. Each is (a) assessable from the idea alone without experiments, (b) able to discriminate strong from weak, and (c) not a proxy for writing polish.

**A — Problem position quality.** Is the gap the Motivation identifies *real, important, non-obvious, and genuinely open* — or shallow, already-solved, or a conveniently easy target?
- Strong: a gap that matters and that the field has not closed; naming it is itself insightful.
- Weak: an obvious / already-handled problem, or a soft target chosen so it can be "solved" cheaply.
- *Why it exists:* when the author picks their own bottleneck, the cheapest way to look successful is to pick a soft target. This axis is what stops a soft-bottleneck-plus-trivial-fix from scoring well.

**B — Method quality.** Is the proposed method good in itself? Score it as ONE number, but in the Reason you MUST decompose into three named sub-judgments, because a single number otherwise hides *which* of them is weak:
- **depth** — a genuinely new mechanism / construction / reframing vs an incremental tweak (a new schedule, one extra loss term, a hyperparameter).
- **soundness** — does the "why it should work" argument hold up internally? Are assumptions justified, or is there hand-waving / an unstated condition / a logical gap? *Judge the method's own logic, regardless of which problem it aims at — fit is Axis C.*
- **feasibility** — is it buildable in principle, or does it require resources / oracles / data that don't plausibly exist? *This means "buildable", NOT "will get good numbers" — do not hallucinate results.* This is the softest sub-judgment; let depth dominate B and treat feasibility as a tie-breaker, not an equal third.
- *Note:* B is about the **magnitude and integrity of the method itself**, judged intrinsically — NOT whether a duplicate exists in the literature (separate prior-art task).

**C — Problem-fit.** Does the Method actually target and *plausibly resolve the specific gap in the Motivation* — rather than an adjacent, easier, or different problem?
- Strong: the method's mechanism clearly bears on the identified gap; if it works, that gap closes.
- Weak: a method aimed at a different problem than the one claimed, or one whose connection to the gap is asserted, not shown.
- *Boundary vs B-soundness:* B-soundness asks "is the method's own logic coherent?"; C asks "does that logic connect to THIS problem?" A method can be internally sound (B high) yet solve the wrong problem (C low); or on-target (C high) yet hand-wavy (B low). Keep them separate.

## Scoring: dual-track

Always run the **absolute** track. When comparing two ideas, ALSO run the **pairwise** track — and treat pairwise as the trustworthy signal, because relative judgments are far less noisy than absolute numbers (which bunch around 3/5). The absolute 0–100 is a readable secondary readout, not a calibrated truth.

Per axis, score **1–5** (integer). There are deliberately no fixed level descriptors — instead **every score quotes the specific phrase / element of the idea that justifies it.** A score with no quoted evidence is not allowed; the evidence requirement, not a rubric table, is what keeps scores honest. Judge **substance, not length or fluency** — a short crisp idea can score 5; a long polished one can score 2.

### Track 1 — Absolute (per idea)

Overall score (equal weight, each axis 1→0 and 5→full):
```
overall = round(100 * (A + B + C - 3) / 12)
```
Verdict band: `strong` ≥ 67 · `borderline` 34–66 · `weak` < 34.

**A/C gate (overrides the band).** A and C are near-necessary, B is not — so:
- If **A ≤ 2 OR C ≤ 2**, the verdict cannot be `strong` (cap at `borderline` at best), regardless of the number. Reason: a great method on a trivial problem (low A), or a great problem with a method that doesn't address it (low C), is not a strong idea — and the equal-weight mean would otherwise mislead. State the cap and why in one line.
- A low **B alone does NOT cap**: a simple method that genuinely addresses an important problem (counter-intuitive minimalism) can still be strong.

### Track 2 — Pairwise (comparing two ideas)

For each axis state which idea is stronger (**Idea 1 / Idea 2 / tie**) and why, in one line; for axis B, note per-sub-judgment (depth / soundness / feasibility) which arm wins so the diagnostic isn't lost. Then give an overall winner **holistically** — but problem-fit (C) is near-necessary: **a decisive C loss usually decides the overall, even if that idea wins A and B**, because a method that doesn't fit its problem isn't the better idea. Decide each axis independently; do not let one axis sway the others.

**Judge blind to source.** If two ideas are compared as part of an evaluation, do NOT factor in which system/model produced which — provenance is not evidence of quality. (For this to be fair, the two inputs must share the same Title/Motivation/Method format; flag it if they don't.)

## Output format

For a single idea:

```
## Idea Review — <title>

**Decomposition**
- Problem / gap (from Motivation): …
- Method (the proposed move): …
- Why it should work: …
(assumptions inferred, if any: …)

**Axis scores**
| Axis | Score (1–5) | Evidence (quoted from the idea) | Reason |
|------|-------------|----------------------------------|--------|
| A — Problem position | | | |
| B — Method quality | | | depth: … · soundness: … · feasibility: … |
| C — Problem-fit | | | |

**Overall: NN / 100  ·  Verdict: strong | borderline | weak**
<if the A/C gate fired: one line naming the cap and why>

**Strongest point:** <one sentence>
**Most fixable weakness:** <one sentence, phrased as what would raise the score>
```

For a comparison, output the absolute block for each idea, then:

```
## Pairwise verdict (Idea 1 vs Idea 2)
| Axis | Stronger | Why (one line) |
|------|----------|----------------|
| A — Problem position | 1 / 2 / tie | |
| B — Method quality | 1 / 2 / tie | depth / soundness / feasibility: who wins each |
| C — Problem-fit | 1 / 2 / tie | |

**Overall winner: Idea 1 | Idea 2 | tie** — <one–two sentence rationale; if a decisive C loss drove it, say so>
```

## Anti-bias rules (why they matter)

- **Quote evidence for every score.** A bare number is a vibe, and vibes don't separate strong ideas from weak ones; tying each score to a specific claim makes the judgment auditable and the comparison fair.
- **Judge substance, not length / fluency / formatting.** A confident, well-structured write-up can dress up a thin idea — resist rewarding presentation, especially in B-soundness where fluent prose most easily hides an unsound step.
- **Stay at the idea stage.** Don't imagine experimental results to justify a score. If verifying a claim would need an experiment, score the *argument's plausibility*, not a hallucinated outcome.
- **In comparisons, judge blind to source.** Which model or system produced an idea is not evidence about its quality; ignore it.
