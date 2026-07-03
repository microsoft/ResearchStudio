"""subpattern_citation_consistency validator: catch fabricated sub-pattern citations in
Phase 2's gap_closure[].

Why this exists:
  Phase 2.2 asks the model to pick, for each gap, a `main_pattern` (parent ideation pattern)
  and a `sub_pattern` (a C##-tagged tactical cluster under that parent), then open that cluster's
  C##.md card and apply its tactical pattern. Nothing in the generation path forces the cited
  sub_pattern to actually exist or to live under the cited main_pattern. A model that never opened
  the card can still emit a plausible-looking citation invented from the main-pattern's gist.

  Note on this taxonomy's citation format: overview.md formats each row as
  `| \`C##\` | \`parent_slug\` (Parent Display Name) | n_papers |`, and ideate_generate.txt asks
  the model to write sub_pattern as `C## (parent display name)`. So the parenthetical is the
  PARENT's display name, NOT the cluster's own label (cluster labels live only inside C##.md).
  That means a clean citation here proves only parent-consistency, not that the C## card was read —
  the semantic recipe_application_check in critique.txt carries that load.

What it checks (per gap_closure[] entry), deterministically against overview.md:
  1. main_pattern is a real parent slug (one of the ~15 in overview.md).
  2. The sub_pattern's C## cluster id exists in overview.md.
  3. The cluster's true parent slug == the cited main_pattern (parent-consistency).
  4. The cited parenthetical == the cluster's parent display name (fuzzy on whitespace/case/
     punctuation, so paraphrase is allowed but a different concept is not).

Severity: fail. A fabricated citation means the parent/cluster wiring was guessed, not read.
Blocking the run forces a real overview read.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

_OVERVIEW = (Path(__file__).resolve().parents[2]
             / 'references' / 'ideation-sub-patterns' / 'overview.md')

# `| `C29` | `assumption_audit_and_pivot` (Audit and Pivot an Assumption) | 21 |`
_ROW = re.compile(r'^\|\s*`(C\d+)`\s*\|\s*`([^`]+)`\s*\(([^)]+)\)\s*\|')
_CLUSTER_ID = re.compile(r'\bC\d+\b')


def _load_overview() -> tuple[dict, set]:
    """Return ({cluster_id -> (parent_slug, parent_display_name)}, {valid_parent_slugs})."""
    clusters: dict = {}
    parents: set = set()
    if not _OVERVIEW.exists():
        return clusters, parents
    for line in _OVERVIEW.read_text().splitlines():
        m = _ROW.match(line)
        if m:
            cid, parent, disp = m.group(1), m.group(2).strip(), m.group(3).strip()
            clusters[cid] = (parent, disp)
            parents.add(parent)
    return clusters, parents


def _norm(s: str) -> str:
    """Whitespace/case/punctuation-insensitive key for fuzzy name comparison."""
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def validate_subpattern_citation_consistency(phase2_path: str) -> list[dict]:
    findings = []
    p2 = json.loads(Path(phase2_path).read_text())
    gap_closure = p2.get('gap_closure') or []

    clusters, valid_parents = _load_overview()
    if not clusters:
        findings.append({
            "severity": "warn", "validator": "subpattern_citation_consistency",
            "message": f"Could not load sub-pattern overview at {_OVERVIEW}; citation consistency unchecked.",
        })
        return findings

    if not isinstance(gap_closure, list) or len(gap_closure) == 0:
        findings.append({
            "severity": "warn", "validator": "subpattern_citation_consistency",
            "message": "gap_closure[] missing or empty; nothing to check.",
        })
        return findings

    for i, entry in enumerate(gap_closure):
        entry = entry or {}
        main_pattern = (entry.get('main_pattern') or '').strip()
        sub_pattern = (entry.get('sub_pattern') or '').strip()

        # 1. main_pattern must be a real parent slug
        if main_pattern and main_pattern not in valid_parents:
            findings.append({
                "severity": "fail", "validator": "subpattern_citation_consistency",
                "message": (f"gap_closure[{i}].main_pattern '{main_pattern}' is not a real parent "
                            f"slug in overview.md. The pattern was cited by gist, not read."),
            })

        # Parse the C## cluster id out of the sub_pattern string.
        cid_match = _CLUSTER_ID.search(sub_pattern)
        if not cid_match:
            findings.append({
                "severity": "fail", "validator": "subpattern_citation_consistency",
                "message": (f"gap_closure[{i}].sub_pattern '{sub_pattern}' has no C## cluster id; "
                            f"cannot verify it against overview.md."),
            })
            continue
        cid = cid_match.group(0)

        if cid not in clusters:
            findings.append({
                "severity": "fail", "validator": "subpattern_citation_consistency",
                "message": f"gap_closure[{i}].sub_pattern cites '{cid}', which is not a real cluster id in overview.md.",
            })
            continue

        true_parent, true_disp = clusters[cid]

        # 3. parent-consistency: cluster's real parent must equal the cited main_pattern
        if main_pattern and true_parent != main_pattern:
            findings.append({
                "severity": "fail", "validator": "subpattern_citation_consistency",
                "message": (f"gap_closure[{i}] cites {cid} under main_pattern '{main_pattern}', but "
                            f"{cid}'s real parent is '{true_parent}'. Parent mismatch — the cluster's "
                            f"row in overview.md was not actually read."),
            })

        # 4. name-consistency: cited parenthetical must match the cluster's parent display name
        cited_name = sub_pattern[cid_match.end():].strip(' ()[]:-')
        if cited_name and _norm(cited_name) != _norm(true_disp):
            findings.append({
                "severity": "fail", "validator": "subpattern_citation_consistency",
                "message": (f"gap_closure[{i}] cites {cid} as '{cited_name}', but {cid}'s parent display "
                            f"name is '{true_disp}'. Name mismatch — a name was invented, not read."),
            })

    if not findings:
        findings.append({
            "severity": "pass", "validator": "subpattern_citation_consistency",
            "message": "All gap_closure[] sub-pattern citations resolve to real clusters under their cited parents.",
        })
    return findings
