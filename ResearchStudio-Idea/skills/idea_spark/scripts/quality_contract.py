"""Version-2 evidence contracts. Hashes establish provenance, never scientific truth.

All navigation helpers are pure. Requests are prepared BEFORE a model call and
results are committed only against the same inputs. Historical output is never
silently adopted as a fresh review.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

VERSION = 2
MECHANISM_FIELDS = ('core_mechanism', 'core_mechanism_reasoning', 'core_mechanism_steps',
                    'gap_closure', 'falsification_prediction')
CARDS = ('idea.std.zh.md', 'idea.std.en.md', 'idea.detail.en.md')


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def fingerprint(path):
    p = Path(path)
    if not p.exists():
        return None
    if p.is_dir():
        return digest({str(f.relative_to(p)): fingerprint(f) for f in sorted(p.rglob('*'))
                       if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc'})
    return hashlib.sha256(p.read_bytes()).hexdigest()


def atomic_json(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, ensure_ascii=False); f.write('\n')
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def has_contract(run):
    return (read(Path(run) / 'run_contract.json', {}) or {}).get('contract_version') == VERSION


def init_run(run):
    d = Path(run).resolve()
    if d.exists() and any(d.iterdir()):
        if has_contract(d):
            return
        raise ValueError('Refusing to migrate a nonempty historical run. Use a new run directory.')
    atomic_json(d / 'run_contract.json', {'contract_version': VERSION,
                'purpose': 'research proposal; not experimentally validated',
                'run_id': str(uuid.uuid4()), 'depth': depth_from_env()})


def depth_from_env():
    """`idea` (default): audit what makes the idea an idea — the mechanism computes, measures what it
    claims, differs from its ablation and from prior work; the experiment's arithmetic is not audited and
    Phase 4 lists implementation holes instead of executing, repairing and re-reviewing. `experiment`
    (IDEASPARK_DEPTH=experiment): the full Phase 4 — executed implementability trace, bounded technical
    repair, technical review, falsification-revision route — for a reader who will run the minimal
    experiment. Fixed at init so a run never changes depth midway."""
    return 'experiment' if os.environ.get('IDEASPARK_DEPTH', 'idea').strip().lower() in ('experiment', 'full') else 'idea'


def run_depth(run):
    """A contract written before depths existed was audited in full: it reads `experiment`."""
    return read(Path(run) / 'run_contract.json', {}).get('depth', 'experiment')


def stage_dir(run, stage):
    if not re.fullmatch(r'[a-z0-9_]+', stage):
        raise ValueError('Invalid stage identifier')
    return Path(run) / '.quality' / stage


def path_in_run(run, rel):
    d = Path(run).resolve(); p = (d / rel).resolve()
    if not p.is_relative_to(d) or p == d:
        raise ValueError(f'Artifact path escapes run: {rel}')
    return p


def input_hashes(inputs):
    out = {str(Path(p).resolve()): fingerprint(p) for p in inputs}
    if any(v is None for v in out.values()):
        raise ValueError('Missing inputs: ' + ', '.join(p for p, v in out.items() if v is None))
    return out


def prepare(run, spec):
    if not has_contract(run):
        raise ValueError('A version-2 run contract is required')
    sd = stage_dir(run, spec['stage'])
    req = {'contract_version': VERSION, 'request_id': str(uuid.uuid4()), **spec,
           'inputs_sha256': input_hashes(spec['inputs'] + spec.get('prompts', []))}
    req['output_before'] = {r: fingerprint(path_in_run(run, r)) for r in spec['outputs']}
    req['candidate_digests'] = {str(Path(p).resolve()): digest(read(p)) for p in spec['inputs']
                                if Path(p).suffix == '.json' and isinstance(read(p), dict)}
    prior = read(sd / 'request.json')
    if prior:
        atomic_json(sd / 'history' / (prior['request_id'] + '.json'), prior)
    atomic_json(sd / 'request.json', req)
    return req


def receipt_valid(run, stage, spec=None):
    sd = stage_dir(run, stage)
    try:
        receipt = read(sd / 'receipt.json', {})
        if receipt.get('contract_version') != VERSION:
            return False
        if spec and receipt.get('spec_hash') != digest(spec):
            return False
        if any(fingerprint(p) != h for p, h in receipt['inputs_sha256'].items()):
            return False
        return bool(receipt['outputs_sha256']) and all(
            h is not None and fingerprint(path_in_run(run, p)) == h for p, h in receipt['outputs_sha256'].items())
    except (ValueError, KeyError, TypeError, OSError):
        return False


class RecordRejected(ValueError):
    """The result is well-formed but breaks a rule the author can fix in place. Not a needs_work:
    the same request stays open, the findings go back to the author, and the fixed result is
    recorded against the same request_id."""


PHASE1 = 'phase1/phase1_output.json'
RECORD_REJECTIONS = 2         # a third result on the same request is committed with the findings as warns


def assemble_parts(sd, req):
    """A large artifact may be written in parts: `.quality/<stage>/result.parts/*.json`, each an
    envelope fragment `{"artifacts": {"rel/path": {some top-level fields}}}`. Parts merge in name
    order into one result.json. Observed: a single 88 KB Write stalled the author twice; four
    20 KB writes did not."""
    parts = sorted((sd / 'result.parts').glob('*.json')) if (sd / 'result.parts').is_dir() else []
    if not parts or (sd / 'result.json').exists():
        return
    def deep(into, frag):
        # a part may carry a slice of a nested object (trace_report.formalized_procedure in one part,
        # trace_report.dry_run in the next): dicts merge key by key, anything else is replaced.
        # Observed: a shallow update dropped four trace_report sections and the record went needs_work.
        for k, v in frag.items():
            if isinstance(v, dict) and isinstance(into.get(k), dict):
                deep(into[k], v)
            else:
                into[k] = v
        return into
    merged = {}
    for p in parts:
        frag = read(p)
        arts = frag.get('artifacts') if isinstance(frag, dict) else None
        if not isinstance(arts, dict):
            raise ValueError(f'{p.name}: a part must be {{"artifacts": {{path: object}}}}')
        for rel, payload in arts.items():
            if not isinstance(payload, dict):
                raise ValueError(f'{p.name}: {rel} must be a JSON object fragment')
            deep(merged.setdefault(rel, {}), payload)
    atomic_json(sd / 'result.json', {'contract_version': VERSION, 'request_id': req['request_id'], 'artifacts': merged})


def record_findings(run, stage, payloads):
    """Rules the author can satisfy in the result itself. plain_derive: the Chinese word-order rule
    (a rule, not a request — checked before commit, so the fix is a field edit and not a re-render).
    generation: every Phase 1 collateral family is either queried by an alias term or named in
    composition_note as unreachable (the audit weighs the reason; silence was the measured failure)."""
    from scripts.validators.chinese_word_order import chinese_word_order_findings
    from scripts.validators.alias_collateral_coverage import unjustified_collateral
    out = []
    if stage == 'plain_derive':
        for payload in payloads.values():
            out += [f for f in chinese_word_order_findings(payload) if f.get('severity') in ('warn', 'fail')]
    if stage == 'generation':
        p1 = read(run / PHASE1, {})
        for rel, payload in payloads.items():
            if rel.endswith('phase2_generate_output.json') and p1:
                missing = unjustified_collateral(payload, p1)
                if missing:
                    out.append(finding('alias_collateral_unjustified',
                                       'alias_terms[] queries none of these Phase 1 collateral families and '
                                       'composition_note does not name them: ' + '; '.join(m[:70] for m in missing[:5]) +
                                       '. Add one alias term per family in THAT field\'s vocabulary, or say in '
                                       'composition_note which family is unreachable from this mechanism and why.', 'warn'))
    return out


def record(run, stage):
    sd = stage_dir(run, stage)
    req = read(sd / 'request.json')
    if req:
        assemble_parts(sd, req)
    result = read(sd / 'result.json')
    if not req or not result or result.get('request_id') != req['request_id']:
        raise ValueError('Missing result or wrong request_id; old output cannot stand in for a new call')
    if any(fingerprint(p) != h for p, h in req['inputs_sha256'].items()):
        raise ValueError('Inputs or prompts changed during review; prepare a fresh request')
    payloads = result.get('artifacts', {})
    if set(payloads) != set(req['outputs']):
        raise ValueError('Result must contain exactly the requested artifact paths')
    if receipt_valid(run, stage) and read(sd / 'receipt.json').get('request_id') == req['request_id']:
        return  # repeated commit is idempotent
    for rel, old in req['output_before'].items():
        if fingerprint(path_in_run(run, rel)) != old:
            raise ValueError(f'Concurrent output modification: {rel}')
    for rel, payload in payloads.items():
        if not isinstance(payload, dict):
            raise ValueError(f'{rel}: expected JSON object')
    fs = record_findings(run, stage, payloads)
    if fs:
        rej = read(sd / 'rejection.json', {})
        attempts = (rej.get('attempts', 0) if rej.get('request_id') == req['request_id'] else 0) + 1
        atomic_json(sd / 'rejection.json', {'request_id': req['request_id'], 'attempts': attempts,
                                             'result_sha256': fingerprint(sd / 'result.json'), 'findings': fs,
                                             'accepted': attempts > RECORD_REJECTIONS})
        if attempts <= RECORD_REJECTIONS:
            raise RecordRejected('; '.join(f['message'][:300] for f in fs))
    # Keep prior outputs recoverable; receipt is the transaction commit marker.
    for rel, payload in payloads.items():
        target = path_in_run(run, rel)
        if target.exists():
            atomic_json(sd / 'history' / req['request_id'] / (target.name + '.before.json'), read(target))
        atomic_json(target, payload)
    spec = {k: req[k] for k in ('stage', 'inputs', 'prompts', 'outputs', 'notes') if k in req}
    atomic_json(sd / 'receipt.json', {'contract_version': VERSION,
        'request_id': req['request_id'], 'spec_hash': digest(spec),
        'inputs_sha256': req['inputs_sha256'],
        'outputs_sha256': {r: fingerprint(path_in_run(run, r)) for r in req['outputs']}})


def deterministic_receipt(run, stage, inputs, outputs):
    """Only called by the deterministic command that actually produced these outputs."""
    hashes = {r: fingerprint(path_in_run(run, r)) for r in outputs}
    if not hashes or any(v is None for v in hashes.values()):
        raise ValueError('Cannot record an execution with missing outputs')
    atomic_json(stage_dir(run, stage) / 'receipt.json', {'contract_version': VERSION,
        'request_id': 'deterministic', 'inputs_sha256': input_hashes(inputs),
        'outputs_sha256': hashes})


def object_key(candidate):
    o = candidate.get('intervention_object') if isinstance(candidate, dict) else None
    if not isinstance(o, dict): return None
    return ' | '.join(re.sub(r'\s+', ' ', str(o.get(k, '')).strip().lower()) for k in ('acts_on', 'operator'))


def candidate_findings(candidate, selection, archived=()):
    out = []
    o = candidate.get('intervention_object')
    if not isinstance(o, dict) or not all(str(o.get(k, '')).strip() for k in ('acts_on', 'operator')):
        out.append(finding('candidate_contract', 'Missing intervention_object (acts_on, operator, decision_variables)'))
    else:
        # A retry that keeps the same object under a new name is the pattern that produced three
        # consecutive executed abandons on one topic; the gate refuses it before any call is spent.
        key = object_key(candidate)
        for a in archived:
            if object_key(a) and object_key(a) == key:
                out.append(finding('candidate_contract', 'Intervention object repeats an archived cycle: '
                                   + str(a.get('title', ''))[:80] + ' — change the object or the anchor gap'))
                break
    for key in ('title', 'hook', 'core_mechanism', 'core_mechanism_reasoning',
                'core_mechanism_steps', 'compute_budget', 'falsification_prediction'):
        if not isinstance(candidate.get(key), str) or not candidate[key].strip():
            out.append(finding('candidate_contract', 'Missing/non-string candidate field: ' + key))
    for key in ('signature_terms', 'alias_terms'):
        if not isinstance(candidate.get(key), list) or not candidate[key]:
            out.append(finding('candidate_contract', 'Missing candidate terms: ' + key))
    gaps = candidate.get('gap_closure', []); selected = selection.get('selected_gaps', [])
    if not isinstance(gaps, list) or [g.get('gap') for g in gaps] != [g.get('gap') for g in selected]:
        out.append(finding('candidate_contract', 'Candidate gaps do not mirror selection in order'))
    elif any(g.get('companion_pattern') != s.get('companion_pattern') for g, s in zip(gaps, selected)):
        out.append(finding('candidate_contract', 'Candidate silently changed a companion binding'))
    return out


def change_scope(before, after):
    changed = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    mechanism = any(k in MECHANISM_FIELDS for k in changed)
    novelty = mechanism or any(k in changed for k in
        ('signature_terms', 'alias_terms', 'differentiation_from_lit', 'what_step_was_missed'))
    return {'changed_fields': sorted(changed), 'mechanism': mechanism, 'novelty': novelty,
            'falsification': 'falsification_prediction' in changed,
            # No 'cost' here: compute_budget is immutable to revision (revise.txt rule 1) and the
            # cost verdict is arithmetic at implementability (computed_cost_status against the
            # ceiling). Observed live: a post-revision cost fail had no recovery that could touch it.
            'required_checks': (['dataflow', 'dry_run', 'degenerate_probes', 'claim_step_map',
                                  'falsification', 'novelty'] if mechanism else
                                (['novelty', 'presentation'] if novelty else ['presentation'])
                                + (['falsification'] if 'falsification_prediction' in changed and not mechanism else []))}


def object_level_survivors(rounds, coherence, blocking):
    """True when every surviving blocking finding is one the author declared object-level. Ids are
    re-issued by each re-trace, so after a re-trace the match is by the trace's own
    `previous_findings_status`: every declared id persists and nothing new was found. When the loop
    stopped on the declaration itself (stop: object, no re-trace) the ids are the same and match directly."""
    rounds = [r for r in (rounds or []) if isinstance(r, dict)]
    surviving = [b.get('finding_id') for b in (blocking or []) if isinstance(b, dict)]
    declared = set().union(*(set(r.get('object_declared') or []) for r in rounds)) if rounds else set()
    if not surviving or not declared:
        return False
    if rounds[-1].get('stop') == 'object':
        return set(surviving) <= declared
    status = [s for s in (coherence or {}).get('previous_findings_status') or [] if isinstance(s, dict)]
    persisting = [s for s in status if s.get('finding_id') in declared and s.get('status') == 'persists']
    return bool(persisting) and len(persisting) == len(surviving) and all(
        s.get('status') == 'persists' for s in status if s.get('finding_id') in declared)


def finding(code, message, severity='fail'):
    return {'validator': code, 'severity': severity, 'message': message}


def attested_companions():
    """Corpus co-occurrence table (references/ideation-patterns/companion-combos.md): pattern -> set.
    Descriptive, so an absent pairing is a warn: the selector must say why the corpus never
    composed these two moves. It is the one data-derived constraint on chains; v2 keeps it as a
    signal rather than a gate."""
    table = {}; current = None
    p = Path(__file__).resolve().parent.parent / 'references/ideation-patterns/companion-combos.md'
    try:
        for line in p.read_text().splitlines():
            if line.startswith('### '):
                current = line[4:].strip(); table[current] = set()
            elif current and ' · ' in line or (current and line.strip() and line.strip().replace('_', '').isalpha() and not line.startswith('#')):
                table[current] |= {x.strip() for x in line.split('·') if x.strip()}
    except OSError:
        return {}
    return table


def selection_findings(selection, contribution_type, strict=True):
    out = []; gaps = selection.get('selected_gaps', [])
    # No corpus-attestation warn on companion pairs any more: whether 1,947 papers composed two
    # moves is a prior about shape, not evidence about this candidate.
    if not 1 <= len(gaps) <= 3:
        return [finding('component_dependency', 'Expected one anchor and at most two siblings')]
    for i, gap in enumerate(gaps):
        for role, present in [('sibling', i > 0), ('companion', bool(gap.get('companion_pattern')))]:
            if not present:
                continue
            dep = gap.get(role + '_dependency', {})
            if not all(isinstance(dep.get(k), str) and dep[k].strip()
                       for k in ('object', 'producer', 'consumer', 'removal_effect', 'usage')):
                out.append(finding('component_dependency', f'gap {i} {role}: missing dependency declaration',
                                   'fail' if strict else 'warn'))
            pattern = gap.get('chosen_pattern_id') if role == 'sibling' else gap.get('companion_pattern')
            if contribution_type == 'method' and (pattern == 'controlled_diagnostic_design' or
                                                  dep.get('usage') == 'evaluation_only'):
                # HARD RULE (ideate_select.txt, Step 2b): on a method anchor a measurement is not a
                # component. Not conditioned on the self-declared `usage` — in the paired A/B the
                # selector kept the diagnostic in 3/5 runs and declared it "training"/"inference";
                # the archive baseline is 228/793 selections. The generation stage gets one bounded
                # REGENERATE with this finding as input; the second failure is terminal.
                out.append(finding('measurement_component',
                    f'gap {i} {role}: {pattern} on a method anchor is an evaluation instrument, not a '
                    f'method component. Move the measurement into falsification_prediction (ablation '
                    f'arm / negative control); if the mechanism really consumes a runtime signal, '
                    f'express that leg as self_supervised_signal_engineering or '
                    f'assumption_audit_and_pivot and name what it produces.', 'fail'))
    return out


def review_findings(report, required):
    out = []
    if report.get('verdict') not in ('pass', 'needs_work', 'redesign'):
        out.append(finding('review_contract', 'Missing pass/needs_work/redesign verdict'))
    checks = report.get('checks', {})
    for name in required:
        c = checks.get(name, {})
        if c.get('status') not in ('pass', 'conditional', 'n_a', 'fail') or not c.get('evidence'):
            out.append(finding('review_contract', f'{name}: missing disposition/evidence'))
        elif c['status'] == 'fail':
            # A reviewer's fail blocks only when it rests on something that was executed or derived
            # and recorded (`executed: true` with the record in evidence); a fail by judgement alone
            # is recorded as unverified. Same rule the coherence gate lives under.
            out.append(finding('semantic_review' if c.get('executed') is True else 'unverified_fail',
                               f'{name}: {c["evidence"]}', 'fail' if c.get('executed') is True else 'warn'))
    if report.get('verdict') != 'pass':
        # The contract is check-based: a FAILED required check blocks. A verdict of needs_work with
        # every check pass/conditional/n_a is the reviewer contradicting its own status scheme
        # ("pass: required checks satisfied or appropriately conditional"); it is recorded, not
        # terminal — observed live: four conditionals, no fail, verdict needs_work, run dead.
        failed = any(c.get('status') == 'fail' and c.get('executed') is True for c in checks.values() if isinstance(c, dict))
        out.append(finding('semantic_review', report.get('reason', 'Review did not pass'),
                           'fail' if failed else 'warn'))
    return out


_STEP_ID = re.compile(r'\bS\d+\b')


def _norm_text(s):
    return ' '.join(str(s or '').lower().split())


def _quotes(target, texts, window=30):
    """Does a 30-character window of the quoted target occur in any of the candidate's own texts?"""
    t = _norm_text(target)
    if len(t) < window:
        return any(t and t in _norm_text(x) for x in texts)
    norm = [_norm_text(x) for x in texts]
    return any(t[i:i + window] in x for i in range(0, len(t) - window + 1, 10) for x in norm)


