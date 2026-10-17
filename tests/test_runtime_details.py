import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_runtime_details import RuntimeDetailsReader


class RuntimeDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.logs = self.root / 'profile-logs'
        self.logs.mkdir()
        self.process = Mock(pid=42)
        self.process.create_time.return_value = 100
        self.process.is_running.return_value = True
        self.log = self.logs / 'engine.log'
        self.log.write_text('startup facts')
        self.config = self.logs / 'run.json'
        self.config.write_text(json.dumps({'log': str(self.log), 'args': ['--kv', 'int8']}))
        self.active = self.logs / 'active-profile.json'
        self.active.write_text(json.dumps({'server_pid': 42, 'server_started': 100, 'config': str(self.config)}))
        self.reader = RuntimeDetailsReader(self.root)

    def read(self):
        return self.reader.read([(self.process, 'strata-server')], self.process)

    def test_reads_only_current_managed_runtime(self):
        config, log = self.read()
        self.assertEqual(config['args'], ['--kv', 'int8'])
        self.assertEqual(log, 'startup facts')
        self.process.create_time.return_value = 101
        self.assertEqual(self.read(), (None, ''))

    def test_untrusted_path_and_reused_identity_clear_cache(self):
        self.read()
        self.config.write_text(json.dumps({'log': str(self.root / 'outside.log')}))
        self.assertEqual(self.read(), (None, ''))
        self.assertIsNone(self.reader.key)

    def test_log_read_is_bounded_and_latest_tail_is_used(self):
        self.log.write_text('old data\n' * 50000 + 'latest startup')
        _, text = self.read()
        self.assertLessEqual(len(text.encode()), 192 * 1024)
        self.assertTrue(text.endswith('latest startup'))

    def test_changed_runtime_and_log_invalidate_cache(self):
        self.read()
        self.log.write_text('new startup facts')
        self.assertEqual(self.read()[1], 'new startup facts')
        self.process.is_running.return_value = False
        self.assertEqual(self.read(), (None, ''))

    def test_another_live_server_cannot_supply_listener_configuration(self):
        listener = Mock(pid=99)
        listener.create_time.return_value = 200
        listener.is_running.return_value = True
        self.process.children.return_value = []
        self.assertEqual(self.reader.read([(self.process, 'strata-server')], listener), (None, ''))
        self.process.children.return_value = [listener]
        config, text = self.reader.read([(self.process, 'strata-server')], listener)
        self.assertEqual(config['args'], ['--kv', 'int8'])
        self.assertEqual(text, 'startup facts')

    def test_pending_engine_settings_compare_saved_and_active_values(self):
        record = json.loads(self.active.read_text())
        record['profile'] = 'quality-iq3-xxs'
        self.active.write_text(json.dumps(record))
        profiles = self.root / 'profiles'
        profiles.mkdir()
        saved = profiles / 'quality-iq3-xxs.json'
        saved.write_text(json.dumps({'args': ['--kv', 'int8']}))
        config, _ = self.read()
        self.assertFalse(self.reader.pending_memory(config))
        saved.write_text(json.dumps({'args': ['--kv', 'int8', '--ple-io', 'ram', '--prefill', 'auto']}))
        self.assertTrue(self.reader.pending_memory(config))
        self.assertEqual(config['args'], ['--kv', 'int8'])

    def test_missing_saved_profile_is_not_reported_as_applied(self):
        record = json.loads(self.active.read_text())
        record['profile'] = 'quality-iq3-xxs'
        self.active.write_text(json.dumps(record))
        config, _ = self.read()
        self.assertIsNone(self.reader.pending_memory(config))
