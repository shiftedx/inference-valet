import unittest

from ai_telemetry import adapt_infernix, adapt_ninfer_stats, normalize_strata


class InfernixTelemetryTests(unittest.TestCase):
    def test_active_and_completed_metrics_map_to_panel(self):
        metrics = {
            "schema": "infernix.telemetry/1",
            "engine": {"max_context": 131072, "max_concurrency": 4},
            "live": {"state": "generating", "running": 2, "waiting": 1, "tok_s": 350,
                     "prefill_tok_s_mean": 12000,
                     "active": [{"phase": "prefill", "prompt_tokens": 30000, "processed_tokens": 12000},
                                {"phase": "decode", "prompt_tokens": 1000, "output_tokens": 100}]},
            "requests": [{"prompt_tokens": 2000, "reused": 1500, "hit_rate": .75,
                          "prefill_tok_s": 5000, "decode_tok_s": 200, "ttft_ms": 100,
                          "drafts_accepted": 80, "drafts_offered": 100}],
        }
        adapted, status = adapt_infernix(metrics)
        result = normalize_strata(adapted)
        self.assertTrue(status["loaded"])
        self.assertEqual(status["concurrency"]["serving"], 4)
        self.assertEqual(result["live_speed"], 350)
        self.assertEqual(result["last_speed"], 200)
        self.assertEqual(result["last_prefill"], 5000)
        self.assertEqual(result["ttft_ms"], 100)
        self.assertEqual(result["prompt_read"], 12000)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["capacity"], 4)
        self.assertEqual(result["occupied_slots"], 2)
        self.assertEqual([slot["used"] for slot in result["slots"]], [12000, 1100])
        self.assertEqual(result["reuse"], 75)
        self.assertIsNone(result["expert_hits"])
        self.assertNotIn("slots", metrics["live"])

    def test_ninfer_stats_uses_interval_rates_and_handles_restart(self):
        previous = {"uptime_seconds": 20, "counters": {"committed_decode_tokens": 100}}
        stats = {"object": "ninfer.stats", "uptime_seconds": 22,
                 "requests": {"running": 2, "decode_ready": 2, "waiting": 1},
                 "capacity": {"max_context": 32768, "max_concurrency": 2},
                 "counters": {"committed_decode_tokens": 700}}
        adapted, status = adapt_ninfer_stats(stats, previous)
        result = normalize_strata(adapted)
        self.assertEqual(result["live_speed"], 300)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(status["context"]["native"], 32768)
        self.assertIsNone(result["last_speed"])
        restarted, _ = adapt_ninfer_stats({**stats, "uptime_seconds": 1}, stats)
        self.assertIsNone(restarted["live"]["tok_s"])

    def test_strata_inflight_can_exceed_occupied_engine_slots(self):
        result=normalize_strata({'engine':{'batch_slots':4},'live':{
            'state':'generating','running':6,'queued':0,'outside_slots':2,
            'slots':[{'state':'decoding'} for _ in range(4)]}})
        self.assertEqual(result['running'],6)
        self.assertEqual(result['capacity'],4)
        self.assertEqual(result['occupied_slots'],4)
        self.assertEqual(result['outside_slots'],2)
