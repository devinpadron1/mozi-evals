"""Structured Responses adapter; OAuth secrets never cross the Node boundary."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from openai.lib._pydantic import to_strict_json_schema

BRIDGE = Path(__file__).resolve().parent/'chatgpt'/'bridge.mjs'

def call_bridge(command, payload=None):
    done=subprocess.run(['node',str(BRIDGE),command],
        input=json.dumps(payload) if payload is not None else '',
        capture_output=True,text=True,timeout=190)
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or 'Local ChatGPT request failed.')
    return json.loads(done.stdout)

class ChatGPTResponses:
    def parse(self, *, model, store, input, text_format, **parameters):
        instructions='\n\n'.join(m['content'] for m in input if m['role']=='system')
        result=call_bridge('request',{
            'model':model,'instructions':instructions,
            'input':[m for m in input if m['role']!='system'],
            'parameters':{k:v for k,v in parameters.items() if k=='reasoning'},
            'text':{'format':{'type':'json_schema','name':text_format.__name__,
                'strict':True,'schema':to_strict_json_schema(text_format)}}})
        response=result['response']
        if response.get('status')!='completed':
            raise RuntimeError('ChatGPT stream did not complete.')
        parsed=text_format.model_validate_json(result['text'])
        usage=response.get('usage')
        return SimpleNamespace(status='completed',output_parsed=parsed,
            model=response['model'],id=response['id'],
            usage=SimpleNamespace(model_dump=lambda:usage) if usage else None)

class ChatGPTClient:
    def __init__(self, required_models):
        catalog=call_bridge('models')
        available={m['slug'] for m in catalog['models']}
        missing=set(required_models)-available
        if missing:
            raise RuntimeError(f'Requested models unavailable to this ChatGPT connection: {sorted(missing)}. Available: {sorted(available)}')
        self.responses=ChatGPTResponses()
