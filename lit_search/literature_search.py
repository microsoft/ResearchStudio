"""
Phase 1.5 / Phase 4 Recent-Literature Grounding.

Searches arXiv + Google Scholar over [today - months_back, today - exclude_recent_months],
dedupes by normalized title, and (optionally) classifies each paper's primary
innovation lens (C00-C17) via a pluggable LLM backend.

Default exclude_recent_months = 0 — the full last `months_back` months are included.
Papers < 2 months old are kept and can be flagged as concurrent work by the caller.

On failure (network down, rate-limited, 0 results), returns a result with
`warning` populated and `papers = []`. Callers MUST surface the warning.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from .backends import call_llm_json, detect_backend
from .clusters import CLUSTER_NAMES, CLUSTER_TO_META


ARXIV_API = "http://export.arxiv.org/api/query"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


# ----------------------------- helpers --------------------------------------

def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:80]


def _date_window(months_back: int, exclude_recent_months: int) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    end = now - timedelta(days=exclude_recent_months * 30)
    start = now - timedelta(days=months_back * 30)
    return start, end


# ----------------------------- arxiv ----------------------------------------

def search_arxiv(query: str, start: datetime, end: datetime, max_results: int = 50) -> list[dict]:
    date_filter = (
        f"submittedDate:[{start.strftime('%Y%m%d')}0000 "
        f"TO {end.strftime('%Y%m%d')}2359]"
    )
    search_q = f"(all:{query}) AND {date_filter}"
    params = {
        "search_query": search_q,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "NoveltySkill/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read().decode("utf-8")

    root = ET.fromstring(xml_data)
    out = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        pub_node = entry.find("atom:published", _ATOM_NS)
        if pub_node is None or not pub_node.text:
            continue
        try:
            pub = datetime.strptime(pub_node.text[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if not (start <= pub <= end):
            continue

        title_node = entry.find("atom:title", _ATOM_NS)
        summary_node = entry.find("atom:summary", _ATOM_NS)
        id_node = entry.find("atom:id", _ATOM_NS)
        title = (title_node.text or "").strip() if title_node is not None else ""
        summary = (summary_node.text or "").strip() if summary_node is not None else ""
        url_val = (id_node.text or "").strip() if id_node is not None else ""
        authors = [
            (a.find("atom:name", _ATOM_NS).text or "").strip()
            for a in entry.findall("atom:author", _ATOM_NS)
            if a.find("atom:name", _ATOM_NS) is not None
        ]
        out.append({
            "title": title,
            "authors": authors,
            "date": pub.strftime("%Y-%m-%d"),
            "abstract": summary,
            "url": url_val,
            "source": "arxiv",
            "citations": 0,
        })
    return out


# ----------------------------- google scholar -------------------------------

def search_google_scholar(query: str, start: datetime, end: datetime, max_results: int = 20) -> list[dict]:
    try:
        from scholarly import scholarly
    except ImportError:
        raise RuntimeError("scholarly not installed. pip install scholarly")

    out: list[dict] = []
    gen = scholarly.search_pubs(query, year_low=start.year, year_high=end.year)
    for i, r in enumerate(gen):
        if i >= max_results:
            break
        bib = r.get("bib", {}) if isinstance(r, dict) else {}
        pub_year = bib.get("pub_year")
        try:
            pub_year_int = int(pub_year)
        except (TypeError, ValueError):
            pub_year_int = None
        if pub_year_int is None or not (start.year <= pub_year_int <= end.year):
            continue
        out.append({
            "title": bib.get("title", ""),
            "authors": bib.get("author", []) if isinstance(bib.get("author"), list) else [bib.get("author", "")],
            "date": f"{pub_year_int}-01-01",
            "abstract": bib.get("abstract", ""),
            "url": r.get("pub_url", "") if isinstance(r, dict) else "",
            "source": "gs",
            "citations": (r.get("num_citations", 0) if isinstance(r, dict) else 0) or 0,
        })
    return out


# ----------------------------- dedup + classify ------------------------------

def merge_dedup(*paper_lists: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for papers in paper_lists:
        for p in papers:
            key = _norm_title(p.get("title", ""))
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(p)
                continue
            existing = merged[key]
            if existing.get("source") == "gs" and p.get("source") == "arxiv":
                cites = max(existing.get("citations", 0) or 0, p.get("citations", 0) or 0)
                merged[key] = dict(p)
                merged[key]["citations"] = cites
            else:
                existing["citations"] = max(
                    existing.get("citations", 0) or 0,
                    p.get("citations", 0) or 0,
                )
    return list(merged.values())


def classify_primary_lens(title: str, abstract: str, backend: Optional[str] = None) -> tuple[Optional[str], str]:
    """Classify a paper's primary lens (C00-C17). Returns (lens_id, reason)."""
    if not CLUSTER_NAMES:
        return None, "lens taxonomy unavailable"

    lens_block = "\n".join(f"C{cid:02d}: {name}" for cid, name in sorted(CLUSTER_NAMES.items()))
    prompt = (
        "Given the title and abstract below, classify the paper's PRIMARY innovation lens "
        "from the 18 lenses listed. Pick exactly one.\n\n"
        f"Title: {title}\n\n"
        f"Abstract: {(abstract or '')[:1500]}\n\n"
        "Lenses:\n"
        f"{lens_block}\n\n"
        'Output JSON only: {"primary_lens": "C##", "reason": "<=20 words"}'
    )
    try:
        result = call_llm_json(prompt, max_tokens=200, backend=backend)
    except Exception as e:
        return None, f"llm error: {type(e).__name__}: {e}"
    if not result or "primary_lens" not in result:
        return None, "classification failed"
    lens = str(result["primary_lens"]).strip().upper()
    m = re.match(r"C(\d{1,2})", lens)
    if not m:
        return None, f"invalid lens format: {lens}"
    cid = int(m.group(1))
    if cid not in CLUSTER_NAMES:
        return None, f"unknown cluster: {cid}"
    return f"C{cid:02d}", str(result.get("reason", ""))[:200]


