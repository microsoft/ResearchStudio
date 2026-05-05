# JSON schemas

## `lit_results.json` (map mode)

```json
{
  "query": "<original user query>",
  "queries_run": ["...", "..."],
  "retrieved_at": "<ISO datetime>",
  "n_papers": <int>,
  "papers": [
    {
      "paper_id": "<source-prefixed unique id>",
      "title": "...",
      "abstract": "...",
      "year": <int>,
      "year_month": "YYYY-MM",
      "venue": "...",
      "authors": ["..."],
      "citations": <int>,
      "source": "openalex | arxiv | openreview | dblp",
      "arxiv_id": "...",
      "openreview_id": "...",
      "doi": "...",
      "paper_url": "...",
      "primary_methodology": "<methodology_id from the 13>",
      "supporting_methodologies": ["<id>", ...],
      "bottleneck_targeted": "<one sentence>",
      "open_issue": "<one sentence>",
      "resolves_problem": [
        {"methodology_id": "<id>", "what_resolved": "<one sentence; high bar — see pattern-summary-rubric.md>"}
      ],
      "retrieved_via": "arxiv | dblp | openalex | openreview | webfallback"
    }
  ],
  "retrieved_at": "<ISO datetime>",
  "lit_grounding_mode": "real | webfallback | inline_unverified",
  "warnings": ["..."]
}
```

`year_month`, `primary_methodology`, `supporting_methodologies`, `bottleneck_targeted`, `open_issue`, and `resolves_problem` are populated during Step 4 pattern summary. Pre-Step-4 papers (raw retrieval output) carry only the connector-level fields above the line.

## `lit_table.md` (map mode)

Markdown table with one row per paper, used by the parent novelty-skill's Phase 1 lens probing. Columns:

```markdown
| paper_id | year_month | venue | title | methodology tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem | retrieved_via |
|---|---|---|---|---|---|---|---|---|
| ICLR_2024_xxxx | 2024-05 | ICLR | ... | {audit, sharpen} | "i.i.d. binding in OOD regime" | "extension to non-i.i.d. unaddressed" | "" | arxiv |
| NeurIPS_2024_yyyy | 2024-12 | NeurIPS | ... | {audit} | "i.i.d. assumption" | "" | "assumption_audit_and_relax: exhausts head-init/feature-stability/data-rebalancing tradeoff for supervised OOD" | openalex |
```

- `methodology tags`: `primary_methodology` first, then `supporting_methodologies`.
- `resolves_problem`: empty string when the paper does not definitively close any innovation pattern's load-bearing problem (the common case, ~95% of rows). When non-empty, format is `<methodology_id>: <what_resolved>`; multiple entries separated by `;`.
- `retrieved_via`: which connector the paper came from. `arxiv | dblp | openalex | openreview` when retrieval was via API; `webfallback` only when `lit_grounding_mode = webfallback` and the row was retrieved via WebSearch in the absence of any working connector. The parent novelty-skill's Phase 1 spot-checks this column: > 50% `webfallback` rows downgrades the run to webfallback even if the orchestrator nominally reported `real`.
- 40-100 rows total.

The orchestrator (`novelty-skill/scripts/run.py phase0`) writes `.lit_grounding_mode` and `.retrieved_at` sentinel files alongside `lit_table.md`. These are the canonical source-of-truth for downstream phases; do not infer mode from any other signal.

## `novelty_pattern_summary.md` (map mode)

Structured markdown:

```markdown
# Pattern summary for "<query>"

**Window**: last 24 months (broad), last 4 months (fresh).
**Papers analyzed**: <n>.

## Methodology distribution (top-30 by relevance)

| Methodology | n | share |
|---|---|---|
| ... |

**Saturated** (≥40%): ...
**Under-used** (≤5%): ...

## Recent landscape narrative (3-5 sentences)

...

## Collision warnings

- arXiv:2025.xxxxx (1 month old) overlaps with the user's framing on point X.
```

## `collision_report.json` (collision mode)

See the "Output schema" section in [references/collision-rubric.md](collision-rubric.md).

## Internal paper format (for cross-source dedup)

Each connector emits papers in this shape; `dedup_merge.py` consumes them.

```json
{
  "title": "...",
  "title_norm": "<lowercase, punct-stripped, first-80-chars>",
  "abstract": "...",
  "year": <int>,
  "venue": "...",
  "authors": ["..."],
  "citations": <int or null>,
  "source": "openalex | arxiv | openreview | dblp",
  "source_id": "...",
  "doi": "...",
  "paper_url": "..."
}
```

After dedup, the merged record gets a `paper_id` of `<best_source>:<source_id>`.

## Validation

All output JSON files are schema-validated against the structures above before being returned. Failures raise; partial output is never silently emitted.

For `lit_table.md`, validation checks: 40 ≤ rows ≤ 100; every `paper_id` matches one in `lit_results.json`; `year_month` parses as YYYY-MM; `methodology tags` non-empty (use `outside_taxonomy` if no fit). The `resolves_problem` column has no minimum count — empty across all rows is allowed when the corpus has no recent settling papers.
