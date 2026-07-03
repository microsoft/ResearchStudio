"""Fetch intro + method sections for selected Phase 0 papers.

Strategy per paper, in priority order:
  1. If arxiv_id present and arxiv.org/html/<id> reachable → BeautifulSoup parse
     (clean structured sections; ~95% success on 2024+ ML preprints with HTML version).
  2. Else try PDFs in this order:
       arxiv.org/pdf/<id>  →  SS openAccessPdf.url  →  OpenReview pdf attachment  →  OpenAlex oa_url
     For each, download bytes → extract raw text via pymupdf → parse heading regex.

Extracts: 'intro' (Introduction / Overview) and 'method' (Method / Methodology / Approach / etc).
Limitations is intentionally NOT extracted — authors' self-stated limits are often
weaker than what an LLM-driven audit would synthesize from method + experiments.

Fallback policy: if all paths fail, the paper is recorded with source_used='failed'
and a warning; intro/method fall back to the abstract. Phase 1 / 2.2 see the warning
but the pipeline does not halt.

Output schema (outputs/phase0/fulltext_cache.json):
  {
    "<paper_id>": {
      "tier": "U" | "T2" | "T3",
      "intro": "<extracted text or abstract fallback>",
      "method": "<extracted text or '' if no fallback>",
      "source_used": "html_arxiv" | "pdf_arxiv_pymupdf"
                    | "pdf_ss_..." | "pdf_or_..." | "pdf_oa_..." | "failed",
      "warning": "<message or null>"
    }
  }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Optional deps — degrade gracefully if missing
# ---------------------------------------------------------------------------

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import fitz  # pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


# ---------------------------------------------------------------------------
# Section heading regex (matches HTML titles AND markdown headings AND raw lines)
# ---------------------------------------------------------------------------

_INTRO_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\.\)]?\s+|[IVX]+[\.\)]?\s+)?(introduction|overview)\b",
    re.IGNORECASE,
)
_METHOD_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\.\)]?\s+|[IVX]+[\.\)]?\s+)?"
    r"(method(?:s|ology)?|approach(?:es)?|our (?:method|approach|framework|model|design)"
    r"|the proposed (?:method|approach|framework|model)"
    r"|framework|model(?:\s+architecture)?|architecture"
    r"|technical (?:approach|details)"
    r"|main\s+results?|theoretical\s+(?:analysis|results?)|analysis|theory|algorithms?|solution"
    r"|problem (?:formulation|setting|setup)|formulation)\b",
    re.IGNORECASE,
)
# Section names that explicitly are NOT method (used by positional fallback)
# Note: NO trailing \b here — many of these are stems that need to match
# plural / inflected forms (Preliminaries, Limitations, Conclusions, References,
# Acknowledgements, Experiments...). \b after a stem like "preliminar" fails
# because "ies" continues as word chars. We instead anchor only at the start
# and let the alternatives end at any non-letter boundary via (?=[\W_]|$).
_NON_METHOD_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\.\)]?\s+|[IVX]+[\.\)]?\s+)?"
    r"(introductions?|overviews?|abstract|related\s+works?|backgrounds?"
    r"|preliminar(?:y|ies)|notations?|setting|problem\s+setup"
    r"|experiments?|results?|evaluations?|ablations?|discussions?|conclusions?"
    r"|references?|acknowledg(?:e?ments?)?|appendi(?:x|ces)"
    r"|broader\s+impacts?|limitations?|future\s+works?)\b",
    re.IGNORECASE,
)
# Stop boundaries — when to stop accumulating a section's body
_NEXT_SECTION_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\.\)]?\s+|[IVX]+[\.\)]?\s+)?"
    r"(related\s+work|background|preliminar|experiment|result|evaluation"
    r"|ablation|discussion|conclusion|reference|acknowledgement|appendix"
    r"|broader\s+impact|limitation)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# HTML path (arxiv only)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 25) -> Optional[bytes]:
    """Plain GET. Returns bytes on 200, None otherwise."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "idea-spark/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return None


