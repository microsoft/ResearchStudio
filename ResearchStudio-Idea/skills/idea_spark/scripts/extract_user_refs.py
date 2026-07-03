"""Extract user-provided paper references from a research-direction query.

Recognised formats (regex-based, no LLM call):
  - arxiv URL:        https://arxiv.org/abs/2401.12345, arxiv.org/pdf/2401.12345v2.pdf, arxiv.org/html/2401.12345
  - arxiv shorthand:  arxiv:2401.12345, arxiv: 2401.12345
  - bare arxiv ID:    2401.12345  (only when standalone — avoid matching version numbers in prose)
  - OpenReview URL:   openreview.net/forum?id=<id>, openreview.net/pdf?id=<id>
  - DOI:              doi.org/10.xxx/..., doi:10.xxx/...

Paper titles are NOT extracted by regex — that requires an LLM step. The host
LLM can populate user_refs[] in the .intent_extraction_pending sentinel; that
augments (does not replace) what this module finds.

Output: list[dict] each with {type, value, raw_match}.
  type ∈ {'arxiv_id', 'openreview_id', 'doi'}
  value: the canonical ID
  raw_match: the original substring (for debugging)
"""

from __future__ import annotations

import re
from typing import List, Dict


# arxiv ID is YYMM.NNNNN (4-5 digit suffix). Optional v<digits> version.
_ARXIV_ID_CORE = r"(\d{4}\.\d{4,5})(?:v\d+)?"

_ARXIV_URL_RE = re.compile(
    r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html|e-print)/" + _ARXIV_ID_CORE + r"(?:\.pdf)?",
    re.IGNORECASE,
)

_ARXIV_SHORTHAND_RE = re.compile(
    r"\barxiv\s*[:#]\s*" + _ARXIV_ID_CORE + r"\b",
    re.IGNORECASE,
)

# Bare arxiv ID — only match when surrounded by whitespace / punctuation, not
# inside another token. We require word boundaries on both sides AND the next
# char is not a letter (avoid '2401.12345abc').
_ARXIV_BARE_RE = re.compile(
    r"(?<![\w.\-])" + _ARXIV_ID_CORE + r"(?![\w.\-])",
)

_OPENREVIEW_URL_RE = re.compile(
    r"https?://(?:www\.)?openreview\.net/(?:forum|pdf|attachment)\?(?:[^=&]+=[^&]+&)*id=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_DOI_URL_RE = re.compile(
    r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s,;\)\]\}'\">]+)",
    re.IGNORECASE,
)
_DOI_SHORTHAND_RE = re.compile(
    r"\bdoi\s*[:#]\s*(10\.\d{4,9}/[^\s,;\)\]\}'\">]+)",
    re.IGNORECASE,
)


def extract_refs_from_query(query: str) -> List[Dict[str, str]]:
    """Scan query text for paper references. Returns list of {type, value, raw_match}.

    The order of returned refs reflects the order they appear in the query.
    Duplicates (same canonical ID) are deduplicated, keeping the first occurrence.
    """
    seen: set[str] = set()
    refs: List[Dict[str, str]] = []

    def _add(ref_type: str, value: str, raw: str) -> None:
        key = f"{ref_type}:{value}"
        if key in seen:
            return
        seen.add(key)
        refs.append({"type": ref_type, "value": value, "raw_match": raw})

    # Order matters: prefer URL/shorthand matches first (they consume context
    # that the bare-ID regex might otherwise re-match).
    for m in _ARXIV_URL_RE.finditer(query):
        _add("arxiv_id", m.group(1), m.group(0))
    for m in _ARXIV_SHORTHAND_RE.finditer(query):
        _add("arxiv_id", m.group(1), m.group(0))
    for m in _OPENREVIEW_URL_RE.finditer(query):
        _add("openreview_id", m.group(1), m.group(0))
    for m in _DOI_URL_RE.finditer(query):
        _add("doi", m.group(1), m.group(0))
    for m in _DOI_SHORTHAND_RE.finditer(query):
        _add("doi", m.group(1), m.group(0))

    # Bare arxiv IDs — done last so URL/shorthand matches above are not
    # re-extracted. We compare position: only emit a bare match if it does
    # not overlap any previously consumed span.
    consumed_spans: list[tuple[int, int]] = []
    for m in _ARXIV_URL_RE.finditer(query):
        consumed_spans.append(m.span())
    for m in _ARXIV_SHORTHAND_RE.finditer(query):
        consumed_spans.append(m.span())
    for m in _ARXIV_BARE_RE.finditer(query):
        s, e = m.span()
        if any(cs <= s < ce or cs < e <= ce for cs, ce in consumed_spans):
            continue
        _add("arxiv_id", m.group(1), m.group(0))

    return refs


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query", help="The research-direction query string to scan")
    args = ap.parse_args()
    print(json.dumps(extract_refs_from_query(args.query), indent=2, ensure_ascii=False))
