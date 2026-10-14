import json
import pathlib
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ai_demand as demand


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.detector = Mock(); self.detector.running.return_value = []
        self.gpu = Mock(return_value=dict(util=0, used=1000, free=31000, ram=60, commit=70))
        self.guard = demand.Guard(self.detector, self.gpu, lambda: self.now)

    def test_unknown_game_state_blocks(self):
        self.detector.running.side_effect = OSError('inaccessible')
        self.assertIn('unknown', self.guard.load_reason())
        self.gpu.assert_not_called()

    def test_idle_gpu_never_overrides_active_windowed_game(self):
        self.detector.running.return_value = ['game.exe']
        self.assertIn('Gaming busy', self.guard.load_reason())
        self.gpu.assert_not_called()

    def test_game_exit_cooldown_then_safe_load(self):
        self.detector.running.return_value = ['game.exe']; self.guard.sample()
        self.detector.running.return_value = []; self.now += 1
        self.assertIn('cooldown', self.guard.load_reason())
        self.now += 30; self.assertIsNone(self.guard.load_reason())

    def test_retained_comfy_models_block_without_eviction(self):
        self.gpu.return_value['used'] = 16000
        self.assertIn('left untouched', self.guard.load_reason())

    def test_resource_failure_blocks(self):
        self.gpu.side_effect = OSError('counter failed')
        self.assertIn('unknown', self.guard.load_reason())

    def test_optional_comfy_busy_queue_blocks(self):
        self.guard.options['comfyui_url'] = 'http://127.0.0.1:8188'
        reply = Mock(); reply.__enter__ = Mock(return_value=reply); reply.__exit__ = Mock()
        reply.read.return_value = b'{"queue_running":[[1]],"queue_pending":[]}'
        with patch.object(demand.urllib.request, 'urlopen', return_value=reply):
            self.assertIn('ComfyUI', self.guard.load_reason())
        self.gpu.assert_not_called()


