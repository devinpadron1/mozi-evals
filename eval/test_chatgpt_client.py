import unittest
from unittest.mock import patch
from chatgpt_client import ChatGPTClient, ChatGPTResponses
from runner import Brief

class ChatGPTTests(unittest.TestCase):
    @patch('chatgpt_client.call_bridge')
    def test_missing_requested_model_stops_before_inference(self,call):
        call.return_value={'models':[{'slug':'gpt-6-luna'}]}
        with self.assertRaisesRegex(RuntimeError,'gpt-6-sol'):
            ChatGPTClient(['gpt-6-luna','gpt-6-sol'])
        self.assertEqual(call.call_count,1)
    @patch('chatgpt_client.call_bridge')
    def test_structured_request_keeps_prompt_and_metadata(self,call):
        brief=Brief(constraint='focus',diagnosis='test',evidence=[],next_action='test',follow_up_question='test?',missing_information=[],source_ids=[])
        call.return_value={'text':brief.model_dump_json(),'response':{'status':'completed','model':'test-model','id':'test-id','usage':{'output_tokens':12}}}
        result=ChatGPTResponses().parse(model='test-model',store=False,input=[{'role':'system','content':'test instruction'},{'role':'user','content':'test intake'}],text_format=Brief,temperature=0,reasoning={'effort':'none'},max_output_tokens=100)
        request=call.call_args.args[1]
        self.assertEqual(request['instructions'],'test instruction')
        self.assertEqual(request['parameters'],{'reasoning':{'effort':'none'}})
        self.assertEqual(request['input'],[{'role':'user','content':'test intake'}])
        self.assertTrue(request['text']['format']['strict'])
        self.assertFalse(request['text']['format']['schema']['additionalProperties'])
        self.assertEqual(result.model,'test-model')
        self.assertEqual(result.output_parsed,brief)
        self.assertEqual(result.usage.model_dump(),{'output_tokens':12})
