---
name: paper-search
description: Search papers across arXiv, DBLP, OpenAlex, OpenReview, Semantic Scholar, and Crossref for a given query and year range, using ./scripts/search_papers.py. Use when the user asks to find papers, related work, prior art, or recent publications on a specific topic, especially when they mention a date range or specific venues like NeurIPS, ICLR, or ICML.
---

# Paper Search Skill

Unified paper search across **arXiv**, **DBLP**, **OpenAlex**, **OpenReview**
(NeurIPS / ICLR / ICML), **Semantic Scholar**, and **Crossref** using
`./scripts/search_papers.py`. All sources are searched **concurrently** (in
independent child processes) by default for maximum speed. Queries within one
source remain serial. Returns results grouped by source.


## When to use

Trigger this skill when the user asks things like:
- "Find papers on X published between 2023 and 2025."
- "Search NeurIPS / ICLR / ICML for work on X."
- "Get arXiv + Semantic Scholar results for X."
- "Show me recent prior art on X."

## Inputs (all auto-inferred — NEVER ask the user for confirmation or clarification)

Derive these automatically from the user's message. Run the search immediately without asking for confirmation:
- **query**: Rephrase the user's question into a focused search phrase.
- **start_year** (int): If the user gives a year, use it directly. If they say
  "last 2 years", compute from today. Default: 2 years ago.
- **end_year** (int): Default: current year.
- **max_papers** (int): Number of results per source. Default: 10.
- **sources**: Which sources to query. Default: all 6 API sources plus the
  model-knowledge source, in this canonical order (highest-signal first, so
  the best results render before the user scrolls):
  `semantic_scholar open_alex arxiv openreview crossref dblp model_knowledge`.
  Only restrict sources if the user explicitly asks.

## How to run

Preferred: call the CLI directly. The script lives at
`${CLAUDE_PROJECT_DIR}/skills/paper_search/scripts/search_papers.py` — invoke
it by absolute path so the command works regardless of the current working
directory (relying on `cd scripts && ...` breaks when the model is running
from a different folder, which happens often).

For brevity in the examples below, treat `$SEARCH` as shorthand for that
absolute path:

```bash
SEARCH="${CLAUDE_PROJECT_DIR}/skills/paper_search/scripts/search_papers.py"
```

Basic search:

```bash
python "$SEARCH" \
    --query "<QUERY>" \
    --start-year <YYYY> \
    --end-year <YYYY> \
    --max-papers 10
```

To restrict to specific sources:

```bash
python "$SEARCH" \
    --query "<QUERY>" \
    --start-year 2024 --end-year 2026 \
    --sources arxiv semantic_scholar openreview
```

Multi-query union (each query hits every source; results are unioned, deduped,
and ranked against the combined term set):

```bash
python "$SEARCH" \
    --queries "diffusion watermarking|latent-space watermark|generative model IP protection" \
    --start-year 2024 --end-year 2026
```

Opt-in noise filter (drops papers with relevance score below N; the CLI always
prints exactly how many were dropped — omit for full recall):

```bash
python "$SEARCH" --query "<QUERY>" --start-year 2024 --end-year 2026 --min-score 2
```

Legacy per-source view (no dedup, no ranking — raw connector output):

```bash
python "$SEARCH" --query "<QUERY>" --start-year 2024 --end-year 2026 --raw
```

To disable parallel execution (rarely needed):

```bash
python "$SEARCH" \
    --query "<QUERY>" \
    --start-year 2024 --end-year 2026 \
    --no-parallel
```

`--no-parallel` still uses an isolated worker process for each source, but runs
those workers in source order instead of starting them together.

Or call the function directly when more control is needed (e.g. consuming the
structured dict rather than CLI text output). This is rarely necessary — see
`references/programmatic_api.md` for the snippet.

## Valid source names

| Source | Key |
|:---|:---|
| arXiv | `arxiv` |
| DBLP | `dblp` |
| OpenAlex | `open_alex` |
| OpenReview | `openreview` |
| Semantic Scholar | `semantic_scholar` |
| Crossref | `crossref` |
| Model knowledge (LLM recall, no API call) | `model_knowledge` |

## Output schema

`search_papers()` returns a dict mapping source name to a list of paper dicts:

```
{
  "arxiv": [
    {
      "title": str,
      "authors": [str, ...],
      "year": int,
      "abstract": str,
      "url": str,
      "venue": str,
      "citation_count": int,
      "publication_date": str,
      "source": str,
      "doi": str | None,
      "arxiv_id": str | None
    }, ...
  ],
  "semantic_scholar": [...],
  ...
}
```

