---
name: scoop-check
description: Check whether a proposed research novelty (given a problem statement and claimed idea/novelty) overlaps with existing published work. TRIGGER when the user asks to verify research novelty, check if an idea is new, compare a proposed contribution to prior art, do a literature/prior-art search for a specific claim, or assess whether a paper idea has been scooped. DO NOT TRIGGER for general literature reviews unrelated to a specific novelty claim, or for writing related-work sections of an already-validated idea.
---

# Scoop Check

Systematically verify whether a proposed research novelty overlaps with existing literature. The goal is to either (a) surface prior work that already covers the claim, or (b) produce a crisp, defensible "delta" statement that distinguishes the proposed contribution.

## Inputs

This skill requires exactly **two inputs** from the user:

1. **Research problem** — the specific issue, challenge, or gap in knowledge being addressed.
2. **Novelty** — the specific claimed contribution (new method, theorem, dataset, framing, or insight) that distinguishes this work from prior art.

If either input is missing, vague, or conflated (e.g., the "novelty" merely restates the problem), infer the most reasonable interpretation and proceed immediately. Do **not** use `AskUserQuestion` or pause for confirmation at any point — always proceed directly through every step.

## Procedure

Execute the steps below in order. At the start of the procedure, use `TaskCreate` to register all seven steps as tasks up front, then mark each as `in_progress` when you begin it and `completed` when you finish. The procedure is long enough that progress tracking is always worth the small overhead — without it, it's easy to skip a step (especially the per-step logging in the Important Notes) or lose track of which candidates still need a deep dive.

### Step 1 — Decompose the Novelty

Break the claimed **Novelty** into four atomic axes, presented as a labeled list:

- **Problem framing** — Task definition, inputs, outputs, and evaluation regime.
- **Core mechanism** — The technical contribution — architecture, algorithm, proof technique, or data construction.
- **Key insight** — What makes it work; what prior state-of-the-art lacked.
- **Application domain** — Where it applies and how broadly.

### Step 2 — Search and Deduplicate

Read the **Research problem** and craft three complementary search queries:

- **Query 1 — Original-Problem:** restate the original research problem.
  *Example:* `score-based generative model fast inference`
- **Query 2 — Broad-Domain:** the high-level area, ~3–5 words.
  *Example:* `diffusion model sampling efficiency`
- **Query 3 — Method-Signature:** the specific technical move, ~5–8 words.
  *Example:* `consistency model knowledge distillation`

Send all three queries to the **`paper-search`** skill (located in `.claude/skills/`). `paper-search` runs a unified query across multiple sources and returns structured JSON with title, abstract, and metadata.

Because the three queries hit arXiv as separate process invocations, pace them so adjacent arXiv requests are **≥ 4 s apart** to avoid triggering the rate limit (HTTP 429) that silently zeroes out the connector. `paper-search`'s arXiv module enforces this automatically via a cross-process file lock (`arxiv_search_throttle.lock` in the temp dir), so concurrent/back-to-back queries queue and each request fires ≥ 4 s after the previous one — you do not need to add manual sleeps, but do not bypass that module by calling arXiv directly. Override the interval only via the `ARXIV_MIN_INTERVAL` env var if needed.

Then merge the results across all three queries and deduplicate by title (normalize case and whitespace before comparing).

After the search-based results are merged, augment the set with **additional papers recalled from your own training knowledge** that are directly relevant to the Research problem or Novelty but did not surface in the search results. The reason for this step: `paper-search` depends on keyword matches against indexed sources and routinely misses landmark or tangentially-phrased prior work that you nonetheless know about — and missing the canonical reference is the most common way a novelty check fails. Add these recalled papers with the same fields as the searched ones (Title, Date, Source if known) so they flow through the rest of the pipeline identically.

Constraints on recalled papers:

- **No overlap.** Before adding a recalled paper, check it against the deduplicated search results by normalized title (and by arXiv ID / DOI when available). Skip any that are already present.
- **Mark provenance.** Tag each recalled entry with `Source: model-recall` (in addition to any URL/ID you can supply) so downstream steps know the entry did not come from a live search and may need extra verification in Step 5.
- **Stay relevant and modest in count.** Add only papers you are confident exist and are directly relevant — typically 0–5. If you cannot recall any with confidence, add none; fabricating citations is far worse than a smaller candidate pool.
- **Flag uncertainty.** If you are unsure about a recalled paper's exact date, venue, or author list, leave those fields blank rather than guessing — the deep dive in Step 5 will resolve them from the actual PDF.

