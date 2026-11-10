import json
import pathlib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from ai_llamacpp import telemetry
from ai_llamacpp_metrics import History, Observation, SlotRates
from ai_telemetry import normalize_strata
from ai_activity import build_activity


class LlamaMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name)/'metrics.json'
        self.history = History(self.path)
        self.now = 10
        self.identity = (123, 456.0)

    def observer(self):
        return Observation(self.identity, started=10, history=self.history,
                           clock=lambda: self.now, wall=lambda: 1700000000+self.now)

    def timings(self):
        return dict(prompt_n=100, cache_n=900, predicted_n=40, prompt_ms=50,
                    predicted_ms=200, prompt_per_second=2000, predicted_per_second=200,
                    draft_n=100, draft_n_accepted=80, secret='PRIVATE')

    def finish(self, observer):
        self.now = 12
        observer.finish()
        return self.history.read(self.identity)[0]

    def test_streaming_reasoning_ttft_and_native_metrics_reach_dashboard_and_history(self):
        o = self.observer()
        o.event({'choices':[{'delta':{'role':'assistant'}}]})
        self.now = 10.25
        o.event({'choices':[{'delta':{'reasoning_content':'PRIVATE_THINKING'}}]})
        o.event({'choices':[{'delta':{'content':'PRIVATE_OUTPUT'},'finish_reason':'stop'}],
                 'timings':self.timings(),'usage':{'prompt_tokens':1000,'completion_tokens':40}})
        row = self.finish(o)
        self.assertEqual(row['ttft_ms'], 250)
        self.assertEqual(row['prompt_tokens'], 1000)
        self.assertEqual(row['duration_s'], 2)
        props = {'default_generation_settings':{'n_ctx':262144},'total_slots':1}
        metrics, status = telemetry(props, [], requests=[row])
        normalized = normalize_strata(metrics)
        self.assertEqual((normalized['last_prefill'], normalized['last_speed']), (2000, 200))
        self.assertEqual((normalized['reuse'], normalized['draft_acceptance']), (90,80))
        recent = build_activity(status, metrics, {}, {}, [], {123})['recent'][0]
        self.assertEqual((recent['prefill_tok_s'],recent['decode_tok_s'],recent['ttft_ms']), (2000,200,250))
        self.assertEqual((recent['reuse_percent'],recent['draft_percent']), (90,80))
        self.assertNotIn('PRIVATE', self.path.read_text())
        self.assertNotIn('PRIVATE', json.dumps([metrics,status,recent]))

    def test_anthropic_and_responses_streams_observe_tools_and_nested_timings(self):
        for kind in ['anthropic','responses']:
            with self.subTest(kind=kind):
                o=self.observer();self.now=10.5
                if kind=='anthropic':
                    o.event({'type':'message_start','message':{'usage':{'input_tokens':100}}})
                    self.assertFalse(o.done)
                    o.event({'type':'content_block_delta','delta':{'type':'input_json_delta','partial_json':'PRIVATE_ARGS'}})
                    o.event({'type':'message_delta','delta':{'stop_reason':'max_tokens'},'timings':self.timings()})
                    o.event({'type':'message_stop'})
                else:
                    o.event({'type':'response.function_call_arguments.delta','delta':'PRIVATE_ARGS'})
                    o.event({'type':'response.completed','response':{'usage':{'output_tokens':40},'timings':self.timings()}})
                row=self.finish(o)
                self.assertEqual(row['ttft_ms'],500)
                self.assertEqual(row['decode_tok_s'],200)
                self.assertEqual(row['finish'],'length' if kind=='anthropic' else 'stop')

    def test_nonstreaming_has_native_speeds_but_does_not_invent_ttft(self):
        o=self.observer()
        o.event({'choices':[{'message':{'content':'PRIVATE'},'finish_reason':'stop'}], 'timings':self.timings()},False)
        row=self.finish(o)
        self.assertIsNone(row['ttft_ms'])
        self.assertEqual(row['prefill_tok_s'],2000)

    def test_truncated_stream_errors_and_http_failures_are_not_successes(self):
        for event,status,failed in [({'type':'message_start','message':{'usage':{}}},200,False),
                                    ({'type':'error','error':{'message':'PRIVATE'}},200,False),
                                    ({},500,False),({},200,True)]:
            o=self.observer();o.event(event);o.finish(status,failed)
            self.assertEqual(self.history.read(self.identity)[0]['finish'],'error')
        self.assertNotIn('PRIVATE',self.path.read_text())

    def test_history_is_bounded_private_instance_scoped_and_thread_safe(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i:self.history.append(self.identity,{'output_tokens':i,'prompt':'PRIVATE','time':i}),range(120)))
        self.assertEqual(len(self.history.read(self.identity)),100)
        self.assertEqual(len({r['output_tokens'] for r in self.history.read(self.identity)}),100)
        self.assertEqual(self.history.read((124,456)),[])
        self.assertEqual(self.history.read((123,457)),[])
        self.assertNotIn('PRIVATE',self.path.read_text())
        self.history.append((124,457),{'decode_tok_s':float('nan'),'ttft_ms':-1,'finish':'PRIVATE'})
        row=self.history.read((124,457))[0]
        self.assertIsNone(row['decode_tok_s']);self.assertIsNone(row['ttft_ms'])
        self.assertEqual(row['finish'],'completed')
        self.path.write_text('broken')
        self.assertEqual(self.history.read(self.identity),[])

    def test_write_failure_and_duplicate_finish_do_not_break_inference(self):
        o=self.observer();o.event({'type':'message_stop'})
        o.finish();o.finish()
        self.assertEqual(len(self.history.read(self.identity)),1)
        with patch('ai_llamacpp_metrics.write_json',side_effect=OSError('disk full')):
            self.observer().finish(500)

    def test_slot_rates_reset_on_task_process_idle_or_counter_reset(self):
        rates=SlotRates()
        slot=dict(id=0,id_task=9,is_processing=True,n_prompt_tokens_processed=100,next_token=[{'n_decoded':0}])
        self.assertIsNone(rates.sample(self.identity,[slot],1)[0]['tok_s'])
        slot['n_prompt_tokens_processed']=300
        self.assertEqual(rates.sample(self.identity,[slot],3)[0]['prefill_tok_s'],100)
        slot['next_token'][0]['n_decoded']=20
        self.assertEqual(rates.sample(self.identity,[slot],4)[0]['tok_s'],20)
        slot['id_task']=10
        self.assertIsNone(rates.sample(self.identity,[slot],5)[0]['tok_s'])
        slot['next_token'][0]['n_decoded']=1
        self.assertIsNone(rates.sample(self.identity,[slot],6)[0]['tok_s'])
        self.assertIsNone(rates.sample((999,0),[slot],7)[0]['tok_s'])
        rates.sample((999,0),[],8)
        self.assertIsNone(rates.sample((999,0),[slot],9)[0]['tok_s'])

    def test_counter_rates_and_input_cache_accounting_are_displayed_without_double_counting_output(self):
        props={'default_generation_settings':{'n_ctx':262144},'total_slots':1}
        slot=dict(id=0,id_task=1,is_processing=True,n_prompt_tokens=1040,n_prompt_tokens_processed=100,
                  n_prompt_tokens_cache=900,next_token=[{'n_decoded':40}])
        metrics,_=telemetry(props,[slot],{0:{'tok_s':200,'prefill_tok_s':None}})
        panel=normalize_strata(metrics)
        self.assertEqual(panel['live_speed'],200)
        self.assertEqual(panel['generated'],40)
        self.assertEqual(panel['slots'][0]['used'],1040)


if __name__=='__main__':
    unittest.main()
