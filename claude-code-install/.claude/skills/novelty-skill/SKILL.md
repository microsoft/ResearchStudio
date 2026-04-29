---
name: novelty-skill
description: "Generate Oral-level ML research ideas using 18 data-driven innovation lenses extracted from 1,370 ICLR/NeurIPS/ICML papers (2020-2025). Includes three-way contrastive methodology (Oral vs High-Cited vs Rejected), failure mode warnings, and framing strategy. Use when user asks for research ideas, novelty analysis, or innovation guidance."
user-invocable: true
argument-hint: "[research problem description]"
allowed-tools: Read, Grep, Glob, Bash, Agent, WebFetch, WebSearch
---

# NoveltySkill v3 — Data-Driven Innovation Engine

From 1,370 ICLR+NeurIPS+ICML 2020-2025 papers (1,024 Oral + 239 High-Cited + 132 Rejected), we discovered 18 innovation patterns via unsupervised clustering, each with a complete methodology built from three-way contrastive analysis.

## 18 Innovation Lenses

These are **thinking tools**, not classification labels. You don't need to "match" the user's problem to one lens. Instead, use the most promising lenses to generate deep, specific reasoning about the problem.

| # | Lens | Core Question | When to reach for it |
|---|------|--------------|---------------------|
| C00 | **Security Inversion** | Can I invert an existing technique's role? | A tool designed for purpose A could achieve the opposite purpose B |
| C01 | **Expressivity Analysis** | What structural bottleneck limits current methods? | A model class has a known ceiling that adjacent-field math can break |
| C02 | **Causal Identification** | Does causal structure give stronger guarantees? | Statistical methods fail where causal reasoning succeeds |
| C03 | **Cross-Domain Reframing** | Has another domain already solved this? | A proven technique exists elsewhere but no one adapted it here |
| C04 | **Objective Reframing** | Can the system supervise itself? | The bottleneck is the supervision source, not model capacity |
| C05 | **Symmetry Exploitation** | What symmetry does the problem respect? | A missing structural constraint makes the problem harder than necessary |
| C06 | **Domain-Knowledge Injection** | What domain structure is being ignored? | Domain experts know the right unit/constraint but it's not in the model |
| C07 | **Probabilistic Reformulation** | Does a different math language reveal the solution? | The current formulation hides the correct solution class |
| C08 | **Compositional Decomposition** | Can I decompose this into sub-operations? | A monolithic model fails but could succeed step-by-step |
| C09 | **Diagnostic Metric Design** | Does the standard metric measure the right thing? | The evaluation conflates two distinct phenomena |
| C10 | **Framework Import** | Has a non-ML field solved the same problem? | Org theory, psychophysics, economics have validated solutions |
| C11 | **Assumption Inversion** | What untested assumption do all methods share? | Every method assumes X, but inverting X removes a failure mode |
| C12 | **Loss Redesign** | Is the loss function mathematically flawed? | The training objective has a named structural defect |
| C13 | **Game-Theoretic Reformulation** | Which component causes intractability? | Only one bottleneck component needs substitution |
| C14 | **Formal Characterization** | What structural property has been overlooked? | Generic tools fail but a problem-specific property enables tight bounds |
| C15 | **Variational Reformulation** | Can I rewrite "what to compute" as an optimization? | An intractable quantity is the solution to a tractable program |
| C16 | **Structural Reparameterization** | Does parameter geometry reveal a better path? | A compute-expressiveness tradeoff hides an algebraic shortcut |
| C17 | **Convergence Analysis** | Is the standard assumption a proof artifact? | A widely-used assumption is unnecessary; a weaker one suffices |

Each lens has a complete methodology in `methodologies.md`: step-by-step procedure, success conditions (from Oral), failure modes (from Rejected), impact drivers (from High-Cited), cognitive barriers, and reviewer expectations.

## Two-Level Hierarchy

The 18 lenses organize into 9 meta-categories. Use this for coarse-to-fine reasoning:

