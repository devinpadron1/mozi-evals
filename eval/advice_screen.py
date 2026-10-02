"""Screen the local MoreMozi corpus for actionable business advice using Jev."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from jev_runner import CORPUS, ROOT, read_json, transcript_for, write_atomic

PROGRESS = ROOT / '.eval-runs' / 'advice-screen-progress.json'
REPORT = ROOT / 'dist' / 'advice_screen_report.json'
ENDPOINT = 'https://openrouter.ai/api/alpha/decisions'
QUESTION = (
    'Does this transcript contain substantive, actionable advice for someone running, '
    'growing, or fixing a business? Include one-to-one coaching, business Q&A, and '
    'educational material that gives concrete guidance applicable to a business. '
    'Exclude announcements, entertainment, personal life, motivation without business '
    'guidance, and interviews without useful business advice.'
)


def screen_one(api_key, episode, spec):
    video_id = episode['episode_id']
    case = {
        'id': video_id,
        'name': episode.get('title') or video_id,
        'source': {
            'video_id': video_id,
            'transcript_url': f'https://github.com/poseljacob/ask-hormozi/blob/main/corpus/transcripts/{video_id}.md',
        },
    }
    transcript, source_digest, input_digest, transform = transcript_for(case)
    title = episode.get('title') or episode['episode_id']
    payload = {
        'model': spec['model'],
        'state': {'title': title, 'transcript': transcript},
        'questions': {'business_advice': {'type': 'noul', 'instructions': QUESTION}},
    }
    started = time.perf_counter()
    for attempt in range(5):
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), method='POST',
                          headers={'Authorization': f'Bearer {api_key}',
                                   'Content-Type': 'application/json',
                                   'User-Agent': 'mozi-evals/1.0'})
        try:
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f'OpenRouter returned HTTP {error.code}') from error
            retry_after = error.headers.get('Retry-After')
            try:
                pause = min(30, max(1, int(float(retry_after)))) if retry_after else min(16, 2 ** attempt)
            except ValueError:
                try:
                    pause = min(30, max(1, int((parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())))
                except (TypeError, ValueError, OverflowError):
                    pause = min(16, 2 ** attempt)
            time.sleep(pause)
        except URLError as error:
            if attempt == 4:
                raise RuntimeError('Could not reach OpenRouter') from error
            time.sleep(min(16, 2 ** attempt))
    answer = result.get('answers', {}).get('business_advice', {})
    score = answer.get('noul')
    if answer.get('type') != 'noul' or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise RuntimeError(f'Jev did not return a valid Noul score for {episode["episode_id"]}')
    return {
        'episode_id': episode['episode_id'], 'title': title,
        'advice_probability': float(score), 'transcript_sha256': source_digest,
        'transcript_input_sha256': input_digest,
        'promotional_outro_removed': transform['removed'],
        'promotional_outro_marker': transform['marker'],
        'promotional_outro_removed_chars': transform['removed_chars'],
        'transcript_chars_original': transform['original_chars'],
        'transcript_chars': len(transcript),
        'latency_seconds': round(time.perf_counter() - started, 3),
        'usage': result.get('usage', {}), 'response_id': result.get('id'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--workers', type=int, help='Concurrent screening calls; default 32.')
    args = parser.parse_args()
    if not args.run:
        parser.error('Run with --run to screen the local transcripts.')
    load_dotenv(args.env_file or ROOT / '.env', override=bool(args.env_file))
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        parser.error('OPENROUTER_API_KEY is required.')
    workers = args.workers if args.workers is not None else int(os.getenv('JEV_WORKERS', '32'))
    if not 1 <= workers <= 32:
        parser.error('Choose between 1 and 32 concurrent workers.')
    snapshot = read_json(CORPUS / 'snapshot.json')
    catalog = read_json(CORPUS / 'catalog.json')['episodes']
    spec = read_json(ROOT / 'dist' / 'jev_spec.json')
    missing = [e['episode_id'] for e in catalog
               if not (CORPUS / 'transcripts' / f'{e["episode_id"]}.md').is_file()]
    if missing:
        parser.error(f'The local corpus is missing {len(missing)} transcript(s).')

    results = {}
    if PROGRESS.is_file():
        saved = read_json(PROGRESS)
        if saved.get('snapshot_commit') == snapshot['commit'] and saved.get('question') == QUESTION:
            results = {r['episode_id']: r for r in saved.get('results', [])}
    pending = [e for e in catalog if e['episode_id'] not in results]
    errors = []
    run_started = time.time()
    total_cost = sum(float(r.get('usage', {}).get('cost') or 0) for r in results.values())
    finished = len(results)

    def save(status='running'):
        ordered = [results[e['episode_id']] for e in catalog if e['episode_id'] in results]
        write_atomic(PROGRESS, {
            'status': status, 'question': QUESTION, 'model': spec['model'],
            'snapshot_commit': snapshot['commit'], 'started_at': run_started,
            'elapsed_seconds': round(time.time() - run_started, 2),
            'total': len(catalog), 'finished': finished, 'completed': len(results),
            'failed': len(errors), 'workers': workers,
            'total_cost_usd': round(total_cost, 8), 'results': ordered, 'errors': errors[-20:],
        })

    save()
    print(f'Screening {len(pending)} transcripts with {workers} concurrent Jev requests.', flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(screen_one, api_key, e, spec): e for e in pending}
        for future in as_completed(futures):
            episode = futures[future]
            try:
                item = future.result()
                with lock:
                    results[episode['episode_id']] = item
                    total_cost += float(item['usage'].get('cost') or 0)
                    finished += 1
                print(f'{finished}/{len(catalog)} p={item["advice_probability"]:.2f} {episode["title"]}', flush=True)
            except Exception as error:
                with lock:
                    errors.append({'episode_id': episode['episode_id'], 'message': str(error)[:240]})
                    finished += 1
                print(f'FAILED {episode["episode_id"]}: {error}', flush=True)
            save()
    if errors:
        save('failed')
        raise RuntimeError(f'{len(errors)} transcripts failed; successful results are saved for resume.')
    save('completed')
    report = read_json(PROGRESS)
    report['created_at'] = datetime.now(timezone.utc).isoformat()
    report['input_kind'] = 'complete local transcript and title'
    write_atomic(REPORT, report)
    positives = sum(r['advice_probability'] >= 0.5 for r in results.values())
    print('Saved {}. {} of {} scored >= 0.50; cost {:.4f}.'.format(
        REPORT, positives, len(catalog), total_cost), flush=True)


if __name__ == '__main__':
    main()