CLI output (default): a single **deduped, relevance-ranked** list. Cross-source
duplicates are merged into one record (matched by DOI, then arXiv id, then
normalized title) that keeps the highest-signal source's fields, the max
citation count, and a `Sources:` provenance line; every paper carries a
lexical relevance score against the query; survey/review-titled papers are
tagged `[survey]` and sunk to the bottom (never dropped). Nothing is filtered
unless `--min-score` is passed, and then the drop count is printed. A
per-source hit-count line plus "N cross-source duplicate records merged"
precedes the list. `--raw` restores the legacy grouped-by-source printout.

## Output to the user

After running, display every unique paper in the CLI's ranked order (it is
already deduped and sorted by relevance), then the Model Knowledge section,
then a summary. With `--raw`, fall back to per-source groups in this order:
Semantic Scholar, OpenAlex, arXiv, OpenReview, Crossref, DBLP, Model Knowledge.

Why full recall matters: users invoking this skill are doing literature reviews,
related-work surveys, or prior-art checks. The value comes from seeing the
complete set of hits — a missed paper can mean a missed citation or a
duplicated research effort. Summaries are meant to *augment* the full tables,
not replace them, so don't collapse results into a digest "to save space."
The user can skim; they can't un-skip a paper they never saw.

### Step 1: Display ALL results

Default (unified ranked view): display every unique paper in ONE markdown
table, preserving the CLI's rank order. Prefix `[survey]` in the Title cell
where tagged. Reproduce the CLI's per-source hit counts + merged-duplicates
line above the table, and the drop count line when `--min-score` was used.

```
per-source hits: semantic_scholar=10, open_alex=10, arxiv=10 … · 22 unique (8 duplicates merged)

| #   | Title       | Date    | Venue   | Citations | Score | Sources |
|-----|-------------|---------|---------|-----------|-------|---------|
| [1](paper url) | Title here | 2024-03 | NeurIPS | 42 | 5 | SS, arXiv |
| [2](paper url) | [survey] Title here | 2023-11 | ICLR | 10 | 4 | OpenAlex |
```

With `--raw`: one table per source under a source heading (legacy format).
If a source returned 0 results, note it explicitly
(e.g. "### OpenReview (0 papers) — No matches found in this window").

If errors occurred during search, they are printed to stderr by the script —
surface them to the user, never hide them.

### Step 2: Summary of all searched results

After displaying all papers, provide a **comprehensive summary** with the
following sections, in this exact order:

1. **Overview**: query used, year range, and total number of papers found. One or
   two sentences framing what the corpus covers.
2. **Trends**: Temporal patterns (e.g. "interest surged in 2024"), dominant
   venues, methodological shifts, and recurring author groups or labs.
3. **Key themes**: 3–6 main research themes / clusters across all results,
   each with a one-line description and 2–3 representative paper numbers.
4. **Keywords frequency**: A table of the most frequent technical terms /
   concepts extracted from titles (abstracts are in the JSON schema but not
   printed by the CLI), with counts. Format:
   `| Keyword | Count |`. Include the top 5.
5. **Most cited by accepted paper**: Top 5 most-cited accepted papers across all sources,
   ranked by citation count, as a table: `| Rank | Title | Year | Citations |`.
6. **Most cited by first author**: Top 5 first authors ranked by total citations
   accumulated across papers in this result set, as a table:
   `| Rank | Author | Papers in set | Total citations |`.
   The **Author** column must contain ONLY the author's name (e.g. `Jane Doe`).
   Do not append paper titles, affiliations, venues, or any other information
   in this column — paper counts and citation totals live in their own columns.
7. **Recommendations for reading**: 3–5 papers most relevant and impactful to the user's
   original query, ordered as a reading path (foundational → recent), each
   with a one-line justification.


## Dependencies & failure modes

- **arXiv**: uses the arXiv API.
- **DBLP**: uses DBLP API.
- **OpenAlex**: uses OpenAlex API.
- **OpenReview**: requires `pip install openreview-py`.
- **Semantic Scholar**: uses Semantic Scholar API.
- **Crossref**: uses Crossref API.
- **Model knowledge**: no API call. Papers are recalled from the model's own
  training data — fast and free, but capped by the model's knowledge cutoff
  and prone to hallucination. See the "Model knowledge source" section below
  for how to use it responsibly.