def claim_texts(doc):
    """Everything the candidate asserts in its own voice: claims, sub-claims, hook, the falsification paragraph."""
    out = [doc.get('core_claim'), doc.get('hook'), doc.get('falsification_prediction')]
    out += [c.get('statement') if isinstance(c, dict) else c for c in doc.get('sub_claims', []) or []]
    return [x for x in out if isinstance(x, str) and x.strip()]


def trace_findings(trace, step_ids, label='trace', asserted=()):
    """The one deterministic reading of a coherence-shaped trace_report.

    A step is `instantiated` or `stopped`. A stopped step that a claim depends on (its id appears in
    claim_step_map.established_by) is a fail — when the dry run was executed; without executed
    evidence the same finding is `unverified` (warn). A stopped step no claim depends on is an open
    question (warn). `equivalent_to_naive` and a negative control that does not move the outcome are
    fails on the same executed-evidence condition. Labels are inputs; the verdict is computed here."""
    out = []
    steps = {str(e.get('step')): e for e in trace.get('formalized_procedure', []) if isinstance(e, dict)}
    missing = [i for i in step_ids if i not in steps]
    if missing:
        out.append(finding(label + '_incomplete', f'trace covers no entry for {missing}'))
    executed = (trace.get('dry_run') or {}).get('execution', {}).get('mode') == 'executed'
    depended = set()
    for c in trace.get('claim_step_map', []) or []:
        if isinstance(c, dict):
            depended |= set(_STEP_ID.findall(str(c.get('established_by', ''))))
    for sid, e in steps.items():
        if e.get('status') != 'stopped':
            continue
        why = str(e.get('stopped_reason') or e.get('missing') or 'undefined')
        if sid in depended:
            out.append(finding(label + '_stopped_claim_dependent',
                               f'{sid}: {why} — a claim depends on this step', 'fail' if executed else 'warn'))
        else:
            out.append(finding(label + '_open_question', f'{sid}: {why} — no claim depends on it', 'warn'))
    # Executed structural anomalies: an anomaly the tracer ties to a claim or prediction the candidate
    # makes is a contradiction (fail when executed); a structural anomaly tied to nothing is a warn.
    claims = [str(c.get('claim', '')) for c in trace.get('claim_step_map', []) or [] if isinstance(c, dict)] + list(asserted)
    for a in (trace.get('dry_run') or {}).get('anomalies', []) or []:
        if not isinstance(a, dict) or a.get('kind') != 'structural':
            continue
        target = str(a.get('contradicts_claim') or '').strip()
        hit = bool(target) and target.lower() not in ('none', 'null') and _quotes(target, claims)
        if hit:
            out.append(finding(label + '_structural_contradiction',
                               f"{str(a.get('anomaly', ''))[:160]} — contradicts: {target[:80]}", 'fail' if executed else 'warn'))
        else:
            out.append(finding(label + '_structural_anomaly', str(a.get('anomaly', ''))[:160], 'warn'))
    nc = trace.get('naive_comparison') or {}
    if nc.get('verdict') == 'equivalent_to_naive':
        # Blocking only as 'component X is inert': the naive is an ablation of the mechanism and the
        # executed outputs coincide. Against a constructed alternative design the verdict flipped in
        # 4 of 6 consecutive traces of one candidate; that is a note, not a gate.
        ablation = nc.get('naive_kind') == 'ablation' and nc.get('identity') == 'bit_identical'
        out.append(finding(label + ('_equivalent_to_naive' if ablation else '_equivalent_to_naive_note'),
                           str(nc.get('reasoning', ''))[:200], 'fail' if (executed and ablation) else 'warn'))
    ctrl = trace.get('negative_control') or {}
    if ctrl:
        if ctrl.get('executed') is True and ctrl.get('moved_outcome') is False:
            out.append(finding(label + '_negative_control_noop',
                               'the negative control leaves the outcome quantity unchanged on the instance: '
                               + str(ctrl.get('evidence', ''))[:200], 'fail'))
        elif ctrl.get('executed') is not True:
            out.append(finding(label + '_negative_control_unexecuted', 'negative control was not executed on the instance', 'warn'))
    return out


