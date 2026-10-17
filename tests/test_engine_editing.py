"""Profile-only edits: backend launch settings remain untouched until next load."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_profiles import ProfileStore, argument, set_argument


class EngineEditingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        self.store = ProfileStore(root/'backend', root/'state')
        self.key = 'strata-128k'
        self.path, self.shared, _ = self.store.paths(self.key)
        self.path.parent.mkdir(parents=True)
        self.data = dict(parallel=1, args=['--max-context', '163840', '--kv', 'int8',
            '--resident-budget-gib', '12.00', '--expert-cache', 'auto', '--ple-io', 'direct',
            '--kv-resident', '32768', '--prefill', '8192', '--spec', '4',
            '--native', 'unchanged.gguf'], env={'KEEP': 'yes'},
            vision={'enabled': True}, reasoning_effort='high')
        self.path.write_text(json.dumps(self.data))
        self.runtime = root/'backend'/'runtime-config.json'
        self.runtime.write_text('{"live":"unchanged"}')
        self.runtime_before = self.runtime.read_bytes()

    def test_roundtrip_next_load_only_preserves_unrelated_settings_and_backup(self):
        values, snapshot = self.store.load(self.key)
        before = self.path.read_bytes()
        values.update(ple_io='ram', expert_cache='12000', resident='9.5', reserve='2048')
        backup = self.store.save(self.key, values, snapshot)
        saved = json.loads(self.path.read_text())
        self.assertEqual(argument(saved['args'], '--ple-io'), 'ram')
        self.assertEqual(argument(saved['args'], '--expert-cache'), '12000')
        self.assertEqual(argument(saved['args'], '--resident-budget-gib'), '9.5')
        self.assertEqual(saved['env'], self.data['env'])
        self.assertEqual(saved['vision'], self.data['vision'])
        self.assertEqual(argument(saved['args'], '--native'), 'unchanged.gguf')
        self.assertEqual((backup/self.path.name).read_bytes(), before)
        self.assertEqual(self.runtime.read_bytes(), self.runtime_before)
        self.assertEqual(self.store.load(self.key)[0]['ple_io'], 'ram')

    def test_blank_removes_override_and_omitted_fields_preserve(self):
        values, snapshot = self.store.load(self.key)
        values.update(ple_io='', expert_cache='', resident='')
        values.pop('kv_resident')
        _, data, _ = self.store.prepare(snapshot, values)
        for flag in ('--ple-io', '--expert-cache', '--resident-budget-gib'):
            self.assertNotIn(flag, data['args'])
        self.assertEqual(argument(data['args'], '--kv-resident'), '32768')

    def test_noop_preserves_argument_formatting(self):
        values, snapshot = self.store.load(self.key)
        _, data, _ = self.store.prepare(snapshot, values)
        self.assertEqual(data['args'], self.data['args'])

    def test_legacy_absent_serving_fields_survive_unrelated_edit(self):
        data = copy.deepcopy(self.data)
        set_argument(data['args'], '--prefill', None)
        set_argument(data['args'], '--spec', None)
        self.path.write_text(json.dumps(data))
        values, snapshot = self.store.load(self.key)
        _, prepared, _ = self.store.prepare(snapshot, dict(values, name='Renamed'))
        self.assertEqual(prepared['args'], data['args'])

    def test_supported_expert_and_placement_values(self):
        values, snapshot = self.store.load(self.key)
        for expert in ('auto', '0', '1', '13370', ''):
            for placement in ('', 'direct', 'mmap', 'ram'):
                with self.subTest(expert=expert, placement=placement):
                    _, data, _ = self.store.prepare(snapshot, dict(values,
                        expert_cache=expert, ple_io=placement, workers='0'))
                    self.assertEqual(argument(data['args'], '--expert-cache'), expert)

    def test_invalid_values_do_not_write(self):
        values, snapshot = self.store.load(self.key)
        before = self.path.read_bytes()
        cases = {'ple_io': ['gpu', 'auto', 'RAM'],
                 'expert_cache': ['-1', '1.5', 'NaN', '2147483648'],
                 'resident': ['0', '-1', 'NaN', 'inf', '1e999', '1025'],
                 'reserve': ['-1', '1.5', 'NaN'],
                 'prefill': ['', '0'], 'spec': ['', '0', '1', '9'],
                 'kv_resident': ['1', '20479', '163841'],
                 'workers': ['-1']}
        for key, invalid in cases.items():
            for value in invalid:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        self.store.save(self.key, dict(values, **{key: value}), snapshot)
                    self.assertEqual(self.path.read_bytes(), before)
                    self.assertEqual(self.runtime.read_bytes(), self.runtime_before)

    def test_kv_streaming_zero_or_minimum(self):
        values, snapshot = self.store.load(self.key)
        for resident in ('0', '20480', '163840', ''):
            self.store.prepare(snapshot, dict(values, kv_resident=resident))

    def test_conflict_preserves_external_edit(self):
        values, snapshot = self.store.load(self.key)
        external = dict(self.data, outside=True)
        self.path.write_text(json.dumps(external))
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.store.save(self.key, dict(values, ple_io='mmap'), snapshot)
        self.assertEqual(json.loads(self.path.read_text()), external)

    def test_reject_ambiguous_or_malformed_imported_arguments(self):
        for tail in (['--ple-io', 'ram'], ['--resident-budget-gib'],
                     ['--expert-cache', '--native']):
            data = copy.deepcopy(self.data)
            data['args'].extend(tail)
            self.path.write_text(json.dumps(data))
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                self.store.load(self.key)

    def test_replacing_override_removes_duplicates(self):
        args = ['--ple-io', 'direct', '--native', 'keep', '--ple-io', 'ram']
        set_argument(args, '--ple-io', 'mmap')
        self.assertEqual(args, ['--ple-io', 'mmap', '--native', 'keep'])
        set_argument(args, '--ple-io', None)
        self.assertEqual(args, ['--native', 'keep'])


if __name__ == '__main__':
    unittest.main()