The combined set (search results + non-overlapping recalled papers) is the input to the next step.

### Step 3 — Abstract-Level Triage

For every deduplicated paper, read the title and abstract and extract a first-pass record with the following fields:

- **Title** — Full paper title.
- **Date** — Publication or preprint date (YYYY-MM).
- **Problem framing** — The task, inputs, outputs, and evaluation setup the paper targets.
- **Core mechanism** — The main technical contribution — architecture, algorithm, proof technique, or data construction method.
- **Key insight** — The central idea that enables the contribution; what prior work lacked.
- **Application domain** — The field, modality, or setting where the method is applied or evaluated.
- **Overlap score (0–4)** — Number of the four axes (problem framing, core mechanism, key insight, application domain) that plausibly match the proposed novelty, judging from the abstract alone. This count feeds the 5-level verdict in Step 6 via `level = 5 − (axes matching)` (0 axes matching → Level 5 / most novel; 4 axes matching → Level 1 / fully scooped).
- **Source** — URL, arXiv ID, DOI, or other identifier needed to retrieve the full text. The hostname usually encodes the venue well enough for triage (e.g., `arxiv.org` → preprint, `openreview.net` → conference submission, publisher domains → peer-reviewed); the formal venue is captured in Step 5 once it's actually needed.

Abstracts are short and often hide the details that determine whether a paper actually scoops a contribution — methodological assumptions, scope of experiments, and limitations frequently live only in the body. The overlap score is therefore a triage signal, not a final verdict.

### Step 4 — Identify High-Potential Candidates

Select the subset of papers most likely to threaten or inform the novelty claim. The input here is the **full combined set** from Step 3 — both `paper-search` results and any non-overlapping recalled papers from Step 2's memory-augmentation pass. Apply the criteria below to every paper uniformly; do **not** auto-promote recalled papers just because you added them, and do not auto-demote them just because their Source is `model-recall`. They earn their slot the same way as anything else.

A paper is a **high-potential candidate** if **any** of the following hold:

- Overlap score ≥ 2 on the abstract pass.
- The abstract matches on **core mechanism** specifically, even if the application domain or framing differs (mechanism overlap is the most dangerous kind of overlap).
- The paper is from the same narrow subfield and published within the last 24 months, even with a lower overlap score, since recent close-neighborhood work is the most likely to have anticipated the contribution.
- The abstract is ambiguous about the method in a way that could either confirm or rule out overlap — i.e., the paper cannot be safely dismissed from the abstract alone.

Cap the candidate set at the top **3–7 papers** *after* triage — the cap applies to the post-filter selection, not the Step 3 input set, so a large search + recall pool is fine as long as you narrow it here. If more than 7 papers qualify, keep the 7 with the highest overlap score (breaking ties in favor of mechanism matches and recency). If fewer than 3 papers meet the criteria, lower the threshold and include the next-most-similar papers so that the deep-dive in Step 5 still has meaningful coverage. List the candidates explicitly with the reason each was selected.

### Step 5 — Full-Paper Deep Dive on Candidates

For each high-potential candidate, retrieve and read the full paper using the recipe below. Don't shortcut by handing the PDF URL to `WebFetch` directly — it returns a model-written summary that drops the methodological detail this step exists to capture.

**Budget per paper.** Skim, don't read end-to-end. The deep dive's purpose is to verify the four axes against the body of the paper — not to summarize the whole work. A practical heuristic: once you've quoted or referenced **three concrete passages** that together pin down the problem setup, the core mechanism, and the scope/assumptions, you have enough to fill in the verified record — stop reading. If the extracted `.txt` is unusually large (e.g., a long thesis, a survey, or a paper with extensive appendices), restrict the skim to the introduction, method, and conclusion / limitations sections and note the partial coverage in the candidate's record. If `fetch_paper.sh` fails or produces garbled output, stop early and use the graceful fallback in sub-step 4 below rather than burning the budget on retries.

