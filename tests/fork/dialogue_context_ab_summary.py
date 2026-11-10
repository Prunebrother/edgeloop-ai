# SPDX-License-Identifier: AGPL-3.0-only
"""Aggregate the frozen, arm-blind review and paired local replay outputs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def summarize(directory):
    p = Path(directory)
    read = lambda name: json.loads((p/name).read_text())
    freeze = read('annotation-freeze.json')
    assert hashlib.sha256((p/'annotations.txt').read_bytes()).hexdigest() == freeze['annotation_sha256']
    assert hashlib.sha256((p/'blind-review.json').read_bytes()).hexdigest() == freeze['blind_review_sha256']
    cases = {c['id']: c for c in read('cases.json')}
    results = read('results.json')
    key = read('blind-key.json')
    lookup = {(r['case'], r['seed'], r['variant']): r for r in results}
    assert len(results) == len(lookup) == 384
    annotations = {}
    for line in (p/'annotations.txt').read_text().splitlines():
        if not line.startswith('Q'):
            continue
        fields, note = line.split('|', 1)
        q, e, h, u, a = fields.split()
        pair = (key[q]['case'], key[q]['variant'])
        assert pair not in annotations
        annotations[pair] = dict(echo=int(e), history=int(h), unsupported=int(u),
                                 adherence=int(a), blind_id=q, note=note.strip())
    assert len(annotations) == 192
    metrics = {}
    for seed in (271828, 314159):
        for arm in ('A', 'B'):
            rows = [r for r in results if r['seed'] == seed and r['variant'] == arm]
            def group(subset):
                d = dict(n=len(subset), literal=sum(bool(r['literal_markers']) for r in subset))
                if seed == 271828:
                    for metric in ('echo', 'history', 'unsupported'):
                        d[metric] = sum(annotations[(r['case'], arm)][metric] for r in subset)
                    d['adherence_counts'] = dict(Counter(str(annotations[(r['case'], arm)]['adherence']) for r in subset))
                return d
            m = group(rows)
            for field, name in (('identity', 'by_model'), ('route', 'by_route')):
                m[name] = {value: group([r for r in rows if cases[r['case']][field] == value])
                           for value in sorted({c[field] for c in cases.values()})}
            if seed == 271828:
                m['adherence_mean'] = sum(annotations[(r['case'], arm)]['adherence'] for r in rows)/len(rows)
            metrics[f'{seed}/{arm}'] = m
    paired = {}
    for seed in (271828, 314159):
        paired[str(seed)] = dict(Counter(''.join(str(int(bool(lookup[c, seed, arm]['literal_markers'])))
                                                for arm in ('A', 'B')) for c in cases))
    for metric in ('echo', 'history', 'unsupported'):
        paired[metric] = dict(Counter(''.join(str(annotations[c, arm][metric]) for arm in ('A', 'B')) for c in cases))
    paired['adherence_change'] = dict(Counter(
        'improved' if annotations[c, 'B']['adherence'] > annotations[c, 'A']['adherence'] else
        'worsened' if annotations[c, 'B']['adherence'] < annotations[c, 'A']['adherence'] else 'same'
        for c in cases))
    controls = []
    for c, case in cases.items():
        if case['route'] != 'none':
            continue
        for seed in (271828, 314159):
            a, b = lookup[c, seed, 'A'], lookup[c, seed, 'B']
            controls.append(dict(case=c, seed=seed,
                                 same_request=a['request_sha256'] == b['request_sha256'],
                                 same_raw=a['raw_content'] == b['raw_content'], same_text=a['text'] == b['text']))
    return dict(metrics=metrics, paired=paired, controls=controls,
                done_reasons=dict(Counter(r['done_reason'] for r in results)),
                thinking_outputs=sum(bool(r['thinking_characters']) for r in results), annotation_freeze=freeze)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), indent=2))
