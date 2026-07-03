# Evaluation

A 100-seed benchmark answering one question: **does IdeaSpark produce stronger idea-stage research proposals than the same frontier models on their own?**

## How the evaluation works

1. **Seeds / prompts.** [`iclr2026_oral_problem_seeds_formal_100.jsonl`](iclr2026_oral_problem_seeds_formal_100.jsonl) holds 100 problem seeds, each derived from the **title only** of an ICLR-2026 **Oral** paper — the domain object and task are kept, while explicit method suffixes and any abstract-derived bottleneck are removed, to limit leakage of the published solution. Each record's `problem_seed` field is the exact prompt fed to every system (e.g. *"I want a novel ML research idea about physical realism in text-to-video models."*); `leakage_risk` and the rewrite method are recorded alongside.

2. **Systems compared.** Each seed produces one idea card from each of: **IdeaSpark** (the skill, on Claude Opus 4.8) and three baselines — Opus 4.8 (bare), Opus 4.8 self-generated, and GPT-5.5 (bare).

3. **Reference.** Every seed traces back to the real ICLR-2026 Oral paper it was derived from (identified by each seed's `openreview_id` / `original_title`) — the upper anchor for what a strong human team actually published from that direction. The Oral papers themselves are not redistributed here.

4. **Scoring.** Two skills score the generated ideas:
   - **Quality** — [`idea-quality`](idea_quality/) rates each idea's Title / Motivation / Method on three axes (problem position / method quality / problem–method fit), giving a 0–100 score + verdict, or a blind head-to-head between two systems.
   - **Novelty** — [`scoop-check`](../skills/scoop_check/SKILL.md) checks each idea against prior art and assigns a 5-level overlap score.

The headline results are in the [top-level README](../README.md#evaluation): IdeaSpark scores highest on quality across every research domain while staying novel.

## The two scoring skills

| Skill | Location | Scores | Intro |
|---|---|---|---|
| **idea-quality** | [`idea_quality/`](idea_quality/) (here) | idea **quality** — 3 axes, 0–100 + verdict | [`idea_quality/SKILL.md`](idea_quality/SKILL.md) |
| **scoop-check** | [`../skills/scoop_check/`](../skills/scoop_check/) | idea **novelty** — prior-art overlap level | [`../skills/scoop_check/SKILL.md`](../skills/scoop_check/SKILL.md) |

`idea-quality` consults no corpus or other skill — it judges from first principles on the three axes above, so its score is reproducible from the idea text alone (which is why it lives here rather than in `skills/`). To run it standalone:

```bash
ln -s "$(pwd)/evaluation/idea_quality" ~/.claude/skills/idea-quality
```

- **Input:** an idea `.md` with `# Title` / `## Motivation` / `## Method` sections.
- **Output:** a per-axis assessment + an overall 0–100 score + verdict; or a blind pairwise comparison of two idea files.
