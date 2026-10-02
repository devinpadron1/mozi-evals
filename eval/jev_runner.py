"""Classify complete source transcripts with Jev through OpenRouter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'data' / 'ask-hormozi'
TRANSCRIPTS = CORPUS / 'transcripts'
REPORT = ROOT / 'dist' / 'jev_report.json'
PROGRESS = ROOT / '.eval-runs' / 'jev-progress.json'
ENDPOINT = 'https://openrouter.ai/api/alpha/decisions'
TRANSCRIPT_TRANSFORM_VERSION = 'acq-roadmap-cta-v2'

_CAPTION_TIMESTAMP = r'(?:\s*##\s*\[\d{1,2}:\d{2}\]\([^)]+\)\s*)?'
_CTA_STARTS = (
    ('free_roadmap_offer', re.compile(
        r"\b(?:(?:i['’]?d)\s+)?like\s+to" + _CAPTION_TIMESTAMP +
        r"\s*give\s+you\s+this\s+thing\s+absolutely\s+free", re.IGNORECASE)),
    ('gift_offer', re.compile(
        r"\b(?:my|our)\s+gift\s+to\s+you" + _CAPTION_TIMESTAMP +
        r".{0,60}?absolutely\s+free", re.IGNORECASE | re.DOTALL)),
    ('team_consult_offer', re.compile(
        r"\bmy\s+team\s+spends?\s+(?:two|2)\s+days\s+with\s+you\s+to\s+identify\s+"
        r"the\s+thing(?:" + _CAPTION_TIMESTAMP + r")?\s*that['’]?s\s+holding\s+your\s+business\s+back",
        re.IGNORECASE)),
)
_CTA_SIGNALS = (
    re.compile(r'acquisition.{0,40}road\s*map', re.IGNORECASE | re.DOTALL),
    re.compile(r'link.{0,100}description', re.IGNORECASE | re.DOTALL),
    re.compile(r'thank\s*you page', re.IGNORECASE),
    re.compile(r'book a call(?: with (?:my|our|the) team)?', re.IGNORECASE),
    re.compile(r'(?:invite|see) you out (?:to|here in) Vegas', re.IGNORECASE),
    re.compile(r'my team spends?\s+(?:two|2)\s+days with you', re.IGNORECASE),
)


def read_json(path):
    return json.loads(path.read_text())


def write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def strip_promotional_outro(transcript):
    """Remove a recognizable Acquisition.com outro only when it occurs at the tail."""
    candidates = []
    for marker, pattern in _CTA_STARTS:
        for match in pattern.finditer(transcript):
            if match.start() / max(1, len(transcript)) < 0.65:
                continue
            tail = transcript[match.start():]
            if any(signal.search(tail) for signal in _CTA_SIGNALS):
                candidates.append((match.start(), marker))
                break
    if not candidates:
        return transcript, {
            'removed': False,
            'marker': None,
            'original_chars': len(transcript),
            'input_chars': len(transcript),
            'removed_chars': 0,
        }
    start, marker = min(candidates)
    cleaned = transcript[:start].rstrip()
    # The roadmap pitch is often introduced by a final spoken transition.
    cleaned = re.sub(r'\s+(?:and\s+)?so[,.:]?\s*$', '', cleaned, flags=re.IGNORECASE)
    return cleaned, {
        'removed': True,
        'marker': marker,
        'original_chars': len(transcript),
        'input_chars': len(cleaned),
        'removed_chars': len(transcript) - len(cleaned),
    }


def transcript_for(case):
    """Read the complete caption Markdown from the installed local snapshot."""
    video_id = case['source']['video_id']
    source_url = case['source']['transcript_url']
    expected = f'https://github.com/poseljacob/ask-hormozi/blob/main/corpus/transcripts/{video_id}.md'
    if source_url != expected or Path(video_id).name != video_id:
        raise ValueError(f'Unexpected transcript source for {case["id"]}')
    path = TRANSCRIPTS / f'{video_id}.md'
    if not path.is_file():
        raise FileNotFoundError(f'Missing local transcript for {case["id"]}. Run python eval/sync_transcripts.py to install the corpus.')
    if path.stat().st_size > 200_000:
        raise ValueError(f'Transcript exceeds the 200 KB safety limit: {case["id"]}')
    raw = path.read_bytes()
    transcript = raw.decode('utf-8')
    if not transcript.strip() or len(transcript) > 200_000:
        raise ValueError(f'Transcript is empty or too large: {case["id"]}')
    transcript, transform = strip_promotional_outro(transcript)
    return (transcript, hashlib.sha256(raw).hexdigest(),
            hashlib.sha256(transcript.encode('utf-8')).hexdigest(), transform)


def classify(api_key, transcript, spec):
    payload = {'model': spec['model'], 'state': {'transcript': transcript},
               'questions': {'primary_constraint': spec['question']}}
    started = time.perf_counter()
    for attempt in range(4):
        request = Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'), method='POST',
                          headers={'Authorization': f'Bearer {api_key}',
                                   'Content-Type': 'application/json',
                                   'User-Agent': 'mozi-evals/1.0'})
        try:
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(min(2 ** attempt * 2, 12))
                continue
            raise RuntimeError(f'OpenRouter returned HTTP {error.code}') from error
        except URLError as error:
            if attempt < 3:
                time.sleep(min(2 ** attempt * 2, 12))
                continue
            raise RuntimeError('Could not reach OpenRouter') from error
    latency = round(time.perf_counter() - started, 3)
    answer = result.get('answers', {}).get('primary_constraint', {})
    if answer.get('type') != 'choice':
        raise RuntimeError('Jev did not return a Choice answer')
    return result, answer, latency


def classify_case(api_key, case, spec, labels):
    transcript, source_digest, input_digest, transform = transcript_for(case)
    response, answer, latency = classify(api_key, transcript, spec)
    choice = answer.get('choice')
    probabilities = answer.get('probabilities')
    if choice not in labels or not isinstance(probabilities, dict) or set(probabilities) != set(labels):
        raise RuntimeError(f'Unexpected Jev labels for {case["id"]}')
    if any(not isinstance(probabilities[label], (int, float)) or not 0 <= probabilities[label] <= 1 for label in labels):
        raise RuntimeError(f'Invalid Jev probabilities for {case["id"]}')
    confidence = answer.get('confidence')
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise RuntimeError(f'Invalid Jev confidence for {case["id"]}')
    reference = case.get('reference') or {}
    reference_choice = reference.get('constraint')
    return {
        'case_id': case['id'],
        'video_id': case['source']['video_id'],
        'transcript_url': case['source']['transcript_url'],
        'transcript_sha256': source_digest,
        'transcript_input_sha256': input_digest,
        'transcript_chars_original': transform['original_chars'],
        'transcript_chars': len(transcript),
        'promotional_outro_removed': transform['removed'],
        'promotional_outro_marker': transform['marker'],
        'promotional_outro_removed_chars': transform['removed_chars'],
        'reference': reference_choice,
        'choice': choice,
        'match': choice == reference_choice if reference_choice in labels else None,
        'probabilities': probabilities,
        'confidence': confidence,
        'latency_seconds': latency,
        'resolved_model': response.get('model'),
        'response_id': response.get('id'),
        'usage': response.get('usage', {}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Classify all complete transcripts with Jev.')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--workers', type=int, help='Concurrent requests (default: JEV_WORKERS or 32).')
    args = parser.parse_args()
    if not args.run:
        parser.error('Run with --run to classify the transcripts.')
    if args.env_file and not args.env_file.is_file():
        parser.error('The specified .env file does not exist.')
    load_dotenv(args.env_file or ROOT / '.env', override=bool(args.env_file))
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        parser.error('OPENROUTER_API_KEY is required. Add it to the environment or local .env.')
    manifest = read_json(ROOT / 'dist' / 'manifest.json')
    spec = read_json(ROOT / 'dist' / 'jev_spec.json')
    cases = manifest['cases']
    if not (CORPUS / 'snapshot.json').is_file():
        parser.error('Install the local transcripts first: python eval/sync_transcripts.py')
    snapshot = read_json(CORPUS / 'snapshot.json')
    missing = sum(not (TRANSCRIPTS / f'{case["source"]["video_id"]}.md').is_file() for case in cases)
    if missing:
        parser.error(f'The local corpus is missing {missing} selected transcript(s).')
    labels = manifest['prompts']['taxonomy']
    if list(spec['question']['criteria']) != labels:
        raise ValueError('Jev criteria must match the manifest taxonomy and order.')
    workers = args.workers if args.workers is not None else int(os.getenv('JEV_WORKERS', '32'))
    if not 1 <= workers <= 32:
        parser.error('Choose between 1 and 32 concurrent workers.')

    started_at = time.time()
    created_at = datetime.now(timezone.utc).isoformat()
    result_lock = threading.Lock()
    results = {}
    errors = []
    total_cost = 0.0
    finished = 0

    def progress(status='running'):
        elapsed = round(time.time() - started_at, 2)
        ordered = [results[case['id']] for case in cases if case['id'] in results]
        snapshot = {
            'status': status,
            'started_at': started_at,
            'created_at': created_at,
            'elapsed_seconds': elapsed,
            'total': len(cases),
            'finished': finished,
            'completed': len(ordered),
            'failed': len(errors),
            'workers': workers,
            'total_cost_usd': round(total_cost, 8),
            'results': ordered,
            'errors': errors[-5:],
        }
        write_atomic(PROGRESS, snapshot)

    progress()
    print(f'Classifying {len(cases)} transcripts with {workers} concurrent requests.', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_cases = {pool.submit(classify_case, api_key, case, spec, labels): case for case in cases}
        for future in as_completed(future_cases):
            case = future_cases[future]
            try:
                result = future.result()
                with result_lock:
                    results[case['id']] = result
                    total_cost += float(result['usage'].get('cost') or 0)
                    finished += 1
                print(f'{finished}/{len(cases)} {case["name"]}: {result["choice"]}', flush=True)
            except Exception as error:
                with result_lock:
                    errors.append({'case_id': case['id'], 'message': str(error)[:240]})
                    finished += 1
                print(f'FAILED {case["name"]}: {error}', flush=True)
            progress()

    ordered_results = [results[case['id']] for case in cases if case['id'] in results]
    if errors:
        progress('failed')
        raise RuntimeError(f'{len(errors)} transcript(s) failed. Successful partial classifications remain in the live progress file.')
    report = {
        'schema_version': 2,
        'created_at': created_at,
        'dataset_version': manifest['dataset_version'],
        'spec_version': spec['version'],
        'model': spec['model'],
        'question': spec['question'],
        'taxonomy': labels,
        'input_kind': 'complete automatic-caption Markdown, with a recognized promotional outro removed when present',
        'transcript_transform_version': TRANSCRIPT_TRANSFORM_VERSION,
        'transcript_snapshot': snapshot,
        'concurrency': workers,
        'total_elapsed_seconds': round(time.time() - started_at, 2),
        'results': ordered_results,
        'reference_count': sum(row['match'] is not None for row in ordered_results),
        'matches': sum(row['match'] is True for row in ordered_results),
        'total_cost_usd': round(total_cost, 8),
    }
    write_atomic(REPORT, report)
    progress('completed')
    print(f'Saved {REPORT}', flush=True)


if __name__ == '__main__':
    main()
