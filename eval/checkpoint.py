"""Keep validated outputs locally even when a later request fails."""
from copy import deepcopy
import hashlib
import json
from threading import Lock

IDENTITY_FIELDS=('model','judge_model','auth_method','dataset_hash','prompt_hash',
                 'model_parameters','judge_parameters')

class RunCheckpoint:
    def __init__(self, directory, report, resume=False):
        self.lock=Lock()
        identity={key:report[key] for key in IDENTITY_FIELDS}
        digest=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/(digest+'.json')
        self.data=deepcopy(report)
        if resume and self.path.exists():
            saved=json.loads(self.path.read_text())
            if any(saved.get(key)!=value for key,value in identity.items()):
                raise ValueError('Checkpoint does not match the requested run.')
            self.data=saved

    def get(self, case_id, variant):
        with self.lock:
            return deepcopy(next((r for r in self.data['results']
                if r['case_id']==case_id and r['variant']==variant),None))

    def save(self, result):
        with self.lock:
            self.data['results']=[r for r in self.data['results']
                if (r['case_id'],r['variant'])!=(result['case_id'],result['variant'])]
            self.data['results'].append(deepcopy(result))
            temp=self.path.with_suffix('.json.tmp')
            temp.write_text(json.dumps(self.data,indent=2))
            temp.replace(self.path)
