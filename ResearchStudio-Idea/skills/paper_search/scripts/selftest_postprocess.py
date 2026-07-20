#!/usr/bin/env python3
"""Pure-function self-test for paper_search post-processing (no network).

Run: python3 scripts/selftest_postprocess.py    Exit 0 = green.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postprocess import (dedup, is_survey, norm_arxiv, norm_doi, rank,
                         relevance_score, term_words, title_norm)

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(ok)
    print(('  ok ' if ok else 'FAIL ') + name + ('' if ok else f' — {detail}'),
          file=sys.stderr)


def P(**kw):
    base = {'title': '', 'authors': [], 'year': 2025, 'abstract': '', 'url': '',
            'venue': '', 'citation_count': 0, 'publication_date': '2025-01-01',
            'source': 'arxiv', 'doi': None, 'arxiv_id': None}
    base.update(kw)
    return base


# --- normalizers ---
check('title_norm strips case/punct',
      title_norm('  Held-Out: Widget Gating!  ') == 'held out widget gating')
check('norm_doi strips url prefixes',
      norm_doi('https://doi.org/10.1000/XYZ') == '10.1000/xyz'
      and norm_doi('doi:10.1/a') == '10.1/a')
check('norm_arxiv strips version + prefix',
      norm_arxiv('arXiv:2401.12345v2') == '2401.12345')

# --- survey regex ---
check('survey titles tagged',
      is_survey('A Comprehensive Survey of Widget Gating')
      and is_survey('Widget Gating: A Systematic Review')
      and not is_survey('Surveying the Loss Landscape of Widgets'))

# --- scoring ---
words = term_words(['held-out widget gating'])
check('term_words drops stopwords/short', 'with' not in words and 'held' in words)
check('stemming via startswith',
      relevance_score(P(title='Widgets and gates for held-out evaluation'), words) >= 2)
check('irrelevant paper scores 0',
      relevance_score(P(title='Australian humor as informal governance'), words) == 0)

# --- dedup: doi match across sources, priority keep + field fill + max cites ---
r = {'semantic_scholar': [P(source='semantic_scholar', title='Widget Gating',
                            doi='10.1/wg', citation_count=5, abstract='')],
     'open_alex': [P(source='open_alex', title='Widget gating.', doi='10.1/WG',
                     citation_count=9, abstract='full abstract here')],
     'arxiv': [P(source='arxiv', title='Widget Gating', arxiv_id='2401.00001',
                 citation_count=0)]}
m = dedup(r)
check('dedup collapses doi+title matches to one record', len(m) == 1, f'{len(m)} records')
rec = m[0]
check('dedup keeps priority source + provenance',
      rec['source'] == 'semantic_scholar'
      and rec['found_in'] == ['semantic_scholar', 'open_alex', 'arxiv'])
check('dedup max citations + fills missing fields',
      rec['citation_count'] == 9 and rec['abstract'] == 'full abstract here'
      and rec['arxiv_id'] == '2401.00001')

# --- dedup: different papers stay separate ---
r2 = {'arxiv': [P(title='Paper One', arxiv_id='2401.1'),
                P(title='Paper Two', arxiv_id='2401.2')]}
check('distinct papers not merged', len(dedup(r2)) == 2)

# --- dedup: doi-only vs title-only bridge (cluster key registration) ---
r3 = {'crossref': [P(source='crossref', title='Bridged Paper', doi='10.2/bp')],
      'dblp': [P(source='dblp', title='Bridged Paper', doi=None)],
      'open_alex': [P(source='open_alex', title='BRIDGED PAPER!', doi='10.2/bp')]}
check('title bridges doi-less duplicate into the doi cluster', len(dedup(r3)) == 1)

# --- rank: sort by score desc, surveys sunk, no dropping by default ---
papers = [P(title='A Survey of Widget Gating', citation_count=999),
          P(title='Widget gating with held-out oracles', citation_count=1),
          P(title='Unrelated cosmology paper', citation_count=50)]
for p in papers:
    p['found_in'] = [p['source']]
ranked, n_drop = rank(papers, ['held-out widget gating'])
check('rank keeps everything by default', len(ranked) == 3 and n_drop == 0)
check('most relevant first, survey sunk despite citations',
      ranked[0]['title'].startswith('Widget gating')
      and ranked[-1]['is_survey'] is True)

# --- rank: opt-in min_score drops and reports ---
ranked2, n_drop2 = rank([dict(p) for p in papers], ['held-out widget gating'],
                        min_score=1)
check('min_score drops and counts', n_drop2 >= 1 and len(ranked2) == 3 - n_drop2)

n_fail = RESULTS.count(False)
print(f"\n[{'GREEN' if n_fail == 0 else 'RED'}] selftest_postprocess: "
      f"{len(RESULTS) - n_fail}/{len(RESULTS)} passed", file=sys.stderr)
sys.exit(0 if n_fail == 0 else 1)
