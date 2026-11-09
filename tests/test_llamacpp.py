import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import ai_llamacpp as llama
import ai_ninfer as native
from ai_provider_runtime import catalog, loaded_profile


class LlamaCppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.exe = self.root/'llama-server.exe'
        self.artifact = self.root/'model.gguf'
        self.draft = self.root/'draft.gguf'
        for p in (self.exe, self.artifact, self.draft):
            p.write_bytes(b'fixture; not executable')
        self.entry = dict(engine='llamacpp', label='Local GGUF', exe=str(self.exe), artifact=str(self.artifact),
                          model='gguf-fixture', context=262144, slots=1, auth=True,
                          args=['--spec-type', 'draft-dflash', '--spec-draft-model', str(self.draft),
                                '--spec-draft-n-max', '7', '--n-predict', '32768', '--reasoning-budget', '8192'])
        self.config = {'ninfer_profiles': {'g': self.entry}, 'strata_api_key': 'private-fixture-token'}
        self.patcher = patch.object(native, 'CONFIG', self.config)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def profile(self):
        return native.descriptors(pathlib.Path('python.exe'))['g']

    def test_discovery_and_command_keep_draft_context_and_quality_settings(self):
        profile = self.profile()
        native.verify_assets(profile)
        command = llama.command(profile)
        self.assertEqual(command[command.index('--ctx-size')+1], '262144')
        self.assertEqual(command[command.index('--parallel')+1], '1')
        self.assertIn('--no-kv-unified', command)
        self.assertEqual(command[-len(self.entry['args']):], self.entry['args'])
        self.assertNotIn('private-fixture-token', ' '.join(command))
        self.assertTrue(llama.matching_command(command+['--api-key-file', 'auth-file'], profile))
        self.assertFalse(llama.matching_command(command+['--ctx-size', '4096'], profile))
        two = {**profile, 'slots': 2}
        self.assertEqual(llama.command(two)[llama.command(two).index('--ctx-size')+1], '524288')

    def test_protected_flag_aliases_and_alternate_sources_are_rejected(self):
        for flag in llama.RESERVED:
            for arg in (flag, flag+'=other'):
                self.entry['args'] = [arg]
                with self.subTest(flag=arg), self.assertRaises(ValueError):
                    self.profile()
        self.entry['args'] = ['--n-predict', 5]
        with self.assertRaises(ValueError):
            self.profile()

    def test_missing_draft_fails_preflight_before_any_process_start(self):
        self.draft.unlink()
        with patch.object(native.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'draft model'):
                native.verify_assets(self.profile())
            start.assert_not_called()
        self.entry['args'] = ['--spec-draft-model=relative.gguf']
        with self.assertRaises(ValueError):
            native.verify_assets(self.profile())
        self.entry['args'] = ['--spec-type', 'draft-dflash']
        with self.assertRaisesRegex(ValueError, 'draft model'):
            native.verify_assets(self.profile())
        self.entry['args'] = ['--chat-template-file', str(self.root/'missing.jinja')]
        with self.assertRaisesRegex(ValueError, 'chat template'):
            native.verify_assets(self.profile())

    def test_model_and_executable_types_are_checked(self):
        self.entry['artifact'] = str(self.root/'model.ninfer')
        with self.assertRaisesRegex(ValueError, 'GGUF'):
            self.profile()
        self.entry['artifact'] = str(self.artifact)
        self.entry['exe'] = str(self.root/'foreign.exe')
        with self.assertRaises(ValueError):
            self.profile()

    def test_owned_process_requires_exact_executable_model_position_and_creation_time(self):
        owner = self.root/'owner.json'
        record = dict(pid=123, created=456, exe=str(self.exe), artifact=str(self.artifact), profile='g')
        owner.write_text(json.dumps(record))
        process = Mock()
        process.create_time.return_value = 456
        process.exe.return_value = str(self.exe)
        process.cmdline.return_value = llama.command(self.profile())
        with patch.object(native, 'OWNER', owner), patch.object(native.psutil, 'Process', return_value=process):
            self.assertEqual(native.owned_process(), (process, record))
            process.cmdline.return_value = [str(self.exe), '--model', str(self.root/'other.gguf')]
            self.assertIsNone(native.owned_process())
            process.cmdline.return_value = [str(self.exe), str(self.artifact)]
            self.assertIsNone(native.owned_process())
            process.create_time.return_value = 457
            self.assertIsNone(native.owned_process())

    def test_loaded_profile_requires_matching_native_arguments_and_live_capacity(self):
        profile = self.profile()
        process = Mock()
        process.is_running.return_value = True
        process.cmdline.return_value = llama.command(profile)
        rows = lambda: [(process, 'ninfer-server')]
        listener = lambda processes: process if processes else None
        owner = lambda: (process, dict(profile='g', artifact=str(self.artifact), exe=str(self.exe)))
        props = dict(default_generation_settings=dict(n_ctx=262144), total_slots=1, is_sleeping=False)
        fetch = Mock(side_effect=lambda path: {'/health': {'status':'ok'}, '/props': props,
                                              '/v1/models': {'data':[{'id':'gguf-fixture'}]}}[path])
        def loaded():
            return loaded_profile({'g':profile}, rows, listener, owner, fetch, self.root)
        self.assertEqual(loaded(), 'g')
        props['total_slots'] = 2
        self.assertIsNone(loaded())
        props['total_slots'] = 1
        props['is_sleeping'] = True
        self.assertIsNone(loaded())
        props['is_sleeping'] = False
        process.cmdline.return_value = llama.command({**profile,'context':131072})
        self.assertIsNone(loaded())

    def test_catalog_describes_fixed_slot_pool_and_text_only_input(self):
        profile = self.profile()
        info = catalog({'g': profile}, Mock())['g']
        self.assertFalse(info['kv_shared'])
        self.assertEqual(info['kv_cache_tokens_per_slot'], 262144)
        self.assertEqual(info['kv_cache_tokens'], 262144)
        self.assertEqual(info['default_max_output_tokens'], 32768)
        self.assertEqual(info['max_output_tokens'], 262144)
        self.assertEqual(info['input_modalities'], ['text'])

    def test_telemetry_discards_prompts_and_does_not_invent_rates_or_queue_counts(self):
        props = dict(default_generation_settings=dict(n_ctx=262144), total_slots=1)
        slot = dict(id=0, is_processing=True, n_prompt_tokens=40000, n_prompt_tokens_processed=1000,
                    n_prompt_tokens_cache=39000, next_token=[{'n_decoded':12}], prompt='PRIVATE_PROMPT',
                    params={'key':'PRIVATE_KEY'}, generated='PRIVATE_OUTPUT')
        metrics, status = llama.telemetry(props, [slot])
        self.assertEqual(metrics['live']['state'], 'generating')
        self.assertEqual(metrics['live']['running'], 1)
        self.assertIsNone(metrics['live']['queued'])
        self.assertNotIn('tok_s', metrics['live'])
        self.assertNotIn('PRIVATE', json.dumps([metrics,status]))
        slot.update(n_prompt_tokens_processed=1000, n_prompt_tokens_cache=0, next_token=[])
        self.assertEqual(llama.telemetry(props,[slot])[0]['live']['state'], 'reading')
        slot['is_processing'] = False
        self.assertEqual(llama.telemetry(props,[slot])[0]['live']['state'], 'idle')
        with self.assertRaises(ValueError):
            llama.telemetry({}, [])

    def test_llama_auth_file_is_not_a_toml_line_and_is_removed_after_exit(self):
        # Run the real native wrapper with a mocked process and guard; no executable starts.
        guard = Mock()
        guard.load_reason.return_value = None
        child = Mock()
        child.pid = 123
        child.poll.return_value = 0
        child.returncode = 0
        process = Mock()
        process.create_time.return_value = 456
        seen = {}
        def start(command, **kwargs):
            self.assertNotIn('private-fixture-token', ' '.join(command))
            path = pathlib.Path(command[command.index('--api-key-file')+1])
            seen['path'] = path
            self.assertEqual(path.read_text(), 'private-fixture-token\n')
            return child
        with patch.dict(native.os.environ, VALET_NINFER_STARTED='1'), patch.object(native,'STATE_DIR',self.root), \
             patch.object(native,'OWNER',self.root/'owner.json'), patch.object(native,'owned_process',return_value=None), \
             patch('ai_demand.Guard',return_value=guard), patch.object(native.subprocess,'Popen',side_effect=start), \
             patch.object(native.psutil,'Process',return_value=process):
            self.assertEqual(native.run('g'), 0)
        self.assertFalse(seen['path'].exists())


if __name__ == '__main__':
    unittest.main()
