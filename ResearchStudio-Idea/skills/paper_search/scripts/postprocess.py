#!/usr/bin/env python3
"""Post-processing for paper_search: cross-source dedup, relevance ranking,
survey tagging, and (opt-in) noise filtering.

Design contract (mirrors the skill's full-recall philosophy):
- Dedup NEVER loses information: duplicates collapse into one record that
  keeps the highest-priority source's fields, fills gaps from the others,
  takes the max citation count, and lists every source in `found_in`.
- Ranking SORTS, it does not drop. The only dropping path is the explicit
  `min_score` opt-in, and the caller is told exactly how many were dropped.
- Surveys are TAGGED and sunk to the bottom, never removed.

The lexical scorer and survey regex are ports of the idea_spark literature
pipeline's equivalents (kept as an independent copy: the two skills must stay
standalone-installable).
"""
import re

# Display/priority order: highest-signal source first. Dedup keeps the record
# from the earliest source in this list; the CLI prints groups in this order.
CANONICAL_ORDER = ["semantic_scholar", "open_alex", "arxiv", "openreview",
                   "crossref", "dblp"]

_STOP = {"with", "from", "that", "this", "into", "over", "under", "then",
         "than", "them", "their", "through", "based", "using", "toward",
         "towards", "via", "what", "when", "where", "which", "will", "have",
         "been", "does", "about"}

_SURVEY_RE = re.compile(
    r"^(a |an )?(comprehensive |systematic |brief )*(survey|review|meta-analysis)\b"
    r"|:\s*(a )?(comprehensive |systematic )*(survey|review)\b",
    re.I)


def title_norm(t) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in (t or "")).split())


def norm_doi(d) -> str:
    d = (d or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def norm_arxiv(a) -> str:
    a = (a or "").strip().lower()
    a = re.sub(r"^(arxiv:)", "", a)
    return re.sub(r"v\d+$", "", a)  # 2401.12345v2 -> 2401.12345


def is_survey(title) -> bool:
    return bool(_SURVEY_RE.search(title or ""))


def term_words(queries) -> set:
    """Content words (>3 chars, non-stopword) across one or more queries."""
    words = set()
    for q in queries:
        for w in re.split(r"[^a-z0-9]+", str(q or "").lower()):
            if len(w) > 3 and w not in _STOP:
                words.add(w)
    return words


def relevance_score(paper, words) -> int:
    """Count of query content-words appearing in title+abstract.
    startswith gives crude stemming: 'watermark' matches 'watermarking'."""
    text = ((paper.get("title") or "") + " " + (paper.get("abstract") or "")).lower()
    tokens = set(re.split(r"[^a-z0-9]+", text))
    return sum(1 for w in words if any(tok.startswith(w) for tok in tokens))


def _source_priority(source) -> int:
    try:
        return CANONICAL_ORDER.index(source)
    except ValueError:
        return len(CANONICAL_ORDER)


_FILL_FIELDS = ("abstract", "venue", "publication_date", "doi", "arxiv_id",
                "url", "year")


def dedup(results) -> list:
    """Collapse cross-source duplicates. `results` is {source: [paper, ...]}.

    Matching keys, in strength order: normalized DOI, normalized arXiv id,
    normalized title. A paper joins an existing cluster if ANY key matches
    (so a DOI-only record and a title-only record of the same paper merge).
    Returns merged papers; each carries `found_in` (canonical-order source
    list) and max `citation_count`; missing fields are filled from dups.
    """
    clusters: list[dict] = []
    by_doi: dict[str, int] = {}
    by_arxiv: dict[str, int] = {}
    by_title: dict[str, int] = {}

    ordered = []
    for source in sorted(results.keys(), key=_source_priority):
        for p in results.get(source) or []:
            ordered.append(p)

    for p in ordered:
        doi = norm_doi(p.get("doi"))
        arx = norm_arxiv(p.get("arxiv_id"))
        tit = title_norm(p.get("title"))
        idx = None
        for key, table in ((doi, by_doi), (arx, by_arxiv), (tit, by_title)):
            if key and key in table:
                idx = table[key]
                break
        if idx is None:
            rec = dict(p)
            rec["found_in"] = [p.get("source")]
            clusters.append(rec)
            idx = len(clusters) - 1
        else:
            rec = clusters[idx]
            src = p.get("source")
            if src and src not in rec["found_in"]:
                rec["found_in"].append(src)
            rec["citation_count"] = max(rec.get("citation_count") or 0,
                                        p.get("citation_count") or 0)
            for f in _FILL_FIELDS:
                if not rec.get(f) and p.get(f):
                    rec[f] = p[f]
        # register ALL keys of this paper against the cluster, so later
        # records matching by a different key still land in the same cluster
        for key, table in ((doi, by_doi), (arx, by_arxiv), (tit, by_title)):
            if key and key not in table:
                table[key] = idx

    for rec in clusters:
        rec["found_in"].sort(key=_source_priority)
    return clusters


def rank(papers, queries, min_score=None):
    """Score, tag surveys, sort (non-surveys by score desc then citations desc;
    surveys sunk to the bottom in the same order). Returns (ranked, n_dropped);
    n_dropped is 0 unless min_score is set (opt-in dropping only)."""
    words = term_words(queries)
    for p in papers:
        p["relevance_score"] = relevance_score(p, words)
        p["is_survey"] = is_survey(p.get("title"))
    n_dropped = 0
    if min_score is not None:
        kept = [p for p in papers if p["relevance_score"] >= min_score]
        n_dropped = len(papers) - len(kept)
        papers = kept
    papers.sort(key=lambda p: (p["is_survey"],
                               -p["relevance_score"],
                               -(p.get("citation_count") or 0)))
    return papers, n_dropped