def implementation_points(report, expansion, repairs=None):
    """Derived, not declared: the implementation audit's holes come from its trace.
    stopped + the missing information exists verbatim in the candidate → source_omission (repairable);
    stopped + a claim depends on it → mechanism_blocking; stopped otherwise → open_question;
    instantiated with an unbound default → implementation_choice. A legacy report that still carries
    its own `underspecified_points` is passed through."""
    if 'underspecified_points' in report and 'trace_report' not in report:
        return list(report.get('underspecified_points') or [])
    trace = report.get('trace_report') or {}
    depended = set()
    for c in trace.get('claim_step_map', []) or []:
        if isinstance(c, dict):
            depended |= set(_STEP_ID.findall(str(c.get('established_by', ''))))
    pts = []
    for e in trace.get('formalized_procedure', []) or []:
        if not isinstance(e, dict):
            continue
        sid = str(e.get('step'))
        if e.get('status') == 'stopped':
            kind = ('source_omission' if str(e.get('source_present', '')).lower() in ('yes', 'true') else
                    'mechanism_blocking' if sid in depended else 'open_question')
            pts.append({'step_id': sid, 'kind': kind, 'hole': str(e.get('stopped_reason') or e.get('missing') or ''),
                        'evidence': str(e.get('note') or ''), 'suggestion': str(e.get('suggestion') or '')})
        for u in e.get('unbound_defaults', []) or []:
            pts.append({'step_id': sid, 'kind': 'implementation_choice', 'hole': str(u.get('parameter', u)),
                        'evidence': str(u.get('basis', '') if isinstance(u, dict) else ''),
                        'suggestion': str(u.get('suggestion', '') if isinstance(u, dict) else '')})
    # Executed contradictions between the trace and a stated claim stay visible on the card even after the
    # technical review adjudicated the repaired text: the reader sees what the trace found.
    claims = claim_texts(expansion)
    for a in (trace.get('dry_run') or {}).get('anomalies', []) or []:
        if isinstance(a, dict) and a.get('kind') == 'structural' and _quotes(str(a.get('contradicts_claim') or ''), claims):
            pts.append({'step_id': '-', 'kind': 'trace_contradiction', 'hole': str(a.get('anomaly', ''))[:400],
                        'evidence': 'contradicts: ' + str(a.get('contradicts_claim', ''))[:200], 'suggestion': ''})
    # A step the bounded technical repair specified is no longer a hole: the card says what was chosen.
    steps = [s.get('step_id') for s in (expansion.get('method_flow') or {}).get('steps', []) or []]
    for op in (repairs or {}).get('applied_revisions', []) or []:
        m = re.match(r'method_flow\.steps\[(\d+)\]', str(op.get('field', ''))) if isinstance(op, dict) else None
        if m and op.get('kind') == 'specification' and int(m.group(1)) < len(steps):
            for p in pts:
                if p['step_id'] == steps[int(m.group(1))] and p['kind'] in ('mechanism_blocking', 'open_question'):
                    p['kind'] = 'specified_by_repair'; p['suggestion'] = str(op.get('rationale', ''))[:400]
    return pts


