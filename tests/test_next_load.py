import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_next_load as next_load
from ai_profiles import argument


class PendingMemoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root/'profiles').mkdir()
        logs = self.root/'profile-logs'
        logs.mkdir()
        self.runtime = logs/'quality-iq3-xxs-example.json'
        self.profile = self.root/'profiles'/'quality-iq3-xxs.json'
        self.active = logs/'active-profile.json'
        args = ['--native', 'keep.gguf', '--max-context', '163840', '--kv', 'int8',
                '--spec', '4', '--prefill', '8192', '--resident-budget-gib', '12',
                '--expert-cache', 'auto', '--vram-reserve-mib', '700']
        self.template = dict(args=args, parallel=1, env={'AUTH': 'untouched'}, host='127.0.0.1',
                             reasoning_effort='high', vision={'gpu': True})
        self.profile.write_text(json.dumps(self.template))
        self.runtime_config = dict(self.template, args=[*args, '--backend-extra', 'retained'],
                                   parallel=2, env={'AUTH': 'original'}, host='0.0.0.0')
        self.runtime.write_text(json.dumps(self.runtime_config))
        self.record = dict(profile='quality-iq3-xxs', config=str(self.runtime), server_pid=100,
                           server_started=123.5)
        self.active.write_text(json.dumps(self.record))
        self.svc = SimpleNamespace(config_path=self.runtime,
            engine=SimpleNamespace(unloaded=True, spawn=('strata.exe', list(self.runtime_config['args']),
                'cwd', 'engine.log', {'KEEP': 'env'}, False, None)),
            loaded=lambda: False, vram_reserve=555, vram_reserve_asked=True)
        self.owner_patch = patch.object(next_load, '_verify_owner')
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)

    def edit(self, **settings):
        from ai_profiles import set_argument
        for flag, value in settings.items():
            set_argument(self.template['args'], flag.replace('_', '-'), value)
        self.profile.write_text(json.dumps(self.template))

    def test_apply_memory_only_to_next_spawn_and_runtime(self):
        from ai_profiles import set_argument
        for flag, value in [('--ple-io', 'ram'), ('--resident-budget-gib', '9'),
                            ('--expert-cache', '0'), ('--vram-reserve-mib', '1500'),
                            ('--kv-resident', '20480'), ('--max-context', '262144')]:
            set_argument(self.template['args'], flag, value)
        self.template.update(parallel=4, host='remote', env={'AUTH': 'changed'})
        self.profile.write_text(json.dumps(self.template))
        template_before = self.profile.read_bytes()
        self.assertTrue(next_load.apply_pending_memory(self.svc, self.root))
        args = self.svc.engine.spawn[1]
        self.assertEqual(argument(args, '--ple-io'), 'ram')
        self.assertEqual(argument(args, '--expert-cache'), '0')
        self.assertEqual(argument(args, '--max-context'), '163840')
        self.assertEqual(argument(args, '--backend-extra'), 'retained')
        runtime = json.loads(self.runtime.read_text())
        self.assertEqual(runtime['parallel'], 2)
        self.assertEqual(runtime['env'], {'AUTH': 'original'})
        self.assertEqual(runtime['host'], '0.0.0.0')
        self.assertEqual(self.profile.read_bytes(), template_before)
        self.assertEqual(self.svc.engine.spawn[4], {'KEEP': 'env'})
        self.assertIsNone(self.svc.vram_reserve)
        self.assertFalse(self.svc.vram_reserve_asked)

    def test_loaded_or_unmanaged_services_are_untouched(self):
        for svc in (SimpleNamespace(), SimpleNamespace(config_path='ignored', loaded=lambda: True,
                    engine=SimpleNamespace(unloaded=True)), SimpleNamespace(config_path='ignored',
                    loaded=lambda: False, engine=SimpleNamespace(unloaded=False))):
            self.assertFalse(next_load.apply_pending_memory(svc, self.root))

    def test_engine_tab_tuning_applies_with_other_profile_fields_retained(self):
        from ai_profiles import set_argument
        expected = {'--prefill': 'auto:16384', '--pool-workers': '0', '--spec': '6',
                    '--spec-min-p': '0.6', '--pcie-frac': '0.4'}
        for flag, value in expected.items():
            set_argument(self.template['args'], flag, value)
        set_argument(self.template['args'], '--max-context', '262144')
        set_argument(self.template['args'], '--kv', 'q4_0')
        self.template['parallel'] = 4
        self.profile.write_text(json.dumps(self.template))
        self.svc.loaded = lambda: True
        original = copy.deepcopy(self.svc.engine.spawn)
        self.assertFalse(next_load.apply_pending_memory(self.svc, self.root))
        self.assertEqual(original, self.svc.engine.spawn)
        self.svc.loaded = lambda: False
        self.assertTrue(next_load.apply_pending_memory(self.svc, self.root))
        for flag, value in expected.items():
            self.assertEqual(argument(self.svc.engine.spawn[1], flag), value)
        self.assertEqual(argument(self.svc.engine.spawn[1], '--max-context'), '163840')
        self.assertEqual(argument(self.svc.engine.spawn[1], '--kv'), 'int8')
        self.assertEqual(argument(self.svc.engine.spawn[1], '--backend-extra'), 'retained')
        self.assertEqual(json.loads(self.runtime.read_text())['parallel'], 2)

    def test_legacy_missing_required_flags_keep_listener_serving_values(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--prefill', None)
        set_argument(self.template['args'], '--spec', None)
        set_argument(self.template['args'], '--ple-io', 'mmap')
        self.profile.write_text(json.dumps(self.template))
        self.assertTrue(next_load.apply_pending_memory(self.svc, self.root))
        self.assertEqual(argument(self.svc.engine.spawn[1], '--prefill'), '8192')
        self.assertEqual(argument(self.svc.engine.spawn[1], '--spec'), '4')
        self.assertEqual(argument(json.loads(self.runtime.read_text())['args'], '--spec'), '4')

    def test_legacy_retained_serving_flags_still_must_be_valid(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--spec', None)
        self.profile.write_text(json.dumps(self.template))
        args = self.svc.engine.spawn[1]
        set_argument(args, '--spec', '0')
        before = copy.deepcopy(self.svc.engine.spawn)
        runtime = self.runtime.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Draft tokens'):
            next_load.apply_pending_memory(self.svc, self.root)
        self.assertEqual(before, self.svc.engine.spawn)
        self.assertEqual(runtime, self.runtime.read_bytes())

    def test_noop_does_not_write_or_clear_hot_reserve(self):
        before = self.runtime.read_bytes()
        self.assertFalse(next_load.apply_pending_memory(self.svc, self.root))
        self.assertEqual(before, self.runtime.read_bytes())
        self.assertEqual(self.svc.vram_reserve, 555)

    def test_cleared_memory_override_is_removed(self):
        self.template['args'].remove('--resident-budget-gib')
        self.template['args'].remove('12')
        self.profile.write_text(json.dumps(self.template))
        self.assertTrue(next_load.apply_pending_memory(self.svc, self.root))
        self.assertNotIn('--resident-budget-gib', self.svc.engine.spawn[1])
        self.assertEqual(self.svc.vram_reserve, 555)

    def test_invalid_template_blocks_before_mutation(self):
        from ai_profiles import set_argument
        for invalid in ('0', 'NaN'):
            set_argument(self.template['args'], '--resident-budget-gib', invalid)
            self.profile.write_text(json.dumps(self.template))
            before = self.runtime.read_bytes()
            spawn = copy.deepcopy(self.svc.engine.spawn)
            with self.assertRaises(ValueError):
                next_load.apply_pending_memory(self.svc, self.root)
            self.assertEqual(spawn, self.svc.engine.spawn)
            self.assertEqual(before, self.runtime.read_bytes())

    def test_saved_context_change_cannot_make_effective_kv_invalid(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--max-context', '262144')
        set_argument(self.template['args'], '--kv-resident', '200000')
        self.profile.write_text(json.dumps(self.template))
        before = self.runtime.read_bytes()
        spawn = copy.deepcopy(self.svc.engine.spawn)
        with self.assertRaisesRegex(ValueError, 'exceeds current context; load the profile from Valet'):
            next_load.apply_pending_memory(self.svc, self.root)
        self.assertEqual(spawn, self.svc.engine.spawn)
        self.assertEqual(before, self.runtime.read_bytes())

    def test_runtime_args_are_validated_against_their_retained_context(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--kv-resident', '100000')
        self.profile.write_text(json.dumps(self.template))
        set_argument(self.runtime_config['args'], '--max-context', '65536')
        self.runtime.write_text(json.dumps(self.runtime_config))
        before = self.runtime.read_bytes()
        spawn = copy.deepcopy(self.svc.engine.spawn)
        with self.assertRaisesRegex(ValueError, 'exceeds current context'):
            next_load.apply_pending_memory(self.svc, self.root)
        self.assertEqual(spawn, self.svc.engine.spawn)
        self.assertEqual(before, self.runtime.read_bytes())

    def test_invalid_ownership_and_profile_paths_block(self):
        for change in (dict(config=str(self.root/'other.json')), dict(profile='../escape')):
            self.active.write_text(json.dumps(dict(self.record, **change)))
            with self.assertRaises(ValueError):
                next_load.apply_pending_memory(self.svc, self.root)
        self.svc.config_path = self.root/'outside.json'
        with self.assertRaises(ValueError):
            next_load.apply_pending_memory(self.svc, self.root)

    def test_atomic_replace_failure_restores_spawn(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--ple-io', 'mmap')
        self.profile.write_text(json.dumps(self.template))
        before = self.runtime.read_bytes()
        spawn = copy.deepcopy(self.svc.engine.spawn)
        with patch.object(Path, 'replace', side_effect=OSError('blocked')):
            with self.assertRaisesRegex(ValueError, 'blocked'):
                next_load.apply_pending_memory(self.svc, self.root)
        self.assertEqual(spawn, self.svc.engine.spawn)
        self.assertEqual(before, self.runtime.read_bytes())
        self.assertFalse(list(self.runtime.parent.glob('*.tmp')))

    def test_model_becomes_loaded_before_commit_is_untouched(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--ple-io', 'ram')
        self.profile.write_text(json.dumps(self.template))
        self.svc.loaded = iter((False, True)).__next__
        before = self.runtime.read_bytes()
        spawn = copy.deepcopy(self.svc.engine.spawn)
        self.assertFalse(next_load.apply_pending_memory(self.svc, self.root))
        self.assertEqual(spawn, self.svc.engine.spawn)
        self.assertEqual(before, self.runtime.read_bytes())
        self.assertFalse(list(self.runtime.parent.glob('*.tmp')))

    def test_profile_race_is_rejected(self):
        from ai_profiles import set_argument
        set_argument(self.template['args'], '--ple-io', 'mmap')
        self.profile.write_text(json.dumps(self.template))
        real_fingerprint = next_load.fingerprint
        calls = 0
        def fingerprint(path):
            nonlocal calls
            # Windows runner TEMP may use an alias normalized by apply_pending_memory.
            if path.resolve() == self.profile.resolve():
                calls += 1
                if calls == 2:
                    return 'changed'
            return real_fingerprint(path)
        spawn = copy.deepcopy(self.svc.engine.spawn)
        before = self.runtime.read_bytes()
        with patch.object(next_load, 'fingerprint', side_effect=fingerprint):
            with self.assertRaisesRegex(ValueError, 'changed'):
                next_load.apply_pending_memory(self.svc, self.root)
        self.assertEqual(spawn, self.svc.engine.spawn)
        self.assertEqual(before, self.runtime.read_bytes())
        self.assertFalse(list(self.runtime.parent.glob('*.tmp')))


class OwnerVerificationTests(unittest.TestCase):
    def test_owner_can_be_verified_venv_parent_shim(self):
        root = Path('D:/test/Strata-Valet').resolve()
        wrapper = str(root/'managed_strata_server.py')
        python = str(root/'Strata'/'.venv'/'Scripts'/'python.exe')
        owner = SimpleNamespace(pid=100, create_time=lambda: 123.5,
            cmdline=lambda: [python, wrapper, '--config', 'run.json'], exe=lambda: python)
        current = SimpleNamespace(pid=200, parents=lambda: [owner], create_time=lambda: 124,
            cmdline=lambda: [python, wrapper, '--config', 'run.json'], exe=lambda: python)
        with patch.object(next_load.psutil, 'Process', return_value=current):
            next_load._verify_owner(dict(server_pid=100, server_started=123.5), root)
            for record in (dict(server_pid=101, server_started=123.5),
                           dict(server_pid=100, server_started=120),
                           dict(server_pid=100, server_started=float('nan'))):
                with self.assertRaises(ValueError):
                    next_load._verify_owner(record, root)
            current.cmdline = lambda: [python, str(root/'unrelated.py')]
            with self.assertRaises(ValueError):
                next_load._verify_owner(dict(server_pid=100, server_started=123.5), root)
            current.cmdline = lambda: [python, wrapper]
            owner.exe = lambda: str(root/'unrelated.exe')
            with self.assertRaises(ValueError):
                next_load._verify_owner(dict(server_pid=100, server_started=123.5), root)


if __name__ == '__main__':
    unittest.main()
