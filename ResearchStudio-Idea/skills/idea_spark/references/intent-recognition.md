# Intent recognition

Goal: turn the user's free-text input into 4-6 search queries (map mode) or 3-5 signature terms (collision mode).

## Map mode — query extraction

Use a [CLASSIFY_FAST]-capable LLM with this system prompt:

```
You read a user's research question and extract 4-6 search queries to send to academic search APIs.

Return JSON: {"queries": ["...", "..."], "domain_hints": ["..."], "venue_hints": ["..."]}

Rules:
- Query 1: BROAD-DOMAIN — the high-level area, ~3-5 words. Example: "diffusion model sampling efficiency".
- Query 2: METHOD-SIGNATURE — the specific technical move, ~5-8 words. Example: "consistency model knowledge distillation".
- Query 3: MOST-SIMILAR-PROBLEM — the closest analogue problem, ~5-8 words. Example: "score-based generative model fast inference".
- Query 4: ESCAPE-MECHANISM — the vocabulary a paper that *already fixed* this bottleneck would title itself with, ~4-7 words. A solver paper names itself by its solution ("empirical Bayes shrinkage baseline", "global running reward statistic"), not by the problem — so queries 1-3, all keyed on the problem, systematically miss exactly the closest prior work (the paper that scoops you). Reason about 1-2 plausible solution families for the stated bottleneck and phrase this query in that SOLUTION vocabulary, not the problem's. This query is load-bearing for recall; do not skip it.
- Query 5 (optional): APPLICATION-ANGLE — domain or use-case, ~3-5 words. Example: "text-to-image generation".
- Query 6 (optional): VENUE-INSIDER — phrase a top-conference reviewer would use, ~5-8 words.

domain_hints: 1-3 lowercase tags (e.g. "nlp", "rl", "diffusion").
venue_hints: 0-3 venue names if the user mentioned them.

No quotes around individual words; no boolean operators; just plain phrases for arXiv/OpenAlex full-text search.

**OOD short-circuit (return early)**: If the user_query is too broad to produce 3-5 specific queries — i.e., it matches the parent skill's `../../idea_spark/references/intake-routing.md` OOD trigger #1 ("Too broad", e.g., "I want to do an AI paper", "give me ideas in ML", "what should I work on at NeurIPS") OR trigger #2 ("No anchor": no domain / task / data / baseline named) — DO NOT attempt to produce broad-noise queries. Return JSON `{"ood": true, "trigger_id": 1 | 2, "trigger_quote": "...", "match_evidence": "..."}` instead. The orchestrator-side handshake re-uses this signal to skip Phase 0 retrieval entirely and proceeds straight to Phase 1's do_not_generate emission. Producing broad-noise queries (e.g., "machine learning recent advances") wastes 30+ seconds of API calls on a lit_table nobody can consume; the OOD short-circuit is honest and saves the work.
```

### Worked example

User input: "I'm working on speeding up diffusion model sampling — currently I distill an EDM teacher into a student via consistency loss."

Output:
```json
{
  "queries": [
    "diffusion model sampling acceleration",
    "consistency distillation diffusion student teacher",
    "score model fast inference few step",
    "distillation-free higher-order ODE solver sampler",
    "EDM consistency model",
    "diffusion sampling efficiency reviewer"
  ],
  "domain_hints": ["diffusion", "generative-models"],
  "venue_hints": []
}
```

## Collision mode — signature extraction

Use the same [CLASSIFY_FAST] LLM with this prompt:

```
You read a candidate research idea and extract 3-5 signature terms — tightly worded phrases for phrase matching.

Return JSON: {"signature_terms": ["...", "..."]}

Rules:
- Each term is 3-7 words.
- Cover (a) the mechanism, (b) the claim, (c) the setting/setup. One term per facet, plus 1-2 specific identifiers (e.g. dataset name, theorem name).
- Avoid generic terms ("deep learning", "transformer") — they retrieve too much noise.
- Prefer noun phrases over verb phrases.
- These terms will be sent verbatim to a BM25 retriever AND embedded for cosine search.
```

### Worked example

Idea input:
```
title: "Truncated-step training for diffusion samplers"
core_mechanism: "Skip the timesteps below threshold T0 during training, where T0 is identified analytically from a Lipschitz-constant argument"
novelty_claim: "Provably reduces compute without changing terminal sample quality"
```

Output:
```json
{
  "signature_terms": [
    "diffusion sampler timestep truncation",
    "Lipschitz constant noise schedule",
    "score function singularity boundary",
    "training-free sampling acceleration",
    "EDM truncated training"
  ]
}
```

## Calibration

After running on 5-10 user examples, check:

- Do the queries actually retrieve relevant papers? If query 1 returns the same set as query 2, drop one.
- Are the signature terms specific enough to filter out generic noise? If retrieval returns 100+ papers and only 5 are relevant, the signature is too broad — re-prompt with stricter examples.
- Does the LLM produce consistent JSON across runs? If not, lower the temperature in the script.
