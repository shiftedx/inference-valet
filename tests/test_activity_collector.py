import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ai_telemetry as telemetry


class ActivityCollectorTests(unittest.TestCase):
    def setUp(self):
        self.listener = Mock(pid=123)
        self.listener.create_time.return_value = 100.0
        self.listener.is_running.return_value = True
        self.connection = SimpleNamespace(status='LISTEN', laddr=SimpleNamespace(ip='127.0.0.1', port=8080))
        self.listener.net_connections.return_value = [self.connection]
        self.processes = [(self.listener, 'strata-server')]
        self.metrics = {'live': {'state': 'generating', 'running': 3, 'queued': 2,
                                 'tok_s': 42.0, 'prefill_tok_s_mean': 1000.0,
                                 'generated': 12},
                        'requests': [{'time': 1, 'duration_s': 2, 'finish': 'stop',
                                      'output_tokens': 12, 'prompt': 'private'}],
                        'hardware': {'gpu_mem_total': 32 * telemetry.GIB}}
        self.status = {'service': 'strata', 'loaded': True, 'activity': {'in_flight': 1}}
        self.fetch = Mock(side_effect=lambda path: {
            '/health': {'status': 'ok'}, '/metrics': self.metrics,
            '/v1/status': self.status}[path])
        self.collector = telemetry.Collector(self.fetch, lambda: self.processes,
                                            lambda: {'owner_pid': 123, 'owner_created': 100.0},gpu_probe=lambda:{})
        self.host = self.enter(patch.object(telemetry, 'host_hardware', return_value={}))
        self.driver = self.enter(patch.object(telemetry.subprocess, 'run', return_value=SimpleNamespace(
            returncode=0, stdout='0, 100, 32768, 40, 20')))
        self.comfy = self.enter(patch('ai_activity.read_comfy', return_value={'state': 'not_configured'}))
        self.gpu = self.enter(patch('ai_activity.read_gpu_processes', return_value={'available': True, 'processes': []}))

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def test_foreign_listener_never_receives_backend_fetches(self):
        self.listener.net_connections.return_value = []
        socket_probe = self.enter(patch.object(telemetry.socket, 'create_connection'))
        result = self.collector.collect()
        self.fetch.assert_not_called()
        socket_probe.assert_called_once()
        self.assertEqual(result['activity']['state'], 'unavailable')
        self.assertEqual(result['activity']['recent'], [])

    def test_listener_vanishes_during_sample_discards_native_results(self):
        self.listener.net_connections.side_effect = [[self.connection], []]
        result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'unavailable')
        self.assertEqual(result['activity']['recent'], [])
        self.assertIsNone(result['live_speed'])
        self.assertEqual(result['slots'], [])

    def test_wrong_owner_demand_does_not_block_ready_backend(self):
        self.metrics['live'] = {'state': 'idle', 'running': 0, 'queued': 0}
        self.status['activity']['in_flight'] = 0
        self.collector.demand = lambda: {'owner_pid': 999, 'owner_created': 100.0,
                                          'games': ['a game'], 'unknown': True}
        result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'ready')
        self.assertEqual(result['activity']['blockers'], [])

    def test_reused_pid_demand_does_not_block_ready_backend(self):
        self.metrics['live'] = {'state': 'idle', 'running': 0, 'queued': 0}
        self.status['activity']['in_flight'] = 0
        self.collector.demand = lambda: {'owner_pid': 123, 'owner_created': 99.0,
                                          'games': ['a game']}
        result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'ready')
        self.assertEqual(result['activity']['blockers'], [])

    def test_listener_on_other_interface_does_not_authorize_loopback_fetch(self):
        for address in ('::1', '192.168.1.2'):
            with self.subTest(address=address):
                self.connection.laddr.ip = address
                self.fetch.reset_mock()
                with patch.object(telemetry.socket, 'create_connection', side_effect=OSError):
                    result = self.collector.collect()
                self.fetch.assert_not_called()
                self.assertEqual(result['activity']['state'], 'unavailable')

    def test_partial_status_failure_clears_live_phase_and_speed(self):
        self.collector.gpu_probe=lambda:{'gpu_power':400}
        def fetch(path):
            if path == '/v1/status':
                raise OSError('listener unavailable')
            return {'/health': {'status': 'ok'}, '/metrics': self.metrics}[path]
        self.fetch.side_effect = fetch
        result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'unavailable')
        self.assertIsNone(result['live_speed'])
        self.assertIsNone(result['prefill_speed'])
        self.assertEqual(result['power_stats']['samples'],0)
        self.assertEqual(result['slots'], [])

    def test_unloaded_status_overrides_older_generating_metrics(self):
        self.status.update(loaded=False, activity={'in_flight': 0})
        result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'unloaded')
        self.assertIsNone(result['running'])
        self.assertIsNone(result['live_speed'])
        self.assertIsNone(result['prefill_speed'])
        self.assertIsNone(result['generated'])
        self.assertEqual(result['slots'], [])

    def test_parallel_metrics_count_survives_scalar_status_count(self):
        result = self.collector.collect()
        self.assertEqual(result['running'], 3)
        self.assertEqual(result['queued'], 2)
        self.assertEqual(result['activity']['state'], 'generating')
        self.assertNotIn('prompt', result['activity']['recent'][0])

    def test_summary_reads_backend_without_host_or_driver_process_probes(self):
        result = self.collector.summary()
        self.host.assert_not_called()
        self.driver.assert_not_called()
        self.gpu.assert_not_called()
        self.comfy.assert_called_once()
        self.assertEqual(result['activity']['state'], 'generating')

    def test_tuning_and_active_average_work_in_hidden_summary_without_process_probes(self):
        self.collector.gpu_probe=Mock(return_value={'gpu_power':400,'gpu_clock':2800,'gpu_memory_busy':80})
        result=self.collector.summary()
        self.driver.assert_not_called();self.host.assert_not_called();self.gpu.assert_not_called()
        self.assertEqual(result['hardware']['gpu_clock'],2800)
        self.assertEqual(result['power_stats'],{'average_watts':400,'samples':1})
        self.status.update(loaded=False,activity={'in_flight':0})
        self.collector.gpu_probe.return_value={'gpu_power':70}
        result=self.collector.summary()
        self.assertEqual(result['power_stats'],{'average_watts':400,'samples':1})

    def test_foreign_listener_cannot_attribute_power_to_strata(self):
        self.collector.gpu_probe=lambda:{'gpu_power':400}
        self.listener.net_connections.return_value=[]
        with patch.object(telemetry.socket,'create_connection',side_effect=OSError):result=self.collector.summary()
        self.assertIsNone(result['power_stats']['average_watts'])
        self.assertEqual(result['power_stats']['samples'],0)

    def test_missing_live_metrics_do_not_invent_active_power(self):
        self.metrics['live']=None
        self.status['activity']['in_flight']=0
        self.collector.gpu_probe=lambda:{'gpu_power':70}
        result=self.collector.summary()
        self.assertEqual(result['power_stats']['samples'],0)
        self.assertIsNone(result['power_stats']['average_watts'])

    def test_smi_partial_fields_preserve_supported_metrics(self):
        self.metrics['hardware']={}
        self.driver.return_value.stdout='4, 100, 32768, 40, 60, N/A, 17001, 2, 600'
        result=self.collector.collect()
        self.assertNotIn('gpu_clock',result['hardware'])
        self.assertEqual(result['hardware']['gpu_memory_clock'],17001)
        self.assertEqual(result['hardware']['gpu_memory_busy'],2)
        self.assertEqual(result['hardware']['gpu_power_limit'],600)

    def test_compute_process_probe_is_cached_across_detailed_reads(self):
        self.collector.collect()
        self.collector.collect()
        self.gpu.assert_called_once()

    def test_observed_comfy_work_does_not_create_admission_priority(self):
        self.status.update(loaded=False, activity={'in_flight': 0})
        self.comfy.return_value = {'state': 'busy', 'running': 1, 'queued': 0}
        configuration = {'activity': {'comfyui_url': 'http://127.0.0.1:8188'}}
        with patch.object(telemetry, 'CONFIG', configuration):
            result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'unloaded')
        self.assertEqual(result['activity']['blockers'], [])
        self.assertEqual(result['activity']['comfy']['running'], 1)
        self.comfy.assert_called_once_with('http://127.0.0.1:8188')

    def test_exact_comfy_admission_url_applies_existing_priority(self):
        self.status.update(loaded=False, activity={'in_flight': 0})
        self.comfy.return_value = {'state': 'busy', 'running': 1, 'queued': 0}
        configuration = {'activity': {'comfyui_url': 'http://127.0.0.1:8188/'},
                         'on_demand': {'comfyui_url': 'http://127.0.0.1:8188'}}
        with patch.object(telemetry, 'CONFIG', configuration):
            result = self.collector.collect()
        self.assertEqual(result['activity']['state'], 'blocked')
        self.assertIn('ComfyUI generation has configured admission priority', result['activity']['blockers'])


if __name__ == '__main__':
    unittest.main()