1. **Resolve a PDF URL.** Start from the source link / ID recorded in Step 3. For arXiv entries, convert `https://arxiv.org/abs/<id>` to `https://arxiv.org/pdf/<id>.pdf`. For OpenReview / ACL Anthology / publisher pages, follow the "PDF" link. Use `WebFetch` first only to locate the PDF URL when it is not obvious (e.g., ask it "what is the direct PDF link on this page?").
2. **Fetch and extract with the bundled script.** Pick a `<pdf_name>` that identifies the paper (e.g., a slugified title or the arXiv ID like `2310_12345`) so multiple candidates don't clobber each other, then run:
   ```bash
   scripts/fetch_paper.sh "<PDF_URL>" "<pdf_name>"
   ```
   The script downloads to `${CLAUDE_PROJECT_DIR}/papers/<pdf_name>.pdf`, verifies the result is a real PDF (HTML error pages saved as `.pdf` are a common failure mode), extracts text with `pdftotext -layout`, and falls back through plain `pdftotext` → `pdfplumber` → `pymupdf` if needed. On success it prints `ok: …` and the final `.txt` path on the last line; on failure it prints `FAILED: <reason>` and exits non-zero.
3. **Read the extracted text.** Use the `Read` tool on the printed `.txt` path. Focus on the introduction (for claimed contributions), the method section (for the actual mechanism), the experiments section (for scope and assumptions), and the conclusion / limitations. Skim related-work for what the authors themselves consider prior art — this often surfaces additional papers to triage.
4. **Fall back gracefully.** If `fetch_paper.sh` exits non-zero (paywall, 403, dead link, scanned-image PDF that no extractor can handle), try `WebFetch` on the abstract / HTML version with a targeted question, and record the limitation explicitly. Do not pretend to have read the full paper when you have not — the deep dive's value comes from grounding judgments in the body of the work.

From the full paper, extract a richer record that **supersedes** the abstract-level entry:

| Field | What to capture (from full text) |
|-------|----------------------------------|
| **Problem framing (verified)** | Exact task setup, inputs/outputs, datasets and metrics actually used |
| **Core mechanism (verified)** | The actual algorithm/architecture/proof — including the specific technical moves, not just the headline name |
| **Key insight (verified)** | The reasoning the authors give for why the mechanism works; what they claim prior work lacked |
| **Application domain (verified)** | Concrete domains, modalities, and scales evaluated |
| **Venue (verified)** | The publication venue or repository where the paper appears (e.g., NeurIPS 2024, ICLR 2023, ACL Findings, TMLR, arXiv preprint, OpenReview submission). Use "arXiv preprint" if the paper has not yet appeared at a peer-reviewed venue, and "unknown" only if the PDF genuinely does not disclose it. |
| **Assumptions & scope** | Stated assumptions, limitations, and regimes where the method does/does not apply |
| **Closest-passage evidence** | A short verbatim quote or precise section reference grounding the overlap judgment |
| **Refined overlap** | Updated per-axis match against the proposed novelty (match / partial / differ), now grounded in the body of the paper |

If the deep dive shows that a paper initially flagged as high-overlap actually targets a different setting or uses a materially different mechanism, downgrade it and note the reason. Conversely, if the body reveals a closer match than the abstract suggested, upgrade it. The point of Step 5 is to correct the unavoidable noise in abstract-level triage before the final comparison.

### Step 6 — Compare Against the Proposed Novelty

Build a comparison as a list, starting with the proposed work and followed by each prior work. For every entry, include the same set of fields so the comparison is structured and directly readable.

Use exactly this layout — note that every `Field: value` pair sits on its own indented line:

- **Proposed work**
  - Title: —
  - Date: —
  - Source: —
  - Problem framing: …
  - Core mechanism: …
  - Key insight: …
  - Application domain: …
- **Prior work A**
  - Title: …
  - Date: …
  - Source: …
  - Problem framing: …
  - Core mechanism: …
  - Key insight: …
  - Application domain: …
- **Prior work B**
  - Title: …
  - Date: …
  - Source: …
  - Problem framing: …
  - Core mechanism: …
  - Key insight: …
  - Application domain: …

Continue the list for every prior work under consideration. For each prior work, count how many of the four axes match the proposed work (0–4) and map that count to one of **five novelty levels**, where **Level 5 is the most novel** (no axis overlaps) and **Level 1 is the least novel** (all four axes match / fully scooped). The four axes give exactly five possible match-counts, so each count corresponds 1:1 to a level: `level = 5 − (axes matching)`.

| Axes matching | Level | Label |
|---------------|-------|-------|
| 0 | 5 | **No Overlap** — most novel |
| 1 | 4 | **Low Overlap** |
| 2 | 3 | **Medium Overlap** |
| 3 | 2 | **High Overlap** |
| 4 | 1 | **Full Overlap** — fully scooped, least novel |

A higher level means **more novel** (less overlap with prior work): Level 5 = no overlapping prior work, Level 1 = a prior work matches on all four axes.