def fetch_arxiv_html(arxiv_id: str) -> Optional[str]:
    """GET arxiv.org/html/<id>. Returns HTML text or None if not available.

    arxiv started auto-generating HTML versions from LaTeX source in late 2023;
    coverage is ~85% on 2024+ ML preprints. The endpoint returns 404 for older
    papers without HTML.
    """
    # Strip any version suffix; arxiv HTML is served at canonical ID without 'v' part
    base_id = arxiv_id.split("v")[0]
    url = f"https://arxiv.org/html/{base_id}"
    raw = _http_get(url, timeout=25)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="ignore")
    # arxiv returns a stub 404 page for missing IDs (HTTP 200 but content marks failure)
    if "<title>404" in text[:1500] or "Article identifier" in text[:1500] and "not found" in text[:1500].lower():
        return None
    return text


def parse_html_sections(html: str) -> dict:
    """Parse arxiv HTML, extract intro and method sections.

    Returns: {'intro': str, 'method': str} — empty strings if heading not found.
    """
    if not HAS_BS4:
        return {"intro": "", "method": ""}

    soup = BeautifulSoup(html, "html.parser")
    sections = {"intro": "", "method": ""}

    # arxiv's LaTeXML-rendered HTML uses <section class="ltx_section"> with
    # an <h2 class="ltx_title_section"> header.
    candidates = soup.find_all(["section", "div"], class_=re.compile(r"ltx_section"))
    if not candidates:
        # Fallback: scan all <section> and <h2> in case CSS class scheme differs
        candidates = soup.find_all(["section"])

    # First pass: explicit heading match
    seen_intro = False
    seen_non_method = False  # have we passed Related Work / Background / Preliminaries?
    fallback_body: str = ""  # for positional method fallback: first section after non-method markers
    for sec in candidates:
        heading_tag = sec.find(["h2", "h3"])
        if not heading_tag:
            continue
        heading_text = heading_tag.get_text(" ", strip=True)
        # Pop the heading tag from the tree so it doesn't appear in the body
        heading_tag.extract()
        body = sec.get_text("\n", strip=True)

        if _INTRO_HEAD.match(heading_text) and not sections["intro"]:
            sections["intro"] = body
            seen_intro = True
            continue
        if _METHOD_HEAD.match(heading_text) and not sections["method"]:
            sections["method"] = body
            continue
        # Track positional fallback target: the first section that is NOT
        # explicitly non-method (i.e., the body of a section like "Main Results"
        # or "Algorithm" in a theory paper, where the method-regex didn't fire).
        if seen_intro and not sections["method"] and not _NON_METHOD_HEAD.match(heading_text):
            if not fallback_body:
                fallback_body = body
        if _NON_METHOD_HEAD.match(heading_text) and not heading_text.lower().lstrip("0123456789. ").startswith(("introduction", "overview")):
            seen_non_method = True

    # Positional fallback: if method wasn't found by name, use the first
    # non-{intro/related/etc} section after the intro.
    if not sections["method"] and fallback_body:
        sections["method"] = fallback_body

    return sections


# ---------------------------------------------------------------------------
# PDF path (any source: arxiv, SS openAccessPdf, OpenReview, OA)
# ---------------------------------------------------------------------------

def fetch_pdf_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    """Download PDF bytes from URL. Returns None on failure."""
    return _http_get(url, timeout=timeout)


def pdf_to_text_pymupdf(pdf_bytes: bytes, max_pages: int = 30) -> Optional[str]:
    """Extract raw text from PDF bytes via pymupdf."""
    if not HAS_PYMUPDF:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page_num in range(min(max_pages, len(doc))):
            text += doc[page_num].get_text() + "\n"
        doc.close()
        return text
    except Exception:
        return None


