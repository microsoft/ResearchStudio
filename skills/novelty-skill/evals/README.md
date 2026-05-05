# Evals

Starter eval set for iterating on the skill's quality, following the [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) loop pattern.

## Why

Per Anthropic's [official skill best practices](https://docs.claude.com/en/api/agent-skills):

> **First build evals.** Before writing extensive documentation, create evals. This ensures your skill solves real problems, not imaginary ones.

The current skill has been validated end-to-end on two real queries (diffusion-sampling acceleration via consistency distillation; RLHF reward-model overoptimization), both producing idea cards that pass both validators. But systematic evaluation against held-out queries with human reviewer agreement is the next iteration step. The starter set in [evals.json](evals.json) is the seed.

## How to run (skill-creator workflow)

1. Install both skills + set env (`OPENALEX_API_KEY`, `OPENREVIEW_USER`, `OPENREVIEW_PASS`).
2. Spawn one with-skill run per eval prompt (and baseline if comparing against vanilla LLM critique):

```python
# In Claude Code, use the Agent tool to spawn parallel runs:
for eval in evals.json["evals"]:
    Agent({
        description: f"Eval {eval.id} with-skill",
        prompt: f"Execute this task using novelty-skill: {eval.prompt}\n"
                f"Save outputs to <workspace>/iteration-1/eval-{eval.id}/with_skill/"
    })
    Agent({
        description: f"Eval {eval.id} baseline",
        prompt: f"Execute this task without any skill (vanilla LLM critique): {eval.prompt}\n"
                f"Save outputs to <workspace>/iteration-1/eval-{eval.id}/without_skill/"
    })
```

3. Draft assertions (skill-creator's `agents/grader.md` rubric).
4. Aggregate: `python -m scripts.aggregate_benchmark <workspace>/iteration-1 --skill-name novelty-skill`.
5. Open the viewer for side-by-side review: `python eval-viewer/generate_review.py <workspace>/iteration-1/ --skill-name novelty-skill`.
6. Review, leave feedback, iterate prompts.

## What's been verified end-to-end (manual)

- ✅ Phase 0 retrieval — 4 connectors (arxiv/dblp/openalex/openreview), role-based windows, dedup priority
- ✅ Phase 1 OOD detection — 6 trigger types route to `do_not_generate.md`
- ✅ Phase 2.1 selection — top-3 ranked compositions by structural fit; anti-pattern flag
- ✅ Phase 2.2 generation — K=1 candidate with 13-pattern composition + sub-pattern selection
- ✅ Phase 3.1 collision retrieval — mechanism-specific 6mo retrieval via signature_terms[]
- ✅ Phase 3.2 audit — 3 corpus-anchored checks + 2-layer verdict (advance / revise / abandon)
- ✅ Phase 3.3 revise — kill-switch byte-identical preservation under audit's revision_targets
- ✅ Phase 4.1 expansion — full idea-card content generation
- ✅ Phase 4.2 render — PDF + Markdown + LaTeX outputs
- ✅ kill_switch_integrity validator — both routes (advance: Phase 2 → 4; revise: Phase 2 → 3.3 → 4)
- ✅ expansion_completeness validator — soft-warns on missing structural sections

## What needs eval validation

- Inter-rater reliability of the 3 audit checks across multiple queries (does the LLM consistently flag the same borderlines?)
- Phase 2.1 selection consistency — does the same query reproduce the same ranked top-3 across runs?
- Phase 3.2 paper-pointed threat search recall — does it surface threats the user manually flags as relevant?
- Phase 3.3 revision quality — does the revision actually address the audit's revision_target, or just paraphrase the issue?
- Soft judgment vs hard floor calibration in Phase 3.2's two-layer verdict — are the right cases routed to each layer?
- Cross-domain coverage — does the skill produce reasonable candidates outside the diffusion / RLHF queries already validated?
- Output usefulness — would a domain expert use the idea card as the basis for a paper / project?

These are the primary questions for the first iteration loop.

## Eval prompts (`evals.json`)

The starter set covers:

1. **Bottlenecked direction within an active subfield** — diffusion sampling acceleration via consistency distillation
2. **RLHF overoptimization** — reward-model overoptimization mitigation
3. **OOD too-vague query** — should route to `do_not_generate.md`
4. **Stretch direction** — pushing toward an Oral-shape outside common compositions
5. **Outside-taxonomy direction** — should produce a candidate with `outside_taxonomy: true`

See [evals.json](evals.json) for the full prompts.
