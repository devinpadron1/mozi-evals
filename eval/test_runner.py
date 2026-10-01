"""No network calls or production example outputs are created by these tests."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from pydantic import ValidationError
from runner import Brief, Grade, predict, read

def fake_response(source_ids=None,status='completed'):
    brief=Brief(constraint='customer_acquisition',diagnosis='Test-only diagnosis',
                evidence=['Test-only intake evidence'],next_action='Test-only action',
                follow_up_question='Test-only question?',missing_information=[],
                source_ids=source_ids or [])
    return SimpleNamespace(status=status,output_parsed=brief,usage=None,
                           model='test-model',id='test-response')

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.prompts=read('prompts.json')
        self.case=read('cases.json')['cases'][0]
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
