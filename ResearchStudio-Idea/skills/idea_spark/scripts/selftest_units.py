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
import json
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

# --- alias_collateral_coverage -------------------------------------------------
#
# Severity split under test: ZERO coverage is a fail (the measured failure mode —
# Phase 1 handed over the list and Phase 2.2 never opened it); PARTIAL coverage is
# a warn (a family can be genuinely unreachable, and forcing a fabricated term
# would evict real ones from a channel that truncates by lexical relevance).
from scripts.validators.alias_collateral_coverage import validate_alias_collateral_coverage  # noqa: E402


def _ac(alias_terms, collateral_methods):
    """Write a minimal phase1/phase2 pair to temp files and validate them."""
    import tempfile
    p1 = {'method_lineage': {'nodes': (
        [{'node_id': 'n0', 'method': 'Held-out model selection', 'is_collateral': False}]
        + [{'node_id': f'c{i}', 'method': m, 'is_collateral': True}
           for i, m in enumerate(collateral_methods)])}}
    p2 = {'alias_terms': alias_terms}
    dd = Path(tempfile.mkdtemp(prefix='i2r_ac_'))
    (dd / 'p1.json').write_text(json.dumps(p1))
    (dd / 'p2.json').write_text(json.dumps(p2))
    return validate_alias_collateral_coverage(str(dd / 'p2.json'), str(dd / 'p1.json'))


_DDMIN = 'Delta debugging / ddmin and 1-minimality (Zeller & Hildebrandt, 2002)'
_GT = 'Quantitative group testing and screening designs: Dorfman pooling (1943)'

f = _ac(['reflective prompt rewriting loop', 'held-out gated scaffold search'], [_DDMIN, _GT])
check('A1 zero collateral coverage fails',
      len(f) == 1 and f[0]['severity'] == 'fail', str(f))

f = _ac(['delta debugging ddmin minimality', 'quantitative group testing pooling'], [_DDMIN, _GT])
check('A2 full collateral coverage passes',
      len(f) == 1 and f[0]['severity'] == 'pass', str(f))

f = _ac(['delta debugging ddmin minimality'], [_DDMIN, _GT])
check('A3 partial coverage warns and names the gap',
      len(f) == 1 and f[0]['severity'] == 'warn' and 'group testing' in f[0]['message'], str(f))

# No collateral nodes -> nothing to check. A diagnosis that pinned no cross-field
# families must not be punished for it; that judgment belongs to Phase 1.
f = _ac(['anything at all'], [])
check('A4 no collateral nodes -> silent', f == [], str(f))

# Generic-word overlap must NOT count as coverage. Without this, "cost-aware
# agent evaluation" would "cover" every node whose name contains cost/agent —
# a validator that can be satisfied by vocabulary noise trains people to ignore it.
# Two nodes, so the verdict is the generic-token rule and not the single-node rule
# tested in A7.
f = _ac(['cost aware agent evaluation method'],
        ['Cost-sensitive learning with test/attribute acquisition costs',
         'Screening designs for batched assays'])
check('A5 generic-token overlap does not count as coverage',
      len(f) == 1 and f[0]['severity'] == 'fail', str(f))

# A family whose name carries ONE distinctive token cannot share two, so a flat
# threshold made `ddmin` and `McNemar's test` permanently uncoverable — `ddmin`
# being the family whose omission this validator exists to catch.
f = _ac(['ddmin delta debugging', 'mcnemar paired significance'],
        ['ddmin', "McNemar's test"])
check('A6 single-distinctive-token family can be covered',
      len(f) == 1 and f[0]['severity'] == 'pass', str(f))

# One node is not a list to ignore. The measured failure was nine named and zero
# queried; a lone unreachable family is the case A3 already treats as legitimate.
f = _ac(['unrelated vocabulary'], ['Combinatorial group testing'])
check('A7 a single uncovered node warns rather than blocking',
      len(f) == 1 and f[0]['severity'] == 'warn', str(f))

# --- B: compute-budget parsing -------------------------------------------
# Measured failure (i2r run `dllm-oracle`): intake said
#   "NTU EEE cluster02, slurm; pro6000/a40/a6000/l40/6000ada nodes"
# — no GPU-day figure anywhere — and the bare-number fallback returned 2
# (from `cluster02`). A 6 GPU-day request was then judged `infeasible` at 200%
# of a budget that never existed. `a40` would have given 40, `pro6000` 6000.
#
# The parse did not fail loudly; it produced a plausible number. That is the
# worse failure mode, and it is why the fallback now refuses to guess.
from phase4_skeleton import _extract_gpu_days as _gd    # noqa: E402

check('B1 hardware model numbers are not budgets',
      _gd('NTU EEE cluster02, slurm; pro6000/a40/a6000/l40/6000ada nodes') is None,
      repr(_gd('NTU EEE cluster02, slurm; pro6000/a40/a6000 nodes')))
check('B2 unit-bearing figures still parse', _gd('about 30 GPU-days on L40') == 30.0)
check('B3 H100 counts double', _gd('4 H100-day') == 8.0)
check('B4 dollars are not GPU-days', _gd('$8k API, no GPUs') is None)
check('B5 a bare number with no time unit is not a budget',
      _gd('budget 12 , mostly inference') is None)
