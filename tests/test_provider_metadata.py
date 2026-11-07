import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock
from ai_provider import model_info
from ai_provider_runtime import catalog, loaded_profile, active_profile

class CatalogMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.store = Mock()
        self.store.paths.side_effect = lambda key: (
            self.root / (key + '.json'), self.root / (key + '.shared.json'), self.root / 'names.json')
        self.strata = dict(label='Four agents', engine='strata', model='flash',
                           context=131072, slots=4, profile='four')
        self.native = dict(label='Shared', engine='infernix', model='dense',
                           context=131072, slots=6,
                           args=['--kv-capacity', '262144', '--default-max-tokens', '32768'])

    def test_native_pool_is_not_multiplied_by_concurrency(self):
        item = catalog({'n': self.native}, self.store)['n']
        info = model_info('n', item, loaded=True)
        self.assertEqual(info['kv_cache_tokens'], 262144)
        self.assertTrue(info['kv_shared'])
        self.assertIsNone(info['kv_cache_tokens_per_slot'])
        self.assertEqual(info['parallel_slots'], 6)
        self.assertEqual(info['context_length'], 131072)
        self.assertEqual(info['default_max_output_tokens'], 32768)
        self.assertEqual(info['max_output_tokens'], 131072)
        self.assertTrue(info['output_tokens_share_context'])
        self.assertTrue(info['loaded'])
        self.assertEqual(self.native['args'][1], '262144')

    def test_strata_independent_slots_and_output_defaults(self):
        path, shared, _ = self.store.paths('s')
        path.write_text(json.dumps({'max_tokens': 65536}))
        shared.write_text(json.dumps({'max_tokens': 32768}))
        item = catalog({'s': self.strata}, self.store)['s']
        self.assertFalse(item['kv_shared'])
        self.assertEqual(item['kv_cache_tokens'], 4 * 131072)
        self.assertEqual(item['kv_cache_tokens_per_slot'], 131072)
        self.assertEqual(item['default_max_output_tokens'], 32768)
        self.assertEqual(item['max_output_tokens'], 131072 - 8)
        self.assertEqual(item['context_reserved_tokens'], 8)
        shared.unlink()
        self.assertEqual(catalog({'s': self.strata}, self.store)['s']['default_max_output_tokens'], 65536)

    def test_unknown_auto_and_ambiguous_overrides_are_null(self):
        for args in ([], ['--kv-capacity', 'auto'],
                     ['--kv-capacity', '123', '--kv-capacity=456']):
            with self.subTest(args=args):
                item = catalog({'n': {**self.native, 'args': args}}, self.store)['n']
                self.assertIsNone(item['kv_cache_tokens'])
                self.assertIsNone(item['default_max_output_tokens'])
        item = catalog({'n': {**self.native, 'args': [
            '--kv-capacity=229376', '--default-max-tokens=8192']}}, self.store)['n']
        self.assertEqual(item['kv_cache_tokens'], 229376)
        self.assertEqual(item['default_max_output_tokens'], 8192)

    def test_bad_shared_settings_do_not_fabricate_an_output_default(self):
        path, shared, _ = self.store.paths('s')
        path.write_text('{}')
        shared.write_text('{broken')
        item = catalog({'s': self.strata}, self.store)['s']
        self.assertIsNone(item['default_max_output_tokens'])
        self.assertEqual(item['kv_cache_tokens'], 524288)

class LoadedProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.process = Mock()
        self.process.pid = 123
        self.process.create_time.return_value = 456
        self.process.is_running.return_value = True
        self.listener = lambda rows: self.process if rows else None
        self.processes = lambda: [(self.process, 'ninfer-server')]
        self.profile = dict(engine='infernix', model='dense', context=131072, slots=6,
                            exe='engine.exe', artifact='model.ninfer', args=['--kv-capacity', '262144'])
        self.record = dict(profile='n', exe='engine.exe', artifact='model.ninfer')
        self.owner = lambda: (self.process, self.record)
        self.process.cmdline.return_value = ['engine.exe', 'model.ninfer', '--model-id', 'dense',
                                             '--kv-capacity', '262144', '--config', 'auth-only.toml']
        self.status = {'loaded': True, 'model': 'flash', 'context': {'native': 131072},
                       'concurrency': {'serving': 4}}
        self.native_metrics = {'schema': 'infernix.telemetry/1', 'engine': {
            'model': 'dense', 'max_context': 131072, 'max_concurrency': 6}}
        self.health = {'status': 'ok'}
        self.fetch = Mock(side_effect=lambda path: {
            '/health': self.health, '/metrics?format=json': self.native_metrics,
            '/v1/status': self.status}[path])

    def loaded(self, profiles=None, owner=None):
        return loaded_profile(profiles or {'n': self.profile}, self.processes,
                              self.listener, owner or self.owner, self.fetch, self.root)

    def test_native_requires_matching_resident_launch(self):
        self.assertEqual(self.loaded(), 'n')
        self.health['status'] = 'loading'
        self.assertIsNone(self.loaded())
        self.health['status'] = 'ok'
        self.native_metrics['engine']['max_concurrency'] = 8
        self.assertIsNone(self.loaded())

    def test_pending_launch_changes_and_dead_process_are_not_loaded(self):
        self.profile['args'] = ['--kv-capacity', '229376']
        self.assertIsNone(self.loaded())
        self.profile['args'] = ['--kv-capacity', '262144']
        self.process.is_running.return_value = False
        self.assertIsNone(self.loaded())

    def test_lazy_strata_listener_is_active_but_not_loaded(self):
        profile = dict(engine='strata', model='flash', context=131072, slots=4, profile='four')
        profiles = {'s': profile}
        self.status['loaded'] = False
        no_native = lambda: None
        self.assertEqual(active_profile(profiles, self.processes, self.listener,
                                        no_native, self.fetch, self.root), 's')
        self.assertIsNone(self.loaded(profiles, no_native))
        self.status['loaded'] = True
        self.assertEqual(self.loaded(profiles, no_native), 's')

    def test_unavailable_health_does_not_report_loaded(self):
        self.fetch.side_effect = OSError('unavailable')
        self.assertIsNone(self.loaded())


    def test_malformed_health_or_metrics_fail_closed(self):
        self.fetch.side_effect = lambda path: None
        self.assertIsNone(self.loaded())
        self.fetch.side_effect = lambda path: []
        self.assertIsNone(self.loaded())

    def test_ninfer_resident_metadata_checks_stats_and_model(self):
        self.profile['engine'] = 'ninfer'
        stats = {'object': 'ninfer.stats', 'capacity': {'max_context': 131072, 'max_concurrency': 6}}
        models = {'data': [{'id': 'dense'}]}
        self.fetch.side_effect = lambda path: {'/stats': stats, '/v1/models': models, '/health': self.health}[path]
        self.assertEqual(self.loaded(), 'n')
        models['data'] = [{'id': 'different'}]
        self.assertIsNone(self.loaded())
        models['data'] = [{'id': 'dense'}]
        stats['capacity']['max_context'] = 32768
        self.assertIsNone(self.loaded())
