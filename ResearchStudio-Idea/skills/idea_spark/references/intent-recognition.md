# Intent recognition

Goal: turn the user's free-text input into 4 search queries (map mode; 3-5 with a stated reason — see the count rule below) or 3-5 signature terms (collision mode).

## Map mode — query extraction

Use a [CLASSIFY_FAST]-capable LLM with this system prompt:

```
You read a user's research question and extract 4 search queries (3-5 only with a specific reason) to send to academic search APIs.

Return JSON: {"queries": ["...", "..."], "domain_hints": ["..."], "venue_hints": ["..."]}

Rules:
- Query 1: BROAD-DOMAIN — the high-level area, ~3-5 words. Example: "diffusion model sampling efficiency".
- Query 2: METHOD-SIGNATURE — the specific technical move, ~5-8 words. Example: "consistency model knowledge distillation".
- Query 3: MOST-SIMILAR-PROBLEM — the closest analogue problem, ~5-8 words. Example: "score-based generative model fast inference".
- Query 4: ESCAPE-MECHANISM — the vocabulary a paper that *already fixed* this bottleneck would title itself with, ~4-7 words. A solver paper names itself by its solution ("empirical Bayes shrinkage baseline", "global running reward statistic"), not by the problem — so queries 1-3, all keyed on the problem, systematically miss exactly the closest prior work (the paper that scoops you). Reason about 1-2 plausible solution families for the stated bottleneck and phrase this query in that SOLUTION vocabulary, not the problem's. This query is load-bearing for recall; do not skip it.
  - **VOCABULARY-OWNERSHIP TEST — apply it before you commit this query.** Ask NOT "would my field use these words" (too weak — it passes for words my field merely borrows) but ***is my field the dominant OWNER of this phrase, or does a bigger field own it?*** Solution vocabulary is frequently OWNED by a much larger neighbouring literature, and a lexical search engine will return that literature no matter what else you add. Measured on a real run: `adaptive KV cache compression token budget policy` returned 76 in-window papers of which **3% were robotics** — the rest were LLM-serving infrastructure. Appending domain words does NOT rescue it (`+robot manipulation` → 6%, `+VLA` → 10%): you cannot pull a small field out of a big field's vocabulary by adding terms. The sibling query `retrieval augmented episodic memory embodied agent` — same escape-mechanism role, but phrased in vocabulary the embodied-AI community itself uses — scored **77%**. So: pick the solution words YOUR field OWNS ("VLA memory eviction", "keyframe retention policy"), not the generic technique name ("KV cache compression", "token pruning"). If the only solution vocabulary you can find belongs to the bigger neighbour, still write the query — it is the one channel that finds solution-named work — but expect ~5% yield and count it as the low-yield probe it is.
  - **The weak form of this test is not enough — measured.** A second blind topic ("size generalization of GNNs for combinatorial optimization") got the escape query `unsupervised size invariant neural solver`, which PASSES "would my field say this" (neural-CO papers do say "neural solver") yet still returned ~50% noise, because scientific-ML owns "neural solver" (electromagnetic NDE solvers, hyperbolic-PDE solvers, quantum eigensolvers) and the generic modifiers pulled their own crowds: `size invariant` → grid-size-invariant geoscience surrogates, `invariant` → Cardinality-Invariant PDE control and Domain-Invariant fault diagnosis, `branch` → "Cross-Branch Consistency" (an unrelated sense of the word), `unsupervised` → text classification. Compare a topic whose vocabulary its field genuinely owns: the same rule applied to diffusion watermarking gave `tree-ring semantic watermark inversion detection`, ~70% on-topic, and it pulled back exactly the solution-named papers it was aimed at (a Tree-Ring watermark paper and an inversion-based detector). **Prefer a phrase that is unusable outside your field over one that is merely common inside it.**
  - **THE CONCRETE-OBJECT TEST — apply it to EVERY query, not just the escape one.** Each query must name at least one CONCRETE OBJECT the field manipulates — an artifact, a data structure, a unit of computation you could point at in a system (`keyframe`, `tutorial video`, `skill library`, `agent trajectory`, `workflow memory`, `visuomotor policy`). A query built only from regime, property and framework names retrieves whichever field owns those names. Measured over 12 queries on 3 topics, this predicts yield where the query's ROLE does not: all six queries at >=70% on-topic named a concrete object; of the six below, four named none (`latent world model planning` 64%, `online world model adaptation during deployment` 45%, `learned dynamics model compounding error planning` 42%, `test-time adaptation world model model predictive control` 33%) and the other two paired an object with a magnet head (`memory augmented ...`, bare `... memory`, both 55%). The escape role is NOT inherently low-yield — the same role scored 92% (`keyframe memory eviction robot manipulation policy`) and 33% in this set, so a low-yield escape query is a bad query, not a cost of the role.
  - The magnets are NOUN PHRASES naming a research regime, not just adjectives: `test-time adaptation`, `model predictive control`, `world model`, `memory augmented`, `in-context learning`, `neural solver`. Each is owned by a literature far larger than yours and none contains a suspect adjective, so an adjective-keyed check passes them. Generic ML adjectives (`invariant`, `unsupervised`, `efficient`, `robust`, `adaptive`) fail the same way — they select on the modifier, not on your problem. Where a regime name is genuinely the subject, anchor it to an object rather than to another regime.
- Query 5 (add on a stated reason; a 6th is rarely justified): APPLICATION-ANGLE (~3-5 words) or VENUE-INSIDER (~5-8 words). **Default to 4.**
  - What the cap does: every connector's cap SATURATES and the merge is round-robin, so each query takes a guaranteed share of a fixed number of slots. A 5th query gets no free slots — it takes them from the other four.
  - **The risk is that the 5th query is BAD, not that it is fifth** — the same mechanism cuts both ways, and both directions are measured. Dropping low-yield queries helped: same topic, same caps, **6 queries → 10 on-topic / 3 landmark; the best 4 → 14 / 5; the best 3 → 18 / 4**, and adding one foreign-vocabulary query to a 3-query set cost 5 on-topic papers for nothing. Adding a HIGH-yield 5th also helped: at a fixed cap of 30 through the production round-robin, with the relevance call made blind, the 5th query **displaced 0 core papers and added 5** — the six it pushed out were 2 off_topic and 4 adjacent. Queries barely overlap in practice (~90% of core papers are reached by exactly ONE query, measured across 3 topics), which is why a good addition mostly adds rather than displaces.
  - So the gate is QUALITY PER SLOT, not count — and it must be decidable BEFORE retrieval, which "reaches papers the first four cannot" is not. Admit a 5th query when it (a) passes the VOCABULARY-OWNERSHIP and CONCRETE-OBJECT tests above, and (b) is phrased in a vocabulary community none of the first four sits in — a different ROLE is not enough, since role does not predict yield (over 12 queries the same ESCAPE role scored both 92% and 33%). Judge by the distinct work a query brings back, not by its purity: a 57%-on-topic METHOD-SIGNATURE query was the ONLY one to surface a landmark paper.

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
    "distillation-free higher-order ODE solver sampler"
  ],
  "domain_hints": ["diffusion", "generative-models"],
  "venue_hints": []
}
```

