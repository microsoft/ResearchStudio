#!/usr/bin/env python3
"""Search for academic papers using the arXiv API."""

import argparse
import os
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

# arXiv asks for no more than ~1 request every 3s. We enforce a stricter 4s floor and,
# crucially, do it ACROSS processes: a multi-query run spawns one process per query, so an
# in-process lock would not help. We serialize on a lockfile in the system temp dir and hold
# the exclusive lock across the sleep, so concurrent processes queue and each request is
# spaced >= MIN_INTERVAL after the previous one actually fired. Override with ARXIV_MIN_INTERVAL.
_MIN_INTERVAL = float(os.environ.get("ARXIV_MIN_INTERVAL", "4.0"))
_THROTTLE_FILE = os.path.join(tempfile.gettempdir(), "arxiv_search_throttle.lock")


def _throttle() -> None:
    """Block until >= _MIN_INTERVAL has elapsed since the last arXiv request (cross-process).

    Uses fcntl.flock for an exclusive, process-serializing lock; on platforms without fcntl
    (non-POSIX) it degrades to a plain per-process sleep floor."""
    try:
        import fcntl
    except ImportError:
        time.sleep(_MIN_INTERVAL)
        return

    fd = os.open(_THROTTLE_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # serializes all arXiv callers on this machine
        raw = os.read(fd, 64).decode("utf-8").strip()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        wait = _MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        # Stamp the moment this request is about to fire, so the next caller spaces from here.
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(time.time()).encode("utf-8"))
    finally:
        os.close(fd)  # releasing the fd also releases the flock


def search_papers_by_arxiv(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on arXiv.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    ARXIV_API = "https://export.arxiv.org/api/query"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

    date_filter = (
        f"submittedDate:[{start_year}01010000 TO {end_year}12312359]"
    )
    params = {
        "search_query": f"(all:{query}) AND {date_filter}",
        "sortBy": "relevance",
        #"sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "PaperSearch/1.0"})

    max_retries = 4  # initial try + 3 retries, with backoff 3s -> 6s -> 12s before giving up
    xml_data = None
    for attempt in range(max_retries):
        _throttle()  # space every attempt (incl. retries) >= _MIN_INTERVAL apart, cross-process
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 3 * (2 ** attempt)  # 3, 6, 12
                print(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    root = ET.fromstring(xml_data)
    papers: list[dict] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        pub_node = entry.find("atom:published", ATOM_NS)
        if pub_node is None or not pub_node.text:
            continue
        try:
            pub = datetime.strptime(pub_node.text[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if not (start_year <= pub.year <= end_year):
            continue

        title_node = entry.find("atom:title", ATOM_NS)
        summary_node = entry.find("atom:summary", ATOM_NS)
        id_node = entry.find("atom:id", ATOM_NS)

        title = (title_node.text or "").strip() if title_node is not None else ""
        abstract = (summary_node.text or "").strip() if summary_node is not None else ""
        paper_url = (id_node.text or "").strip() if id_node is not None else ""
        authors = [
            (a.find("atom:name", ATOM_NS).text or "").strip()
            for a in entry.findall("atom:author", ATOM_NS)
            if a.find("atom:name", ATOM_NS) is not None
        ]

        papers.append({
            "title": title,
            "authors": authors,
            "year": pub.year,
            "abstract": abstract,
            "url": paper_url,
            "venue": "arXiv",
            "citation_count": 0,
            "publication_date": pub.strftime("%Y-%m-%d"),
            "source": "arxiv",
        })

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on arXiv")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_arxiv(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_arxiv.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