def specified_steps(expansion, repairs):
    """Step ids that a bounded technical repair specified (`kind: specification`)."""
    steps = [s.get('step_id') for s in (expansion.get('method_flow') or {}).get('steps', []) or []]
    out = set()
    for op in (repairs or {}).get('applied_revisions', []) or []:
        m = re.match(r'method_flow\.steps\[(\d+)\]', str(op.get('field', ''))) if isinstance(op, dict) else None
        if m and op.get('kind') == 'specification' and op.get('outcome', 'applied') == 'applied' and int(m.group(1)) < len(steps):
            out.add(steps[int(m.group(1))])
    return out


def implementability_findings(report, expansion, repairs=None, reviewed=False, advisory=False):
    out = []; ids = [s['step_id'] for s in expansion.get('method_flow', {}).get('steps', [])]
    if report.get('contract_version') != VERSION or report.get('reviewed_step_ids') != ids:
        out.append(finding('implementability_completeness', 'Audit must cover every technical step in order'))
    if 'enriched_steps' in report:
        out.append(finding('implementability_completeness', 'v2 audit cannot rewrite steps'))
    if any(k in report for k in ('compute_budget', 'falsification_prediction', 'final_candidate')):
        out.append(finding('implementability_completeness', 'Audit cannot replace protected source commitments'))
    if 'trace_report' in report:
        # v3 shape: the audit is a trace over the technical steps; holes are derived, not declared.
        # A step the bounded repair SPECIFIED afterwards is no longer stopped: the technical review of the
        # repaired text decided it (observed: publish re-judged the pre-repair trace and refused the card).
        done = specified_steps(expansion, repairs)
        for f in trace_findings(report['trace_report'], ids, label='technical_trace', asserted=claim_texts(expansion)):
            sid = f['message'].split(':', 1)[0].strip()
            if f['validator'].endswith('_stopped_claim_dependent') and sid in done:
                out.append(finding('technical_trace_specified_by_repair', f['message'][:200], 'warn'))
            elif advisory and f['severity'] == 'fail':
                # idea depth: the implementation trace informs the reader; it does not gate the card
                out.append(finding('technical_trace_note', f['message'][:200], 'warn'))
            elif reviewed and f['severity'] == 'fail':
                # The audit traced the PRE-repair text; the technical review of the repaired text is the
                # decider (the flow's rule). A fail the review did not uphold is carried on the card as a
                # reviewed contradiction, not re-litigated at publish (observed: publish refused a card
                # on two pre-repair contradictions after the review had passed).
                out.append(finding('technical_trace_reviewed', f['message'][:200], 'warn'))
            else:
                out.append(f)
        return out
    points = report.get('underspecified_points')
    if not isinstance(points, list):
        return out + [finding('implementability_completeness', 'Missing underspecified_points[]')]
    for p in points:
        if p.get('step_id') not in ids or p.get('kind') not in ('source_omission', 'implementation_choice', 'mechanism_blocking'):
            out.append(finding('implementability_completeness', 'Invalid step or hole kind'))
        if not p.get('hole') or not p.get('evidence'):
            out.append(finding('implementability_completeness', 'Hole needs explicit evidence'))
        if p.get('kind') == 'mechanism_blocking':
            out.append(finding('mechanism_blocking', p.get('hole', 'undefined operation')))
    return out


