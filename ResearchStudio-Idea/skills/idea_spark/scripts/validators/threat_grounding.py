"""Validator: the audit's named threat must exist in the pools the audit was given.

`paper_pointed_threat.threat_paper_id` is the ONE audit field that names an external
entity, and it is load-bearing — an exact-mechanism collision is a hard floor, and the
id flows on into Phase 4's reviewer_concerns and the rendered card. critique.txt forbids
inventing one in prose, but prose is the only thing that forbade it: measured across 44
audit reports, 6 named a threat that appears in neither `lit_results.json` nor the
collision pool. Those ids came from parametric memory wearing the format of a retrieved
one, which is worse than a vague threat because it looks checkable.

`parametric_family_concern` is the sanctioned channel for un-retrieved knowledge and is
specified as a family name plus query vocabulary — never a paper cite. Two of the 44
reports put concrete ids there too, so the same check covers it.

Both are `fail`: an unverifiable citation in the deliverable is not a style problem.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ID = re.compile(r'\b(?:arxiv|semanticscholar|openalex|dblp|doi|openreview):[^\s"\',;)\]]+')


def _pool_text(run_dir: Path) -> str:
    """Everything the audit was allowed to draw a threat from."""
    parts = []
    for rel in ('phase0/lit_results.json', 'phase0/lit_table.md',
                'phase3_collision/collision_hits.json',
                'phase3_collision/collision_hits.full.json'):
        try:
            parts.append((run_dir / rel).read_text())
        except Exception:
            pass
    return '\n'.join(parts)


def _in_pool(ident: str, pool: str) -> bool:
    if not pool:
        return True          # no pool on disk -> cannot judge, do not cry wolf
    if ident in pool:
        return True
    # An id may be written with/without a version suffix, or the audit may have put a
    # TITLE where an id belongs; accept a distinctive-token match before failing.
    base = re.sub(r'v\d+$', '', ident)
    if base and base in pool:
        return True
    toks = [t for t in re.split(r'[^A-Za-z0-9]+', ident) if len(t) > 4][:3]
    return bool(toks) and all(t in pool for t in toks)


def validate_threat_grounding(phase3_path: str, run_dir: str | None = None) -> list[dict]:
    findings: list[dict] = []
    p3 = Path(phase3_path)
    try:
        rep = json.loads(p3.read_text())
    except Exception:
        return findings
    threat = rep.get('paper_pointed_threat')
    if not isinstance(threat, dict):
        return findings

    # run dir: caller-supplied, else walk up from the report (…/phase3_critique/x.json,
    # or …/attempt_N/phase3_critique/x.json)
    rd = Path(run_dir) if run_dir else p3.parent.parent
    if rd.name.startswith('attempt_'):
        rd = rd.parent
    pool = _pool_text(rd)

    tid = str(threat.get('threat_paper_id') or '').strip()
    if tid and tid.lower() != 'no_threat_found' and not tid.startswith('user_ref:'):
        if not _in_pool(tid, pool):
            findings.append({
                'validator': 'threat_grounding',
                'severity': 'fail',
                'message': (
                    f'paper_pointed_threat.threat_paper_id "{tid}" appears in neither '
                    f'lit_results/lit_table nor the collision pool under {rd}. The threat '
                    f'must be named FROM those pools; an id recalled from parametric memory '
                    f'reads as retrieved evidence and flows into the rendered card. Either '
                    f're-name the threat from the pools, set it to no_threat_found, or move '
                    f'the observation to parametric_family_concern as a FAMILY (no id).'),
            })

    pfc = threat.get('parametric_family_concern')
    if pfc:
        ids = _ID.findall(json.dumps(pfc, ensure_ascii=False))
        if ids:
            findings.append({
                'validator': 'threat_grounding',
                'severity': 'fail',
                'message': (
                    f'parametric_family_concern cites concrete paper id(s) {ids[:3]}. This '
                    f'field is the channel for UN-retrieved parametric knowledge and is '
                    f'specified as a family name plus query vocabulary only — a specific '
                    f'cite here has passed through no retrieval and cannot be checked. '
                    f'Name the family and the query terms instead.'),
            })
    return findings