The overall verdict is determined by the strongest (most-overlapping) entry: take the **worst case** — the **minimum level** across all prior works, since the single closest prior work caps the novelty. If there are no prior works at all, the verdict is Level 5 (No Overlap). This explicit mapping is what the Report's Verdict section consumes — do not introduce a different rule there.

### Step 7 — Articulate the Delta

Produce a one-sentence delta statement in this form:

> Unlike [closest prior work], which [does X under assumption Y], the proposed work [does X′ / drops Y / extends to Z], yielding [concrete measurable benefit].

The sentence is the artifact reviewers actually care about — it names the closest prior work, the specific axis on which the proposed work diverges, and the resulting benefit. Make those three slots concrete: a generic "extends prior work to a new setting" tells the reader nothing. If the closest prior work is from Step 5's verified records, draw the assumption/mechanism phrasing directly from that record so the comparison is grounded in the body of the paper rather than the abstract.

If no crisp one-sentence delta can be written, the novelty likely overlaps with existing work and the user should reframe — say so explicitly, and identify which prior work is blocking the delta, rather than forcing a sentence that doesn't hold up.

After producing the delta, roll up the per-paper levels from Step 6 into an overall **Verdict** (take the worst case — the **minimum level** across all prior works) — exactly one of the five levels:

- **Level 5 — No Overlap (most novel)** — every entry in Step 6 was *all axes differ*, or there were no prior works at all. The delta statement stands on its own.
- **Level 4 — Low Overlap** — the closest entry matched on exactly one axis (*three axes differ*). Tangential prior work exists; the delta is comfortable.
- **Level 3 — Medium Overlap** — the closest entry matched on two axes (*two axes differ*). Related work exists; the delta is defensible but must be stated explicitly in any future write-up.
- **Level 2 — High Overlap** — the closest entry matched on three axes (*one axis differs*). Closely competing work exists; the delta hinges on a single distinguishing axis and is fragile — sharpen it or reframe.
- **Level 1 — Full Overlap (least novel)** — at least one entry matched on all four axes (*all axes match*). Matching prior work exists on all axes; recommend reframing the contribution.

State the chosen verdict label **with its level number** (e.g., "Level 3 — Medium Overlap"), then a one-paragraph justification that names the specific papers (by title) driving the decision.

Note: the *kind* of delta (new territory vs. measurable improvement vs. sideways tradeoff) is already conveyed by the sentence itself and by the verdict, so no separate category label is needed — adding one would just duplicate the verdict on a different axis and invite contradictions (e.g., a "Medium Overlap" verdict paired with a "Strictly new" label).

## Report

Render the final report inline in the conversation as a single, self-contained markdown document. Include **all** of the following sections in this exact order, with no omissions or summarization:

1. **Verdict** — exactly one of the five levels from Step 7, stated with its level number and label: **Level 5 — No Overlap (most novel)**, **Level 4 — Low Overlap**, **Level 3 — Medium Overlap**, **Level 2 — High Overlap**, or **Level 1 — Full Overlap (least novel)**.
2. **Delta** — the one-sentence delta statement from Step 7. If no crisp delta could be written, say so and identify which prior work blocks it.
3. **Decomposed claim** — the four axes from Step 1, presented as a labeled list (Problem framing, Core mechanism, Key insight, Application domain).
4. **Structured papers** — every deduplicated paper from Step 3, rendered as a markdown list. For each paper, include one bullet per field (Title, Date, Problem framing, Core mechanism, Key insight, Application domain, Overlap score, Source), matching the field list defined in Step 3. Separate papers with a blank line or a horizontal rule for readability. Do not truncate the list; if zero papers were found, state this explicitly and list the queries that returned no results.
5. **Comparison result** — the full comparison list from Step 6 (proposed work first, each prior work following), with each entry rendered as a nested bullet list of fields, followed by the per-paper level and label from Step 6's 5-level table — i.e. the axes-matching count, the level (1–5, where 5 = most novel), and the label (*all axes differ* / *three axes differ* / *two axes differ* / *one axis differs* / *all axes match*).

## Important Notes

- **Negative results are valuable.** A thorough search that returns nothing is itself evidence of novelty — document the queries used.
- **Log every step.** After completing each step, write a markdown file to `${CLAUDE_PROJECT_DIR}/step{step_number}.md` containing the step number, step name, timestamp, and the full structured result of that step. This produces one file per step, enabling downstream tooling to inspect intermediate results.
- **Display the full report.** Provide the complete detailed report — including all search results, analysis, and reasoning — not just a summary.