Four queries, not six — the 5th/6th ("EDM consistency model", "diffusion sampling efficiency reviewer") were dropped because neither reaches papers the first four cannot, and under a saturated cap each would have taken a guaranteed share from the four that do.

Note the escape query (#4) passes the native-vocabulary test: "higher-order ODE solver" is how the diffusion-sampling community itself names that solution family, so it retrieves that community's papers. The failing version of the same idea would have been a generic systems phrase like "adaptive step size scheduling", which is owned by numerical-analysis and would return that literature instead.

## Collision mode — signature + alias extraction

Use the same [CLASSIFY_FAST] LLM with this prompt:

```
You read a candidate research idea and extract TWO term sets: 3-5 signature terms (the candidate's own vocabulary) and 2-4 alias terms (other communities' names for the same mechanism).

Return JSON: {"signature_terms": ["...", "..."], "alias_terms": ["...", "..."]}

signature_terms rules:
- Each term is 3-7 words.
- Cover (a) the mechanism, (b) the claim, (c) the setting/setup. One term per facet, plus 1-2 specific identifiers (e.g. dataset name, theorem name).
- Avoid generic terms ("deep learning", "transformer") — they retrieve too much noise.
- Prefer noun phrases over verb phrases.
- These terms will be sent verbatim to a BM25 retriever AND embedded for cosine search, over a RECENT window (scoop risk).

alias_terms rules:
- Each term is 3-7 words, naming the SAME core mechanism in a vocabulary the candidate's own community does not use.
- This is a parametric-knowledge step: "if a reward-modeling / classical-CV / RL / NLP / theory group had built this mechanism 2-3 years ago, what would their titles call it?" Same-mechanism ancestors usually exist under a different name — a "goal-image conditioned scorer for task completion" is elsewhere a "goal-conditioned success detector" or "goal-image reward model".
- Do NOT paraphrase signature_terms — a paraphrase retrieves what the signature channel already retrieves. Change the community, not the wording.
- These terms run over a MULTI-YEAR window (renamed-ancestor risk).
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
  ],
  "alias_terms": [
    "annealed Langevin early stopping",
    "SDE solver step-size adaptivity bound",
    "curriculum over noise levels"
  ]
}
```

## Calibration

After running on 5-10 user examples, check:

- Do the queries actually retrieve relevant papers? If query 1 returns the same set as query 2, drop one.
- Are the signature terms specific enough to filter out generic noise? If retrieval returns 100+ papers and only 5 are relevant, the signature is too broad — re-prompt with stricter examples.
- Does the LLM produce consistent JSON across runs? If not, lower the temperature in the script.
