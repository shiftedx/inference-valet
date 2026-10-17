import os
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ai_idle as idle


class GameDetectionTests(unittest.TestCase):
 def process(self, name, exe=None, command=None):
  proc=Mock()
  proc.info={'exe':exe or 'C:\\Other\\'+name,'name':name}
  proc.exe.return_value=proc.info['exe']
  proc.name.return_value=name
  proc.cmdline.return_value=command or [proc.info['exe']]
  return proc

 def running(self, state, processes=(), foreground=None, extra=()):
  detector=idle.GameDetector()
  detector.refreshed=idle.time.monotonic()
  detector.roots=[os.path.normcase('C:\\Games\\Installed\\')]
  detector.recorded={os.path.normcase('C:\\Recorded\\game.exe')}
  def query(pointer):pointer._obj.value=state;return 0
  shell=types.SimpleNamespace(SHQueryUserNotificationState=query)
  with patch.object(idle.ctypes,'windll',types.SimpleNamespace(shell32=shell)),patch.object(idle.psutil,'process_iter',return_value=processes),patch.object(detector,'foreground_fullscreen_process',return_value=foreground):
   return detector.running(extra)

 def test_busy_and_presentation_are_not_games(self):
  for state in (1,2,4,5,6,7):
   with self.subTest(state=state):
    self.assertEqual(self.running(state,foreground=self.process('browser.exe')),[])

 def test_exact_valet_window_never_triggers_fallback(self):
  launcher=str(pathlib.Path(idle.__file__).resolve().parent/'ai-launcher.py')
  valet=self.process('python.exe',sys.executable,[sys.executable,launcher])
  self.assertEqual(self.running(3,foreground=valet),[])

 def test_other_python_app_is_not_exempted(self):
  other=self.process('python.exe',sys.executable,[sys.executable,'C:\\Games\\game.py'])
  self.assertEqual(self.running(3,foreground=other),['Exclusive fullscreen: python.exe'])

 def test_valet_venv_redirector_and_exact_system_base(self):
  base=pathlib.Path(idle.__file__).resolve().parent
  launcher=str(base/'ai-launcher.py')
  system='C:\\TrustedPython\\python.exe'
  images=[str(base/'.venv/Scripts/pythonw.exe'),system,'C:\\TrustedPython\\pythonw.exe']
  with patch.object(sys,'_base_executable',system):
   for image in images:
    with self.subTest(image=image):
     proc=self.process('pythonw.exe',image,[str(base/'.venv/Scripts/pythonw.exe'),launcher])
     self.assertTrue(idle.GameDetector.valet_process(proc))
     self.assertEqual(self.running(3,foreground=proc),[])
   unrelated=self.process('pythonw.exe','C:\\OtherPython\\pythonw.exe',['C:\\OtherPython\\pythonw.exe',launcher])
   self.assertFalse(idle.GameDetector.valet_process(unrelated))
   other_script=self.process('pythonw.exe','C:\\TrustedPython\\pythonw.exe',['C:\\TrustedPython\\pythonw.exe','C:\\Other\\ai-launcher.py'])
   self.assertFalse(idle.GameDetector.valet_process(other_script))

 def test_matching_title_or_script_basename_is_not_identity(self):
  other=self.process('Inference Valet.exe',sys.executable,[sys.executable,'C:\\Unrelated\\ai-launcher.py'])
  self.assertFalse(idle.GameDetector.valet_process(other))

 def test_known_game_prioritized_with_valet_foreground(self):
  launcher=str(pathlib.Path(idle.__file__).resolve().parent/'ai-launcher.py')
  valet=self.process('python.exe',sys.executable,[sys.executable,launcher])
  for state in (1,2,3,4):
   for path in ('C:\\Games\\Installed\\game.exe','C:\\Recorded\\game.exe','C:\\Custom\\game.exe'):
    with self.subTest(state=state,path=path):
     game=self.process('game.exe',path)
     self.assertEqual(self.running(state,[game],valet,['C:\\Custom\\game.exe']),['game.exe'])

 def test_exclusive_unknown_game_needs_foreground_fullscreen(self):
  self.assertEqual(self.running(3),[])
  self.assertEqual(self.running(3,foreground=self.process('unknown-game.exe')),['Exclusive fullscreen: unknown-game.exe'])

 def test_inaccessible_or_exited_foreground_is_handled(self):
  proc=self.process('game.exe')
  proc.name.side_effect=idle.psutil.NoSuchProcess(123)
  self.assertEqual(self.running(3,foreground=proc),[])

 def test_actual_foreground_bounds_on_secondary_monitor(self):
  user=Mock()
  user.GetForegroundWindow.return_value=123
  user.MonitorFromWindow.return_value=456
  user.GetWindowThreadProcessId.side_effect=lambda window,pid:setattr(pid._obj,'value',999) or 1
  def monitor(handle,pointer):
   rect=pointer._obj.rcMonitor
   rect.left=-1920;rect.top=0;rect.right=0;rect.bottom=1080
   return 1
  user.GetMonitorInfoW.side_effect=monitor
  def window_rect(window,pointer):
   rect=pointer._obj
   rect.left=-1920;rect.top=0;rect.right=0;rect.bottom=1080
   return 1
  user.GetWindowRect.side_effect=window_rect
  proc=self.process('game.exe')
  with patch.object(idle.ctypes,'windll',types.SimpleNamespace(user32=user)),patch.object(idle.psutil,'Process',return_value=proc):
   self.assertIs(idle.GameDetector.foreground_fullscreen_process(),proc)
   def partial(window,pointer):
    window_rect(window,pointer);pointer._obj.bottom=900;return 1
   user.GetWindowRect.side_effect=partial
   self.assertIsNone(idle.GameDetector.foreground_fullscreen_process())


if __name__=='__main__':unittest.main()