| Meta-Category | Lenses | Core Question |
|--------------|--------|--------------|
| **Cross-Domain Transfer** | C03 + C10 | Has another domain solved this? |
| **Theoretical Formalization** | C01 + C14 + C17 | Can we prove formal properties? |
| **Structural Diagnosis & Redesign** | C12 + C16 | Is the objective/parameterization flawed? |
| **Sequential Decision & Game Theory** | C04 + C13 | Can we reframe what to optimize? |
| **Symmetry & Domain Structure** | C05 + C06 | What structural constraint is missing? |
| **Compositional & Process Innovation** | C08 + C09 | Can we decompose and supervise steps? |
| **Mathematical Reformulation** | C07 + C15 | Does a different math language help? |
| **Assumption & Role Inversion** | C00 + C11 | What shared assumption can we challenge? |
| **Causal Identification** | C02 | Does causal structure give stronger guarantees? |

## Proven Lens Combinations

52% of top-conference papers combine two innovation strategies. The most successful combinations:

| Combination | Papers | Meaning |
|------------|--------|---------|
| C16 + C17 (Reparameterization + Convergence) | 89 | Geometric insight enables theoretical proof |
| C03 + C07 (Cross-Domain + Probabilistic) | 75 | Import technique + recast in new math language |
| C08 + C10 (Compositional + Framework Import) | 59 | Decompose task + import evaluation framework |
| C12 + C15 (Loss Redesign + Variational) | 55 | Diagnose loss flaw + fix via variational formulation |
| C03 + C11 (Cross-Domain + Assumption Inversion) | 52 | Import technique + challenge domain assumption |

Within-meta combinations (e.g., C16+C17) reinforce depth; cross-meta combinations (e.g., C03+C11) create novel hybrids.

## Workflow

### Phase 1: Understand the Problem
Do NOT jump to solutions. First understand:
- What is the **essential bottleneck**? (not the surface symptom)
- Why are current methods **specifically** insufficient? (root cause, not "they don't work well")
- What would a **perfect solution** look like? (helps identify the gap)

### Phase 1.5: Recent Literature Grounding (MANDATORY)

**Why this phase exists**: The 18-lens library and your internal training data both have time cutoffs. Without a live literature check, the novelty audit only compares against stale knowledge and the LLM may propose ideas that have already been published on arXiv in recent months. This phase grounds the reasoning in **what the community has actually tried in the last 24 months (including the most recent weeks)**.

**Date window**: `[today - 24 months, today]`. No recent-months exclusion — the most recent work IS included so the audit stays fully current. Papers < 2 months old are still flagged as concurrent work in the output, but they are not filtered out.

**Procedure**:
1. **Formulate queries** — extract 2-4 search queries from the user's problem: one broad-domain query, one method-signature query, one most-similar-problem query, optionally one application-angle query.
2. **Search arXiv** — use `WebFetch` on `http://export.arxiv.org/api/query?search_query=all:<query>&sortBy=submittedDate&sortOrder=descending&max_results=50`. Filter to the 24-month window.
3. **Search Google Scholar** — use `WebSearch` with query format `"<query>" site:scholar.google.com <YEAR_RANGE>` or `WebFetch` on `https://scholar.google.com/scholar?q=<query>&as_ylo=<Y1>&as_yhi=<Y2>`. Filter to the window.
4. **Merge & dedup** — union both sources, dedup by normalized title (lowercase, punctuation-stripped, first 80 chars). Prefer the arXiv record (has full abstract + date); attach Google Scholar citation count when available.
5. **Select top-15** by (citation_count, relevance) descending.
6. **Per-paper lens classification** — for each of the top-15, read title + abstract and assign its **primary lens** from the 18 lenses. Output `"primary_lens": "C##"` plus a 1-sentence justification.
7. **Compute lens distribution** — count how many of the 15 papers fall into each of the 18 lenses and each of the 9 meta-categories.
8. **Summarize** — 3-5 sentence summary: "In the last 24 months, the dominant approaches to this problem are …; open problems the community has not solved are …".

**If both searches fail** (network down, rate-limited, 0 results): emit a `⚠️ Literature check unavailable: <reason>` warning in Phase 1.5 output and **continue** to Phase 2 using only the internal pattern library. Do NOT silently skip this phase — the warning is load-bearing for the final novelty assessment.

**Output of Phase 1.5** (always shown, even if warned):
- Query list
- Date window actually used
- Top-5 most-related papers (title, 1-line TL;DR, primary lens, citation count, arxiv/DOI)
- Lens distribution over top-15 (e.g., `C11: 7, C03: 3, C09: 2, …`)
- Over-saturated lenses (lenses ≥ 40% of recent work → warn for Phase 2b)
- Under-used lenses (lenses ≤ 5% of recent work in this domain → candidate for Phase 2b)
- Any concurrent work (within last 2 months of the window) noted separately as "not blocking but awareness"