class NativeHTTPTests(unittest.TestCase):
    """Actual Strata HTTP/SSE with an unloaded simulated engine, no GPU needed."""
    def setUp(self):
        from ai_config import STRATA_ROOT
        if not (STRATA_ROOT/'Strata/serve/server.py').is_file():
            self.skipTest('Native HTTP integration requires an external Strata checkout')
        sys.path.insert(0, str(STRATA_ROOT / 'Strata'))
        from serve import server
        from serve.frontend import ChatTemplate
        from serve.test_lifecycle import ResidentEngine
        self.server = server
        self.detector = Mock(); self.detector.running.return_value = []
        self.guard = demand.Guard(self.detector, gpu=lambda:dict(util=0,used=1000,free=31000,ram=60,commit=70),
                                  options=dict(poll_seconds=.25, grace_seconds=.25,cooldown_seconds=0,max_pending=2))
        original = server.make_handler
        self.addCleanup(setattr, server, 'make_handler', original)
        # Suppress the infinite production monitor; drive its exact tick in the test.
        with patch.object(demand.threading, 'Thread'):
            demand.install(server, self.guard)
            tok = server.ByteTokenizer()
            self.engine = ResidentEngine(tok)
            svc = server.Service(self.engine, tok, ChatTemplate(STRATA_ROOT/'Strata/serve/chat_template.jinja'))
            handler = server.make_handler(svc)
        self.svc = svc; self.tick = handler.valet_tick
        self.http = server.Server(('127.0.0.1', 0), handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close); self.addCleanup(self.http.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.http.server_address[1])

    def post(self, model='test', stream=False):
        req = urllib.request.Request(self.url+'/v1/chat/completions',
              data=json.dumps(dict(model=model,messages=[dict(role='user',content='Hi')],max_tokens=10,stream=stream)).encode(),
              headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:return r.status,r.read().decode()
        except urllib.error.HTTPError as e:return e.code,e.read().decode()

    def test_first_request_single_load_stream_and_reload(self):
        self.assertFalse(self.engine.loaded)
        self.assertEqual(self.post(self.svc.model)[0],200)
        self.assertEqual(self.engine.starts,1)
        code, body=self.post(self.svc.model,True)
        self.assertEqual(code,200); self.assertIn('[DONE]',body)
        self.assertEqual(self.engine.starts,1)
        self.assertEqual(self.svc.unload(),'unloaded')
        self.assertEqual(self.post(self.svc.model)[0],200)
        self.assertEqual(self.engine.starts,2)

    def test_wrong_model_never_loads(self):
        self.assertEqual(self.post('wrong-model')[0],404)
        self.assertEqual(self.engine.starts,0)

    def test_game_blocks_load_and_loaded_requests(self):
        self.assertEqual(self.post(self.svc.model)[0],200)
        self.detector.running.return_value=['windowed-game.exe'];self.tick()
        code,body=self.post(self.svc.model)
        self.assertEqual(code,503);self.assertIn('gaming_busy',body)
        time.sleep(.3);self.tick()
        self.assertFalse(self.engine.loaded)
        self.assertEqual(self.engine.starts,1)

    def test_game_appearing_during_load_unloads_before_answer(self):
        native = self.engine.restart
        def restart():
            native();self.detector.running.return_value=['game.exe'];self.guard.sample()
        self.engine.restart=restart
        self.assertEqual(self.post(self.svc.model)[0],503)
        self.assertFalse(self.engine.loaded)

    def test_full_queue_returns_retryable_error(self):
        barrier=threading.Event(); entered=threading.Event()
        native=self.engine.restart
        def restart():entered.set();barrier.wait(3);native()
        self.engine.restart=restart
        threads=[threading.Thread(target=lambda:self.post(self.svc.model)) for _ in range(2)]
        for t in threads:t.start()
        entered.wait(1);time.sleep(.1)
        try:
            code,body=self.post(self.svc.model)
            self.assertEqual(code,503);self.assertIn('queue_full',body)
        finally:
            barrier.set()
            for t in threads:t.join(3)

    def test_game_grace_cancels_sse_explicitly(self):
        started=threading.Event()
        native=self.engine.reply.generate
        def slow(*args, **kwargs):
            started.set()
            for item in native(*args, **kwargs):
                time.sleep(.1)
                yield item
        self.engine.reply.generate=slow
        result=[]
        worker=threading.Thread(target=lambda:result.append(self.post(self.svc.model,True)))
        worker.start();started.wait(2)
        self.detector.running.return_value=['game.exe'];self.tick()
        self.assertTrue(self.engine.loaded)
        time.sleep(.3);self.tick();worker.join(3);self.tick()
        self.assertEqual(len(result),1)
        self.assertIn('gaming priority',result[0][1])
        self.assertIn('[DONE]',result[0][1])
        self.assertFalse(self.engine.loaded)

    def test_failed_native_load_reports_and_backs_off(self):
        now=[100]
        self.guard.clock=lambda:now[0]
        attempts=[]
        def fail():
            attempts.append(1)
            raise self.server.EngineDied('CUDA out of memory while starting engine')
        self.engine.restart=fail
        code,body=self.post(self.svc.model)
        self.assertEqual(code,503)
        self.assertIn('CUDA out of memory',body)
        self.assertEqual(self.guard.load_issue['code'],'vram_allocation_failed')
        self.assertFalse(self.engine.loaded)
        code,body=self.post(self.svc.model)
        self.assertEqual(code,503)
        self.assertIn('cooldown',body)
        self.assertEqual(len(attempts),1)
        self.tick()
        status=json.loads((demand.STATE_DIR/'demand-status.json').read_text())
        self.assertIn('CUDA out of memory',status['reason'])
        self.assertEqual(status['owner_pid'],__import__('os').getpid())
        now[0]+=31
        self.post(self.svc.model)
        self.assertEqual(len(attempts),2)

    def test_vram_denial_reports_measured_headroom_without_loading(self):
        self.guard.gpu=lambda:dict(util=0,used=12000,free=18000,ram=60,commit=70)
        code,body=self.post(self.svc.model)
        self.assertEqual(code,503)
        self.assertIn('18000 MiB free',body)
        self.assertEqual(self.engine.starts,0)
        self.assertEqual(self.guard.load_issue['code'],'vram_headroom')
        self.guard.gpu=lambda:dict(util=0,used=1000,free=31000,ram=60,commit=70)
        self.assertEqual(self.post(self.svc.model)[0],200)
        self.assertIsNone(self.guard.load_issue)

    def test_unchanged_guard_status_uses_bounded_heartbeat(self):
        now=[100];self.guard.clock=lambda:now[0]
        path=demand.STATE_DIR/'demand-status.json'
        self.tick();first=json.loads(path.read_text())
        now[0]=100.5;self.tick()
        self.assertEqual(json.loads(path.read_text())['checked_at'],first['checked_at'])
        self.detector.running.return_value=['game.exe'];now[0]=100.6;self.tick()
        self.assertEqual(json.loads(path.read_text())['games'],['game.exe'])
        now[0]=103;self.tick()
        self.assertGreaterEqual(json.loads(path.read_text())['checked_at'],first['checked_at'])

if __name__ == '__main__': unittest.main()