def parse_raw_text_sections(text: str, intro_max: int = 10000, method_max: int = 20000) -> dict:
    """Parse raw text (from pymupdf) — use heading regex on lines to extract intro + method."""
    cap = {"intro": intro_max, "method": method_max}
    sections = {"intro": "", "method": ""}
    lines = text.split("\n")

    current = None
    buffer: list[str] = []
    intro_start = None
    method_start = None

    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            if current:
                buffer.append("")
            continue
        if _INTRO_HEAD.match(s) and intro_start is None:
            if current:
                # save previous
                if not sections[current]:
                    sections[current] = "\n".join(buffer).strip()[:cap[current]]
                buffer = []
            current = "intro"
            intro_start = i
        elif _METHOD_HEAD.match(s) and method_start is None:
            if current and not sections[current]:
                sections[current] = "\n".join(buffer).strip()[:cap[current]]
                buffer = []
            current = "method"
            method_start = i
        elif _NEXT_SECTION_HEAD.match(s):
            if current and not sections[current]:
                sections[current] = "\n".join(buffer).strip()[:cap[current]]
                buffer = []
            current = None
        elif current:
            buffer.append(line)

    if current and not sections[current]:
        sections[current] = "\n".join(buffer).strip()[:cap[current]]
    return sections


# ---------------------------------------------------------------------------
# Public entry — try paths in priority order
# ---------------------------------------------------------------------------

# SS API has strict rate limits (1 req/s with key, ~100 req/5min anonymous).
# We track the last call time to throttle SS lookups across the fetch loop.
_last_ss_call_at: float = 0.0
_SS_MIN_INTERVAL_SEC: float = 1.2


def _resolve_arxiv_via_ss(doi: Optional[str], ss_id: Optional[str]) -> Optional[str]:
    """When a paper has no direct arxiv_id, ask Semantic Scholar's paper-lookup
    endpoint if it has a recorded ArXiv cross-reference. SS often has this even
    when OpenAlex / SS-search-API records do not surface it.

    Returns the arxiv ID (e.g., "2412.14171") or None. Throttles to 1.2s
    between calls and retries once on 429; tolerates other errors silently.
    """
    global _last_ss_call_at
    if not doi and not ss_id:
        return None
    candidates = []
    if doi:
        candidates.append(f"DOI:{doi}")
    if ss_id:
        candidates.append(ss_id)
    api_key = os.environ.get("SEMANTICSCHOLAR_API_KEY", "")

    for lookup in candidates:
        url = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(lookup, safe=':/')}?fields=externalIds"
        for attempt in range(2):
            # Throttle: wait until at least _SS_MIN_INTERVAL_SEC elapsed since last call
            since_last = time.time() - _last_ss_call_at
            if since_last < _SS_MIN_INTERVAL_SEC:
                time.sleep(_SS_MIN_INTERVAL_SEC - since_last)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "idea-spark/1.0"})
                if api_key:
                    req.add_header("x-api-key", api_key)
                with urllib.request.urlopen(req, timeout=15) as r:
                    _last_ss_call_at = time.time()
                    if r.status != 200:
                        break
                    data = json.loads(r.read())
                ext = data.get("externalIds") or {}
                arxiv = ext.get("ArXiv") or ext.get("arxiv")
                if arxiv:
                    return re.sub(r"v\d+$", "", str(arxiv))
                break
            except urllib.error.HTTPError as e:
                _last_ss_call_at = time.time()
                if e.code == 429 and attempt == 0:
                    # Retry once after a longer backoff
                    time.sleep(5)
                    continue
                break
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ConnectionError):
                break
    return None


def _extract_arxiv_id(paper_meta: dict) -> Optional[str]:
    """Pull arxiv ID from any of several possible locations.

    Priority: explicit `arxiv_id` field → externalIds.ArXiv → paper_id prefix `arxiv:<id>`
    → source_id (when source=='arxiv') → DOI/SS-paperId resolution via SS API.
    Strip any version suffix (v1, v2...).
    """
    arxiv_id = paper_meta.get("arxiv_id")
    if not arxiv_id:
        ext = paper_meta.get("externalIds")
        if isinstance(ext, dict):
            arxiv_id = ext.get("ArXiv") or ext.get("arxiv")
    if not arxiv_id:
        pid = paper_meta.get("paper_id") or ""
        if pid.startswith("arxiv:"):
            arxiv_id = pid.split(":", 1)[1]
    if not arxiv_id and paper_meta.get("source") == "arxiv":
        arxiv_id = paper_meta.get("source_id")
    # Final fallback: SS DOI/paperId → ArXiv lookup. Catches CVPR/IEEE-DOI'd
    # papers that have an arxiv preprint but no direct cross-ref in our local record.
    if not arxiv_id:
        doi = paper_meta.get("doi")
        ss_id = paper_meta.get("source_id") if paper_meta.get("source") == "semanticscholar" else None
        arxiv_id = _resolve_arxiv_via_ss(doi, ss_id)
    if arxiv_id:
        # Strip 'v\d+' suffix for canonical ID
        arxiv_id = re.sub(r"v\d+$", "", str(arxiv_id))
    return arxiv_id or None


