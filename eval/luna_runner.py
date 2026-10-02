"""Classify complete source transcripts with GPT-5.6 Luna through OpenRouter."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from jev_runner import ROOT, read_json, transcript_for, write_atomic

REPORT = ROOT / 'dist' / 'luna_report.json'
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
MODEL = 'openai/gpt-5.6-luna'


def classify(api_key, transcript, labels, criteria):
    prompt = (
        'Read the complete automatic-caption transcript below. Decide which single business constraint '
        "the advisor ultimately prioritizes for the owner's stated growth goal. Use the central diagnosis "
        'and recommended action when several problems are discussed. Ignore the promotional roadmap outro. '
        'Choose exactly one label using the definitions below. Return only the required JSON object.\n\n'
        'LABEL DEFINITIONS:\n' + '\n'.join(f'- {label}: {criteria[label]}' for label in labels) +
        '\n\nTRANSCRIPT:\n' + transcript
    )
    schema = {
        'name': 'constraint_classification',
        'strict': True,
        'schema': {
            'type': 'object',
            'properties': {'constraint': {'type': 'string', 'enum': labels}},
            'required': ['constraint'],
            'additionalProperties': False,
        },
    }
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': 'Classify the business constraint from the transcript. Follow the label definitions and return the requested structured output.'},
            {'role': 'user', 'content': prompt},
        ],
        'response_format': {'type': 'json_schema', 'json_schema': schema},
        'temperature': 0,
    }
    request = Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'), method='POST',
                      headers={'Authorization': f'Bearer {api_key}',
                               'Content-Type': 'application/json',
                               'HTTP-Referer': 'http://127.0.0.1:8765',
                               'X-Title': 'Mozi Constraint Classifier',
                               'User-Agent': 'mozi-evals/1.0'})
    started = time.perf_counter()
    for attempt in range(3):
        try:
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f'OpenRouter returned HTTP {error.code}') from error
        except URLError as error:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError('Could not reach OpenRouter') from error
    latency = round(time.perf_counter() - started, 3)
    try:
        choice = json.loads(result['choices'][0]['message']['content'])['constraint']
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError('Luna did not return the required structured answer') from error
    if choice not in labels:
        raise RuntimeError('Luna returned a label outside the defined taxonomy')
    return result, choice, latency


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Classify all ten full transcripts with GPT-5.6 Luna.')
    parser.add_argument('--env-file', type=Path)
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
    labels = manifest['prompts']['taxonomy']
    criteria = spec['question']['criteria']
    if list(criteria) != labels:
        raise ValueError('Luna criteria must match the manifest taxonomy and order.')
    report = {
        'schema_version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'dataset_version': manifest['dataset_version'],
        'spec_version': 'gpt-5.6-luna-choice-v1',
        'model': MODEL,
        'question': {'instructions': spec['question']['instructions'], 'criteria': criteria},
        'taxonomy': labels,
        'input_kind': 'complete automatic-caption Markdown, including advisor resolution',
        'results': [],
    }
    for index, case in enumerate(manifest['cases'], 1):
        transcript, source_digest, input_digest, transform = transcript_for(case)
        response, choice, latency = classify(api_key, transcript, labels, criteria)
        usage = response.get('usage', {})
        report['results'].append({
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
            'reference': case['reference']['constraint'],
            'choice': choice,
            'match': choice == case['reference']['constraint'],
            'latency_seconds': latency,
            'resolved_model': response.get('model'),
            'response_id': response.get('id'),
            'usage': usage,
        })
        print(f'{index}/{len(manifest["cases"])} {case["id"]}: {choice}', flush=True)
    report['matches'] = sum(row['match'] for row in report['results'])
    report['total_cost_usd'] = round(sum(float(row['usage'].get('cost') or 0) for row in report['results']), 8)
    write_atomic(REPORT, report)
    print(f'Saved {REPORT}', flush=True)


if __name__ == '__main__':
    main()
