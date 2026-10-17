import unittest

from ai_engine_details import build_engine_details, parse_startup_facts


START = '''strata generate: memory guard: limit 47.7 GiB
strata generate: PLE direct read probe: 183427 rows/s (fine)
strata generate: PLE on, table 320001536 rows of D:\\private\\model.gguf
strata generate: profile D:\\private\\expert-profile.bin: 24576 ranked pairs, built for 24576 slots
FileExpertSource: RAM budget 12.00 GiB: 7326 of the 18.04 GiB of experts the GPU cache does not hold
FileExpertSource: mapped pinned cache complement ready: resident 12.00 GiB, pinned 12.00 GiB in 4 s
strata generate: KV streaming: 32768 of 163840 cells per QSA layer in VRAM, the K/V in 1.93 GiB of pinned RAM
strata generate: native pack: x experts, token embedding IQ3_S in mapped host memory (260 MiB, 0.2 s)
'''


def rows(groups):
    return {row['label']: row for group in groups for row in group['rows']}


class EngineDetailsTests(unittest.TestCase):
    def test_reports_actual_over_configured_and_labels_sources(self):
        data = rows(build_engine_details({'engine': {'spec': 6, 'expert_slots': 13501,
                                                      'expert_cache_mib': 22449}},
                                        {'loaded': True},
                                        {'args': ['--spec', '4', '--resident-budget-gib', '12'],
                                         'reasoning_effort': 'high'}, parse_startup_facts(START)))
        self.assertEqual(data['Verify window']['value'], '6 tokens')
        self.assertEqual(data['Verify window']['source'], 'Reported')
        self.assertEqual(data['RAM experts']['value'], '7,326 experts')
        self.assertEqual(data['RAM experts']['source'], 'Startup log')
        self.assertEqual(data['GPU expert slots']['value'], '13,501 slots')
        self.assertEqual(data['Expert RAM budget']['source'], 'Active configuration')
        self.assertEqual(data['Engram / PLE placement']['value'], 'Disk / direct file reads')

    def test_unloaded_cannot_claim_resident_memory(self):
        data = rows(build_engine_details({'engine': {'expert_slots': 13501}},
                                        {'loaded': False}, startup_facts=parse_startup_facts(START)))
        self.assertEqual(data['Model residency']['value'], 'Model unloaded')
        self.assertEqual(data['GPU expert slots']['source'], 'Last start')
        self.assertEqual(data['RAM experts']['source'], 'Last start')

    def test_unknown_residency_also_marks_cached_memory(self):
        data = rows(build_engine_details({'engine': {'expert_slots': 100}}, {}))
        self.assertEqual(data['GPU expert slots']['source'], 'Last start')
        self.assertEqual(data['Model residency']['source'], 'Not reported')

    def test_missing_telemetry_does_not_invent_placement_or_defaults(self):
        data = rows(build_engine_details({}, {'loaded': True},
                                        {'args': ['--ple-gguf', 'D:\\private\\model.gguf']}))
        self.assertEqual(data['Engram / PLE placement']['value'], 'Not reported')
        self.assertEqual(data['Engram / PLE source']['value'], 'model.gguf')
        self.assertEqual(data['Engram / PLE source']['source'], 'Active configuration')
        self.assertEqual(data['RAM experts']['value'], 'Not reported')

    def test_latest_start_wipes_old_memory_and_ple(self):
        later = '\n[strata] 2026-10-17 engine started: new-model\nstrata generate: memory guard: limit 47.7 GiB\n'
        self.assertEqual(parse_startup_facts(START + later), {})
        self.assertEqual(parse_startup_facts('FileExpertSource: RAM budget 12.00 GiB: 7326 of the 18.04 GiB'), {})

    def test_incomplete_ram_allocation_is_not_residency(self):
        facts = parse_startup_facts(START.replace('mapped pinned cache complement ready:', 'allocating:'))
        self.assertNotIn('ram_experts', facts)

    def test_partial_pinning_keeps_resident_and_pinned_memory_distinct(self):
        facts = parse_startup_facts(START.replace('resident 12.00 GiB, pinned 12.00 GiB',
                                                'resident 12.00 GiB, pinned 8.50 GiB'))
        self.assertEqual(facts['ram_expert_gib'], 12.0)
        self.assertEqual(facts['ram_expert_pinned_gib'], 8.5)
        data = rows(build_engine_details({}, {'loaded': True}, startup_facts=facts))
        self.assertEqual(data['Resident expert RAM']['value'], '12.00 GiB')
        self.assertEqual(data['Pinned expert RAM']['value'], '8.50 GiB')

    def test_ple_fallback_overrides_direct_probe(self):
        facts = parse_startup_facts(START + '\nstrata generate: using --ple-io mmap instead\n')
        self.assertEqual(facts['ple_location'], 'Mapped file / OS page cache')
        facts = parse_startup_facts(START + '\nstrata generate: PLE table locked in RAM (--ple-io ram) in 2.0 s\n')
        self.assertEqual(facts['ple_location'], 'Locked host RAM')

    def test_paths_credentials_and_invalid_numbers_are_not_exposed(self):
        result = build_engine_details({'engine': {'expert_slots': float('nan'), 'expert_cache_mib': -1}},
                                      {'loaded': True}, {'token': 'do-not-display', 'env': {'SECRET': 'secret'}},
                                      parse_startup_facts(START))
        rendered = str(result)
        self.assertNotIn('private', rendered)
        self.assertNotIn('do-not-display', rendered)
        self.assertNotIn('SECRET', rendered)
        self.assertEqual(rows(result)['GPU expert slots']['value'], 'Not reported')

    def test_zero_settings_are_preserved(self):
        data = rows(build_engine_details({'engine': {'conversation_cache_mib': 0, 'lookup': 0}},
                                        {'loaded': True, 'vision': {'enabled': False}},
                                        {'reasoning_budget_tokens': 0, 'fit_max_tokens': False}))
        self.assertEqual(data['Conversation cache budget']['value'], '0.0 GiB')
        self.assertEqual(data['Lookup draft limit']['value'], '0 tokens')
        self.assertEqual(data['Reasoning budget']['value'], '0 tokens')
        self.assertEqual(data['Fit output to context']['value'], 'Off')

    def test_current_shared_defaults_override_launch_configuration(self):
        data = rows(build_engine_details({}, {'loaded': True},
                                        {'reasoning_effort': 'low', 'reasoning_budget_tokens': 123,
                                         'max_tokens': 100, 'temperature': 1.0}, None,
                                        {'shared': True, 'defaults': {'max_tokens': 73728,
                                         'reasoning_budget_tokens': 32768, 'reasoning_effort': 'high',
                                         'temperature': 0.6, 'top_k': 20}}))
        self.assertEqual(data['Max output tokens']['value'], '73,728 tokens')
        self.assertEqual(data['Max output tokens']['source'], 'Shared defaults')
        self.assertEqual(data['Reasoning effort']['value'], 'high')
        self.assertEqual(data['Reasoning budget']['value'], '32,768 tokens')
        self.assertEqual(data['Temperature']['value'], '0.6')
        self.assertEqual(data['Top-k']['source'], 'Shared defaults')

    def test_shared_allowlist_never_exposes_request_content(self):
        result = build_engine_details({}, {}, None, None,
                                      {'shared': True, 'defaults': {'prompt': 'private-prompt',
                                       'messages': [{'content': 'private-message'}], 'api_key': 'private-key',
                                       'top_p': 0.95, 'max_tokens': 0}})
        rendered = str(result)
        for private in ('private-prompt', 'private-message', 'private-key', 'api_key'):
            self.assertNotIn(private, rendered)
        self.assertEqual(rows(result)['Top-p']['value'], '0.95')
        self.assertEqual(rows(result)['Profile expert slots']['value'], 'Not reported')
        self.assertNotIn('Model expert slots', rows(result))

    def test_absent_shared_defaults_fall_back_and_optional_sampling_stays_absent(self):
        data = rows(build_engine_details({'engine': {'top_p': 0.8}}, {},
                                        {'reasoning_effort': 'high'}, None, {'shared': False, 'defaults': {}}))
        self.assertEqual(data['Reasoning effort']['source'], 'Active configuration')
        self.assertEqual(data['Top-p']['source'], 'Reported')
        self.assertNotIn('Temperature', data)


if __name__ == '__main__':
    unittest.main()
