#!/usr/bin/env python3
"""Unit self-test for the deterministic helper modules.

`selftest_routing.py` covers the `next` navigator's branches; these two helpers sit
UNDER every phase instead of inside one, so a regression here is silent and global:

  scripts/_merge.py       — the multi-query round-robin every connector merges with
                            (its own docstring carries the regression that motivated
                            it). These fixtures pin the fairness property and the
                            from_query provenance the query-yield report needs.

  scripts/json_repair.py  — tolerant load for LLM-written JSON. Sub-agents writing CJK
                            prose type an ASCII `"` as a content quote and terminate the
                            string early; observed twice in live runs, in two different
                            phases, each time aborting an assemble mid-run.

Stdlib only. Run: python3 scripts/selftest_units.py
Exit 0 = all green; 1 = at least one failure (details on stderr).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._merge import interleave_by_query          # noqa: E402
from scripts.json_repair import loads_llm_json          # noqa: E402

RESULTS = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, ok))
    print(('  ok ' if ok else 'FAIL ') + name + ('' if ok else f' — {detail}'),
          file=sys.stderr)


K = (lambda h: h['t'])


def L(*names):
    return [{'t': n} for n in names]


def T(recs):
    return [r['t'] for r in recs]


# ---- _merge: fairness, provenance, back-compat ---------------------------------
r = interleave_by_query([L('a1', 'a2', 'a3'), L('b1', 'b2'), L('c1')], K, 4)
check('M1 every query represented before any second pick',
      T(r) == ['a1', 'b1', 'c1', 'a2'], str(T(r)))

r = interleave_by_query([L('a1', 'a2', 'a3', 'a4')], K, 2)
check('M2 single query is byte-identical to the old head-truncation',
      T(r) == ['a1', 'a2'], str(T(r)))

r = interleave_by_query([L('x', 'a2'), L('x', 'b2')], K, 4)
check('M3 cross-query duplicate kept once, earlier query wins the slot',
      T(r).count('x') == 1 and T(r)[0] == 'x', str(T(r)))

r = interleave_by_query([L('a1', 'a2', 'a3', 'a4', 'a5'), L('b1')], K, 5)
check('M4 exhausted queue does not stall the survivors',
      T(r) == ['a1', 'b1', 'a2', 'a3', 'a4'], str(T(r)))

r = interleave_by_query([L('a1', 'a2'), L('b1')], K, 0)
check('M5 max_results<=0 means no cap', len(r) == 3, str(T(r)))

# The regression that motivated the module: 6 queries, cap 40. Concatenation kept
# 40 items all from query 1; round-robin must represent all six.
sizes = [53, 41, 37, 76, 57, 18]
per = [L(*[f'q{i}_{j}' for j in range(n)]) for i, n in enumerate(sizes, 1)]
r = interleave_by_query(per, K, 40)
reps = {x['t'].split('_')[0] for x in r}
check('M6 measured 6-query/cap-40 case represents every query',
      len(r) == 40 and len(reps) == 6, f'{len(r)} kept from {sorted(reps)}')

r = interleave_by_query([L('a1'), L('b1')], K, 0, queries=['QA', 'QB'])
check('M7 from_query stamped when query text is supplied',
      [x.get('from_query') for x in r] == [['QA'], ['QB']],
      str([x.get('from_query') for x in r]))

r = interleave_by_query([L('dup'), L('dup')], K, 0, queries=['QA', 'QB'])
check('M8 a paper reachable from two queries credits both',
      len(r) == 1 and r[0]['from_query'] == ['QA', 'QB'], str(r))

src = [{'t': 'a1'}]
r = interleave_by_query([src], K, 0, queries=['QA'])
check('M9 stamping does not mutate the caller\'s input records',
      'from_query' not in src[0], str(src))

# ---- json_repair: the two observed live breakages ------------------------------
obj, rep = loads_llm_json('{"a": "评级短语"重复毫无价值"有多准确。"}')
check('J1 unescaped ASCII quote inside CJK prose is recovered',
      rep and obj['a'].count('"') == 2, str(obj))

obj, rep = loads_llm_json('{"a": "line1\nline2"}')
check('J2 raw newline inside a string is escaped', rep and obj['a'] == 'line1\nline2', str(obj))

obj, rep = loads_llm_json('{"a": "fine", "b": [1, 2]}')
check('J3 valid JSON passes through untouched (not repaired)',
      (not rep) and obj == {'a': 'fine', 'b': [1, 2]}, f'repaired={rep} {obj}')

obj, rep = loads_llm_json('{"a": "says "hi" ok", "b": 1}')
check('J4 inner quote immediately before a delimiter is not mistaken for the terminator',
      rep and obj == {'a': 'says "hi" ok', 'b': 1}, str(obj))

try:
    loads_llm_json('{"a": ')          # genuinely truncated — repair cannot save it
    check('J5 unrepairable input still raises', False, 'no exception')
except Exception:
    check('J5 unrepairable input still raises', True)

# ---- threat_grounding: the audit may not cite what it never retrieved ----------
import json as _json, tempfile as _tf, os as _os          # noqa: E402
from scripts.validators.threat_grounding import validate_threat_grounding  # noqa: E402


def _mk(threat, pool_ids):
    d = Path(_tf.mkdtemp())
    (d / 'phase0').mkdir(); (d / 'phase3_critique').mkdir()
    (d / 'phase0' / 'lit_results.json').write_text(
        _json.dumps([{'paper_id': i, 'title': 'T'} for i in pool_ids]))
    rp = d / 'phase3_critique' / 'phase3_critique_output.json'
    rp.write_text(_json.dumps({'paper_pointed_threat': threat}))
    return str(rp)


f = validate_threat_grounding(_mk({'threat_paper_id': 'arxiv:9999.11111'}, ['arxiv:1111.22222']))
check('G1 threat absent from the pool fails', len(f) == 1 and f[0]['severity'] == 'fail', str(f))

f = validate_threat_grounding(_mk({'threat_paper_id': 'arxiv:1111.22222'}, ['arxiv:1111.22222']))
check('G2 threat present in the pool passes', f == [], str(f))

f = validate_threat_grounding(_mk({'threat_paper_id': 'arxiv:1111.22222v3'}, ['arxiv:1111.22222']))
check('G3 version suffix still matches', f == [], str(f))

f = validate_threat_grounding(_mk({'threat_paper_id': 'no_threat_found'}, ['arxiv:1111.22222']))
check('G4 no_threat_found is legitimate', f == [], str(f))

f = validate_threat_grounding(_mk({'threat_paper_id': 'user_ref:arxiv_id:2606.1'}, ['arxiv:1111.22222']))
check('G5 user_ref exempt (synthetic record, never in lit_results)', f == [], str(f))

f = validate_threat_grounding(_mk(
    {'threat_paper_id': 'arxiv:1111.22222',
     'parametric_family_concern': 'query-adaptive KV retrieval, see arxiv:2507.06961'},
    ['arxiv:1111.22222']))
check('G6 concrete cite inside parametric_family_concern fails',
      len(f) == 1 and 'parametric_family_concern' in f[0]['message'], str(f))

f = validate_threat_grounding(_mk(
    {'threat_paper_id': 'arxiv:1111.22222',
     'parametric_family_concern': 'family: query-adaptive KV cache retrieval; terms: token budget'},
    ['arxiv:1111.22222']))
check('G7 family name + vocabulary passes', f == [], str(f))

n_fail = sum(1 for _n, ok in RESULTS if not ok)
print(f'\n[{"RED" if n_fail else "GREEN"}] selftest_units: '
      f'{len(RESULTS) - n_fail}/{len(RESULTS)} passed', file=sys.stderr)
sys.exit(1 if n_fail else 0)
