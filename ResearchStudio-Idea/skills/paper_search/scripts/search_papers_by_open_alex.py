#!/usr/bin/env python3
"""Search for academic papers using the OpenAlex API."""

import argparse
import os
import time

from _http_runtime import create_session, request


def search_papers_by_open_alex(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on OpenAlex.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    API_KEY = os.environ.get("OPENALEX_API_KEY", "")
    url = "https://api.openalex.org/works"
    papers: list[dict] = []
    page = 1
    per_page = min(200, max_results)  # API max per request is 200
    session = create_session("PaperSearch/1.0")

    while len(papers) < max_results:
        params = {
            "search.semantic": query,
            "filter": f"publication_year:{start_year}-{end_year}",
            "sort": "relevance_score:desc",
            "page": page,
            "per-page": per_page,
            #"mailto": "your_email@example.com",  # OpenAlex polite pool
        }
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}

        response = request(
            session, "GET", url, source="open_alex", params=params, headers=headers
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            break

        for work in results:
            metadata = _source_metadata(work)
            papers.append({
                "title": work.get("title", ""),
                "authors": [
                    name for author in metadata["authors"]
                    if (name := author["raw_name"] or author["display_name"])
                ],
                "year": work.get("publication_year"),
                "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
                "url": work.get("doi") or work.get("id", ""),
                "venue": ((work.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                "citation_count": work.get("cited_by_count", 0),
                "publication_date": work.get("publication_date", ""),
                "source": "open_alex",
                "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
                "arxiv_id": None,
                "source_metadata": [metadata],
            })

        page += 1
        total_count = data.get("meta", {}).get("count", 0)

        if page * per_page >= total_count:
            break

        time.sleep(1)  # Be polite to the API

    return papers[:max_results]


def _source_metadata(work: dict) -> dict:
    """Keep provider-supplied identity and access metadata for downstream readers."""
    ids = work.get("ids") or {}
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        authors.append({
            "raw_name": (authorship.get("raw_author_name") or "").strip() or None,
            "display_name": author.get("display_name"),
            "id": author.get("id"),
            "orcid": author.get("orcid"),
        })

    locations = []
    for location in (work.get("best_oa_location"), work.get("primary_location"),
                     *(work.get("locations") or [])):
        if not location:
            continue
        entry = {
            "landing_page_url": location.get("landing_page_url"),
            "pdf_url": location.get("pdf_url"),
            "is_oa": location.get("is_oa"),
            "license": location.get("license"),
            "version": location.get("version"),
            "source_id": (location.get("source") or {}).get("id"),
        }
        if (entry["landing_page_url"] or entry["pdf_url"]) and entry not in locations:
            locations.append(entry)

    return {
        "source": "open_alex",
        "id": work.get("id"),
        "doi": work.get("doi") or ids.get("doi"),
        "pmid": ids.get("pmid"),
        "pmcid": ids.get("pmcid"),
        "is_oa": (work.get("open_access") or {}).get("is_oa"),
        "oa_status": (work.get("open_access") or {}).get("oa_status"),
        "authors": authors,
        "locations": locations,
    }


def _reconstruct_abstract(inverted_index) -> str:  # dict | None (3.9-safe: no runtime union)
    """Reconstruct abstract text from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on OpenAlex")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_open_alex(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_open_alex.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