HTTP 429/500/502/503/504 responses use bounded retries. If a source still fails,
its worker prints the error and the other source workers continue. Surface those
errors to the user.

### HTTP timeout configuration

All network sources use separate connection and socket read-idle timeouts:

| Environment variable | Default | Meaning |
|:---|:---|:---|
| `PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS` | `15` | TCP/TLS connection timeout |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `300` | Time allowed with no response bytes arriving |
| `PAPER_SEARCH_<SOURCE>_TIMEOUT_SECONDS` | unset | Per-source read-idle override, e.g. `PAPER_SEARCH_OPEN_ALEX_TIMEOUT_SECONDS` |
| `PAPER_SEARCH_MAX_ATTEMPTS` | `4` | Maximum attempts including the first request |

Every configured value must be positive; malformed, zero, negative, NaN, or
infinite values fail before workers start. The 300-second read timeout is not a
total source budget: a response can take longer overall if it continues making
socket-level progress.

## Model knowledge source

The `model_knowledge` source is different from the others: it has no API and
no script call. Instead, after the CLI search returns, recall 5–10 additional
papers from your own training data that match the query and year range, and
present them as a separate source in the output.

### Why include it

API search is high-precision but low-recall in two predictable cases:
1. **Foundational older papers** that practitioners always cite but that
   keyword search misses (e.g. the original BERT or ResNet paper when the
   query is about a recent variant).
2. **Cross-disciplinary classics** that live in venues the APIs index poorly.

Model recall complements the APIs by surfacing the "everyone knows this one"
papers that don't always come back from a fresh keyword query.

### How to populate it

After the CLI run completes:

1. Reflect on what you know about the query topic.
2. List up to 10 papers from your training data that fit the query and year
   range, with: title, primary author(s), year, venue, and a one-line reason
   it's relevant.
3. Deduplicate against the API results — if a paper already appeared in any
   API source, do not repeat it under `model_knowledge`.
4. Flag confidence honestly. The model knowledge column has no citation count
   and no live URL; if you're not sure a paper exists exactly as you remember
   it, mark it `(uncertain — verify)` in the table rather than presenting it
   as confirmed.

### Why honesty matters here

Hallucinated paper titles are the classic LLM failure mode for this task. A
fake "Smith et al., 2023, NeurIPS" looks identical to a real one in a
markdown table, and the user has no way to tell. The point of this source is
to surface *real* papers the APIs missed — not to pad the list. If you can't
recall ≥5 papers with reasonable confidence, return fewer; an empty
model-knowledge section is fine and honest.

### Display format

Use the same table layout as the other sources, but the URL column may link
to a search query (e.g. an arXiv or Google Scholar search) rather than a
canonical paper URL, since you don't have a verified link:

```
### Model Knowledge (N papers, may include uncertain entries)

| #   | Title       | Year | Venue   | Notes |
|-----|-------------|------|---------|-------|
| [1](https://scholar.google.com/scholar?q=Title) | Title here | 2018 | NeurIPS | Foundational; often cited by recent work on X |
| [2](...) | Title here | 2024 | ICLR | (uncertain — verify) |
```

Replace the "Citations" column with "Notes" because you don't have a
reliable citation count from memory.

## Example

User: "Find papers on diffusion policies for robotics from 2023 to 2024."

Run (using `$SEARCH` as defined in the "How to run" section):
```bash
python "$SEARCH" \
    --query "diffusion policy robotics" \
    --start-year 2023 --end-year 2024 \
    --max-papers 10
```

To search only specific sources:
```bash
python "$SEARCH" \
    --query "diffusion policy robotics" \
    --start-year 2023 --end-year 2024 \
    --sources arxiv openreview semantic_scholar \
    --max-papers 10
```

Then read the output and summarize per the rules above.

## Important Notes

- **Log the final report.** After completing the search, write a single
  markdown file to:
  `${CLAUDE_PROJECT_DIR}/allinone.md`
  - Contents: the full **"Display ALL results from every source"** tables
    followed by the **"Summary of all searched results"** section — in that
    order, with no truncation.
- **Display the full report to the user.** Return the complete detailed
  report inline — every paper, every table, plus the analysis and reasoning.
  Never collapse the tables into a summary, and never abbreviate results to
  "save space".
- **Never ask for confirmation.** All inputs are auto-inferred (see the
  "Inputs" section). Run the search immediately on the first turn.
- **Surface errors verbatim.** If a source fails, report the stderr message
  to the user rather than hiding it or retrying blindly.
