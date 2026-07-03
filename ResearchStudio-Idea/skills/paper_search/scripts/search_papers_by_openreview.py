#!/usr/bin/env python3
"""Search for academic papers using the OpenReview API."""

import os
import argparse
import time
from datetime import datetime
from typing import Optional

# Load credentials from .env BEFORE any os.environ.get below, so OPENREVIEW_USER/PASS are
# present even when this script is invoked directly via bash (no shell-sourced .env).
try:
    from _env import load_env_once
    load_env_once()
except Exception:
    pass


OPENREVIEW_DEFAULT_VENUES = [
    "ICLR.cc/2023/Conference",
    "ICLR.cc/2024/Conference",
    "ICLR.cc/2025/Conference",
    "ICLR.cc/2026/Conference",
    "NeurIPS.cc/2023/Conference",
    "NeurIPS.cc/2024/Conference",
    "NeurIPS.cc/2025/Conference",
    "ICML.cc/2023/Conference",
    "ICML.cc/2024/Conference",
    "ICML.cc/2025/Conference",
]


def _openreview_clients():
    """Create OpenReview API clients (v2 and v1)."""
    try:
        import openreview
    except ImportError as e:
        raise RuntimeError("openreview not installed. pip install openreview-py") from e
    v2 = openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=os.environ.get('OPENREVIEW_USER', ''),
        password=os.environ.get('OPENREVIEW_PASS', ''),
    )
    v1 = openreview.Client(
        baseurl="https://api.openreview.net",
        username=os.environ.get('OPENREVIEW_USER', ''),
        password=os.environ.get('OPENREVIEW_PASS', ''),
    )
    return v2, v1


def _or_field(content: dict, key: str, default=""):
    """Extract field from OpenReview content (handles v1 flat and v2 wrapped formats)."""
    v = content.get(key, default)
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


def _or_note_to_paper(note, venue: str) -> Optional[dict]:
    """Convert an OpenReview note to a standardized paper dict."""
    content = getattr(note, "content", {}) or {}
    title = (_or_field(content, "title", "") or "").strip()
    abstract = (_or_field(content, "abstract", "") or "").strip()
    authors = _or_field(content, "authors", []) or []
    if isinstance(authors, str):
        authors = [authors]

    cdate = getattr(note, "cdate", None) or getattr(note, "pdate", None)
    if not cdate:
        return None
    try:
        pub = datetime.utcfromtimestamp(int(cdate) / 1000)
    except Exception:
        return None

    note_id = getattr(note, "id", "") or ""
    return {
        "title": title,
        "authors": list(authors),
        "year": pub.year,
        "abstract": abstract,
        "url": f"https://openreview.net/forum?id={note_id}" if note_id else "",
        "venue": venue,
        "citation_count": 0,
        "publication_date": pub.strftime("%Y-%m-%d"),
        "source": "openreview",
    }


def _query_match(query: str, paper: dict) -> bool:
    """Check if all query tokens appear in the paper's title or abstract."""
    q = (query or "").lower().strip()
    if not q:
        return True
    hay = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    return all(tok in hay for tok in q.split())


def _fetch_venue_notes(v2_client, v1_client, venue: str) -> list:
    """Fetch notes from a venue, trying v2 API first then v1."""
    try:
        notes = v2_client.get_all_notes(content={"venueid": venue})
        if notes:
            return notes
    except Exception:
        pass
    for inv_suffix in ("/-/Blind_Submission", "/-/Submission"):
        try:
            notes = v1_client.get_all_notes(invitation=f"{venue}{inv_suffix}")
            if notes:
                return notes
        except Exception:
            continue
    return []


def search_papers_by_openreview(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
    venues: Optional[list[str]] = None,
) -> list[dict]:
    """Search for papers on OpenReview.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.
        venues: List of OpenReview venue IDs to search. Defaults to major ML conferences.

    Returns:
        List of paper dictionaries.
    """
    venues = venues or OPENREVIEW_DEFAULT_VENUES
    v2_client, v1_client = _openreview_clients()

    papers: list[dict] = []
    for venue in venues:
        notes = _fetch_venue_notes(v2_client, v1_client, venue)
        for n in notes:
            paper = _or_note_to_paper(n, venue)
            if paper is None:
                continue
            if not (start_year <= paper["year"] <= end_year):
                continue
            if not _query_match(query, paper):
                continue
            papers.append(paper)
            if len(papers) >= max_results:
                return papers
        time.sleep(0.2)

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on OpenReview")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_openreview(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_openreview.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
