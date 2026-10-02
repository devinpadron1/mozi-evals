"""Repeat Jev on the same 100 curated cases and compare label stability."""
from __future__ import annotations

import itertools
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from jev_runner import ROOT, classify_case, read_json, write_atomic

RUNS = 3
SAMPLE_SIZE = 100
PROGRESS = ROOT / '.eval-runs' / 'jev-consistency-100x3.json'
REPORT = ROOT / 'dist' / 'jev-consistency-100x3.json'


def compare(replicates, cases):
    by_run = [{row['case_id']: row for row in run['results']} for run in replicates]
    pairwise = []
    for left, right in itertools.combinations(range(len(by_run)), 2):
        matches = sum(by_run[left][case['id']]['choice'] == by_run[right][case['id']]['choice'] for case in cases)
        pairwise.append({'runs': [left + 1, right + 1], 'matches': matches,
                         'total': len(cases), 'agreement': matches / len(cases)})
    all_match = 0
    unstable = []
    for case in cases:
        rows = [run[case['id']] for run in by_run]
        choices = [row['choice'] for row in rows]
        if len(set(choices)) == 1:
            all_match += 1
        else:
            unstable.append({
                'case_id': case['id'], 'video_id': case['source']['video_id'],
                'title': case['name'], 'choices': choices,
                'confidence': [row['confidence'] for row in rows],
                'probabilities': [row['probabilities'] for row in rows],
            })
    return {
        'all_three_agree_cases': all_match,
        'total_cases': len(cases),
        'all_three_agree_rate': all_match / len(cases),
        'pairwise_agreement': pairwise,
        'unstable_cases': unstable,
    }


def main():
    load_dotenv(ROOT / '.env')
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise SystemExit('OPENROUTER_API_KEY is required in the environment or local .env.')
    manifest = read_json(ROOT / 'dist' / 'manifest.json')
    spec = read_json(ROOT / 'dist' / 'jev_spec.json')
    cases = manifest['cases'][:SAMPLE_SIZE]
    labels = manifest['prompts']['taxonomy']
    workers = 32

    saved = {}
    if PROGRESS.is_file():
        candidate = read_json(PROGRESS)
        if candidate.get('dataset_version') == manifest['dataset_version'] and candidate.get('sample_ids') == [case['id'] for case in cases]:
            saved = candidate
    replicates = saved.get('replicates', [])
    experiment = {
        'status': 'running', 'dataset_version': manifest['dataset_version'],
        'model': spec['model'], 'sample_size': SAMPLE_SIZE, 'workers': workers,
        'selection': 'First 100 retained curated cases from the 500-case dataset.',
        'sample_ids': [case['id'] for case in cases],
        'replicates': replicates,
    }
    write_atomic(PROGRESS, experiment)
    for run_number in range(len(replicates) + 1, RUNS + 1):
        started = time.time()
        results = {}
        errors = []
        print(f'Run {run_number}/{RUNS}: classifying {SAMPLE_SIZE} cases with {workers} concurrent requests.', flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(classify_case, api_key, case, spec, labels): case for case in cases}
            for future in as_completed(futures):
                case = futures[future]
                try:
                    results[case['id']] = future.result()
                except Exception as error:
                    errors.append({'case_id': case['id'], 'message': str(error)[:240]})
        if errors:
            experiment.update(status='failed', failed_run=run_number, errors=errors)
            write_atomic(PROGRESS, experiment)
            raise RuntimeError(f'Run {run_number} failed for {len(errors)} cases; partial results were not added as a replicate.')
        ordered = [results[case['id']] for case in cases]
        run_cost = sum(float(row.get('usage', {}).get('cost') or 0) for row in ordered)
        replicate = {
            'run_number': run_number,
            'elapsed_seconds': round(time.time() - started, 2),
            'cost_usd': round(run_cost, 8),
            'results': ordered,
        }
        replicates.append(replicate)
        experiment['replicates'] = replicates
        experiment['completed_runs'] = len(replicates)
        write_atomic(PROGRESS, experiment)
        print(f'Run {run_number}/{RUNS} finished in {replicate["elapsed_seconds"]:.2f}s; cost {run_cost:.4f}.', flush=True)

    experiment['comparison'] = compare(replicates, cases)
    experiment['total_cost_usd'] = round(sum(run['cost_usd'] for run in replicates), 8)
    experiment['status'] = 'completed'
    write_atomic(PROGRESS, experiment)
    write_atomic(REPORT, experiment)
    summary = experiment['comparison']
    print(f'All three agree: {summary["all_three_agree_cases"]}/{SAMPLE_SIZE} '
          f'({summary["all_three_agree_rate"]:.1%}); total cost {experiment["total_cost_usd"]:.4f}.', flush=True)


if __name__ == '__main__':
    main()