# `12 days on 8x a40` is 96 GPU-days, not 12. Guessing 12 UNDERESTIMATES,
# which would call an infeasible plan feasible — the unsafe direction.
check('B6 a GPU-count multiplier makes the fallback abstain',
      _gd('budget: 12 days on 8x a40') is None)
check('B7 bare number adjacent to a unit still works', _gd('roughly 20 days of compute') == 20.0)

# ---- user_direction: a stated direction may be departed from, never silently -------
from scripts.validators.user_direction import validate_user_direction   # noqa: E402

QUERY = 'I want to unify the four action modalities into one space, not retrieval tricks.'


def _ud(intake_dir, disp, query=QUERY):
    d = Path(_tf.mkdtemp())
    (d / 'phase0').mkdir(); (d / 'phase1').mkdir(); (d / 'phase2_select').mkdir()
    if query is not None:
        (d / 'phase0' / 'user_query.txt').write_text(query)
    p1 = d / 'phase1' / 'phase1_output.json'
    p1.write_text(_json.dumps({'intake': {'user_direction': intake_dir}}))
    ps = d / 'phase2_select' / 'phase2_select_output.json'
    ps.write_text(_json.dumps({} if disp is None else {'user_direction_disposition': disp}))
    return str(p1), str(ps)


WANT = 'unify the four action modalities into one space'
OK = {'verdict': 'departed', 'user_wanted': WANT, 'chosen': 'inference-time search',
      'why_departed': 'fusion needs a new architecture, paired data and a retrain'}

f = validate_user_direction(*_ud('n_a', None))
check('U1 no stated direction -> validator silent', f == [], str(f))

f = validate_user_direction(*_ud(WANT, None))
check('U2 direction stated but no disposition fails', len(f) == 1 and f[0]['severity'] == 'fail', str(f))

f = validate_user_direction(*_ud(WANT, OK))
check('U3 departed with a reason passes', [x for x in f if x['severity'] != 'pass'] == [], str(f))

f = validate_user_direction(*_ud(WANT, dict(OK, why_departed='   ')))
check('U4 departed with empty why_departed fails',
      any('why_departed' in x['message'] for x in f), str(f))

f = validate_user_direction(*_ud(WANT, dict(OK, verdict='n_a')))
check('U5 n_a verdict while a direction is stated fails', len(f) == 1, str(f))

f = validate_user_direction(*_ud(WANT, dict(OK, verdict='ignored')))
check('U6 unknown verdict fails', len(f) == 1 and 'verdict' in f[0]['message'], str(f))

# The reason phase0/user_query.txt exists: without it "verbatim" is unfalsifiable.
f = validate_user_direction(*_ud('merge every modality into a shared latent', OK))
check('U7 paraphrased intake.user_direction is caught against the query',
      any('not a span' in x['message'] for x in f), str(f))

f = validate_user_direction(*_ud(WANT, dict(OK, user_wanted='the user wanted fusion')))
check('U8 paraphrased user_wanted is caught', any('user_wanted' in x['message'] for x in f), str(f))

f = validate_user_direction(*_ud(WANT, dict(OK, user_wanted='unify the four ... into one space')))
check('U9 elided middle is tolerated', [x for x in f if x['severity'] != 'pass'] == [], str(f))

f = validate_user_direction(*_ud(WANT, OK, query=None))
check('U10 no query on disk -> skip the span check, do not cry wolf', [x for x in f if x['severity'] != 'pass'] == [], str(f))

# ---- resolve_named_paper: a nickname is not a title ---------------------------
from scripts.extract_user_refs import resolve_named_paper                # noqa: E402


def _fake(*titles):
    recs = [{'title': x, 'arxiv_id': f'0000.{i}', 'year': 2020 + i} for i, x in enumerate(titles)]
    return lambda q, **kw: recs


f = resolve_named_paper('villa-X', _fake('villa-X: Enhancing Latent Action Modeling'), None)
check('N1 nickname resolves through containment, not 0.9 title similarity',
      (f or {}).get('arxiv_id') == '0000.0', str(f))

f = resolve_named_paper('AdaWorld', _fake('A survey that mentions AdaWorld in passing'), None)
check('N2 merely being MENTIONED does not count as being named by it', f is None, str(f))

# The measured miss: preferring the newest picked Genie Envisioner over the canonical Genie.
f = resolve_named_paper('Genie', _fake('Genie Envisioner: A Unified World Foundation Platform',
                                       'Genie: Generative Interactive Environments'), None)
check('N3 two papers leading with the name -> refuse, do not guess',
      isinstance(f, dict) and len(f.get('_ambiguous') or []) == 2, str(f))

f = resolve_named_paper('Nonesuch', _fake('Something else entirely'), None)
check('N4 no candidate -> None', f is None, str(f))

f = resolve_named_paper('', _fake('anything'), None)
check('N5 empty name -> None, no search', f is None, str(f))

f = resolve_named_paper('Cosmos', _fake('Cosmos World Foundation Model Platform for Physical AI'), None)
check('N6 no-colon system title still resolves (containment, not punctuation)',
      (f or {}).get('arxiv_id') == '0000.0', str(f))

n_fail = sum(1 for _n, ok in RESULTS if not ok)
print(f'\n[{"RED" if n_fail else "GREEN"}] selftest_units: '
      f'{len(RESULTS) - n_fail}/{len(RESULTS)} passed', file=sys.stderr)
sys.exit(1 if n_fail else 0)
