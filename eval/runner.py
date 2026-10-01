"""Generate structured OpenAI briefs and independently grade them.

No credential is sent to the browser. Reports contain real inference latency,
source hashes, complete prompts, and the judging rubric.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from threading import Event
from checkpoint import RunCheckpoint

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
LABELS = Literal['customer_acquisition', 'sales_conversion', 'delivery_capacity',
                 'retention', 'unit_economics', 'strategic_focus', 'insufficient_information']

class Brief(BaseModel):
    constraint: LABELS
    diagnosis: str
    evidence: list[str]
    next_action: str
    follow_up_question: str
    missing_information: list[str]
    source_ids: list[str]

class Grade(BaseModel):
    diagnosis_agreement: float = Field(ge=0, le=1)
    diagnosis_reason: str
    grounded_advice: float = Field(ge=0, le=1)
    grounded_reason: str
    missing_information: float = Field(ge=0, le=1)
    missing_reason: str



def read(name):
    return json.loads((ROOT / 'dist' / name).read_text())

MANIFEST = read('manifest.json')
RUBRIC = MANIFEST['judgement']['system_prompt'] + '\nEvaluation criteria:\n' + json.dumps([c for c in MANIFEST['judgement']['criteria'] if c['method'] == 'llm_judge'], indent=2)

def write_atomic(path, obj):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, indent=2))
    temp.replace(path)

def request_settings(config):
    settings={}
    if config.get('max_output_tokens') is not None:
        settings['max_output_tokens']=config['max_output_tokens']
    effort=config.get('reasoning_effort')
    if effort is not None:
        settings['reasoning']={'effort':effort}
    # GPT-6 sampling controls are supported only with reasoning disabled.
    if effort in (None,'none') and config.get('temperature') is not None:
        settings['temperature']=config['temperature']
    return settings

def predict(client, model, inputs, variant, prompts):
    user_data = {'intake': inputs}
    if variant == 'grounded':
        user_data['framework_notes'] = prompts['framework']
    started = time.perf_counter()
    response = client.responses.parse(
        model=model, store=False, **request_settings(MANIFEST['model']),
        input=[{'role':'system', 'content':prompts[variant]},
               {'role':'user', 'content':json.dumps(user_data)}],
        text_format=Brief)
    latency = round(time.perf_counter() - started, 3)
    if response.status != 'completed' or response.output_parsed is None:
        raise RuntimeError(f'No completed structured brief: {response.status}')
    brief = response.output_parsed.model_dump()
    allowed = {s['id'] for s in prompts['framework']} if variant == 'grounded' else set()
    invalid = set(brief['source_ids']) - allowed
    if invalid:
        raise ValueError(f'Unknown source IDs: {sorted(invalid)}')
    return {'brief':brief, 'latency_seconds':latency,
            'usage':response.usage.model_dump() if response.usage else {},
            'resolved_model':response.model, 'response_id':response.id}

def grade(client, model, case, output, prompts, variant):
    data = {'intake':case['inputs'], 'brief':output['brief'],
            'reference':case['reference'],
            'available_sources':prompts['framework'] if variant == 'grounded' else []}
    response = client.responses.parse(
        model=model, store=False, **request_settings(MANIFEST['judgement']),
        input=[{'role':'system','content':RUBRIC},
               {'role':'user','content':json.dumps(data)}],
        text_format=Grade)
    if response.status != 'completed' or response.output_parsed is None:
        raise RuntimeError('Judge did not return a completed grade')
    g = response.output_parsed.model_dump()
    scores={ 'diagnosis_agreement':{'score':g['diagnosis_agreement'],'reason':g['diagnosis_reason']},
             'grounded_advice':{'score':g['grounded_advice'],'reason':g['grounded_reason']},
             'missing_information':{'score':g['missing_information'],'reason':g['missing_reason']},
             'label_match':{'score':int(output['brief']['constraint']==case['reference']['constraint']),
                            'reason':'Exact taxonomy label comparison; does not validate the recommended action.'}}
    return {'scores':scores,'resolved_judge_model':response.model,'judge_response_id':response.id,
            'judge_usage':response.usage.model_dump() if response.usage else {}}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--run',action='store_true',help='Generate and grade new model outputs.')
    parser.add_argument('--auth',choices=['api-key','chatgpt'],default='api-key')
    parser.add_argument('--model',help='Explicit predictor model, overriding .env defaults.')
    parser.add_argument('--judge-model',help='Explicit judge model, overriding .env defaults.')
    parser.add_argument('--resume',action='store_true',help='Reuse saved outputs with matching models, data, prompts and parameters.')
    args=parser.parse_args()
    load_dotenv(args.env_file or ROOT/'.env',override=bool(args.env_file))
    bundle=MANIFEST; prompts=bundle['prompts']; cases=bundle['cases']
    destination=ROOT/'dist'/'report.json'
    if args.run:
        model=args.model or os.getenv('MODEL',bundle['model']['name'])
        judge=args.judge_model or os.getenv('JUDGE_MODEL',bundle['judgement']['model'])
        if args.auth=='chatgpt':
            from chatgpt_client import ChatGPTClient
            print('Using ChatGPT plan. Manage usage: https://chatgpt.com/settings/usage',flush=True)
            client=ChatGPTClient([model,judge])
        else:
            client=OpenAI(timeout=60,max_retries=1)
        report={'schema_version':1,'run_id':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                'created_at':datetime.now(timezone.utc).isoformat(),'model':model,'judge_model':judge,
                'auth_method':args.auth,
                'prompt_version':prompts['version'],'dataset_version':bundle['dataset_version'],
                'prompt_hash':hashlib.sha256(json.dumps(prompts,sort_keys=True).encode()).hexdigest(),
                'dataset_hash':hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest(),
                'model_parameters':request_settings(bundle['model']),
                'judge_parameters':request_settings(bundle['judgement']),
                'judge_rubric':RUBRIC,'evaluation_engine':'Code validation + OpenAI structured judge','results':[]}
        checkpoint=RunCheckpoint(ROOT/'.eval-runs',report,resume=args.resume)
        report['run_id']=checkpoint.data['run_id']
        report['created_at']=checkpoint.data['created_at']
        stopped=Event()
        def task(pair):
            case,variant=pair
            if stopped.is_set():
                raise RuntimeError('No new requests after a run failure.')
            try:
                result=checkpoint.get(case['id'],variant)
                if result and 'scores' in result:
                    print(f'Resumed {case["id"]} / {variant}',flush=True)
                    return result
                if result is None:
                    output=predict(client,model,case['inputs'],variant,prompts)
                    result={'case_id':case['id'],'variant':variant,**output}
                    checkpoint.save(result)
                if stopped.is_set():
                    raise RuntimeError('Prediction saved; judging paused after another request failed.')
                result.update(grade(client,judge,case,result,prompts,variant))
                checkpoint.save(result)
                print(f'Completed {case["id"]} / {variant} ({result["latency_seconds"]}s)',flush=True)
                return result
            except Exception:
                stopped.set()
                raise
        pairs=[(c,v) for c in cases for v in ['baseline','grounded']]
        # Validate model access, parameters and judging on one pair before fan-out.
        first=task(pairs[0])
        with ThreadPoolExecutor(max_workers=3) as pool:
            report['results']=[first,*pool.map(task,pairs[1:])]
        # Replace the prior report only after all outputs and grades succeed.
        write_atomic(destination,report)
    elif destination.exists():
        report=read('report.json')
    else:
        parser.error('Run with --run first to generate real outputs.')
    write_atomic(destination,report)
    print(f'Saved {destination}',flush=True)

if __name__=='__main__':
    main()
