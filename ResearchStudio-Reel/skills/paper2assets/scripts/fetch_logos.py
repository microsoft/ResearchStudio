#!/usr/bin/env python3
"""Fetch institute logos from Wikimedia Commons for the poster titlebar.

Given a list of institute names (one per line, or `;`-separated on a single
line — same shape as the `**Institutes:**` line in `paper_spec.md`), this
script tries to download an official-looking logo for each into
`<outdir>/assets/logos/<slug>.png` and prints the mapping used.

Sourcing strategy (best-effort, never fabricates):

  1. Open the institute's English Wikipedia page (`en.wikipedia.org/wiki/<Name>`,
     with spaces → underscores) and read its Wikidata entity id.
  2. Prefer the entity's `logo image` (P154) on Wikidata — the OFFICIAL current
     logo, usually the modern wordmark (e.g. MIT's red 3-letter mark, not the
     legacy round seal) and, being on Commons, freely licensed to reuse.
  3. Fall back to scraping the infobox `<img>`: pick the filename matching
     `logo`/`wordmark`/`seal`/`crest`, scored so the wordmark/logo beats the
     seal and Commons beats non-free en.wikipedia uploads. Skip flags/photos/maps.
  4. Resolve to a full-resolution image URL, download to
     `<outdir>/assets/logos/<slug>.png`, and verify the bytes are a PNG/SVG
     before keeping. If anything fails for one institute, skip it (the
     `.logo-block:has(no logos)` CSS rule hides the slot gracefully).

Usage:
    python fetch_logos.py --outdir <outdir> --names "Microsoft Research Asia;UCSD;Tsinghua University"
    # or
    python fetch_logos.py --outdir <outdir> --from-spec <outdir>/paper_spec.md
    # WEB-SEARCH FALLBACK for an institute this Wikimedia pass missed:
    python fetch_logos.py --outdir <outdir> --add-logo "Westlake University=https://.../westlake-logo.png"

Prints a JSON summary on stdout AND a ✓/✗ CHECKLIST on stderr. The JSON carries
the resolved logos plus the institutes that produced NONE — run the Step-6 web
search on each of those, then `--add-logo "Name=URL"` to fetch it:
    {"logos":   [{"name": "...", "slug": "...", "path": "assets/logos/<slug>.png", "source": "<url>"}, ...],
     "missing": ["Westlake University", ...]}    # institutes with no Wikimedia logo -> web-search fallback
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Share the canonical bundle layout (utils/layout.py) when run directly.
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from utils import layout  # noqa: E402
try:
    from utils.logo_trim import autotrim  # noqa: E402
except Exception:  # best-effort: a missing trim util / dep degrades to a no-op
    def autotrim(p):
        return p

UA = "Mozilla/5.0 (paper2poster fetch_logos)"
LOGO_KEYWORDS = ("logo", "seal", "wordmark", "crest", "coat_of_arms", "emblem")
# Scored preference for the infobox fallback: the modern wordmark/logo beats the
# legacy seal/crest/coat-of-arms. Many university infoboxes carry BOTH, and
# viewers now expect the wordmark (e.g. MIT's 3 red letters, not the round seal).
# Seals stay eligible (still positive) as a last resort for institutions that
# publish only a seal. The Wikidata P154 lookup runs first and usually wins.
LOGO_WEIGHTS = {"wordmark": 30, "logo": 20, "emblem": 6,
                "seal": 4, "crest": 4, "coat_of_arms": 4}
SKIP_KEYWORDS = ("flag", "map", "campus", "photo", "building", "aerial")

# Some common institute aliases → the Wikipedia article title that actually
# carries an official mark in its infobox. Keeps the lookup robust against
# short forms (UCSD, MIT CSAIL, MSRA, etc.) that don't resolve directly.
ALIASES = {
    # Microsoft Research / MSRA map to the PARENT company Microsoft so the
    # titlebar shows Microsoft's four-square corporate logo (team convention),
    # NOT Microsoft Research's own wordmark. Mirrors google research -> Google.
    "msr": "Microsoft",
    "msra": "Microsoft",
    "microsoft research": "Microsoft",
    "microsoft research asia": "Microsoft",
    "microsoft research lab": "Microsoft",
    "microsoft research lab asia": "Microsoft",
    "ucsd": "University of California, San Diego",
    "uc san diego": "University of California, San Diego",
    "uc berkeley": "University of California, Berkeley",
    "ucb": "University of California, Berkeley",
    "ucla": "University of California, Los Angeles",
    "mit": "Massachusetts Institute of Technology",
    "cmu": "Carnegie Mellon University",
    "nyu": "New York University",
    "ust": "Hong Kong University of Science and Technology",
    "hkust": "Hong Kong University of Science and Technology",
    "cuhk": "Chinese University of Hong Kong",
    "pku": "Peking University",
    "thu": "Tsinghua University",
    "sjtu": "Shanghai Jiao Tong University",
    "ethz": "ETH Zurich",
    "eth zurich": "ETH Zurich",
    "epfl": "EPFL",
    "kaist": "KAIST",
    "nvidia": "Nvidia",
    "google research": "Google",
    "google deepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "facebook ai research": "Meta Platforms",
    "facebook ai": "Meta Platforms",
    "facebook": "Meta Platforms",
    "fair": "Meta Platforms",
    "meta ai": "Meta Platforms",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "ibm research": "IBM",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or "logo"


def fetch(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolve_wikipedia_title(name: str) -> str:
    key = name.strip().lower()
    return ALIASES.get(key, name.strip())


def search_wikipedia_titles(query: str, limit: int = 3) -> list[str]:
    """Resolve an institution name to its best-matching English-Wikipedia
    article title(s) via the opensearch API. This is what makes the lookup
    robust WITHOUT a hand-maintained alias table: it handles abbreviations,
    rebrands (e.g. "Facebook AI" -> "Meta Platforms"), and minor spelling
    differences an exact wiki/<Name> URL guess can't. Returns [] on failure
    so the caller still falls back to the alias/exact candidates."""
    api = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "opensearch", "search": query, "limit": str(limit),
        "namespace": "0", "format": "json", "redirects": "resolve"})
    try:
        data = json.loads(fetch(api).decode("utf-8", errors="ignore"))
        return [t for t in (data[1] if len(data) > 1 else []) if t]
    except Exception:
        return []


_TITLE_TOKEN_STOPWORDS = {
    "a", "an", "and", "ai", "for", "inc", "lab", "labs", "llc", "ltd", "ml",
    "of", "research", "school", "the", "university",
}


def _title_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", text.lower())
        if len(tok) > 1 and tok not in _TITLE_TOKEN_STOPWORDS
    }


def search_title_relevant(query: str, title: str) -> bool:
    """Keep opensearch fallback titles tied to the requested institute.

    Wikipedia opensearch can return pages from the same broad parent brand
    (for example "Google Translate" for "Google Brain"). Exact aliases and
    explicit "(company)" / "(organization)" candidates are tried before this
    fallback, so search results should preserve the distinctive query token
    rather than accepting a merely adjacent brand page.
    """
    query_tokens = _title_tokens(query)
    if not query_tokens:
        return True
    title_tokens = _title_tokens(title)
    if len(query_tokens) == 1:
        return bool(query_tokens & title_tokens)
    # For multi-token institute names, require at least two shared tokens.
    # This rejects adjacent brand pages like "Google Translate" for
    # "Google Brain", while still allowing small article-title variants.
    return len(query_tokens & title_tokens) >= min(2, len(query_tokens))


# Tails we strip when generating parent-candidate fallbacks for an institute
# name. Order: most specific first. Match is case-insensitive.
# Note: "Institute of X" intentionally NOT stripped here — bare "Institute" is
# usually part of the institution's name (Massachusetts Institute of Tech,
# Indian Institute of Tech, ...). The alias dict handles those.
_DEPARTMENTAL_TAIL_PATTERNS = [
    r"\s*[,/;]\s*Department\s+of\s+.*$",
    r"\s+Department\s+of\s+.*$",
    r"\s*[,/;]\s*School\s+of\s+.*$",
    r"\s+School\s+of\s+.*$",
    r"\s*[,/;]\s*College\s+of\s+.*$",
    r"\s+College\s+of\s+.*$",
    r"\s*[,/;]\s*Faculty\s+of\s+.*$",
    r"\s+Faculty\s+of\s+.*$",
    r"\s*[,/;]\s*Division\s+of\s+.*$",
    r"\s+Division\s+of\s+.*$",
    r"\s*[,/;]\s*Center\s+for\s+.*$",
    r"\s+Center\s+for\s+.*$",
    r"\s*[,/;]\s*Centre\s+for\s+.*$",
    r"\s+Centre\s+for\s+.*$",
    r"\s*[,/;]\s*(?:AI\s+|ML\s+|Robotics\s+|Computer\s+Vision\s+)?Lab(?:oratory)?s?\s*$",
    r"\s+(?:AI\s+|ML\s+|Robotics\s+|Computer\s+Vision\s+)?Lab(?:oratory)?s?\s*$",
    r"\s*[,/;]\s*(?:Research\s+)?Group\s*$",
    r"\s+(?:Research\s+)?Group\s*$",
    r"\s*[,/;]\s*Center\s*$",
    r"\s+Center\s*$",
    r"\s*[,/;]\s*Centre\s*$",
    r"\s+Centre\s*$",
    r"\s*[,/;]\s*Division\s*$",
    r"\s+Division\s*$",
]

# Tokens that mark a segment as "looks like an institution proper".
# Used to rank segments when generating parent-institution candidates
# from a comma-separated input like "School of Pharmacy, Microsoft
# Research Asia, Shanghai, China".
#
# Tiered by confidence — when an input contains MULTIPLE
# institution-tokens across segments, the HIGHER-tier token's segment
# wins as the primary parent candidate:
#
#   HIGH = the segment almost certainly IS the institution.
#          Big-tech / lab names (microsoft, google, ...), "university",
#          "polytechnic", and the international variants. Promoting
#          these first fixes the previous-version bug where
#          "School of Pharmacy, Microsoft Research Asia" ranked
#          "School of Pharmacy" first (because both segments matched
#          the unweighted token list) and ended up grabbing a random
#          Wikipedia disambiguation icon instead of MSRA's logo.
#
#   MID  = the segment COULD be the institution (MIT / KAIST / IIT
#          all end in "Institute") OR could be a research-group label.
#          Used as fallback below HIGH.
#
#   LOW  = the segment is typically a SUB-UNIT but occasionally
#          could be the actual institution (some standalone "Schools"
#          and "Colleges" do exist as standalone Wikipedia entries).
#          Always ranked below MID.
_INSTITUTION_TOKENS_HIGH = (
    "university", "universidad", "université", "universität", "academia",
    "polytechnic",
    "microsoft", "google", "meta", "apple", "nvidia", "amazon", "openai",
    "anthropic", "deepmind", "ibm", "intel", "samsung", "tencent", "alibaba",
    "baidu", "huawei", "bytedance",
)
_INSTITUTION_TOKENS_MID = (
    "institute", "research", "labs", "laboratory",
)
_INSTITUTION_TOKENS_LOW = (
    "school", "college", "faculty", "division",
)


def _institution_tier(segment: str) -> int:
    """Return 0/1/2/3 ranking for a segment (lower = higher priority).
       0=HIGH, 1=MID, 2=LOW, 3=other (no institution token at all)."""
    s = segment.lower()
    if any(tok in s for tok in _INSTITUTION_TOKENS_HIGH):
        return 0
    if any(tok in s for tok in _INSTITUTION_TOKENS_MID):
        return 1
    if any(tok in s for tok in _INSTITUTION_TOKENS_LOW):
        return 2
    return 3


def parent_candidates(name: str) -> list[str]:
    """Generate parent-institution candidates for `name`, most specific first.

    The goal: when the input is a second-level institution like
    "Microsoft Research Asia, GenAI Group" or "Tsinghua University,
    Department of Computer Science", we may not find an infobox at the
    specific name's Wikipedia page — but the parent does have one. So we
    fall back: try the input as-is, then try progressively-more-generic
    variants until something resolves.

    Rules applied in order:
      1. The input as-is.
      2. Same with parenthesized phrases stripped: "Tsinghua University (China)"
         -> "Tsinghua University".
      3. Same with departmental tails stripped: "X University Lab" -> "X University".
      4. Each comma/dash/slash/semicolon-separated segment, ordered by
         institution-token TIER (see _institution_tier): HIGH segments
         (containing 'microsoft', 'university', 'polytechnic', ...) first,
         then MID ('institute', 'research', 'labs'), then LOW ('school',
         'college', 'faculty'), then segments with no institution token.
         Within the same tier, segments preserve input order.
         Example: "School of Pharmacy, Microsoft Research Asia, Shanghai"
         yields "Microsoft Research Asia" (HIGH via 'microsoft') BEFORE
         "School of Pharmacy" (LOW via 'school') — the previous version
         treated both as same-priority and randomly picked the first.
      5. Each segment with its own departmental-tail stripping.

    Duplicates are removed while preserving order. The caller (fetch_logo_for)
    tries each candidate via resolve_wikipedia_title -> Wikipedia infobox.
    The first one that yields a real logo wins; misses cascade to the next.
    """
    seen: set[str] = set()
    out: list[str] = []

    def push(s: str) -> None:
        s = s.strip(" ,;-—.").strip()
        if len(s) < 3:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    raw = name.strip()
    push(raw)

    # Strip parenthesized phrases.
    push(re.sub(r"\s*\([^)]*\)", "", raw).strip())

    # Strip departmental tails from the whole string.
    for pat in _DEPARTMENTAL_TAIL_PATTERNS:
        stripped = re.sub(pat, "", raw, flags=re.IGNORECASE).strip()
        if stripped != raw:
            push(stripped)

    # Split into segments and rank by institution-token tier (HIGH=0 first).
    # Stable sort preserves input order within the same tier.
    segments = [s.strip() for s in re.split(r"\s*[,;/]\s*|\s+[-—]\s+", raw) if s.strip()]
    segments_ranked = sorted(segments, key=_institution_tier)
    for seg in segments_ranked:
        push(seg)
        # Also strip tails on the segment itself.
        for pat in _DEPARTMENTAL_TAIL_PATTERNS:
            stripped = re.sub(pat, "", seg, flags=re.IGNORECASE).strip()
            if stripped and stripped != seg:
                push(stripped)
        # And strip parentheses on the segment.
        push(re.sub(r"\s*\([^)]*\)", "", seg).strip())

    return out


def find_logo_url(html: str) -> str | None:
    """Locate the first plausible logo <img> in the page's infobox.

    Restrict search to the infobox table — Wikipedia footers contain a
    Commons-logo.svg and other decorations that would otherwise score high
    on the "logo" keyword.
    """
    # Carve out the infobox HTML, if present. Wikipedia uses
    # <table class="infobox ..."> ... </table>; we grab the first one.
    m_box = re.search(r'<table[^>]*\bclass="[^"]*infobox[^"]*"[^>]*>(.*?)</table>', html, re.IGNORECASE | re.DOTALL)
    scope = m_box.group(1) if m_box else html
    img_pat = re.compile(r"<img\b[^>]*\bsrc=\"([^\"]+)\"", re.IGNORECASE)
    candidates: list[tuple[int, str]] = []
    for m in img_pat.finditer(scope):
        src = m.group(1)
        if "upload.wikimedia.org" not in src:
            continue
        low = src.lower()
        if any(k in low for k in SKIP_KEYWORDS):
            continue
        # Skip Wikipedia chrome (Commons-logo, edit-pencil, etc.) AND
        # generic icons that show up on disambiguation / stub pages
        # (Disambig_gray.svg is the grey wrench that appears on every
        # disambig page — picking it up made e.g. 'CFAR' (the disambig
        # page for Center for Frontier AI Research) produce a wrench
        # icon instead of cascading to A*STAR's real logo).
        if ("commons-logo" in low or "wikimedia-button" in low
                or "edit-ltr" in low or "disambig" in low
                or "question_book" in low or "stub_icon" in low
                or "cscr-featured" in low
                # Sister-project / chrome marks that decorate disambiguation and
                # general (non-company) articles -- a bare ambiguous name like
                # "Runway" lands on such a page and would otherwise pick up the
                # Wiktionary logo. Rejecting these makes the candidate cascade
                # fall through to the real company/org article. GENERAL, not
                # keyed to any one institute.
                or "wiktionary" in low or "wikinews" in low or "wikiquote" in low
                or "wikibooks" in low or "wikisource" in low or "wikiversity" in low
                or "wikivoyage" in low or "wikispecies" in low or "wikidata" in low
                or "wikipedia-logo" in low or "mediawiki" in low or "ambox" in low
                or "_padlock" in low
                or low.endswith("/increase2.svg") or low.endswith("/decrease2.svg")):
            continue
        score = 1  # infobox imgs get a base score so the first <img> wins absent keywords
        # Prefer the modern wordmark/logo over the legacy seal/crest (see LOGO_WEIGHTS).
        for kw, w in LOGO_WEIGHTS.items():
            if kw in low:
                score += w
        if ".svg" in low:
            score += 3
        # Commons files are freely licensed by policy; local en.wikipedia uploads
        # are frequently non-free fair-use marks -- prefer the reusable Commons one.
        if "/commons/" in low:
            score += 2
        candidates.append((score, src))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def _qid_from_html(html: str) -> str | None:
    """Pull the Wikidata entity id (Q…) embedded in a Wikipedia page."""
    m = re.search(r'"wgWikibaseItemId"\s*:\s*"(Q\d+)"', html)
    if m:
        return m.group(1)
    m = re.search(r"/Special:EntityData/(Q\d+)", html)
    return m.group(1) if m else None


def wikidata_logo_urls(qid: str | None) -> list[str]:
    """Commons file URLs from the entity's `logo image` (P154), NEWEST first.

    P154 is the institution's OFFICIAL logo(s), curated on Wikidata -- more up
    to date than the legacy seal a Wikipedia infobox may list first (e.g. MIT's
    2023 red wordmark vs. the round seal). Commons hosts only freely-licensed /
    public-domain files, so a P154 hit is also safe for others to reuse.

    An entity often lists MANY versions (Microsoft has 4, Google 6). Pick the
    CURRENT one by ranking each value on:
      1. Wikidata rank -- editors flag the live logo `preferred`.
      2. no P582 end-time -- a value with an end date is a retired logo.
      3. latest P580 start-time -- the most recently adopted mark.
      4. latest P582 end-time -- tiebreak when every value is retired.
    Older versions stay in the list (after the newest) as download fallbacks.
    """
    if not qid:
        return []
    try:
        raw = fetch(
            f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        ).decode("utf-8", errors="ignore")
        claims = json.loads(raw).get("entities", {}).get(qid, {}).get("claims", {})
    except Exception:
        return []
    RANK = {"preferred": 2, "normal": 1, "deprecated": 0}

    def _qtime(quals: dict, pid: str) -> str:
        # Wikidata times look like "+2012-08-24T00:00:00Z"; the leading-year ISO
        # shape sorts chronologically as a plain string. Missing -> "".
        try:
            return quals[pid][0]["datavalue"]["value"]["time"].lstrip("+")
        except Exception:
            return ""

    rows = []
    for c in claims.get("P154", []):
        fn = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if not isinstance(fn, str):
            continue
        quals = c.get("qualifiers", {})
        end = _qtime(quals, "P582")
        rows.append((
            RANK.get(c.get("rank"), 1),      # preferred (live) logo wins
            0 if end else 1,                 # still-current beats retired
            _qtime(quals, "P580"),           # newest adoption date first
            end,                             # newest retirement date (tiebreak)
            fn,
        ))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]), reverse=True)
    return ["https://commons.wikimedia.org/wiki/Special:FilePath/"
            + urllib.parse.quote(fn.replace(" ", "_")) for *_, fn in rows]


def thumb_to_full(url: str) -> list[str]:
    """Return candidate URLs in priority order: original first, then safe thumbs.

    Wikimedia rejects arbitrary thumb widths with HTTP 400 ("Use thumbnail
    sizes listed on https://w.wiki/GHai"). For raster originals we strip
    `/thumb/.../NNNpx-...` to get the source file; for SVG-derived PNGs we
    fall back to a list of commonly-allowed widths (500, 330, 250).
    """
    if url.startswith("//"):
        url = "https:" + url
    cands: list[str] = []
    if "/thumb/" in url:
        # Strip the /thumb/ middle: .../commons/thumb/a/ab/Foo.png/NNNpx-Foo.png
        # → .../commons/a/ab/Foo.png
        m = re.match(r"(.*?)/thumb/([^/]+/[^/]+/[^/]+)/\d+px-[^/]+$", url)
        if m:
            cands.append(m.group(1) + "/" + m.group(2))
        # Also try a few documented thumb widths for SVG sources (the
        # original .svg cannot be rendered server-side at arbitrary px).
        for w in (500, 330, 250, 1024):
            cands.append(re.sub(r"/\d+px-", f"/{w}px-", url))
    else:
        cands.append(url)
    # De-dup while preserving order.
    seen, out = set(), []
    for u in cands:
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def is_image(data: bytes) -> bool:
    if not data or len(data) < 32:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True  # jpeg
    if data[:4] == b"<svg" or data[:5] == b"<?xml":
        return True
    return False


def detect_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"<svg" or data[:5] == b"<?xml":
        return ".svg"
    return ".png"  # fallback


def download_named_logo(name: str, url: str, logos_dir: Path) -> dict | None:
    """Download ONE logo from an explicit URL for the web-search fallback.

    Reuses the same pipeline as the Wikimedia path (detect ext → slug from the
    institute name → autotrim the border) so a fallback logo looks identical in
    the header to the deterministically-fetched ones. Returns a manifest entry
    (or None on failure). Used by `--add-logo "Name=URL"`.
    """
    try:
        data = fetch(url)
    except Exception as e:
        print(f"[fetch_logos] add-logo {name!r}: download failed ({url}): {e}", file=sys.stderr)
        return None
    if not data or len(data) < 128:
        print(f"[fetch_logos] add-logo {name!r}: empty/too-small file from {url}", file=sys.stderr)
        return None
    ext = detect_ext(data)
    slug = slugify(name)
    out = logos_dir / f"{slug}{ext}"
    out.write_bytes(data)
    tight = autotrim(out)
    if tight != out:
        try:
            out.unlink()
        except Exception:
            pass
        out = tight
    rel = f"{layout.LOGOS}/{out.name}"
    print(f"[fetch_logos] add-logo {name!r} -> {rel}  ({out.stat().st_size} bytes, source={url})", file=sys.stderr)
    return {"name": name, "slug": slug, "path": rel, "source": url}


def fetch_logo_for(name: str) -> dict | None:
    """Fetch (don't yet write) the best logo for `name`.

    Tries a fallback chain of parent-institution candidates (see
    `parent_candidates`): the input as-is first, then progressively-more-
    generic variants. First candidate that resolves to a real infobox
    logo wins. This handles the second-level-institution case where the
    specific sub-org doesn't have its own Wikipedia article — e.g.
    "Microsoft Research Asia, GenAI Group" cascades to "Microsoft Research
    Asia" -> alias to "Microsoft" (parent company, four-square logo) -> hit.
    Same for
    "Tsinghua University, Department of CS" cascading to "Tsinghua
    University". The returned dict's `name` keeps the ORIGINAL input
    string so the spec's display name is preserved; `title` records
    which parent candidate actually resolved.

    Returns {"name", "title", "source", "data"} on success — caller is
    responsible for writing the bytes to disk after dedup. Splitting fetch
    from write lets `main()` skip duplicates (two institutes resolving to
    the same Wikipedia title, the same source URL, or the same image bytes)
    so the titlebar doesn't render two identical tiles.
    """
    candidates = parent_candidates(name) or [name.strip()]
    # Ordered, de-duped Wikipedia article titles to try:
    #   1. alias hit (or raw text) for each parent candidate — fast, no API.
    #   2. opensearch matches for the raw name + the top-ranked candidate —
    #      robust to abbreviations / rebrands / NEW orgs with no hardcoded
    #      alias (e.g. "Facebook AI" -> search -> "Meta Platforms").
    titles: list[str] = []
    seen: set[str] = set()
    def _add(t: str) -> None:
        t = (t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            titles.append(t)
    for cand in candidates:
        _add(resolve_wikipedia_title(cand))
    # Disambiguation-aware company/org variants (GENERAL -- no per-company alias):
    # an ambiguous short name ("Runway", "Cohere") often has its company article
    # under a "(company)" / "(organization)" title while the BARE article is a
    # dictionary word or disambiguation page. Strip a trailing "ML/AI/Inc/Labs/..."
    # so "Runway ML" -> "Runway (company)". Tried BEFORE the noisy opensearch
    # results so e.g. "Runway (company)" beats "Runway (song)".
    core = re.sub(r"\s+(ml|ai|inc\.?|llc|ltd\.?|gmbh|labs?|research|technologies)$",
                  "", name.strip(), flags=re.I).strip()
    for base in dict.fromkeys([name.strip(), core]):
        if base and 1 <= len(base.split()) <= 3:
            for suf in ("(company)", "(organization)", "(software)"):
                _add(f"{base} {suf}")
    for q in dict.fromkeys([name.strip(), candidates[0]]):
        for t in search_wikipedia_titles(q):
            if search_title_relevant(q, t):
                _add(t)

    for title in titles:
        page = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        try:
            html = fetch(page).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[fetch_logos] {name!r} via {title!r}: wiki fetch failed: {e}", file=sys.stderr)
            continue
        # Wikidata `logo image` (P154) = the official CURRENT logo (usually the
        # modern wordmark); try it FIRST, then fall back to scraping the infobox.
        wd_urls = wikidata_logo_urls(_qid_from_html(html))
        src = find_logo_url(html)
        if not wd_urls and not src:
            print(f"[fetch_logos] {name!r} via {title!r}: no logo at {page}", file=sys.stderr)
            continue
        full_candidates = wd_urls + (thumb_to_full(src) if src else [])
        data = None
        chosen_url = None
        for full in full_candidates:
            try:
                blob = fetch(full)
            except Exception:
                continue
            if not is_image(blob):
                continue
            data = blob
            chosen_url = full
            break
        if not data:
            print(f"[fetch_logos] {name!r} via {title!r}: all download candidates failed", file=sys.stderr)
            continue
        if title.strip().lower() != name.strip().lower():
            print(f"[fetch_logos] {name!r}: resolved via {title!r}", file=sys.stderr)
        return {"name": name, "title": title, "source": chosen_url, "data": data}
    print(f"[fetch_logos] {name!r}: no candidate produced a logo (tried {len(titles)})", file=sys.stderr)
    return None


def parse_names(arg: str | None, spec: Path | None) -> list[str]:
    if arg:
        # Accept either ; or newline separation.
        parts = re.split(r"[;\n]", arg)
        return [p.strip() for p in parts if p.strip()]
    if spec and spec.exists():
        # Two accepted formats:
        #   - YAML frontmatter (current paper_spec.md):
        #       institutes: ¹CFAR, A*STAR; ²IHPC, A*STAR; …
        #   - legacy markdown (older spec files):
        #       **Institutes:** CFAR, A*STAR; IHPC, A*STAR; …
        # The institutes are `;`-separated (per SKILL.md Step 3).
        # Don't split on commas — names like 'University of California,
        # San Diego' contain commas. Strip leading superscript markers
        # (¹²³⁴⁵⁶⁷⁸⁹⁰ plus *†‡§¶ commonly used) from each name so the
        # Wikipedia lookup sees 'CFAR, A*STAR' not '¹CFAR, A*STAR'.
        line_pat = re.compile(
            r"^\s*(?:\*\*Institutes:\*\*|institutes\s*:)\s*(.+?)\s*$",
            re.IGNORECASE,
        )
        marker_pat = re.compile(r"^[²³¹⁰-⁹*†‡§¶0-9\s.,\-]+")
        for line in spec.read_text(encoding="utf-8").splitlines():
            m = line_pat.match(line)
            if not m:
                continue
            out: list[str] = []
            for raw in m.group(1).split(";"):
                cleaned = marker_pat.sub("", raw).strip()
                if cleaned:
                    out.append(cleaned)
            if out:
                return out
    return []


def _dedupe_by_source(results: list[dict], logos_dir: Path) -> list[dict]:
    """Collapse manifest entries that resolved to the SAME logo so the poster
    titlebar renders one tile per visually-distinct mark.

    Two-level dedup:
      1. by `source` URL (cheapest; catches MSR + MSRA + Microsoft Research
         all hitting the same Wikipedia file).
      2. by SHA-256 of the downloaded bytes (catches the edge case where two
         institutes resolved via DIFFERENT URLs but Wikipedia served the same
         file — happens when a redirect collapses old and new article names).

    First-seen entry wins; later duplicates have their local file removed
    (the survivor's file stays). The survivor's `name` becomes a `;`-joined
    list of all institute names that shared the file, so downstream
    substitution can show 'A*STAR (CFAR / IHPC)' in alt-text or tooltips."""
    import hashlib
    seen_src: dict[str, dict] = {}     # source URL → keeper entry
    seen_hash: dict[str, dict] = {}    # file hash  → keeper entry
    kept: list[dict] = []

    for entry in results:
        src = entry.get("source", "")
        # Level 1: source URL dedup
        if src and src in seen_src:
            keeper = seen_src[src]
            keeper["name"] = f"{keeper['name']}; {entry['name']}"
            # remove the duplicate's downloaded file (keeper's file stays)
            dup_path = logos_dir.parent / entry["path"]
            dup_path.unlink(missing_ok=True)
            print(f"[fetch_logos] dedup (same source): {entry['name']!r} "
                  f"→ folded into {keeper['name'].split(';')[0]!r}",
                  file=sys.stderr)
            continue

        # Level 2: file hash dedup (different URL, same bytes)
        file_path = logos_dir.parent / entry["path"]
        if file_path.exists():
            try:
                h = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                h = ""
            if h and h in seen_hash:
                keeper = seen_hash[h]
                keeper["name"] = f"{keeper['name']}; {entry['name']}"
                file_path.unlink(missing_ok=True)
                print(f"[fetch_logos] dedup (same bytes): {entry['name']!r} "
                      f"→ folded into {keeper['name'].split(';')[0]!r}",
                      file=sys.stderr)
                continue
            if h:
                seen_hash[h] = entry

        if src:
            seen_src[src] = entry
        kept.append(entry)
    return kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", required=True, type=Path, help="Poster outdir; logos/ is created inside it. (If you pass <outdir>/logos by mistake, the trailing /logos is auto-stripped with a warning — see Step 6 of paper2assets/SKILL.md.)")
    ap.add_argument("--names", help='Semicolon-separated institute names, e.g. "Microsoft Research Asia;UCSD;Tsinghua University"')
    ap.add_argument("--from-spec", "--spec", dest="from_spec", type=Path,
                    help="Read names from the **Institutes:** line of paper_spec.md. "
                         "(`--spec` is a backward-compat alias; the canonical flag is "
                         "`--from-spec` because that's what SKILL.md/help-output says.)")
    ap.add_argument("--add-logo", action="append", default=[], metavar='"Name=URL"',
                    help="Web-search FALLBACK: download ONE logo for an institute the "
                         "deterministic pass reported as missing. Format 'Name=URL'. "
                         "Repeatable. Skips the Wikimedia pass entirely — just downloads, "
                         "autotrims, slugs, and appends to assets/logos/.")
    args = ap.parse_args()

    # Defensive: if caller passed `<outdir>/logos` (a common SKILL.md
    # misreading — script appends /logos itself, so passing it ends up
    # at <outdir>/logos/logos/<slug>.png and downstream paper2poster
    # finds nothing). Strip it once with a loud warning so the bug is
    # visible in batch logs.
    # Defensive: if caller passed `<outdir>/logos` or `<outdir>/assets/logos`
    # (a common SKILL.md misreading — the script appends the canonical
    # `assets/logos/` itself, so passing it ends up nested and downstream
    # paper2poster finds nothing). Strip it once with a loud warning so the
    # bug is visible in batch logs.
    if args.outdir.name == "logos":
        stripped = args.outdir.parent
        if stripped.name == "assets":
            stripped = stripped.parent
        print(f"[fetch_logos] WARNING: --outdir ends in '/logos' "
              f"({args.outdir!s}); auto-stripping to {stripped!s}. "
              f"Pass the POSTER OUTDIR (assets/logos/ is created inside it).",
              file=sys.stderr)
        args.outdir = stripped

    logos_dir = layout.logos_dir(args.outdir, create=True)

    # FALLBACK MODE: download explicit "Name=URL" logos (from the web-search
    # fallback for institutes the Wikimedia pass missed) and exit.
    if args.add_logo:
        added = []
        for spec in args.add_logo:
            if "=" not in spec:
                print(f"[fetch_logos] --add-logo needs 'Name=URL', got {spec!r}", file=sys.stderr)
                continue
            nm, url = spec.split("=", 1)
            info = download_named_logo(nm.strip(), url.strip(), logos_dir)
            if info:
                added.append(info)
        added = _dedupe_by_source(added, logos_dir)
        print(json.dumps({"logos": added}, indent=2))
        return 0 if added else 1

    names = parse_names(args.names, args.from_spec)
    if not names:
        print("[fetch_logos] no institute names provided (use --names or --from-spec)", file=sys.stderr)
        return 2

    # Three-stage dedup so two institutes that resolve to the same logo
    # don't render two identical tiles in the titlebar:
    #   (1) PRE-FETCH by resolved Wikipedia title -- catches the cheap case
    #       (MSRA + "Microsoft Research Asia" both alias to "Microsoft
    #       Research") and saves the HTTP round-trip.
    #   (2) POST-FETCH by source URL -- catches two distinct titles whose
    #       infoboxes link the same Commons file.
    #   (3) POST-FETCH by image SHA-256 -- last-resort: distinct URLs that
    #       happen to serve byte-identical files (rebrands, mirrors).
    results = []
    missing: list[str] = []             # institutes that produced NO logo (need web-search fallback)
    seen_titles: dict[str, dict] = {}   # resolved title -> result
    seen_urls: dict[str, dict] = {}     # chosen source URL -> result
    seen_hashes: dict[str, dict] = {}   # sha256(data) -> result
    for n in names:
        pre_title = resolve_wikipedia_title(n)
        if pre_title in seen_titles:
            prior = seen_titles[pre_title]
            print(f"[fetch_logos] {n!r}: deduped -- resolves to same Wikipedia title as {prior['name']!r} ({pre_title!r}); skipping", file=sys.stderr)
            continue
        fetched = fetch_logo_for(n)
        if not fetched:
            missing.append(n)           # no Wikimedia logo -> fall back to web search (Step 6)
            continue
        url = fetched["source"]
        if url in seen_urls:
            prior = seen_urls[url]
            print(f"[fetch_logos] {n!r}: deduped -- same logo URL as {prior['name']!r} ({url}); skipping", file=sys.stderr)
            continue
        h = hashlib.sha256(fetched["data"]).hexdigest()
        if h in seen_hashes:
            prior = seen_hashes[h]
            print(f"[fetch_logos] {n!r}: deduped -- byte-identical to {prior['name']!r} (sha256 {h[:12]}); skipping", file=sys.stderr)
            continue
        # Survived all three dedup gates -- write to disk.
        # Slug is derived from the RESOLVED Wikipedia title (fetched["title"]),
        # not the raw input name. Why: when the spec writes the institute
        # differently across papers ("Microsoft Research Asia", "MSRA",
        # "Microsoft Research, Shanghai, China", "Department of XX,
        # Microsoft Research Asia"), parent_candidates / aliases all
        # cascade to the same Wikipedia title — so the filename is
        # canonical and downstream code can match the same logo across
        # multiple papers from the same org. Without this, paper_a got
        # `microsoft-research.png` while paper_b got
        # `microsoft-research-shanghai-china.png` (slug overfit on the
        # raw spec text including dept/location prefix).
        slug = slugify(fetched["title"])
        ext = detect_ext(fetched["data"])
        out = logos_dir / f"{slug}{ext}"
        out.write_bytes(fetched["data"])
        # Autotrim: rasterize (SVG -> PNG) + crop the transparent/near-white border
        # so the chip hugs the mark instead of floating in padding. Best-effort --
        # the original file is kept on any failure. An SVG that rasterizes returns a
        # tight <slug>.png; adopt it and drop the .svg so the header references the
        # trimmed raster.
        tight = autotrim(out)
        if tight != out:
            try:
                out.unlink()
            except Exception:
                pass
            out = tight
        rel = f"{layout.LOGOS}/{out.name}"
        print(f"[fetch_logos] {n!r} -> {rel}  ({out.stat().st_size} bytes, source={url})", file=sys.stderr)
        info = {"name": n, "slug": slug, "path": rel, "source": url}
        results.append(info)
        seen_titles[pre_title] = info
        seen_urls[url] = info
        seen_hashes[h] = info

    # Dedup: same source URL or same file bytes → one tile per visual logo.
    results = _dedupe_by_source(results, logos_dir)

    # CHECKLIST — surface exactly which institutes still need a logo so the
    # caller (SKILL.md Step 6) runs the web-search fallback on each one.
    got = {r["name"] for r in results}
    print(f"[fetch_logos] CHECKLIST: {len(got)}/{len(names)} institute(s) resolved via Wikimedia", file=sys.stderr)
    for n in names:
        mark = "✓" if n in got else ("·" if n not in missing else "✗")
        print(f"[fetch_logos]   {mark} {n}", file=sys.stderr)
    if missing:
        print(f"[fetch_logos]   ✗ MISSING — WEB-SEARCH FALLBACK REQUIRED (Step 6): {', '.join(missing)}", file=sys.stderr)

    print(json.dumps({"logos": results, "missing": missing}, indent=2))
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
