"""Cross-source dedup and merge.

Why: each connector returns its own hits; we merge them and keep the richest record
per unique (title-normalized, year) tuple.

Priority is FILE ORDER: the first --inputs file wins on conflict, second backfills
abstract/citations if missing on the primary record. This lets the caller (orchestrator)
own the source-priority decision rather than baking it into this script.

I/O:
  python3 -m scripts.dedup_merge --inputs hi-priority.json med-priority.json lo-priority.json --out merged.json
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

_ISO_YM = re.compile(r'^(\d{4})-(\d{2})')


def derive_year_month(h: dict) -> str:
    """YYYY-MM from published_iso (authoritative), else year+month, else year.

    Connectors populate published_iso for every hit but only some carry a separate
    `month` field, so deriving from the ISO timestamp is what keeps year_month
    populated in collision mode (which skips pattern_summary, the only other place
    year_month was being computed).
    """
    m = _ISO_YM.match(str(h.get('published_iso') or ''))
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    y = str(h.get('year') or '').strip()
    mo = str(h.get('month') or '').strip()
    if mo and len(mo) == 1:
        mo = '0' + mo
    return f'{y}-{mo}' if y and mo else y or ''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', nargs='+', required=True,
                    help='Hit JSON files in priority order — first wins on conflict')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    by_key: dict[tuple, dict] = {}
    for path in args.inputs:
        items = json.loads(Path(path).read_text() or '[]')
        for h in items:
            key = (h.get('title_norm', ''), h.get('year'))
            if not key[0]: continue
            cur = by_key.get(key)
            if cur is None:
                # First time seeing this paper — file order wins
                by_key[key] = h
            else:
                # Backfill abstract / citations from later (lower-priority) source if primary lacks them
                if not cur.get('abstract') and h.get('abstract'):
                    cur['abstract'] = h['abstract']
                if not cur.get('citations') and h.get('citations'):
                    cur['citations'] = h['citations']

    merged = list(by_key.values())
    # canonical paper_id + year_month (the latter so collision_hits.json carries it too)
    for r in merged:
        r['paper_id'] = f"{r['source']}:{r['source_id']}"
        if not r.get('year_month'):
            r['year_month'] = derive_year_month(r)
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'merged {sum(len(json.loads(Path(p).read_text() or "[]")) for p in args.inputs)} hits '
          f'into {len(merged)} unique papers')


if __name__ == '__main__':
    main()