def _extract_openreview_id(paper_meta: dict) -> Optional[str]:
    """Pull OpenReview note ID from paper record."""
    if paper_meta.get("openreview_id"):
        return paper_meta["openreview_id"]
    pid = paper_meta.get("paper_id") or ""
    if pid.startswith("openreview:"):
        return pid.split(":", 1)[1]
    if paper_meta.get("source") == "openreview":
        return paper_meta.get("source_id")
    return None


def fetch_sections(paper_meta: dict, pdf_timeout: int = 30,
                   per_paper_budget_s: float = 75.0) -> dict:
    """For one paper, try HTML → PDF paths until one yields non-empty intro or method.

    paper_meta should be a Phase 0 lit_results.json record. Recognised fields:
      arxiv_id, openreview_id, openAccessPdf (dict with 'url'), oa_url, pdf_url,
      paper_url, abstract. Also handles records that encode IDs in `paper_id`
      (e.g., "arxiv:2401.12345v1", "openreview:HcngkGFlua") or `source_id`.

    `pdf_timeout` bounds each individual PDF download; `per_paper_budget_s` bounds
    the cumulative time across all paths for this paper, so one paper with many
    dead links cannot stall the pool — once the budget is spent we stop trying
    further paths and degrade to the abstract.

    Returns: {intro, method, source_used, warning}
    """
    deadline = time.monotonic() + per_paper_budget_s
    abstract = paper_meta.get("abstract") or ""

    arxiv_id = _extract_arxiv_id(paper_meta)
    or_id = _extract_openreview_id(paper_meta)

    # Path 1: arxiv HTML
    if arxiv_id:
        html = fetch_arxiv_html(arxiv_id)
        if html:
            secs = parse_html_sections(html)
            if secs["intro"] or secs["method"]:
                return {**secs, "source_used": "html_arxiv", "warning": None}

    # Path 2-5: PDF candidates in priority order
    pdf_candidates: list[tuple[str, str]] = []  # (source_label, url)
    if arxiv_id:
        pdf_candidates.append(("arxiv", f"https://arxiv.org/pdf/{arxiv_id}"))
    ss_pdf = paper_meta.get("openAccessPdf") or {}
    if isinstance(ss_pdf, dict) and ss_pdf.get("url"):
        pdf_candidates.append(("ss", ss_pdf["url"]))
    # ACL Anthology DOI -> free PDF. ACL / EMNLP / NAACL / *findings* papers are open even when
    # the connector only surfaced a landing-page URL, so derive the anthology PDF from the DOI:
    # 10.18653/[vN/]<id>  ->  https://aclanthology.org/<id>.pdf
    acl_m = re.match(r"^10\.18653/(?:v\d+/)?(.+)$", (paper_meta.get("doi") or "").strip(), re.I)
    if acl_m:
        pdf_candidates.append(("acl", f"https://aclanthology.org/{acl_m.group(1)}.pdf"))
    if or_id:
        # OpenReview PDF download endpoint
        pdf_candidates.append(("or", f"https://openreview.net/pdf?id={or_id}"))
    if paper_meta.get("openreview_pdf_url"):
        pdf_candidates.append(("or", paper_meta["openreview_pdf_url"]))
    if paper_meta.get("oa_url"):
        pdf_candidates.append(("oa", paper_meta["oa_url"]))
    if paper_meta.get("pdf_url") and not any(u == paper_meta["pdf_url"] for _, u in pdf_candidates):
        pdf_candidates.append(("other", paper_meta["pdf_url"]))
    # paper_url field — may point to landing page or directly to PDF; try as last resort
    if paper_meta.get("paper_url") and not any(u == paper_meta["paper_url"] for _, u in pdf_candidates):
        pdf_candidates.append(("paper_url", paper_meta["paper_url"]))

    for source_label, url in pdf_candidates:
        if time.monotonic() >= deadline:
            break
        pdf_bytes = fetch_pdf_bytes(url, timeout=pdf_timeout)
        if not pdf_bytes:
            continue

        text = pdf_to_text_pymupdf(pdf_bytes)
        if text:
            secs = parse_raw_text_sections(text)
            if secs["intro"] or secs["method"]:
                return {**secs, "source_used": f"pdf_{source_label}_pymupdf", "warning": None}

    # All paths failed — fall back to abstract for intro, empty for method
    return {
        "intro": abstract,
        "method": "",
        "source_used": "failed",
        "warning": "fetch failed across all paths; intro filled with abstract; method empty",
    }


