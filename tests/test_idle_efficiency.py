import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('efficient_launcher',ROOT/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class EfficiencyTests(unittest.TestCase):
    def test_process_name_shortlist_still_requires_verified_executable(self):
        unrelated=Mock(info={'name':'browser.exe'})
        candidate=Mock(info={'name':'python.exe'})
        candidate.exe.return_value='C:/unrelated/python.exe'
        candidate.cmdline.return_value=['C:/unrelated/python.exe','other.py']
        with patch.object(a.psutil,'process_iter',return_value=[unrelated,candidate]):
            self.assertEqual(a.servers(),[])
        unrelated.exe.assert_not_called();unrelated.cmdline.assert_not_called()
        candidate.exe.assert_called_once()

    def test_fresh_server_guard_avoids_redundant_game_and_process_scan(self):
        app=Mock(active=set(),recovery_policy=a.RecoveryPolicy(),idle_policy=a.IdlePolicy(0))
        settings=dict(last_profile='strata-128k',extra_games=[],enabled=True,demand_armed=True)
        with tempfile.TemporaryDirectory() as d,patch.object(a,'LOGS',pathlib.Path(d)),patch.object(a,'IDLE_SETTINGS') as store,patch.object(a,'idle_seconds',return_value=1),patch.object(a,'read_demand_status',return_value={'games':['game.exe'],'unknown':False}),patch.object(a,'servers') as scan:
            store.read.return_value=settings
            _,reading=a.LauncherUI.auto_sample(app)
            self.assertEqual(reading['games'],['game.exe'])
            self.assertFalse(reading['recover'])
        scan.assert_not_called();app.game_detector.running.assert_not_called()

    def test_missing_server_guard_falls_back_to_game_scan(self):
        app=Mock(active=set(),recovery_policy=a.RecoveryPolicy(),idle_policy=a.IdlePolicy(0))
        app.game_detector.running.return_value=[]
        settings=dict(last_profile='strata-128k',extra_games=[],enabled=True,demand_armed=True)
        with tempfile.TemporaryDirectory() as d,patch.object(a,'LOGS',pathlib.Path(d)),patch.object(a,'IDLE_SETTINGS') as store,patch.object(a,'idle_seconds',return_value=1),patch.object(a,'read_demand_status',return_value={}),patch.object(a,'servers',return_value=[]),patch.object(a,'listener_present',return_value=False):
            store.read.return_value=settings
            _,reading=a.LauncherUI.auto_sample(app)
            self.assertTrue(reading['recover'])
        app.game_detector.running.assert_called_once()

    def test_hidden_dashboard_does_not_collect_hardware_telemetry(self):
        app=a.LauncherUI(enable_tray=False,observe=False);app.hide()
        try:
            with patch.object(app.collector,'collect') as collect,patch.object(app.collector,'summary',return_value={}) as summary,patch.object(a,'observed_profile',return_value=(None,'Waiting for request')),patch.object(app.telemetry_worker,'submit',side_effect=lambda target:target()):
                app.refresh()
                collect.assert_not_called()
                summary.assert_called_once()
                event=app.events.get_nowait()
                self.assertEqual(event[0],'snapshot');self.assertEqual(event[1][2],{})
        finally:app.quit()

if __name__=='__main__':unittest.main()
