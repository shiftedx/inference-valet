import gc
import json
import pathlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import Mock

from ai_llamacpp_metrics import History, Observation
from ai_provider import make_server


TIMINGS=dict(prompt_n=100, cache_n=900, predicted_n=40, prompt_ms=50,
             predicted_ms=200, prompt_per_second=2000, predicted_per_second=200,
             draft_n=100, draft_n_accepted=80)


class MetricsBackend(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200)
        if not body.get('stream'):
            self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'choices':[], 'timings':TIMINGS, 'private':'PRIVATE'}).encode());return
        self.send_header('Content-Type','text/event-stream');self.end_headers()
        if self.path=='/v1/messages':
            events=[{'type':'message_start','message':{'model':'native','usage':{'input_tokens':100}}},
                    {'type':'content_block_delta','delta':{'thinking':'PRIVATE_THINKING'}},
                    {'type':'message_delta','delta':{'stop_reason':'end_turn'},'timings':TIMINGS},
                    {'type':'message_stop'}]
        elif self.path=='/v1/responses':
            events=[{'type':'response.output_text.delta','delta':'PRIVATE_OUTPUT'},
                    {'type':'response.completed','response':{'model':'native','timings':TIMINGS}}]
        else:
            events=[{'choices':[{'delta':{'reasoning_content':'PRIVATE_THINKING'}}]},
                    {'choices':[{'delta':{'tool_calls':[{'function':{'name':'PRIVATE_TOOL','arguments':'PRIVATE_ARGS'}}]},'finish_reason':'tool_calls'}],'timings':TIMINGS}]
        for event in events:self.wfile.write(b'data: '+json.dumps(event).encode()+b'\n\n')
        self.wfile.write(b'data: [DONE]\n\n')


class ProviderMetricsTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.history=History(pathlib.Path(self.temp.name)/'history.json')
        self.identity=(123,456)
        self.completed=threading.Event()
        self.backend=self.start(ThreadingHTTPServer(('127.0.0.1',0),MetricsBackend))
        self.profile={'engine':'llamacpp','label':'Fixture','context':262144,'slots':1,'model':'native'}
        def observe(started):
            observer=Observation(self.identity,started=started,history=self.history)
            finish=observer.finish
            def complete(*args):
                finish(*args);self.completed.set()
            observer.finish=complete
            return observer
        self.factory=Mock(side_effect=observe)
        self.api=self.start(make_server('PRIVATE_AUTH',lambda:{'fixture':self.profile},lambda _:'fixture',
                             port=0,backend_port=self.backend.server_port,performance=self.factory))

    def start(self,server):
        threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server

    def request(self,path,stream=True):
        req=Request(f'http://127.0.0.1:{self.api.server_port}'+path,
                    data=json.dumps({'model':'fixture','messages':[{'role':'user','content':'PRIVATE_PROMPT'}],'stream':stream}).encode(),
                    headers={'Authorization':'Bearer PRIVATE_AUTH','Content-Type':'application/json'})
        with urlopen(req,timeout=5) as r:return r.read()

    def test_all_three_streaming_protocols_collect_native_metrics_without_recording_content(self):
        for path in ['/v1/chat/completions','/v1/messages','/v1/responses']:
            self.completed.clear()
            body=self.request(path)
            self.assertTrue(self.completed.wait(2))
            self.assertIn(b'PRIVATE',body)  # Forwarding preserves the response payload.
            row=self.history.read(self.identity)[0]
            self.assertEqual(row['decode_tok_s'],200)
            self.assertEqual(row['prefill_tok_s'],2000)
            self.assertEqual(row['drafts_accepted'],80)
            self.assertIsNotNone(row['ttft_ms'])
            self.assertEqual(row['finish'],'stop')
        self.assertEqual(len(self.history.read(self.identity)),3)
        self.assertNotIn('PRIVATE',self.history.path.read_text())

    def test_nonstreaming_and_counting_and_other_backends(self):
        self.request('/v1/chat/completions',False)
        self.assertTrue(self.completed.wait(2))
        self.assertIsNone(self.history.read(self.identity)[0]['ttft_ms'])
        self.factory.reset_mock()
        self.request('/v1/messages/count_tokens',False)
        self.factory.assert_not_called()
        self.profile['engine']='strata'
        self.request('/v1/chat/completions')
        self.factory.assert_not_called()

    def test_observer_failure_cannot_change_inference_response(self):
        self.factory.side_effect=OSError('fixture failure')
        self.assertIn(b'[DONE]',self.request('/v1/chat/completions'))
        self.factory.side_effect=None
        self.factory.return_value=Mock(event=Mock(side_effect=ValueError('bad metric')),finish=Mock(side_effect=OSError('disk full')))
        self.assertIn(b'[DONE]',self.request('/v1/chat/completions'))


if __name__=='__main__':unittest.main()
