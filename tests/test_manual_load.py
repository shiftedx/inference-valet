"""Manual warm-up, authenticated control, and startup observation regressions."""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('manual_load_launcher', ROOT/'ai-launcher.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class ManualLoadTests(unittest.TestCase):
    def run_start(self, automatic=False, load_error=None, cancel=False):
        with tempfile.TemporaryDirectory() as directory:
            logs = pathlib.Path(directory)
            cfg = dict(label='Fixture', model='fixture', engine='strata', context=1024,
                       slots=1, command=['python', 'launcher.py'], cwd=directory)
            loaded = False
            calls = []

            def fetch(path):
                calls.append(path)
                if path == '/v1/models':
                    return {'data': [{'id': 'fixture'}]}
                return dict(loaded=loaded, context={'native': 1024}, concurrency={'serving': 1})

            def load():
                nonlocal loaded
                calls.append('/load')
                if cancel:
                    (logs/'last-stop.txt').write_text(str(time.monotonic_ns()+1))
                if load_error:
                    raise load_error
                loaded = True

            sock = MagicMock()
            sock.__enter__.return_value.connect_ex.return_value = 1
            with (patch.object(a, 'LOGS', logs), patch.object(a, 'CONFIG',
                      dict(on_demand={'enabled': True}, strata_api_key='fixture-secret')),
                  patch.object(a, 'validate_profile', return_value=cfg),
                  patch.object(a, 'control_lock', side_effect=contextlib.nullcontext),
                  patch.object(a, 'servers', return_value=[]),
                  patch.object(a.socket, 'socket', return_value=sock),
                  patch.object(a.subprocess, 'Popen') as launch,
                  patch.object(a, 'fetch', side_effect=fetch),
                  patch.object(a, 'load_model', side_effect=load) as warm,
                  patch.object(a, 'stop_all'), patch.object(a, 'IDLE_SETTINGS')):
                result = a.start_profile('fixture', automatic_guard=(lambda: True) if automatic else None)
                self.assertEqual(launch.call_args.kwargs['env']['STRATA_API_KEY'], 'fixture-secret')
                self.assertNotIn('fixture-secret', launch.call_args.args[0])
                if automatic:
                    warm.assert_not_called()
                else:
                    warm.assert_called_once()
                return result, calls

    def test_manual_start_loads_before_reporting_ready(self):
        result, calls = self.run_start()
        self.assertFalse(result.get('unloaded', False))
        self.assertLess(calls.index('/load'), len(calls)-1-calls[::-1].index('/v1/status'))

    def test_automatic_recovery_keeps_listener_lazy(self):
        result, calls = self.run_start(automatic=True)
        self.assertTrue(result['unloaded'])
        self.assertNotIn('/load', calls)

    def test_admission_failure_is_not_retried_or_reported_ready(self):
        with self.assertRaisesRegex(RuntimeError, 'GPU workload busy'):
            self.run_start(load_error=RuntimeError('GPU workload busy'))

    def test_stop_during_load_cancels_success_and_connection_failure(self):
        for error in (None, RuntimeError('connection closed')):
            with self.subTest(error=error):
                result, _ = self.run_start(cancel=True, load_error=error)
                self.assertTrue(result['cancelled'])

    def test_load_requires_verified_listener_before_sending_credentials(self):
        with (patch.object(a, 'servers', return_value=[]),
              patch.object(a.urllib.request, 'urlopen') as send):
            with self.assertRaisesRegex(RuntimeError, 'ownership'):
                a.load_model()
            send.assert_not_called()

    def test_authenticated_post_and_keyless_compatibility(self):
        for key in ('fixture-secret', ''):
            with self.subTest(key=bool(key)):
                listener = Mock()
                listener.is_running.return_value = True
                with (patch.object(a, 'strata_listener', return_value=listener),
                      patch.object(a, 'servers', return_value=[]),
                      patch.object(a, 'strata_api_key', return_value=key),
                      patch.object(a.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"loaded"}')) as send):
                    a.load_model()
                    request = send.call_args.args[0]
                    self.assertEqual(request.get_method(), 'POST')
                    self.assertEqual(request.full_url, 'http://127.0.0.1:8080/load')
                    self.assertEqual(request.data, b'{}')
                    self.assertEqual(request.get_header('Origin'), 'http://127.0.0.1:8080')
                    self.assertEqual(request.get_header('Authorization'), 'Bearer '+key if key else None)
                    self.assertGreater(send.call_args.kwargs['timeout'], 300)

    def test_backend_failure_message_survives_http_error(self):
        error = a.urllib.error.HTTPError('http://127.0.0.1:8080/load', 503, 'Busy', {},
                                        io.BytesIO(b'{"error":{"message":"GPU workload busy"}}'))
        with (patch.object(a, 'strata_listener', return_value=Mock()),
              patch.object(a, 'servers', return_value=[]),
              patch.object(a.urllib.request, 'urlopen', side_effect=error)):
            with self.assertRaisesRegex(RuntimeError, 'GPU workload busy'):
                a.load_model()

    def test_listener_replacement_does_not_confirm_success(self):
        with (patch.object(a, 'strata_listener', side_effect=[Mock(), None]),
              patch.object(a, 'servers', return_value=[]),
              patch.object(a.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"loaded"}'))):
            with self.assertRaisesRegex(RuntimeError, 'listener changed'):
                a.load_model()


class StartupDisplayTests(unittest.TestCase):
    def test_completed_load_rejects_inflight_startup_sample(self):
        from profile_fixtures import configure_launcher
        configure_launcher(a)
        app = a.LauncherUI(enable_tray=False, observe=False)
        try:
            app.active.add('start')
            epoch = app.epoch
            stale = dict(sampled=time.monotonic(), activity=dict(
                state='unavailable', title='Unverified backend', detail='Old listener'))
            app.latest_performance = stale
            app.events.put(('done', ('start', 'strata-128k', {})))
            app.events.put(('snapshot', (epoch, (None, 'API unavailable'), stale)))
            app.poll()
            self.assertEqual(app.hero_state.get(), 'Ready')
            self.assertEqual(app.latest_performance, {})
            # A fresh ownership failure must still be visible; only startup samples expire.
            app.events.put(('snapshot', (app.epoch, (None, 'No model loaded.'), stale)))
            app.poll()
            self.assertEqual(app.hero_state.get(), 'Unverified backend')
        finally:
            app.quit()


if __name__ == '__main__':
    unittest.main()
