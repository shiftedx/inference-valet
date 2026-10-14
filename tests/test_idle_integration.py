import sys
import importlib.util, json, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
from ai_idle import GameDetector,IdlePolicy,idle_seconds
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
  replacement=patch.object(a,"LOGS",pathlib.Path(d.name));replacement.start();self.addCleanup(replacement.stop)
 def test_auto_race_never_stops_or_spawns(self):
  for running,eligible in [([],False),([object()],True)]:
   with patch.object(a,'validate_profile',return_value={}),patch.object(a,'servers',return_value=running),patch.object(a,'stop_all') as stop,patch.object(a.subprocess,'Popen') as spawn:
    result=a.start_profile('strata-128k',automatic_guard=lambda:eligible)
    self.assertTrue(result['cancelled']);stop.assert_not_called();spawn.assert_not_called()
 def test_reboot_stale_stop_timestamp(self):
  policy=IdlePolicy(0)
  self.assertTrue(policy.decide(1200,1200,[],False,True,'strata-128k',999999)[0])
 def test_extra_windowed_game_path(self):
  detector=GameDetector()
  self.assertIn('python.exe',detector.running([sys.executable]))
if __name__=='__main__':
 unittest.main()