# ----------------------------- main entry ------------------------------------

def search_recent_literature(
    query: str,
    months_back: int = 24,
    exclude_recent_months: int = 0,
    top_k: int = 15,
    classify_lens: bool = True,
    use_arxiv: bool = True,
    use_scholar: bool = True,
    backend: Optional[str] = None,
) -> dict:
    """Search arXiv + Google Scholar over the window, merge + dedup + classify."""
    start, end = _date_window(months_back, exclude_recent_months)
    warnings: list[str] = []

    arxiv_res: list[dict] = []
    gs_res: list[dict] = []

    if use_arxiv:
        try:
            arxiv_res = search_arxiv(query, start, end, max_results=50)
        except Exception as e:
            warnings.append(f"arxiv search failed: {type(e).__name__}: {e}")

    if use_scholar:
        try:
            gs_res = search_google_scholar(query, start, end, max_results=20)
        except Exception as e:
            warnings.append(f"google scholar search failed: {type(e).__name__}: {e}")

    merged = merge_dedup(arxiv_res, gs_res)
    merged.sort(
        key=lambda p: (p.get("citations", 0) or 0, -len(p.get("abstract", "") or "")),
        reverse=True,
    )
    merged = merged[:top_k]

    active_backend = (backend or detect_backend()).lower()
    if classify_lens and active_backend != "none":
        for p in merged:
            lens, reason = classify_primary_lens(
                p.get("title", ""), p.get("abstract", ""), backend=active_backend
            )
            p["primary_lens"] = lens
            p["lens_reason"] = reason
            time.sleep(0.3)
    elif classify_lens and active_backend == "none":
        warnings.append(
            "no LLM backend detected — lens classification skipped. "
            "Set OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY, "
            "start Ollama, or set NOVELTY_LLM_BACKEND."
        )
        for p in merged:
            p["primary_lens"] = None
            p["lens_reason"] = "no LLM backend available"

    lens_counter: Counter = Counter(
        p.get("primary_lens") for p in merged if p.get("primary_lens")
    )
    meta_counter: Counter = Counter(
        CLUSTER_TO_META.get(int(l[1:]), "?")
        for l in lens_counter.elements()
        if l and len(l) == 3
    )

    total = len(merged) or 1
    saturated = [l for l, c in lens_counter.items() if c / total >= 0.4]
    under_used = sorted(
        [
            f"C{cid:02d}"
            for cid in CLUSTER_NAMES
            if lens_counter.get(f"C{cid:02d}", 0) / total <= 0.05
        ]
    )

    if not merged and not warnings:
        warnings.append("no papers returned from any source")

    return {
        "query": query,
        "date_window": [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
        "backend": active_backend,
        "papers": merged,
        "lens_distribution": dict(lens_counter),
        "meta_distribution": dict(meta_counter),
        "saturated_lenses": saturated,
        "under_used_lenses": under_used,
        "warning": "; ".join(warnings) if warnings else None,
        "source_counts": {"arxiv": len(arxiv_res), "gs": len(gs_res)},
    }


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--months_back", type=int, default=24)
    ap.add_argument("--exclude_recent_months", type=int, default=0)
    ap.add_argument("--top_k", type=int, default=15)
    ap.add_argument("--backend", default=None,
                    help="openai / anthropic / gemini / ollama / none. "
                         "If unset, auto-detect via env vars.")
    ap.add_argument("--no_classify", action="store_true")
    args = ap.parse_args()

    res = search_recent_literature(
        args.query,
        months_back=args.months_back,
        exclude_recent_months=args.exclude_recent_months,
        top_k=args.top_k,
        classify_lens=not args.no_classify,
        backend=args.backend,
    )
    json.dump(res, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
