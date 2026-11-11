import gc
import ipaddress
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_metrics import MetricsExporter, prometheus
from ai_provider import make_server
from ai_provider_runtime import ProfileRouter


def reading():
    return {'hardware': {'gpu_power': 480, 'gpu_mem_used': 1234, 'gpu_util': 50, 'secret': 'PRIVATE'},
            'live_speed': 123, 'last_speed': 250, 'ttft_ms': 120, 'draft_acceptance': 75,
            'activity': {'state': 'generating', 'running': 2, 'queued': None, 'in_flight': 2,
                         'detail': 'PRIVATE', 'recent': [{'time': 10, 'finish': 'stop', 'tokens': 42,
                         'ttft_ms': 100, 'prompt': 'PRIVATE', 'image': 'PRIVATE'}]},
            'slots': [{'slot': 0, 'used': 40000, 'limit': 262144, 'speed': 123, 'prompt': 'PRIVATE'}],
            'identity': 'PRIVATE', 'engine_details': {'PRIVATE': 'PRIVATE'}}


class ExportTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.clock = 100
        self.profile = {'engine': 'llamacpp', 'model': 'PRIVATE', 'context': 262144, 'slots': 2,
                        'kv_cache_tokens': 262144, 'kv_shared': False, 'supports_vision': False}
        self.sample = Mock(side_effect=reading)
        self.key = 'fixture'
        self.exporter = MetricsExporter(self.sample, lambda: (self.key, self.profile),
                                        clock=lambda: self.clock, wall=lambda: 1000)

    def test_allowlists_units_missing_values_and_bounded_history(self):
        result = self.exporter.snapshot()
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result['hardware']['gpu_utilization_ratio'], .5)
        self.assertEqual(result['performance']['last_ttft_seconds'], .12)
        self.assertEqual(result['performance']['draft_acceptance_ratio'], .75)
        self.assertIsNone(result['requests']['queued'])
        self.assertEqual(result['slots'][0]['used_tokens'], 40000)
        self.assertEqual(result['recent_requests'][0]['ttft_seconds'], .1)
        self.assertFalse(result['profile']['supports_vision'])
        self.assertTrue(result['profile']['loaded'])
        raw = reading(); raw['activity']['recent'] *= 100
        raw['last_speed'] = float('nan');raw['hardware']['gpu_util'] = 'PRIVATE'
        self.sample.side_effect = lambda: raw;self.clock += 2
        result = self.exporter.snapshot()
        self.assertEqual(len(result['recent_requests']), 12)
        self.assertIsNone(result['performance']['last_decode_tokens_per_second'])
        self.assertIsNone(result['hardware']['gpu_utilization_ratio'])

    def test_concurrent_scrapes_share_sample_and_failures_keep_explicitly_stale_data(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            snapshots = list(pool.map(lambda _: self.exporter.snapshot(), range(8)))
        self.sample.assert_called_once()
        self.assertTrue(all(item['available'] and not item['stale'] for item in snapshots))
        self.clock += 3;self.sample.side_effect = RuntimeError('PRIVATE')
        result = self.exporter.snapshot()
        self.assertFalse(result['available']);self.assertTrue(result['stale'])
        self.assertEqual(result['age_seconds'], 3)
        self.assertEqual(result['sampled_at'], 1000)
        self.assertEqual(result['performance']['decode_tokens_per_second'], 123)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.exporter.snapshot();self.assertEqual(self.sample.call_count, 2)

    def test_switch_during_collection_does_not_mislabel_another_profiles_reading(self):
        self.sample.side_effect = lambda: (setattr(self, 'key', 'other') or reading())
        result = self.exporter.snapshot()
        self.assertFalse(result['available']);self.assertIsNone(result['profile']['id'])
        self.clock += 3;self.sample.side_effect = reading
        self.assertEqual(self.exporter.snapshot()['profile']['id'], 'other')

    def test_prometheus_labels_types_units_and_unknowns(self):
        self.key = 'quote"slash\\line\nfixture'
        result = prometheus(self.exporter.snapshot())
        self.assertTrue(result.endswith('\n'))
        self.assertIn('valet_hardware_gpu_power_watts 480', result)
        self.assertIn('valet_hardware_gpu_utilization_ratio 0.5', result)
        self.assertIn('quote\\"slash\\\\line\\nfixture', result)
        self.assertIn('# TYPE valet_performance_decode_tokens_per_second gauge\n', result)
        self.assertNotIn('valet_requests_queued', result)
        self.assertNotIn('PRIVATE', result)
        self.assertNotIn('None', result)
        self.assertNotIn('nan', result)

    def test_http_formats_auth_lan_restrictions_and_no_model_loads(self):
        loader = Mock()
        router = ProfileRouter(lambda _: 'fixture', loader)
        api = make_server('fixture-key', lambda: {}, lambda _: 'fixture', port=0,
                          telemetry=self.exporter, router=router)
        threading.Thread(target=api.serve_forever, kwargs={'poll_interval': .01}, daemon=True).start()
        self.addCleanup(api.server_close);self.addCleanup(api.shutdown)
        base = f'http://127.0.0.1:{api.server_port}'
        for path in ['/metrics', '/v1/metrics']:
            with self.assertRaises(HTTPError) as denied:
                urlopen(base + path, timeout=3)
            self.assertEqual(denied.exception.code, 401)
        self.sample.assert_not_called()
        with urlopen(Request(base+'/metrics', headers={'Authorization':'Bearer fixture-key'}), timeout=3) as reply:
            self.assertIn('version=0.0.4', reply.headers['Content-Type'])
            self.assertIn(b'valet_telemetry_up 1', reply.read())
        with urlopen(Request(base+'/v1/metrics', headers={'x-api-key':'fixture-key'}), timeout=3) as reply:
            result = json.load(reply)
            self.assertEqual(result['schema'], 'inference-valet.metrics/1')
            self.assertEqual(result['provider'], {'available':True, 'in_flight': 0, 'queued': 0})
            self.assertEqual(reply.headers['Cache-Control'],'no-store')
        self.sample.assert_called_once();loader.assert_not_called()
        # The same route must remain behind the existing LAN peer filter.
        class BindAddress(str):
            is_loopback = is_unspecified = is_multicast = False
        interface = SimpleNamespace(ip=BindAddress('127.0.0.1'), network=ipaddress.IPv4Network('192.0.2.0/24'))
        with patch('ai_provider.ipaddress.IPv4Interface', return_value=interface):
            restricted = make_server('fixture-key', lambda: {}, lambda _: None, port=0,
                                    lan='fixture', telemetry=self.exporter)
        threading.Thread(target=restricted.serve_forever,kwargs={'poll_interval':.01},daemon=True).start()
        self.addCleanup(restricted.server_close);self.addCleanup(restricted.shutdown)
        self.sample.reset_mock()
        for path in ['/metrics', '/v1/metrics']:
            with self.assertRaises(HTTPError) as denied:
                urlopen(Request(f'http://127.0.0.1:{restricted.server_port}'+path,
                                headers={'Authorization':'Bearer fixture-key'}),timeout=3)
            self.assertEqual(denied.exception.code,403)
        self.sample.assert_not_called()

    def test_slow_collection_does_not_immediately_expire_cache_and_missing_rows_are_safe(self):
        def slow():
            self.clock += 5
            raw = reading();raw['slots'] = None;raw['activity']['recent'] = None
            return raw
        self.sample.side_effect=slow
        self.exporter.snapshot();result=self.exporter.snapshot()
        self.sample.assert_called_once()
        self.assertEqual(result['age_seconds'],0)
        self.assertEqual(result['slots'],[])
        self.assertEqual(result['recent_requests'],[])

    def test_provider_snapshot_does_not_wait_for_model_loading_lock(self):
        router=ProfileRouter(lambda _:None)
        locked=threading.Event();release=threading.Event()
        def loading():
            with router.condition:
                locked.set();release.wait(3)
        worker=threading.Thread(target=loading);worker.start();self.assertTrue(locked.wait(1))
        try:
            self.assertEqual(router.snapshot(),{'available':False,'in_flight':None,'queued':None})
        finally:release.set();worker.join(1)


if __name__ == '__main__':
    unittest.main()