_PRUNE_STOP = {'step', 'steps', 'arm', 'arms', 'sub-arms', 'with', 'from', 'that', 'this', 'over', 'into', 'only',
               'never', 'measured', 'consumed', 'control', 'controls', 'baseline', 'ablation', 'diagnostic'}


def named_in_falsification(component, falsification):
    """Conservative text test: two or more distinctive tokens of the component's name (hyphenated names
    kept whole, >=4 chars, generic words dropped) appear in falsification_prediction. A false positive
    only keeps a component; a false negative would delete an arm the kill-switch paragraph relies on."""
    fp = str(falsification or '').lower()
    toks = {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{3,}", str(component or '').lower()) if w not in _PRUNE_STOP}
    return sum(1 for w in toks if w in fp) >= 2


def prune_findings(post, candidate=None):
    """Removal test on the components a revision added or changed: a component whose removal leaves
    the claim map unchanged (executed) is not load-bearing. One bounded REREVISE deletes it.
    The falsification_prediction is a claim too, and it is immutable to revision (strengthen-only):
    a component it names is never prunable — observed live, a prune removed the SDXL arms the
    falsification calls its discriminator, and the technical trace failed on the contradiction."""
    out = []
    fp = (candidate or {}).get('falsification_prediction', '')
    for t in post.get('removal_tests', []) or []:
        # Only a component that lives in a mechanism field can be pruned; rationale text
        # (core_mechanism_reasoning, hook_shape_rationale) records why, and claims never depend on it.
        if str(t.get('field', '')).split('[')[0].split('.')[0] not in ('core_mechanism', 'core_mechanism_steps', 'gap_closure'):
            continue
        if isinstance(t, dict) and t.get('claims_unchanged') is True and t.get('executed') is True:
            if fp and named_in_falsification(t.get('component'), fp):
                out.append(finding('prune_blocked_by_falsification', f"{t.get('component')}: named in falsification_prediction, kept", 'warn'))
                continue
            out.append(finding('prune_component', f"{t.get('component')}: removal leaves every claim established — "
                               f"{str(t.get('evidence', ''))[:200]}", 'warn'))
    return out


_REF_ID = re.compile(r"^\s*([A-Za-z]+\d+)(?=$|[^A-Za-z0-9])")


def resolve_finding_ref(ref, ids):
    """Map a critique's finding_ref onto an archived finding_id. The exact id wins; otherwise a ref that
    OPENS with the id (`B1 — the artifact funds ...`, the v1 prompt's quoted-text shape) resolves to it.
    Anything else is unresolved (None): evidence is looked up by id, never by prose similarity."""
    ids = set(ids)
    if ref in ids:
        return ref
    m = _REF_ID.match(str(ref or ''))
    return m.group(1) if m and m.group(1) in ids else None


def disposition_findings(report, blocking):
    """Every executed finding needs exactly one resolvable disposition (upheld | refuted) — on EVERY
    verdict, abandon included, because the retry ledger versions lessons by the evidence each
    disposition points at. Observed live: an abandon whose refs carried quoted text crashed the retry
    instead of being re-audited."""
    ids = [b.get('finding_id') for b in blocking]
    if not ids:
        return []
    items = report.get('blocking_findings_disposition') or []
    resolved = [resolve_finding_ref(x.get('finding_ref'), ids) for x in items]
    out = []
    if None in resolved:
        out.append(finding('blocking_disposition', 'finding_ref must be the archived finding_id (B1, B2, ...): unresolved '
                           + ', '.join(repr(str(x.get('finding_ref'))[:40]) for x, r in zip(items, resolved) if r is None)))
    if sorted(r for r in resolved if r) != sorted(ids):
        out.append(finding('blocking_disposition', 'Every executed finding needs one exact disposition'))
    if any(x.get('status') not in ('upheld', 'refuted') for x in items):
        out.append(finding('blocking_disposition', 'Disposition status must be upheld or refuted'))
    return out


def repair_findings(patch, before, blocking, suggested=()):
    """Contract of an author-side formula repair: a v2 patch on the canonical candidate whose targets are
    the executed finding ids (B#) and the gate's suggested repairs (W#), every one covered (applied, or
    skipped with a declaration — `skipped_author_keeps` is the author keeping a strong claim with its
    premise stated), no kill-switch field, every operation declaring whether it changes the intervention
    object, and the author's own re-execution of the tracer's script attached to any applied B# repair."""
    if not isinstance(patch, dict) or patch.get('contract_version') != VERSION:
        return [finding('repair_contract', 'Repair patch needs contract_version=2')]
    out = []
    if patch.get('base_candidate_sha256') != digest(before):
        out.append(finding('repair_contract', 'Patch base_candidate_sha256 does not match the canonical candidate'))
    ops = patch.get('applied_revisions')
    if not isinstance(ops, list):
        return out + [finding('repair_contract', 'Missing applied_revisions list')]
    bids = {b.get('finding_id') for b in blocking}; wids = {w.get('id') for w in suggested}
    ids = bids | wids; covered = set()
    for op in ops:
        if not isinstance(op, dict):
            out.append(finding('repair_contract', 'Operation is not an object')); continue
        if op.get('target_id') not in ids:
            out.append(finding('repair_contract', f'Unknown target_id {op.get("target_id")!r}: repair targets are the finding ids'))
        if str(op.get('field', '')).split('[')[0].split('.')[0] in ('falsification_prediction', 'compute_budget'):
            out.append(finding('repair_contract', 'Kill-switch field in a repair patch'))
        if op.get('outcome') not in ('applied', 'skipped_changes_object', 'skipped_already_satisfied', 'skipped_author_keeps'):
            out.append(finding('repair_contract', 'Every operation needs outcome applied | skipped_changes_object | skipped_already_satisfied | skipped_author_keeps'))
        if op.get('outcome') == 'skipped_author_keeps' and not str(op.get('delta_summary', '')).strip():
            out.append(finding('repair_contract', 'Keeping the text against a suggestion needs the stated premise in delta_summary'))
        if not isinstance(op.get('changes_object'), bool):
            out.append(finding('repair_contract', 'Every operation declares changes_object true|false'))
        covered.add(op.get('target_id'))
    if ids - covered:
        out.append(finding('repair_contract', 'Uncovered findings: ' + ', '.join(sorted(str(i) for i in ids - covered))))
    # `replace` holds the WHOLE field. Observed live: five sequential replaces on core_mechanism, each a
    # fragment, left 268 of 4,770 characters and the re-trace found "method fields hold only repair
    # fragments". Two guards: one replace per field, and no mechanism field may lose most of its text.
    applied_ops = [op for op in ops if isinstance(op, dict) and op.get('outcome') == 'applied']
    seen = {}
    for op in applied_ops:
        if op.get('op') == 'replace':
            seen[op.get('field')] = seen.get(op.get('field'), 0) + 1
    for f, n in seen.items():
        if n > 1:
            out.append(finding('repair_contract', f'{n} replace operations on {f!r}: replace holds the whole field — merge them into one full-field value, or use append_sentence'))
    try:
        from scripts.merge_revisions import apply_patch
        after = apply_patch(before, applied_ops)
        for f in ('core_mechanism', 'core_mechanism_steps', 'core_mechanism_reasoning'):
            b, a = len(str(before.get(f, ''))), len(str(after.get(f, '')))
            if b >= 400 and a < 0.6 * b:
                out.append(finding('repair_contract', f'Repair truncated {f} from {b} to {a} characters: replace holds the WHOLE field text; a repair edits a formula, it does not delete the mechanism'))
    except Exception as e:                               # a malformed op is its own finding
        out.append(finding('repair_contract', 'Patch could not be applied: ' + str(e)[:160]))
    rerun = patch.get('rerun') or {}
    if any(isinstance(op, dict) and op.get('outcome') == 'applied' and op.get('target_id') in bids for op in ops) and not (
            isinstance(rerun, dict) and str(rerun.get('script', '')).strip() and str(rerun.get('output', '')).strip()):
        out.append(finding('repair_contract', 'An applied repair carries the author\'s re-execution: rerun.script and rerun.output'))
    return out


def repair_stops(patch):
    """True when the author says the only fix replaces the intervention object: that is a new idea."""
    return patch.get('stop') == 'object' or any(isinstance(op, dict) and (op.get('changes_object') is True or
                                                op.get('outcome') == 'skipped_changes_object')
                                                for op in patch.get('applied_revisions', []) or [])


def critique_findings(report):
    out = []
    # Two substantive checks. gap_closure_reject_check and anti_pattern_check were retired after
    # 29 audited cycles (two recorded comparisons): 10 lesson matches and 1 anti-pattern match, none of
    # which changed a verdict the executed coherence evidence had not already decided.
    for name in ('paper_pointed_threat', 'falsification_structure_check'):
        if not isinstance(report.get(name), dict) or not report[name]:
            out.append(finding('critique_contract', 'Missing substantive check: ' + name))
    targets = report.get('revision_targets')
    if not isinstance(targets, list):
        out.append(finding('critique_contract', 'Missing revision_targets list'))
    else:
        ids = [t.get('target_id') for t in targets]
        if len(ids) != len(set(ids)) or any(not i for i in ids):
            out.append(finding('critique_contract', 'Revision targets need unique target_id values'))
        if report.get('verdict') == 'revise' and not targets:
            out.append(finding('critique_contract', 'revise requires at least one target'))
    if not report.get('verdict_rationale'):
        out.append(finding('critique_contract', 'Missing evidence-linked verdict rationale'))
    return out


# Only a REPEATED script is illegal (`^{s}^{T}`, `_i_j`); `A_i^s` (sub then super) is fine.
_DOUBLE_SCRIPT = re.compile(r"\^(\{[^{}]*\}|[A-Za-z0-9])[\^']|_(\{[^{}]*\}|[A-Za-z0-9])_")


def latex_findings(expansion):
    """Warn on LaTeX that cannot compile: a double superscript/subscript (`B^{s}^{T}`) aborts xelatex
    and leaves a one-page PDF. Deterministic, warn-level; the field path tells the author where."""
    out = []
    def walk(v, path):
        if isinstance(v, str):
            v = re.sub(r'\$`([^`]*)`\$', r'$\1$', v)    # a $-wrapped code span is typeset as math: keep its body
            v = re.sub(r'`[^`]*`', '', v)          # the other code spans are identifiers, not math
            for m in _DOUBLE_SCRIPT.finditer(v):
                out.append(finding('latex_double_script', f'{path}: double super/subscript near {v[max(0, m.start()-12):m.end()+8]!r}', 'warn')); break
        elif isinstance(v, dict):
            for k, x in v.items(): walk(x, f'{path}.{k}' if path else k)
        elif isinstance(v, list):
            for i, x in enumerate(v): walk(x, f'{path}[{i}]')
    walk(expansion, '')
    return out


def style_findings(candidate, contribution_type='method'):
    out = []                 # the title word-list warn is gone: a lexical prior, not a defect
    for field in ('core_mechanism', 'core_mechanism_reasoning', 'core_mechanism_steps'):
        value = candidate.get(field, '')
        if not isinstance(value, str):
            out.append(finding('legacy_field_shape', field + ': non-string field; sentence check unavailable', 'warn'))
            continue
        sentences = [s.strip() for s in re.split(r'(?<=[.!?。])\s+', value) if len(s.strip()) > 20]
        if len(sentences) != len(set(sentences)):
            out.append(finding('duplicate_sentence', field + ': exact repeated sentence', 'warn'))
    return out


def build_mechanism_record(candidate, coherence, pre_revision=None, post_review=None, unrepaired=None):
    """Verbatim source references, not another authored method or inferred theorem.

    `sources` are read from the candidate handed in (the post-revision final candidate when a
    revision ran), so they are always current. `dataflow` / `claim_step_map` come from the
    coherence trace, which ran on the PRE-revision candidate: when the revision changed a
    mechanism field they describe the old design. Observed live: a reviser replaced the
    mechanism's driver (D → G) and the record still traced D. So the record states which of
    its parts are stale and carries the post-revision reviewer's executed evidence instead."""
    rec = {'contract_version': VERSION, 'candidate_sha256': digest(candidate),
           'sources': {k: candidate.get(k) for k in MECHANISM_FIELDS},
           'claim_step_map': coherence.get('claim_step_map', []),
           'dataflow': coherence.get('formalized_procedure', []),
           'dataflow_status': 'current',
           'regime_notes': [{'finding': str(u.get('finding', ''))[:400], 'derivation': str(u.get('derivation', ''))[:400]}
                            for u in (unrepaired if unrepaired is not None else coherence.get('unrepaired', [])) or []
                            if isinstance(u, dict) and u.get('tag') in ('regime', 'parameter')],
           'limits': 'Source record, not proof. Final independent review checks semantic correspondence.'}
    if pre_revision is not None:
        scope = change_scope(pre_revision, candidate)
        if scope['mechanism']:
            rec['dataflow_status'] = 'stale_since_revision'
            rec['revision_changed_fields'] = scope['changed_fields']
            rec['authority'] = ('sources (the post-revision candidate) are the authority; dataflow and '
                                'claim_step_map trace the PRE-revision design and must not be used '
                                'where they disagree with sources.')
            checks = (post_review or {}).get('checks', {}) if isinstance(post_review, dict) else {}
            rec['post_revision_evidence'] = {k: checks[k].get('evidence') for k in
                                             ('dataflow', 'dry_run', 'degenerate_probes', 'claim_step_map')
                                             if isinstance(checks.get(k), dict)}
    return rec


_GPU = re.compile(r'(\d+(?:\.\d+)?)\s*(?:(?:-|–|~|to)\s*(\d+(?:\.\d+)?))?\s*(?:x\s*)?GPU[\s-]*(day|hour|hr)s?', re.I)


_POINT = re.compile(r'point\s+estimate\s+(?:of\s+|is\s+|about\s+|~\s*)?(\d+(?:\.\d+)?)\s*(?:x\s*)?GPU[\s-]*(day|hour|hr)s?', re.I)


def parse_gpu_days(text):
    """The GPU-day figure the ceiling is tested against. A stated point estimate wins; otherwise the
    FIRST figure, and for a range its UPPER bound — the ceiling test is a worst-case test. (The old
    midpoint rule read '50 to 185 GPU-day, point estimate about 185' as 117.5 and called a 150-day
    ceiling feasible.) Hours become days. None when the text carries no GPU figure."""
    s = str(text or '')
    m = _POINT.search(s)
    if m:
        v = float(m.group(1)); unit = m.group(2)
    else:
        m = _GPU.search(s)
        if not m:
            return None
        v = float(m.group(2)) if m.group(2) else float(m.group(1)); unit = m.group(3)
    return v / 24 if unit.lower().startswith(('hour', 'hr')) else v


def gpu_days_span(text):
    """The exact substring parse_gpu_days read, or None — provenance for the cost arithmetic."""
    m = _POINT.search(str(text or '')) or _GPU.search(str(text or ''))
    return m.group(0) if m else None


def computed_cost_status(cost, phase1):
    """The status is arithmetic, not a label the auditor picks: estimate vs the user ceiling.
    (feasible ≤ 80% of ceiling < tight ≤ ceiling < infeasible; unknown when either side has no figure.)"""
    est = parse_gpu_days(cost.get('current_estimate'))
    ceiling = parse_gpu_days(phase1.get('intake', {}).get('compute', '')) or parse_gpu_days(cost.get('user_budget'))
    if est is None or ceiling is None:
        return 'unknown', est, ceiling
    return ('infeasible' if est > ceiling else 'tight' if est > 0.8 * ceiling else 'feasible'), est, ceiling


def cost_findings(cost, candidate, phase1):
    out = []
    if cost.get('candidate_sha256') != digest(candidate):
        out.append(finding('cost_assessment', 'Cost assessment is bound to a different candidate'))
    if cost.get('user_budget') != phase1.get('intake', {}).get('compute', ''):
        out.append(finding('cost_assessment', 'User budget changed or was omitted'))
    if cost.get('original_estimate') != candidate.get('compute_budget', ''):
        out.append(finding('cost_assessment', 'Original cost estimate must remain visible'))
    if not all(cost.get(k) for k in ('current_estimate', 'basis', 'change_reason')):
        out.append(finding('cost_assessment', 'Current estimate, basis and change reason are required'))
    status, est, ceiling = computed_cost_status(cost, phase1)
    declared = cost.get('status')
    if declared == 'n_a' and est is None:
        return out                      # theory: no GPU figure on either side, declared n_a
    if status == 'unknown':
        out.append(finding('cost_assessment', f'No GPU-day figure could be parsed (estimate {est}, ceiling {ceiling}); '
                           f'feasibility is unknown, not {declared!r}', 'warn'))
        return out
    if declared != status:
        out.append(finding('cost_status_corrected', f'Audit declared {declared!r}; arithmetic says {status} '
                           f'({est:g} GPU-day from {gpu_days_span(cost.get("current_estimate"))!r} against a {ceiling:g} GPU-day '
                           f'ceiling from {gpu_days_span(phase1.get("intake", {}).get("compute", "")) or gpu_days_span(cost.get("user_budget"))!r})', 'warn'))
    if status == 'infeasible':
        out.append(finding('cost_assessment', f'Current estimate {est:g} GPU-day exceeds the user ceiling {ceiling:g} GPU-day', 'fail'))
    elif status == 'tight':
        out.append(finding('cost_assessment', f'Current estimate {est:g} GPU-day is within 20% of the {ceiling:g} GPU-day ceiling', 'warn'))
    return out


def coherence_findings(report):
    trace = report.get('trace_report', {})
    out = []
    for key in ('formalized_procedure', 'dry_run', 'degenerate_probes', 'claim_step_map', 'naive_comparison'):
        if not trace.get(key): out.append(finding('coherence_contract', 'Missing ' + key))
    execution = trace.get('dry_run', {}).get('execution', {})
    if execution.get('mode') not in ('executed', 'unexecuted'):
        out.append(finding('coherence_contract', 'Dry run needs an honest execution mode'))
    if execution.get('mode') == 'executed' and not all(execution.get(k) for k in ('script', 'output')):
        out.append(finding('coherence_contract', 'Executed trace needs script and output'))
    naive = trace.get('naive_comparison', {})
    if naive.get('verdict') == 'n_a' and not naive.get('reasoning'):
        out.append(finding('coherence_contract', 'n_a naive comparison needs a reason'))
    if report.get('applied_revisions'):
        # The gate reports; it does not write the method. Its fixes are suggestions the author applies.
        out.append(finding('coherence_contract', 'The trace reports; it does not patch (use suggested_repairs)'))
    if report.get('verdict') not in ('pass', 'findings'):
        out.append(finding('coherence_contract', 'Coherence verdict must be pass or findings'))
    return out


def finalize_expansion(technical, derive, cost, impl, repairs=None):
    out = copy.deepcopy(technical)
    allowed = {k for k in technical if k.startswith('plain_') or k == 'title_zh'}
    if set(derive) - allowed:
        raise ValueError('Plain derivation attempted to modify a technical field')
    out.update(derive)
    if '<TODO[' in json.dumps(out):
        raise ValueError('Unfilled fields remain')
    out['contract_version'] = VERSION
    out['implementation_notes'] = implementation_points(impl, technical, repairs)
    status, est, ceiling = computed_cost_status(cost, {'intake': {'compute': cost.get('user_budget', '')}})
    if status == 'unknown':
        status = cost.get('status', 'unknown')
    # The arithmetic and what it was parsed from, so a reader can check the parse, not just the verdict.
    out['cost_assessment'] = dict(cost, status=status, parsed={
        'estimate_gpu_days': est, 'estimate_span': gpu_days_span(cost.get('current_estimate')),
        'ceiling_gpu_days': ceiling, 'ceiling_span': gpu_days_span(cost.get('user_budget'))})
    out['feasibility_validation']['compute'] = {'verdict': status, 'rationale': cost['basis']}
    vals = [v.get('verdict') for k, v in out['feasibility_validation'].items() if isinstance(v, dict)]
    out['feasibility_validation']['overall'] = next((v for v in ('infeasible', 'unknown', 'tight') if v in vals), 'feasible')
    out['proposal_status'] = 'Research proposal — not experimentally validated'
    return out