**Feeds Phase 2**: the distribution in Phase 1.5 directly informs the unconventional-vs-primary lens decision in Step 2b. Saturated lenses lose priority even if they are the domain default.

### Phase 2: Hierarchical Lens Reasoning

**Step 2a: Meta-category scan** — Quickly scan the 9 meta-categories. For each, ask its core question against the user's problem. Identify 2-3 meta-categories where the answer is "yes" or "maybe".

**Step 2b: Domain-aware prioritization** — Within promising meta-categories, consult `domain-analysis.md` for which specific lenses are most/least common in the user's domain:
- **Primary lenses** (top patterns for this domain): proven strategies, start here
- **Unconventional lenses** (rare in this domain): higher novelty if they apply

**Step 2c: Deep reasoning** — Select 3-5 lenses across 2+ meta-categories. For each, reason to mathematical/algorithmic depth:
- A specific mathematical formulation or algorithm design
- A provable theoretical proposition
- A concrete, implementable experimental protocol

If reasoning stays at "we could try X approach" level, it's not deep enough. Push further.

**Step 2d: Combination exploration** — This is where the best ideas emerge. Explicitly try:
- **Within-meta combination**: two lenses from the same meta-category reinforce each other (e.g., C12 diagnoses the flaw, C16 exploits parameter geometry to fix it)
- **Cross-meta combination**: two lenses from different meta-categories create novel hybrids (e.g., C03 imports a technique + C11 inverts a domain assumption to make it work)
- Consult the "Proven Lens Combinations" table above — these are empirically validated by 50+ papers each

**Step 2e: Beyond-lens exploration (when needed)** — Trigger this when:
- Phase 2a scan yields no strong "Yes" for any meta-category
- Phase 2c reasoning stays surface-level for all lenses tried
- Phase 4 audit finds the idea is insufficiently novel (too close to existing work)

Four exploration strategies for breaking out of the 18 known lenses:

1. **Lens Intersection**: What lies at the intersection of two lenses that neither covers alone? E.g., C11 (Assumption Inversion) × C09 (Diagnostic Metric) = what if the evaluation metric itself embodies the untested assumption? This is not "combining two lenses" (Step 2d) — it's asking what the **gap between** two lenses reveals.

2. **Dimension Discovery**: What dimension do all 9 meta-categories collectively ignore? They all modify the **method** — can you instead change the problem definition space, the researcher-model interaction paradigm, or the scientific workflow itself?

