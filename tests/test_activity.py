import json
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ai_activity as activity


class SnapshotTests(unittest.TestCase):
    def snapshot(self, **kwargs):
        args = dict(status={'loaded': True, 'activity': {'in_flight': 0}},
                    metrics={'live': {'state': 'idle', 'running': 0, 'queued': 0}},
                    demand={}, hardware={}, processes={'available': True, 'processes': []},
                    owned={100})
        args.update(kwargs)
        return activity.build_activity(**args)

    def test_states_and_precedence(self):
        cases = [
            ({}, 'ready'),
            ({'status': None}, 'unavailable'),
            ({'status': None, 'owned': set()}, 'offline'),
            ({'owned': set()}, 'unavailable'),
            ({'verified': False}, 'unavailable'),
            ({'metrics': {'live': {'state': 'reading'}}}, 'reading'),
            ({'metrics': {'live': {'state': 'generating'}}}, 'generating'),
            ({'status': {'loaded': False}, 'metrics': {'live': {'state': 'loading'}}}, 'unloaded'),
            ({'status': {'loaded': False}, 'metrics': {}}, 'unloaded'),
            ({'status': {'loaded': False}, 'demand': {'games': ['game.exe']}}, 'blocked'),
            ({'metrics': {}, 'status': {'loaded': True}}, 'busy'),
            ({'metrics': {'live': {'running': 1}}}, 'busy'),
        ]
        for inputs, expected in cases:
            with self.subTest(inputs=inputs):
                self.assertEqual(self.snapshot(**inputs)['state'], expected)

    def test_in_flight_does_not_invent_queue_or_stage(self):
        result = self.snapshot(status={'loaded': False}, metrics={}, demand={'active_requests': 3})
        self.assertEqual(result['in_flight'], 3)
        self.assertIsNone(result['running'])
        self.assertIsNone(result['queued'])
        self.assertEqual(result['state'], 'busy')
        self.assertEqual(result['title'], 'Preparing request')
        result = self.snapshot(status={'loaded': True}, metrics={}, demand={'active_requests': 3})
        self.assertEqual(result['state'], 'busy')

    def test_loaded_model_does_not_block_on_its_own_memory(self):
        hardware = dict(gpu_util=90, gpu_mem_used=30000*2**20, gpu_mem_total=32000*2**20)
        result = self.snapshot(hardware=hardware)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['blockers'], [])
        result = self.snapshot(status={'loaded': False}, hardware=hardware)
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(len(result['blockers']), 2)

    def test_blockers_respect_configured_limits(self):
        result = self.snapshot(status={'loaded': False}, hardware=dict(gpu_util=10, gpu_mem_used=2000*2**20, gpu_mem_total=16000*2**20),
                               options=dict(max_gpu_utilization=5, min_free_vram_mib=0, max_vram_used_mib=4000))
        self.assertEqual(result['blockers'], ['GPU workload is above the load limit'])

    def test_history_is_numeric_and_whitelisted(self):
        secret = 'private prompt and credentials'
        result = self.snapshot(status={'loaded': False}, demand={'load_issue': {'code': 'bad', 'message': secret}},
                               metrics={'requests': [dict(time=123, finish=secret, prompt=secret,
                                  error=secret, generated=8, prompt_ms=1000, decode_ms=2000),
                                  dict(time=secret, generated=float('nan'), duration_s=-1)]})
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['recent'][0], dict(time=123, finish='finished', tokens=8, duration_s=3))
        self.assertIsNone(result['recent'][1]['time'])
        self.assertIsNone(result['recent'][1]['tokens'])

    def test_process_names_do_not_establish_ownership(self):
        result = self.snapshot(processes=dict(available=True, processes=[dict(pid=100, name='strata.exe'), dict(pid=101, name='strata.exe')]))
        self.assertEqual(result['gpu_note'], '1 other compute process reported on GPU 0')
        self.assertNotIn('Comfy', result['gpu_note'])

    def test_latest_unload_overrides_old_generating_phase(self):
        result = self.snapshot(status={'loaded': False}, metrics={'live': {'state': 'generating', 'running': 2, 'queued': 1}})
        self.assertEqual(result['state'], 'unloaded')
        self.assertIsNone(result['running'])
        self.assertIsNone(result['queued'])
        self.assertIn('headroom unavailable', result['gpu_note'])

    def test_stale_load_issue_does_not_override_current_resources(self):
        result = self.snapshot(status={'loaded': False}, demand={'load_issue': {'code': 'vram_headroom'}},
                               hardware=dict(gpu_util=0, gpu_mem_used=1000*2**20, gpu_mem_total=32000*2**20))
        self.assertEqual(result['state'], 'unloaded')
        self.assertEqual(result['blockers'], [])
        self.assertIn('GiB free', result['gpu_note'])

    def test_game_blocks_loaded_requests_without_hiding_activity(self):
        result = self.snapshot(demand={'games': ['game.exe']}, metrics={'live': {'state': 'generating', 'running': 2, 'queued': 1}})
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['title'], 'Game priority')
        self.assertEqual(result['running'], 2)
        self.assertEqual(result['queued'], 1)
        self.assertEqual(self.snapshot(demand={'unknown': True})['title'], 'Game status unavailable')

    def test_native_schema_and_phase_counts(self):
        result = self.snapshot(metrics={'live': {'state': 'generating'}, 'requests': [dict(output_tokens=12, generated=99, finish='cancel', time=100, duration_s=3)]})
        self.assertEqual(result['running'], 1)
        self.assertEqual(result['recent'][0], dict(tokens=12, finish='cancel', time=100, duration_s=3))
        result = self.snapshot(metrics={'live': {'state': 'idle'}})
        self.assertEqual(result['running'], 0)
        self.assertIsNone(result['queued'])

    def test_ram_commit_block_only_before_load(self):
        hardware = dict(ram_free_gib=20, commit_free_gib=30)
        self.assertEqual(self.snapshot(hardware=hardware)['blockers'], [])
        result = self.snapshot(status={'loaded': False}, hardware=hardware)
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('System memory', result['blockers'][0])

    def test_process_details_are_bounded_and_path_free(self):
        processes = [dict(pid=i, name='C:\\private\\worker.exe', memory_mib=None) for i in range(1, 12)]
        result = self.snapshot(processes=dict(available=True, processes=processes))
        self.assertEqual(len(result['gpu_processes']), 8)
        self.assertEqual(result['gpu_processes'][0]['name'], 'worker.exe')
        self.assertNotIn('private', json.dumps(result))


    def test_admitted_warmup_does_not_classify_its_allocations_as_blockers(self):
        hardware = dict(gpu_util=95, gpu_mem_used=31000*2**20, gpu_mem_total=32000*2**20,
                        ram_free_gib=10, commit_free_gib=12)
        result = self.snapshot(status={'loaded': False, 'activity': {'in_flight': 0}},
                               demand={'active_requests': 2}, hardware=hardware)
        self.assertEqual(result['in_flight'], 2)
        self.assertEqual(result['state'], 'busy')
        self.assertEqual(result['title'], 'Preparing request')
        self.assertEqual(result['blockers'], [])
        result = self.snapshot(status={'loaded': False, 'activity': {'in_flight': 0}},
                               demand={'active_requests': 0}, hardware=hardware)
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(len(result['blockers']), 3)

    def test_admission_sources_use_maximum_not_sum_and_keep_guard_blockers(self):
        result = self.snapshot(status={'loaded': False, 'activity': {'in_flight': 3}},
                               demand={'active_requests': 2, 'load_retry_seconds': 15})
        self.assertEqual(result['in_flight'], 3)
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['blockers'], ['Waiting for the model load retry cooldown'])
        result = self.snapshot(status={'loaded': False, 'activity': {'in_flight': 3}},
                               demand={'active_requests': 2, 'games': ['game.exe']})
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['title'], 'Game priority')


