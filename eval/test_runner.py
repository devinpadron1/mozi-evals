"""No network calls or production example outputs are created by these tests."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from pydantic import ValidationError
from runner import Brief, Grade, predict, grade, read, request_settings

def fake_response(source_ids=None,status='completed'):
    brief=Brief(constraint='leads',diagnosis='Test-only diagnosis',
                evidence=['Test-only intake evidence'],next_action='Test-only action',
                follow_up_question='Test-only question?',missing_information=[],
                source_ids=source_ids or [])
    return SimpleNamespace(status=status,output_parsed=brief,usage=None,
                           model='test-model',id='test-response')

class RunnerTests(unittest.TestCase):
    def test_non_reasoning_settings_preserve_temperature(self):
        settings=request_settings({'reasoning_effort':'none','temperature':0,'max_output_tokens':1100})
        self.assertEqual(settings,{'reasoning':{'effort':'none'},'temperature':0,'max_output_tokens':1100})
    def test_plan_defaults_do_not_emit_unsupported_overrides(self):
        settings=request_settings({'reasoning_effort':'none','temperature':None,'max_output_tokens':None})
        self.assertEqual(settings,{'reasoning':{'effort':'none'}})
    def test_reasoning_settings_omit_unsupported_temperature(self):
        settings=request_settings({'reasoning_effort':'low','temperature':0,'max_output_tokens':3000})
        self.assertNotIn('temperature',settings)
        self.assertEqual(settings['reasoning'],{'effort':'low'})
    def test_judge_request_and_report_use_the_requested_model(self):
        self.client.responses.parse.return_value=SimpleNamespace(status='completed',
            output_parsed=Grade(diagnosis_agreement=.5,diagnosis_reason='Test-only',
                grounded_advice=.8,grounded_reason='Test-only',
                missing_information=.8,missing_reason='Test-only'),
            model='gpt-6-sol',id='test-only-response',usage=None)
        result=grade(self.client,'gpt-6-sol',self.case,{'brief':fake_response().output_parsed.model_dump()},self.prompts,'baseline')
        request=self.client.responses.parse.call_args.kwargs
        self.assertEqual(request['model'],'gpt-6-sol')
        self.assertEqual(request['reasoning'],{'effort':'none'})
        self.assertEqual(result['resolved_judge_model'],'gpt-6-sol')
        self.assertEqual(result['scores']['label_match']['score'],1)
    def test_ten_cases_have_unique_sources_and_valid_reference_labels(self):
        manifest=read('manifest.json')
        cases=manifest['cases']
        self.assertEqual(len(cases),10)
        self.assertEqual(len({c['id'] for c in cases}),10)
        self.assertEqual(len({c['source']['video_id'] for c in cases}),10)
        for case in cases:
            with self.subTest(case=case['id']):
                source=case['source']
                self.assertRegex(source['video_id'],r'^[A-Za-z0-9_-]{11}$')
                self.assertEqual(source['thumbnail_url'],f"https://i.ytimg.com/vi/{source['video_id']}/hqdefault.jpg")
                self.assertIn(source['video_id'],source['url'])
                self.assertTrue(source['input_window'])
                self.assertTrue(source['reference_window'])
                self.assertIn(case['reference']['constraint'],manifest['prompts']['taxonomy'])
                self.assertTrue(case['reference']['action'])
                self.assertTrue(case['inputs']['unknowns'])
    def setUp(self):
        self.prompts=read('manifest.json')['prompts']
        self.case=read('manifest.json')['cases'][0]
        self.client=Mock()
        self.client.responses.parse.return_value=fake_response()
    def test_reference_does_not_enter_either_model_request(self):
        for variant in ['baseline','grounded']:
            predict(self.client,'test-model',self.case['inputs'],variant,self.prompts)
            payload=self.client.responses.parse.call_args.kwargs
            user=json.loads(payload['input'][1]['content'])
            self.assertEqual(user['intake'],self.case['inputs'])
            self.assertNotIn('reference',user)
            self.assertNotIn(self.case['reference']['action'],json.dumps(payload,default=str))
            self.assertEqual('framework_notes' in user,variant=='grounded')
    def test_invalid_citation_is_rejected(self):
        self.client.responses.parse.return_value=fake_response(['made-up-source'])
        with self.assertRaisesRegex(ValueError,'Unknown source IDs'):
            predict(self.client,'test-model',self.case['inputs'],'grounded',self.prompts)
    def test_baseline_cannot_cite_unprovided_context(self):
        self.client.responses.parse.return_value=fake_response(['roadmap-marketing'])
        with self.assertRaises(ValueError):
            predict(self.client,'test-model',self.case['inputs'],'baseline',self.prompts)
    def test_incomplete_output_is_not_saved_as_a_brief(self):
        self.client.responses.parse.return_value=fake_response(status='incomplete')
        with self.assertRaises(RuntimeError):
            predict(self.client,'test-model',self.case['inputs'],'grounded',self.prompts)
    def test_out_of_range_judge_score_is_rejected(self):
        with self.assertRaises(ValidationError):
            Grade(diagnosis_agreement=1.2,diagnosis_reason='Test-only',
                  grounded_advice=.8,grounded_reason='Test-only',
                  missing_information=.8,missing_reason='Test-only')

if __name__=='__main__':unittest.main()
