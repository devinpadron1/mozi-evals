import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from checkpoint import RunCheckpoint

class CheckpointTests(unittest.TestCase):
    def report(self):
        return dict(model='test-only',judge_model='test-judge',auth_method='test-only',
            dataset_hash='synthetic-dataset',prompt_hash='synthetic-prompt',
            model_parameters={},judge_parameters={},run_id='synthetic-run',results=[])
    def test_interrupted_judging_keeps_prediction_across_restart(self):
        with TemporaryDirectory() as directory:
            report=self.report(); first=RunCheckpoint(Path(directory),report)
            result={'case_id':'test-case','variant':'baseline','brief':{'test_only':True}}
            first.save(result)
            resumed=RunCheckpoint(Path(directory),report,resume=True)
            self.assertEqual(resumed.get('test-case','baseline'),result)
            result['scores']={'test_only':True};resumed.save(result)
            self.assertEqual(len(resumed.data['results']),1)
    def test_changed_prompts_do_not_reuse_results(self):
        with TemporaryDirectory() as directory:
            report=self.report();first=RunCheckpoint(Path(directory),report)
            first.save({'case_id':'test-case','variant':'baseline'})
            report['prompt_hash']='different-synthetic-prompt'
            self.assertIsNone(RunCheckpoint(Path(directory),report,resume=True).get('test-case','baseline'))
    def test_concurrent_saves_retain_every_case(self):
        with TemporaryDirectory() as directory:
            checkpoint=RunCheckpoint(Path(directory),self.report())
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(checkpoint.save,[{'case_id':str(i),'variant':'baseline'} for i in range(20)]))
            resumed=RunCheckpoint(Path(directory),self.report(),resume=True)
            self.assertEqual(len(resumed.data['results']),20)