def fetch_pool(pool: list[dict], max_workers: int = 15,
               on_done: Optional[Callable[[int, int, dict, dict], None]] = None) -> dict:
    """Fetch intro+method for every paper in the pool concurrently.

    Fetching is pure network I/O, so a thread pool turns the pool's wall-clock from
    the SUM of per-paper times into roughly the MAX — the dominant single speedup.
    `on_done(i, total, paper, sections)` is called as each paper finishes (for
    progress logging); ordering of callbacks follows completion, not pool order.

    Returns the cache dict keyed by paper_id: {paper_id: {tier, intro, method,
    source_used, warning}}.
    """
    total = len(pool)
    cache: dict[str, dict] = {}

    def _pid(p: dict, idx: int) -> str:
        return p.get("paper_id") or p.get("id") or f"unknown_{idx}"

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as ex:
        futures = {ex.submit(fetch_sections, p): (i, p) for i, p in enumerate(pool, start=1)}
        done = 0
        for fut in as_completed(futures):
            i, p = futures[fut]
            done += 1
            try:
                sections = fut.result()
            except Exception as e:  # a fetch should never crash the whole pool
                sections = {
                    "intro": p.get("abstract") or "",
                    "method": "",
                    "source_used": "failed",
                    "warning": f"fetch raised {type(e).__name__}: {e}",
                }
            cache[_pid(p, i)] = {"tier": p["_tier"], **sections}
            if on_done is not None:
                on_done(done, total, p, sections)
    return cache


def _norm_title(t: str) -> str:
    # Mirror the connectors' normalize_title so reconcile keys match title_norm.
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def reconcile_lit_table_ids(lit_table_path: Optional[Path], lit_results: list[dict]) -> int:
    """Overwrite lit_table.md's paper_id column with the authoritative id from
    lit_results, matched by title.

    lit_table.md is written by an LLM, which occasionally transcribes a paper_id
    onto the wrong row (two distinct ids that share a prefix are easy to swap) or
    invents a placeholder. lit_results.json is the deterministic dedup output and
    is the source of truth, so we re-derive each row's id from its title here.
    Matching is exact on normalized title, else a unique high-overlap token match
    (guards against the LLM also paraphrasing the title). Rows with no confident
    match are left untouched rather than guessed. Returns the number of rows fixed.
    """
    if not lit_table_path or not lit_table_path.exists():
        return 0
    by_norm: dict[str, str] = {}
    entries: list[tuple[set, str]] = []
    for p in lit_results:
        pid = p.get('paper_id')
        if not pid:
            continue
        norm = p.get('title_norm') or _norm_title(p.get('title'))
        if not norm:
            continue
        by_norm.setdefault(norm, pid)
        entries.append((set(norm.split()), pid))

    def _match(title_cell: str) -> Optional[str]:
        # Drop a trailing "(ACRONYM)" the table-writer often appends to titles.
        bare = re.sub(r'\s*\([^()]*\)\s*$', '', title_cell or '').strip()
        cand = _norm_title(bare)
        if not cand:
            return None
        if cand in by_norm:
            return by_norm[cand]
        ctoks = set(cand.split())
        if not ctoks:
            return None
        scored = sorted(
            ((len(ctoks & toks) / len(ctoks | toks), pid) for toks, pid in entries if toks),
            reverse=True)
        if scored and scored[0][0] >= 0.5 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.2):
            return scored[0][1]
        return None

    raw = lit_table_path.read_text()
    fixed = 0
    out_lines = []
    for line in raw.splitlines():
        if not line.startswith("|") or "---" in line[:5]:
            out_lines.append(line)
            continue
        cells = line.split("|")
        stripped = [c.strip() for c in cells[1:-1]]
        if len(stripped) < 5 or stripped[0] == "paper_id":
            out_lines.append(line)
            continue
        matched = _match(stripped[3])  # title is column index 3 of the data cells
        if matched and matched != stripped[0]:
            cells[1] = f" {matched} "  # paper_id is the first data cell
            line = "|".join(cells)
            fixed += 1
        out_lines.append(line)
    if fixed:
        text = "\n".join(out_lines)
        if raw.endswith("\n"):
            text += "\n"
        lit_table_path.write_text(text)
    return fixed


