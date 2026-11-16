import sys
import unittest
from unittest.mock import patch

from ai_capabilities import capabilities, validator_available, _validator
from ai_provider import model_info
from ai_provider_runtime import catalog


class CapabilitiesTests(unittest.TestCase):
    def profile(self, engine):
        return dict(engine=engine, label='Fixture', model='fixture', context=65536, slots=1, args=[])

    def test_grammar_backends_advertise_constraints_and_schema_subset(self):
        for engine in ('infernix', 'llamacpp'):
            with self.subTest(engine=engine):
                info=model_info('fixture',catalog({'fixture':self.profile(engine)},None)['fixture'])
                self.assertTrue(info['supports_structured_outputs'])
                self.assertTrue(info['supports_json_schema'])
                detail=info['structured_output']
                self.assertTrue(detail['constrained_decoding'])
                self.assertEqual(detail['method'],'grammar_constrained')
                self.assertEqual(detail['schema_scope'],'backend_supported_subset')
                self.assertEqual(detail['endpoints']['/v1/responses'],'text.format')

    def test_prompt_validation_does_not_claim_constrained_decoding(self):
        for engine in ('strata','dsv41','maya'):
            for installed in (True,False,None):
                with self.subTest(engine=engine,installed=installed), patch('ai_capabilities.validator_available',return_value=installed):
                    info=capabilities(self.profile(engine))
                    self.assertTrue(info['supports_json_mode'])
                    self.assertIs(info['supports_json_schema'],installed)
                    self.assertIs(info['supports_structured_outputs'],installed)
                    self.assertFalse(info['structured_output']['constrained_decoding'])
                    self.assertTrue(info['structured_output']['stream_buffered'])
                    self.assertFalse(info['tool_calling']['strict_schema'])

    def test_final_answer_and_tool_constraints_are_distinct(self):
        info=capabilities(self.profile('infernix'))
        self.assertTrue(info['tool_calling']['strict_schema'])
        self.assertFalse(info['structured_output']['anthropic_output_format'])

    def test_unknown_backend_has_no_invented_guarantees(self):
        info=capabilities(self.profile('custom'))
        self.assertFalse(info['supports_json_mode'])
        self.assertIsNone(info['supports_structured_outputs'])
        self.assertEqual(info['structured_output']['formats'],[])
        self.assertIsNone(info['tool_calling']['strict_schema'])

    def test_validator_probe_uses_serving_interpreter_and_dependency_path(self):
        with patch('ai_capabilities._validator',return_value=True) as probe:
            profile=self.profile('dsv41')
            profile['dsv41']={'server_python':'C:/fixture/python.exe','env':{'PYTHONPATH':'C:/fixture/deps'}}
            self.assertTrue(validator_available(profile))
            self.assertEqual(probe.call_args.args[:2],('C:/fixture/python.exe','C:/fixture/deps'))
            profile=self.profile('strata');profile['command']=['C:/strata/python.exe','launch.py']
            self.assertTrue(validator_available(profile))
            self.assertEqual(probe.call_args.args[:2],('C:/strata/python.exe',''))

    def test_probe_failure_or_missing_interpreter_is_unknown(self):
        self.assertIsNone(_validator('C:/nonexistent-valet-python.exe','',0))
        with patch('ai_capabilities.pathlib.Path.is_file',return_value=True), patch('ai_capabilities.subprocess.run',side_effect=OSError):
            self.assertIsNone(_validator('C:/another-python.exe','',0))


if __name__=='__main__':unittest.main()
