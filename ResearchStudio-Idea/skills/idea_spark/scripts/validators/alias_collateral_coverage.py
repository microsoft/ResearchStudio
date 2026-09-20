"""alias_collateral_coverage validator: Phase 2.2's `alias_terms[]` must actually
query the cross-community families Phase 1 already named.

Why this exists — the omission was measured twice, in consecutive runs:

  Run `self-harness-holdout`: the collision pool never surfaced delta debugging /
  `ddmin` / 1-minimality or test-suite minimization. The Phase 3.2 audit found
  them by reading the candidate by hand and flagged the pool as defective.

  Run `skillopt-deploy-cost`: Phase 1 responded by pinning NINE collateral
  families into `method_lineage` (group testing, screening designs, ddmin,
  test-suite minimization, blame bisection, Shapley, McNemar, ...). Phase 2.2's
  `alias_terms[]` then queried ZERO of them, because the prompt asked for alias
  terms from parametric recall and said nothing about the list sitting in its
  own input file. The audit's own retrieval later found combinatorial-group-
  testing work carrying the candidate's exact observation model.

The mechanism of the failure is not laziness — it is that parametric recall
reaches for near neighbours in the writer's own vocabulary, while the collateral
list is by construction the FAR ones. The names were already written down
one phase earlier; nothing was reading them.

What it checks:
  For every `method_lineage.nodes[]` entry with `is_collateral: true`, at least
  one `alias_terms[]` entry shares >= MIN_SHARED distinctive tokens with that
  node's `method` name.

Severity split — deliberate, not hedging:
  * ZERO of N collateral nodes covered -> fail. This is the measured failure
    mode and it is unambiguous: the list was handed over and not opened.
  * SOME but not all covered -> warn, naming the uncovered families. A node can
    legitimately be unreachable from a given mechanism, and forcing a term for
    it would push a fabricated query into a channel that truncates by lexical
    relevance — i.e. a hard fail here would evict REAL terms to make room for
    noise. ideate_generate.txt asks for the skip to be justified in
    `composition_note`; the Phase 3.2 audit weighs whether that defense holds.
  * No collateral nodes at all (or no phase1 file) -> nothing to check.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

MIN_SHARED = 2

# Words that would manufacture false coverage. These are the terms that appear in
# almost every method name in this taxonomy, so an overlap consisting only of them
# proves nothing about whether the family was actually queried.
_GENERIC = {
    'a', 'an', 'and', 'or', 'the', 'of', 'for', 'with', 'to', 'in', 'on', 'by',
    'via', 'from', 'as', 'its', 'their', 'that', 'this', 'is', 'are', 'be',
    'method', 'methods', 'approach', 'approaches', 'model', 'models',
    'learning', 'search', 'optimization', 'optimisation', 'optimizing',
    'based', 'aware', 'driven', 'analysis', 'evaluation', 'estimation',
    'algorithm', 'algorithms', 'framework', 'system', 'systems',
    'data', 'task', 'tasks', 'cost', 'costs', 'score', 'scores', 'test',
    'tests', 'set', 'sets', 'agent', 'agents', 'llm', 'llms', 'neural',
    'and/or', 'successors', 'style',
}


def _tokens(s: str) -> set:
    """Distinctive lowercase tokens: alphanumerics, generic vocabulary stripped."""
    raw = re.split(r'[^a-z0-9]+', (s or '').lower())
    return {t for t in raw if len(t) > 2 and t not in _GENERIC}


def uncovered_collateral(p2: dict, p1: dict) -> list:
    """Names of Phase 1 collateral families that no alias term queries."""
    nodes = ((p1.get('method_lineage') or {}).get('nodes') or [])
    collateral = [n for n in nodes if isinstance(n, dict) and n.get('is_collateral')]
    aliases = [a for a in (p2.get('alias_terms') or []) if isinstance(a, str)]
    alias_tokens = [_tokens(a) for a in aliases]
    uncovered = []
    for n in collateral:
        name = (n.get('method') or n.get('node_id') or '').strip()
        want = _tokens(name)
        if not want:
            continue
        # A family whose name reduces to ONE distinctive token (`ddmin`, `McNemar's
        # test`) can never share two, so a flat MIN_SHARED made those permanently
        # uncoverable — including `ddmin`, the family this validator exists because a
        # run missed. Require the lesser of MIN_SHARED and what the name actually has.
        need = min(MIN_SHARED, len(want))
        if not any(len(want & got) >= need for got in alias_tokens):
            uncovered.append(name)
    return uncovered


def unjustified_collateral(p2: dict, p1: dict) -> list:
    """Uncovered families the candidate neither queries nor explains away: `composition_note` must
    name the family it skips (the generation prompt asks for which and why). Used by the record
    handshake so the explanation is written when the candidate is, not weighed later from silence."""
    note = _tokens(str(p2.get('composition_note') or ''))
    out = []
    for name in uncovered_collateral(p2, p1):
        want = _tokens(name)
        if len(want & note) < min(MIN_SHARED, len(want)):
            out.append(name)
    return out


def validate_alias_collateral_coverage(phase2_path: str, phase1_path: str) -> list[dict]:
    findings = []
    V = 'alias_collateral_coverage'

    p1_file = Path(phase1_path)
    if not p1_file.exists():
        return findings
    try:
        p1 = json.loads(p1_file.read_text())
    except Exception as e:
        findings.append({"severity": "warn", "validator": V,
                         "message": f"Could not parse {phase1_path} ({e}); collateral coverage unchecked."})
        return findings

    nodes = ((p1.get('method_lineage') or {}).get('nodes') or [])
    collateral = [n for n in nodes if isinstance(n, dict) and n.get('is_collateral')]
    if not collateral:
        return findings

    p2 = json.loads(Path(phase2_path).read_text())
    uncovered = uncovered_collateral(p2, p1)

    n_total = len(collateral)
    n_missing = len(uncovered)

    def _short(names, k=4):
        out = [x[:70] for x in names[:k]]
        if len(names) > k:
            out.append(f'... (+{len(names) - k} more)')
        return '; '.join(out)

    # With a single collateral node there is no list to ignore, and the measured
    # failure was ignoring one (nine families named, zero queried). One unreachable
    # family is exactly the case the partial branch already treats as legitimate, so
    # it warns rather than blocking a run on a single judgment call.
    if n_missing == n_total and n_total > 1:
        findings.append({
            "severity": "fail", "validator": V,
            "message": (
                f"alias_terms[] queries NONE of the {n_total} collateral families Phase 1 named: "
                f"{_short(uncovered, 6)}. Those nodes are, by their own definition, methods that "
                f"attack this same residual through a different mechanism — Phase 1 already did the "
                f"cross-community naming and wrote the answers into method_lineage. Alias terms built "
                f"only from parametric recall systematically miss them (measured twice: one run's pool "
                f"never surfaced ddmin/test-suite minimization; the next run pinned nine families and "
                f"queried zero, and the audit's own retrieval then found group-testing work carrying the "
                f"candidate's exact observation model). Add one alias term per collateral node, phrased "
                f"in THAT field's vocabulary, and re-run Phase 3.1 collision."),
        })
    elif n_missing:
        findings.append({
            "severity": "warn", "validator": V,
            "message": (
                f"alias_terms[] covers {n_total - n_missing}/{n_total} of Phase 1's collateral families; "
                f"not queried: {_short(uncovered)}. A family can legitimately be unreachable from this "
                f"mechanism — if so, ideate_generate.txt asks for which and why in composition_note, and "
                f"the Phase 3.2 audit weighs that defense. If it is reachable, the multi-year alias "
                f"channel is the only place it would have been caught."),
        })
    else:
        findings.append({
            "severity": "pass", "validator": V,
            "message": f"alias_terms[] queries all {n_total} collateral families Phase 1 named.",
        })
    return findings