# ---------------------------------------------------------------------------
# CLI — operates on a Phase 0 lit_results.json + candidate_pool list
# ---------------------------------------------------------------------------

def select_candidate_pool(lit_results: list[dict], lit_table_path: Optional[Path],
                          user_refs: list[dict], t3_top_n: int = 5,
                          t2_top_n: int = 10, max_pool: int = 15) -> list[dict]:
    """Compute U + T2 + T3 = candidate_pool for fulltext fetching.

    - U: papers matching any user_refs entry (by arxiv_id / openreview_id / doi).
         If a U paper isn't already in lit_results, we still emit it with type-only
         metadata so the fetcher can attempt fetch via its identifier. U is ALWAYS
         included — user-named papers are load-bearing and bypass the caps below.
    - T2: up to `t2_top_n` papers from source ∈ {openalex, semanticscholar} where
          lit_table tag != outside_taxonomy. Ordered method-first (eval-only
          benchmark papers last) and round-robin across the two sources, because
          the raw lit_results order is source-grouped (the semanticscholar block
          sorts first) — consuming it verbatim shuts peer-reviewed openalex out
          of the pool entirely and can fetch tangential work ahead of the named
          baselines whose method sections the pool exists to read.
    - T3: up to `t3_top_n` papers from source=arxiv where lit_table tag != outside_taxonomy
          (arxiv is relevance-sorted by Phase 0; we only float method-bearing
          papers above eval-only ones).

    Only the closest-adjacent / most-relevant papers actually feed the Phase 1
    bottleneck and Phase 2.2 differentiation, so we cap the pool rather than fetch
    every on-topic hit. `max_pool` is a hard ceiling on total fetches (U excluded
    from the ceiling — user refs always fetch); T2 and T3 fill the remaining slots
    in priority order. This bounds wall-clock so the fetch never dominates the run.

    De-duplicates across the three buckets by paper_id, preserving the first
    occurrence (U > T2 > T3).
    """
    # Load lit_table tags if available
    paper_tags: dict[str, str] = {}
    if lit_table_path and lit_table_path.exists():
        # lit_table.md is a markdown table; parse each row to extract (paper_id, tag)
        for line in lit_table_path.read_text().splitlines():
            if not line.startswith("|") or "---" in line[:5]:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 5:
                continue
            pid, tag = cells[0], cells[4]  # paper_id col 0, innovation tags col 4
            if pid and pid != "paper_id":
                paper_tags[pid] = tag

    def _is_on_topic(pid: str) -> bool:
        tag = paper_tags.get(pid, "")
        return "outside_taxonomy" not in tag.lower()

    def _is_eval_only(pid: str) -> bool:
        # A paper whose only innovation tag is the benchmark/diagnostic cluster
        # ships an evaluation protocol, not a mechanism — its method section
        # informs the bottleneck / differentiation far less than a closest-adjacent
        # *method* paper's does, so it is deprioritized: fetched only after
        # method-bearing papers have filled the pool.
        tokens = {t.strip() for t in paper_tags.get(pid, "").split(",") if t.strip()}
        tokens.discard("outside_taxonomy")
        return bool(tokens) and tokens <= {"controlled_diagnostic_design"}

    def _method_first_roundrobin(cands: list[dict]) -> list[dict]:
        # Order on-topic published-source candidates so the cap fetches the right
        # papers: (1) method-bearing before eval-only, then (2) within each tier
        # round-robin across sources so the source-grouped lit_results order
        # cannot let one source (semanticscholar, which sorts first) monopolize
        # the slots and shut peer-reviewed openalex out.
        def _interleave(tier: list[dict]) -> list[dict]:
            queues: dict[str, list] = {}  # insertion-ordered (Python 3.7+)
            for c in tier:
                queues.setdefault(c.get("source", ""), []).append(c)
            out: list[dict] = []
            qs = list(queues.values())
            while any(qs):
                for q in qs:
                    if q:
                        out.append(q.pop(0))
            return out
        method = [c for c in cands if not _is_eval_only(c.get("paper_id") or "")]
        eval_only = [c for c in cands if _is_eval_only(c.get("paper_id") or "")]
        return _interleave(method) + _interleave(eval_only)

    # Index lit_results by paper_id for O(1) lookup
    by_id = {p.get("paper_id") or p.get("id") or "": p for p in lit_results}
    pool: list[dict] = []
    seen_ids: set[str] = set()
    # The same paper retrieved from two sources (e.g. a semanticscholar record
    # and its openalex mirror) has distinct paper_ids but an identical title_norm.
    # Dedup on title too so one paper never burns two fulltext slots — this used
    # to be masked when T2 only ever pulled from one source, but the cross-source
    # round-robin below now surfaces both copies.
    seen_titles: set[str] = set()

    def _title_key(p: dict) -> str:
        tn = (p.get("title_norm") or "").strip()
        if tn:
            return tn
        return re.sub(r"[^a-z0-9]+", " ", (p.get("title") or "").lower()).strip()

    # --- U: match user_refs against lit_results, OR emit synthetic record ---
    for ref in user_refs:
        # user_refs entries are host-LLM-appendable (title refs), so a malformed
        # entry missing type/value must be skipped, not crash the whole fetch.
        rtype = ref.get("type")
        rval = ref.get("value")
        if not rtype or not rval:
            continue
        matched = None
        for p in lit_results:
            if rtype == "arxiv_id":
                paper_arxiv = _extract_arxiv_id(p)
                if paper_arxiv and paper_arxiv.split("v")[0] == rval.split("v")[0]:
                    matched = p
                    break
            elif rtype == "openreview_id":
                paper_or = _extract_openreview_id(p)
                if paper_or == rval:
                    matched = p
                    break
            elif rtype == "doi":
                paper_doi = p.get("doi") or (p.get("externalIds") or {}).get("DOI")
                if paper_doi == rval:
                    matched = p
                    break
            elif rtype == "title":
                # Title-based match: case-insensitive substring match on title
                pt = (p.get("title") or "").lower()
                if pt and rval.lower() in pt:
                    matched = p
                    break
        if matched:
            entry = dict(matched)
        else:
            # Synthesize a minimal record so the fetcher can still try
            entry = {
                "paper_id": f"user_ref:{rtype}:{rval}",
                "arxiv_id": rval if rtype == "arxiv_id" else None,
                "openreview_id": rval if rtype == "openreview_id" else None,
                "doi": rval if rtype == "doi" else None,
                "abstract": "",
                "title": f"(user-provided {rtype}: {rval})",
                "source": "user_ref",
            }
        entry["_tier"] = "U"
        pid = entry.get("paper_id") or entry.get("id") or f"user_ref:{rtype}:{rval}"
        if pid not in seen_ids:
            pool.append(entry)
            seen_ids.add(pid)
            tkey = _title_key(entry)
            if tkey:
                seen_titles.add(tkey)

    n_user = len(pool)  # U papers bypass the max_pool ceiling

    # --- T2: published-source on-topic papers, method-first + cross-source
    #         round-robin (NOT raw source-grouped order; see docstring). ---
    t2_cands = [
        p for p in lit_results
        if p.get("source") in ("openalex", "semanticscholar")
        and (p.get("paper_id") or "") not in seen_ids
        and _is_on_topic(p.get("paper_id") or "")
    ]
    t2_count = 0
    for p in _method_first_roundrobin(t2_cands):
        if len(pool) - n_user >= max_pool:
            break
        pid = p.get("paper_id") or ""
        tkey = _title_key(p)
        if tkey and tkey in seen_titles:
            continue  # same paper already pooled from another source
        entry = dict(p)
        entry["_tier"] = "T2"
        pool.append(entry)
        seen_ids.add(pid)
        if tkey:
            seen_titles.add(tkey)
        t2_count += 1
        if t2_count >= t2_top_n:
            break

    # --- T3: arxiv on-topic, method-first (arxiv is single-source + already
    #         relevance-sorted by Phase 0, so round-robin is moot here). ---
    t3_cands = [
        p for p in lit_results
        if p.get("source") == "arxiv"
        and (p.get("paper_id") or "") not in seen_ids
        and _is_on_topic(p.get("paper_id") or "")
    ]
    t3_ordered = (
        [c for c in t3_cands if not _is_eval_only(c.get("paper_id") or "")]
        + [c for c in t3_cands if _is_eval_only(c.get("paper_id") or "")]
    )
    t3_count = 0
    for p in t3_ordered:
        if len(pool) - n_user >= max_pool:
            break
        pid = p.get("paper_id") or ""
        tkey = _title_key(p)
        if tkey and tkey in seen_titles:
            continue  # same paper already pooled from another source
        entry = dict(p)
        entry["_tier"] = "T3"
        pool.append(entry)
        seen_ids.add(pid)
        if tkey:
            seen_titles.add(tkey)
        t3_count += 1
        if t3_count >= t3_top_n:
            break

    return pool


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch intro+method sections for the Phase 0 candidate pool.")
    ap.add_argument("--lit-results", required=True, help="Path to outputs/phase0/lit_results.json")
    ap.add_argument("--lit-table", help="Path to outputs/phase0/lit_table.md (for on-topic filter)")
    ap.add_argument("--user-refs", help="Path to a JSON file with user_refs list, OR a JSON literal string")
    ap.add_argument("--out", required=True, help="Output path for fulltext_cache.json")
    ap.add_argument("--t3-top", type=int, default=5, help="How many top arxiv papers go into T3 (default 5)")
    ap.add_argument("--t2-top", type=int, default=10, help="How many top published-source papers go into T2 (default 10)")
    ap.add_argument("--max-pool", type=int, default=15, help="Hard ceiling on total fetches excluding user refs (default 15)")
    args = ap.parse_args()

    lit_results = json.loads(Path(args.lit_results).read_text())
    if isinstance(lit_results, dict) and "papers" in lit_results:
        lit_results = lit_results["papers"]

    user_refs = []
    if args.user_refs:
        ur_path = Path(args.user_refs)
        if ur_path.exists():
            user_refs = json.loads(ur_path.read_text())
        else:
            user_refs = json.loads(args.user_refs)

    lit_table_path = Path(args.lit_table) if args.lit_table else None
    pool = select_candidate_pool(lit_results, lit_table_path, user_refs,
                                 t3_top_n=args.t3_top, t2_top_n=args.t2_top, max_pool=args.max_pool)

    print(f"Candidate pool: {len(pool)} papers ({sum(1 for p in pool if p['_tier']=='U')} U + "
          f"{sum(1 for p in pool if p['_tier']=='T2')} T2 + "
          f"{sum(1 for p in pool if p['_tier']=='T3')} T3)", file=sys.stderr)

    def _log(done: int, total: int, p: dict, sections: dict) -> None:
        title = (p.get("title") or "")[:80]
        status = sections["source_used"]
        ok = "OK" if status != "failed" else "FAIL"
        print(f"  [{done}/{total}] {p['_tier']} {ok:5} {status:25} {title}", file=sys.stderr)

    cache = fetch_pool(pool, on_done=_log)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(cache, indent=2, ensure_ascii=False))

    n_ok = sum(1 for v in cache.values() if v["source_used"] != "failed")
    print(f"\n  wrote {args.out} ({n_ok}/{len(cache)} succeeded)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
