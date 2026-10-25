#!/usr/bin/env python3
"""Deterministic offline retrieval ablation on fixed synthetic development fixtures."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import metrics
from memory_identity import validate, objects, json_text
from query_memory import lexical_score, search, load_index


def load_fixtures(directory):
    directory = Path(directory)
    data = json.loads((directory / 'distill.json').read_text(encoding='utf-8'))
    validate(data)
    cases = json.loads((directory / 'cases.json').read_text(encoding='utf-8'))
    raw = [json.loads(l) for l in (directory / 'raw-transcripts.jsonl').read_text(encoding='utf-8').splitlines()]
    ids = {o['memory_id'] for o, kind, _ in objects(data) if kind == 'card'}
    if cases.get('synthetic') is not True or not 20 <= len(cases['cases']) <= 40:
        raise ValueError('expected 20-40 explicitly synthetic cases')
    if len({c['case_id'] for c in cases['cases']}) != len(cases['cases']):
        raise ValueError('duplicate case_id')
    for c in cases['cases']:
        if not c['query'].strip() or not c['expected_memory_ids'] or not set(c['expected_memory_ids']) <= ids:
            raise ValueError('invalid expected memories/query: ' + c['case_id'])
    if {r['memory_id'] for r in raw} != ids or len(raw) != len(ids):
        raise ValueError('raw provenance mapping must cover every memory exactly once')
    return data, cases['cases'], raw


# Query-intent annotations live in the evaluator, not the frozen fixture or ranking code.
# q05-08 ask "now" despite the fixture scenario label "superseded".
# The noise scenario mixes historical diagnosis (q21/22/24) and a current rule (q23).
INTENT_CASES = {
    'current-state': ('q05', 'q06', 'q07', 'q08', 'q23'),
    'historical/superseded': ('q01', 'q02', 'q03', 'q04', 'q21', 'q22', 'q24'),
    'conflict/controversial': ('q09', 'q10', 'q11', 'q12'),
    'cross-session': ('q13', 'q14', 'q15', 'q16'),
    'compaction-recovery': ('q17', 'q18', 'q19', 'q20'),
}


def summarize_intents(all_runs, statuses):
    annotated = [case for ids in INTENT_CASES.values() for case in ids]
    actual = {r['case_id'] for r in all_runs['Baseline']}
    if len(annotated) != len(set(annotated)) or set(annotated) != actual:
        raise ValueError('intent annotations must cover each fixture query exactly once')
    summary = {}
    for intent, case_ids in INTENT_CASES.items():
        methods = {}
        for method, runs in all_runs.items():
            subset = [r for r in runs if r['case_id'] in case_ids]
            score = metrics(subset, statuses)
            methods[method] = dict(metrics=score)
            if intent == 'current-state':
                methods[method]['current_memory_recall'] = {f'Recall@{k}': score[f'Recall@{k}'] for k in (1, 3, 5)}
                methods[method]['stale_contamination'] = {f'@{k}': score[f'stale-hit@{k}'] for k in (1, 3, 5)}
            if intent == 'conflict/controversial':
                # All expected targets in this slice are disputed. Any-disputed hit is
                # kept separately: incidental controversy is not a correct answer.
                if not all(statuses[mid] == '有争议' for r in subset for mid in r['expected']):
                    raise ValueError('conflict slice must have disputed expected targets')
                methods[method]['expected_controversial_recall'] = {f'@{k}': score[f'Recall@{k}'] for k in (1, 3, 5)}
        subset = [r for r in all_runs['Baseline'] if r['case_id'] in case_ids]
        expired_count = sum(any(statuses[x] == '已过期' for x in r['expected']) for r in subset)
        summary[intent] = dict(case_ids=list(case_ids), query_count=len(case_ids), methods=methods,
                               expected_expired_query_count=expired_count)
        if intent == 'historical/superseded':
            summary[intent]['noncurrent_enabled'] = dict(
                implementation='query_memory.search(include_noncurrent=True); same ranking as Structured Memory',
                metrics=methods['Structured Memory']['metrics'])
            summary[intent]['expired_target_recall'] = None
            summary[intent]['limitation'] = ('No query expects an expired card in this fixture. History-enabled recall measures '
                                             'the original expected IDs only; stale-hit is exposure, not contamination, in this slice.')
    return summary


def evaluate(fixtures):
    data, cases, raw = load_fixtures(fixtures)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/render_notes.py'), '--distill', str(Path(fixtures) / 'distill.json'), '--vault', tmp], capture_output=True, text=True)
        if proc.returncode:
            raise ValueError(proc.stdout + proc.stderr)
        rows = load_index(Path(tmp) / '对话沉淀')
        index_chars = len((Path(tmp) / '对话沉淀/知识索引.jsonl').read_text(encoding='utf-8'))
    statuses = {r['memory_id']: r['status'] for r in rows if r['type'] == 'card'}
    all_runs = {name: [] for name in ('Baseline', 'Structured Memory', 'Status-aware Memory')}
    for case in cases:
        ranked = sorted([(r, lexical_score(case['query'], r, False)) for r in raw], key=lambda x: (-x[1], x[0]['memory_id']))
        candidates = {
            'Baseline': [dict(memory_id=r['memory_id'], text=r['text']) for r, score in ranked if score > 0][:5],
            'Structured Memory': search(rows, case['query'], include_noncurrent=True),
            'Status-aware Memory': search(rows, case['query']),
        }
        for method, hits in candidates.items():
            # Baseline context = complete retrieved raw chunks; structured = complete result JSON.
            chars = sum(len(x['text']) for x in hits) if method == 'Baseline' else len(json.dumps(hits, ensure_ascii=False))
            all_runs[method].append(dict(case_id=case['case_id'], scenario=case['scenario'],
                                        expected=case['expected_memory_ids'], ids=[h['memory_id'] for h in hits], retrieved_characters=chars))
    raw_chars = sum(len(r['text']) for r in raw)
    results = {name: dict(metrics=metrics(runs, statuses),
                         mean_retrieved_characters=round(sum(r['retrieved_characters'] for r in runs)/len(runs), 2),
                         by_scenario={sc: metrics([r for r in runs if r['scenario'] == sc], statuses) for sc in sorted({r['scenario'] for r in runs})},
                         cases=runs) for name, runs in all_runs.items()}
    for value in results.values():
        value['context_size_reduction_vs_full_raw'] = round(1-value['mean_retrieved_characters']/raw_chars, 6)
    digest = hashlib.sha256()
    for name in ('distill.json', 'cases.json', 'raw-transcripts.jsonl'):
        digest.update(name.encode()); digest.update((Path(fixtures)/name).read_bytes())
    return dict(schema_version=1, evidence='synthetic development benchmark; retrieval only', fixture_sha256=digest.hexdigest(),
                dataset=dict(sessions=len(data['conversations']), cards=len(raw), queries=len(cases), raw_transcript_characters=raw_chars, memory_index_characters=index_chars),
                definitions=dict(recall='mean fraction of expected IDs found in top k', MRR='mean reciprocal first relevant rank, cutoff 5',
                                 hit='fraction of queries with at least one result of the named status in top k; controversial is exposure, not necessarily error'),
                results=results, intent_summary_version=1,
                per_intent=summarize_intents(all_runs, statuses))


def markdown(result):
    keys = ['Recall@1', 'Recall@3', 'Recall@5', 'MRR', 'stale-hit@1', 'stale-hit@3', 'stale-hit@5', 'controversial-hit@1', 'controversial-hit@3', 'controversial-hit@5']
    lines = ['# Synthetic development benchmark results', '', result['evidence'], '',
             'Fixture SHA-256: `' + result['fixture_sha256'] + '`', '',
             '| Method | ' + ' | '.join(keys) + ' |', '| --- | ' + ' | '.join(['---']*len(keys)) + ' |']
    for name, value in result['results'].items():
        lines.append('| ' + name + ' | ' + ' | '.join(f"{value['metrics'][k]:.4f}" for k in keys) + ' |')
    lines += ['', 'Dataset: `' + json.dumps(result['dataset'], ensure_ascii=False) + '`', '',
              'MRR is truncated at 5. Hit rates measure queries with any such result. Disputed exposure can be correct.', '',
              '| Method | Mean retrieved characters | Reduction vs full raw corpus |', '| --- | --- | --- |']
    for name, value in result['results'].items():
        lines.append(f"| {name} | {value['mean_retrieved_characters']} | {value['context_size_reduction_vs_full_raw']:.4%} |")
    lines += ['', 'These character counts are not tokens. Whole-corpus reduction is not a fair advantage over an already retrieving baseline; compare retrieved sizes too.',
              'See JSON for every case and scenario, including misses. No model answered questions; no production or real-user accuracy claim.', '']
    lines += ['## Query intent split (additive; aggregate above is unchanged)', '',
              'Intent annotations partition the same 24 queries; fixture text and expected IDs are unchanged.',
              'Current-state: q05–08 and q23. Historical: q01–04, q21, q22, q24. Other groups retain their four cases.',
              'The fixture scenario named superseded asks about the current state, not the old answer.', '',
              '| Intent | N | Method | ' + ' | '.join(keys) + ' |',
              '| --- | --- | --- | ' + ' | '.join(['---'] * len(keys)) + ' |']
    for intent, group in result['per_intent'].items():
        for name, value in group['methods'].items():
            lines.append('| ' + intent + ' | ' + str(group['query_count']) + ' | ' + name + ' | ' +
                         ' | '.join(f"{value['metrics'][k]:.4f}" for k in keys) + ' |')
    history = result['per_intent']['historical/superseded']['noncurrent_enabled']['metrics']
    lines += ['', '### Interpret the slices', '',
              '- Current-memory Recall@1/3/5 uses only the five current-state queries. Stale-hit is contamination here.',
              '- Historical lookup with `--include-noncurrent`: Recall@1/3/5 = ' +
              ' / '.join(f"{history[f'Recall@{k}']:.4f}" for k in (1, 3, 5)) + '.',
              '- **Expired-target recall: not measured (0 expected-expired queries).** Historical queries still expect current decision records. Returning an old card is exposure, not automatically success or contamination.',
              '- Conflict visibility must distinguish the relevant disputed target (Recall) from any disputed result (controversial-hit). Both are reported; default-policy misses remain visible.',
              '- Cross-session and compaction-recovery are contextual intent groups, not claims of live Agent evaluation.', '']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixtures', default=str(Path(__file__).parent / 'fixtures'))
    ap.add_argument('--out', default=str(Path(__file__).parent))
    args = ap.parse_args()
    result = evaluate(args.fixtures)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out/'benchmark-results.json').write_text(json_text(result), encoding='utf-8')
    (out/'benchmark-results.md').write_text(markdown(result), encoding='utf-8')
    print(markdown(result))


if __name__ == '__main__':
    main()
