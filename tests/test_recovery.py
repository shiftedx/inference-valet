import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_recovery import RecoveryPolicy
from ai_issues import failure_code
spec=importlib.util.spec_from_file_location('recovery_launcher',ROOT/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class RecoveryTests(unittest.TestCase):
    def test_dead_listener_recovery_does_not_wait_for_idle_or_games(self):
        app=Mock(active=set(),recovery_policy=RecoveryPolicy(),idle_policy=a.IdlePolicy(100))
        app.game_detector.running.return_value=['game.exe']
        settings=dict(last_profile='strata-128k',extra_games=[],enabled=False,demand_armed=True)
        with tempfile.TemporaryDirectory() as d, patch.object(a,'LOGS',pathlib.Path(d)), patch.object(a,'IDLE_SETTINGS') as store, patch.object(a,'idle_seconds',return_value=1), patch.object(a,'servers',return_value=[]), patch.object(a,'listener_present',return_value=False):
            store.read.return_value=settings
            due,reading=a.LauncherUI.auto_sample(app)
        self.assertFalse(due)
        self.assertTrue(reading['recover'])

    def test_manual_unload_live_process_port_and_busy_action_block_recovery(self):
        p=RecoveryPolicy()
        for armed,owned,listener,busy in [(False,False,False,False),(True,True,False,False),(True,False,True,False),(True,False,False,True)]:
            self.assertFalse(p.decide(100,armed,owned,listener,[],busy)[0])

    def test_single_flight_backoff_and_crash_limit_survive_tray_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'recovery.json';p=RecoveryPolicy(path=path)
            self.assertTrue(p.begin(100));self.assertFalse(p.begin(100));p.finished()
            self.assertFalse(p.decide(104,True,False,False,[],False)[0])
            p=RecoveryPolicy(path=path)
            self.assertTrue(p.decide(105,True,False,False,[],False)[0]);p.begin(105);p.finished()
            p.begin(120);p.finished()
            self.assertFalse(RecoveryPolicy(path=path).decide(200,True,False,False,[],False)[0])
            p.reset();self.assertTrue(p.decide(200,True,False,False,[],False)[0])

    def test_corrupt_recovery_state_requires_manual_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'state.json';path.write_text('broken')
            p=RecoveryPolicy(path=path)
            self.assertFalse(p.decide(100,True,False,False,[],False)[0])
            p.reset();self.assertTrue(p.decide(100,True,False,False,[],False)[0])

    def test_stale_and_reused_process_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch.object(a,'LOGS',pathlib.Path(d)),patch.object(a.time,'time',return_value=100),patch.object(a.psutil,'Process') as proc,patch.object(a,'classify',return_value='strata-server'):
            path=pathlib.Path(d)/'demand-status.json'
            status=dict(checked_at=90,owner_pid=1,owner_created=50,reason='old')
            path.write_text(json.dumps(status));self.assertEqual(a.read_demand_status(),{})
            status['checked_at']=100;path.write_text(json.dumps(status))
            proc.return_value.create_time.return_value=51
            self.assertEqual(a.read_demand_status(),{})
            proc.return_value.create_time.return_value=50
            self.assertEqual(a.read_demand_status()['reason'],'old')

    def test_dead_endpoint_never_displays_stale_waiting_status(self):
        with patch.object(a,'fetch',side_effect=OSError('down')),patch.object(a,'servers',return_value=[]),patch.object(a,'read_demand_status',return_value={'reason':'Waiting for request'}):
            self.assertEqual(a.observed_profile(),(None,'No model loaded.'))

    def test_access_violation_is_not_reported_as_vram_oom(self):
        self.assertEqual(failure_code('0xc0000005 access violation'),'native_crash')
        self.assertEqual(failure_code('CUDA out of memory'),'vram_allocation_failed')

if __name__=='__main__':unittest.main()