3. **Disciplinary Reframing**: How would a completely different discipline see this problem? Not importing a tool from another field (that's C03/C10), but adopting another discipline's **worldview** to reconceptualize the problem. E.g., an ecologist might see a model ensemble as a species community with niche competition; a historian might see benchmark evolution as paradigm shifts.

4. **Future Backcasting**: Assume the problem is perfectly solved 3 years from now. What does the solution look like? Work backwards — what was the single most critical breakthrough that enabled it? That breakthrough is your research target. This bypasses incremental thinking by starting from the end state.

### Phase 3: Idea Generation
From the deepest reasoning (typically a lens combination, or from beyond-lens exploration), form **one concrete research idea**.

### Phase 4: Quality Audit
Before presenting, check against:
1. **Failure modes** — read the relevant lens's failure modes in `methodologies.md`. Does your idea fall into any?
2. **Reviewer expectations** — what will reviewers specifically look for? Does your idea deliver?
3. **Oral vs Rejected gap** — the single most important differentiator for your lens. Does your idea clear it?
4. **Combination coherence** — if using two lenses, do they genuinely complement each other, or is the combination forced?
5. **Alternative lenses** — quick scan: is there an obviously better angle from another meta-category?
6. **Concurrent-work check (MANDATORY, live search)** — run a second, focused literature search scoped to the idea itself:
   - Extract 3-5 signature terms from the idea's title + core approach.
   - Re-run arXiv + Google Scholar on those terms with the same `[today-24mo, today]` window, top_k=10.
   - For each returned paper, judge semantic overlap with the generated idea: **low / medium / high (≥70% method or claim overlap)**.
   - **High overlap** → the idea is scooped. Return to Phase 2 (prefer a different lens combination or Phase 2e beyond-lens strategy) and regenerate. Do not output a scooped idea.
   - **Medium overlap** → treat as strong baseline; add explicit differentiation to the Differentiation section.
   - **Concurrent (< 2 months old)** → note as "concurrent work, not blocking" in Phase 5 Timing.
   - If the search fails, emit `⚠️ Concurrent-work check unavailable` and continue.

### Phase 5: Framing Strategy

**Hook**: What is the surprising observation or counterintuitive finding that opens the paper? Every Oral paper has one. If your idea doesn't, it's not ready.

**Scope calibration**:
- Too broad ("a general framework for X") → reviewers ask "does it work for every case?"
- Too narrow ("2% improvement on dataset Y") → incremental
- Right scope: deep insight on a representative problem + argued generalizability

**Narrative arc**: Observation → Diagnosis → Solution → Dual validation (theory + experiments) → Broader implication

**Timing** (consult `domain-analysis.md`):
- Pattern rising in your domain → timely, submit now
- Pattern saturated → need qualitative breakthrough to stand out
- Pattern never seen in your domain → high risk / high reward

**Impact strategy** (from High-Cited analysis):
- To maximize citations: provide **infrastructure** (tools, datasets, benchmarks) not just methods
- "Solving a problem earns Oral; becoming what everyone uses earns citations"

## Output Format

### 1. Problem Understanding
- **Essential bottleneck**: [one sentence]
- **Root cause of current insufficiency**: [why, specifically]

### 1.5 Recent Literature Grounding
- **Date window used**: [YYYY-MM-DD → YYYY-MM-DD]
- **Queries**: [list of 2-4 queries]
- **Top-5 relevant papers**: [title | primary_lens | citations | source]
- **Lens distribution (top-15)**: [e.g., C11: 7, C03: 3, C09: 2, …]
- **Saturated lenses**: [≥40% of recent work]
- **Under-used lenses**: [≤5% of recent work — candidates for novelty]
- **Unsolved gaps noted**: [2-3 bullets]
- **Concurrent work (<2mo, non-blocking)**: [0-3 items]
- **Warning (if any)**: ⚠️ [reason]

### 2. Lens Reasoning
**Meta-category scan**: [which 2-3 meta-categories are relevant and why]
**Selected lenses**: [which 3-5 specific lenses, from which meta-categories]
**Per-lens reasoning**: [for each lens, the specific reasoning. Must reach mathematical/algorithmic depth.]
**Combination**: [which lens combination works best and why they complement each other]

### 3. Research Idea

**Title**: [paper-level title]

**Research Question**: [one clear question]

**Core Approach**: [3-5 sentences, specific enough to start implementing: input, output, key algorithm/model]

**Differentiation**:
- vs [most related work 1]: they did X, we do Y, key difference is Z
- vs [most related work 2]: ...
- vs [most related work 3]: ...

**Expected Contributions**:
- Theory: [what theorem/property/bound, if any]
- Method: [what new method/framework/algorithm]
- Empirical: [what new finding/benchmark/insight]

**Experiment Plan**:
- Datasets: [what data]
- Baselines: [who to compare against]
- Key metrics: [what to measure]
- Core experiment: [what proves your claim]
- Ablation: [what to remove to show each component matters]

**Key Technical Challenges**: [hardest 1-2 points + initial solution ideas]

### 4. Quality Audit
- **Failure mode check**: [did you check against `methodologies.md` failure modes?]
- **Reviewer will ask**: [2-3 most likely challenges]
- **Response plan**: [how to address each]
- **Concurrent-work check**: [queries used | top-10 overlap classification | any high-overlap paper that forced regeneration | concurrent (<2mo) items]

### 5. Framing
- **Hook**: [the surprising finding that opens the paper]
- **Scope**: [is the claim calibrated correctly?]
- **Narrative arc**: [observation → diagnosis → solution → validation → implication]
- **Timing**: [is this pattern rising/stable/falling in your domain?]

### 6. Abstract Draft
[150-250 words: surprising finding → root cause → our method → key results → broader significance]

## Reference Files
- `methodologies.md` — complete methodology for each of the 18 lenses (step-by-step, success/failure conditions, impact drivers, cognitive barriers, reviewer expectations, examples)
- `domain-analysis.md` — yearly trends, conference preferences, PC bias analysis, timing guidance
- `pitfalls.md` — failure mode checklist organized by lens (quick reference during quality audit)
