import contextlib
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('game_unload_launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class GameUnloadTests(unittest.TestCase):
 def test_game_unload_is_independent_of_idle_restore_and_blocks_reload(self):
  for owned in (False,True):
   app=Mock(active=set(),idle_policy=a.IdlePolicy(0))
   app.game_detector.running.return_value=[]
   with tempfile.TemporaryDirectory() as d:
    settings=a.Settings(pathlib.Path(d)/'settings.json')
    settings.update(unload_games=['C:/Games/Example/game.exe'],enabled=False,demand_armed=False)
    with patch.object(a,'LOGS',pathlib.Path(d)),patch.object(a,'CONFIG',{}),patch.object(a,'IDLE_SETTINGS',settings),patch.object(a,'idle_seconds',return_value=99999),patch.object(a.GameDetector,'running_exact',return_value=['game.exe']),patch.object(a,'servers',return_value=[object()] if owned else []):
     due,reading=a.LauncherUI.auto_sample(app)
    self.assertFalse(due);self.assertEqual(reading['unload'],owned)
    self.assertEqual(reading['games'],['game.exe'])

 def test_only_exact_opted_in_executable_matches(self):
  game=str(pathlib.Path('C:/Games/Example/game.exe').resolve())
  other=Mock(info={'exe':str(pathlib.Path('C:/Other/game.exe').resolve()),'name':'game.exe'})
  actual=Mock(info={'exe':game,'name':'game.exe'})
  with patch.object(sys.modules['ai_idle'].psutil,'process_iter',return_value=[other]):
   self.assertEqual(a.GameDetector.running_exact([game]),[])
  with patch.object(sys.modules['ai_idle'].psutil,'process_iter',return_value=[other,actual]):
   self.assertEqual(a.GameDetector.running_exact([game]),['game.exe'])

 def test_unload_rechecks_game_and_owned_server_and_preserves_manual_settings(self):
  for games,owned in [([],True),(['game.exe'],False),(['game.exe'],True)]:
   with self.subTest(games=games,owned=owned),tempfile.TemporaryDirectory() as d:
    settings=a.Settings(pathlib.Path(d)/'settings.json')
    settings.update(unload_games=['C:/Games/Example/game.exe'],enabled=False,demand_armed=False,last_profile='test')
    with patch.object(a,'IDLE_SETTINGS',settings),patch.object(a,'control_lock',return_value=contextlib.nullcontext()),patch.object(a.GameDetector,'running_exact',return_value=games),patch.object(a,'servers',return_value=[object()] if owned else []),patch.object(a,'stop_all') as stop:
     result=a.stop_for_games()
     self.assertEqual(stop.call_count,int(bool(games) and owned))
     self.assertEqual(result.get('cancelled',False),not(bool(games) and owned))
    saved=settings.read()
    self.assertFalse(saved['enabled']);self.assertFalse(saved['demand_armed']);self.assertEqual(saved['last_profile'],'test')

if __name__=='__main__':unittest.main()