class ProbeTests(unittest.TestCase):
    def test_compute_query_sanitizes_names_and_accepts_wddm(self):
        completed = Mock(returncode=0, stdout='123, C:\\private\\python.exe, [N/A]\n456, worker.exe, 128\n')
        with patch.object(activity.subprocess, 'run', return_value=completed) as run:
            result = activity.read_gpu_processes('nvidia-smi')
        self.assertTrue(result['available'])
        self.assertEqual(result['processes'][0], dict(pid=123, name='python.exe', memory_mib=None))
        self.assertEqual(result['processes'][1]['memory_mib'], 128)
        self.assertIn('--id=0', run.call_args.args[0])
        with patch.object(activity.subprocess, 'run', return_value=Mock(returncode=1)):
            self.assertFalse(activity.read_gpu_processes('nvidia-smi')['available'])

    def test_comfy_configuration_and_failures_are_never_idle(self):
        self.assertEqual(activity.read_comfy(None)['state'], 'not_configured')
        urls = ['https://localhost:8188', 'http://example.com', 'http://127.0.0.1.evil:8188',
                'http://user:secret@localhost:8188', 'http://localhost:8188/?key=secret', 'http://localhost:99999']
        with patch.object(activity.urllib.request, 'build_opener') as build:
            for url in urls:
                with self.subTest(url=url):
                    self.assertEqual(activity.read_comfy(url)['state'], 'unavailable')
            build.assert_not_called()

    def test_comfy_returns_counts_only_and_bounds_response(self):
        reply = Mock()
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock()
        reply.read.return_value = json.dumps(dict(queue_running=[['secret']], queue_pending=[['secret'], ['secret']])).encode()
        opener = Mock()
        opener.open.return_value = reply
        with patch.object(activity.urllib.request, 'build_opener', return_value=opener):
            result = activity.read_comfy('http://127.0.0.1:8188')
            self.assertEqual((result['running'], result['queued']), (1, 2))
            self.assertNotIn('secret', json.dumps(result))
            self.assertEqual(result['state'], 'busy')
            reply.read.assert_called_with(256*1024+1)
            reply.read.return_value = b'x' * (256*1024+1)
            self.assertEqual(activity.read_comfy('http://localhost:8188')['state'], 'unavailable')
            reply.read.return_value = b'{}'
            self.assertEqual(activity.read_comfy('http://localhost:8188')['state'], 'unavailable')
            reply.read.return_value = b'{"queue_running":[],"queue_pending":[]}'
            self.assertEqual(activity.read_comfy('http://localhost:8188')['state'], 'idle')

    def test_comfy_does_not_follow_redirects(self):
        self.assertIsNone(activity._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com'))


if __name__ == '__main__':
    unittest.main()
