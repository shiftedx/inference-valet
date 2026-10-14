import sys
import importlib.util, pathlib, tempfile, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('ai_idle', pathlib.Path(__file__).resolve().parents[1]/'ai_idle.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ReloadTests(unittest.TestCase):
 def test_idle_boundary_and_input(self):
  p=m.IdlePolicy(0)
  self.assertFalse(p.decide(1199,1199,[],False,True,'strata-128k',0)[0])
  self.assertTrue(p.decide(1200,1200,[],False,True,'strata-128k',0)[0])
  self.assertFalse(p.decide(1300,1,[],False,True,'strata-128k',0)[0])
 def test_game_and_post_game_delay(self):
  p=m.IdlePolicy(0)
  self.assertFalse(p.decide(1200,5000,['controller-game.exe'],False,True,'strata-128k',0)[0])
  self.assertFalse(p.decide(1209,5000,[],False,True,'strata-128k',0)[0])
  self.assertFalse(p.decide(2408,5000,[],False,True,'strata-128k',0)[0])
  self.assertTrue(p.decide(2409,5000,[],False,True,'strata-128k',0)[0])
 def test_manual_unload_pause_busy_and_retry(self):
  p=m.IdlePolicy(0)
  self.assertFalse(p.decide(1500,5000,[],False,True,'strata-128k',1499)[0])
  self.assertFalse(p.decide(3000,5000,[],False,False,'strata-128k',1499)[0])
  self.assertFalse(p.decide(3000,5000,[],True,True,'strata-128k',1499)[0])
  self.assertFalse(p.decide(3000,5000,[],False,True,None,1499)[0])
  self.assertTrue(p.decide(3000,5000,[],False,True,'strata-128k',1499)[0])
  p.failed(3000)
  self.assertFalse(p.decide(3299,5000,[],False,True,'strata-128k',1499)[0])
  self.assertTrue(p.decide(3300,5000,[],False,True,'strata-128k',1499)[0])
 def test_configurable_delay_boundaries_and_gates(self):
  for minutes in m.IDLE_MINUTES:
   delay=minutes*60;p=m.IdlePolicy(0)
   self.assertFalse(p.decide(delay-1,delay-1,[],False,True,'model',0,minutes)[0])
   self.assertTrue(p.decide(delay,delay,[],False,True,'model',0,minutes)[0])
   self.assertFalse(p.decide(delay+1,9999,['game.exe'],False,True,'model',0,minutes)[0])
   self.assertFalse(p.decide(delay+2,9999,[],False,True,'model',0,minutes)[0])
   self.assertTrue(p.decide(2*delay+2,9999,[],False,True,'model',0,minutes)[0])
   self.assertFalse(p.decide(3*delay,9999,[],False,True,'model',3*delay-1,minutes)[0])
 def test_delay_persistence_and_legacy_default(self):
  with tempfile.TemporaryDirectory() as d:
   settings=m.Settings(pathlib.Path(d)/'state.json')
   self.assertEqual(settings.read()['idle_minutes'],20)
   for minutes in m.IDLE_MINUTES:
    settings.update(idle_minutes=minutes)
    self.assertEqual(m.Settings(settings.path).read()['idle_minutes'],minutes)
   for invalid in (None,True,'5',0,35):
    settings.update(idle_minutes=invalid)
    self.assertEqual(settings.read()['idle_minutes'],20)
 def test_persistence(self):
  with tempfile.TemporaryDirectory() as d:
   s=m.Settings(pathlib.Path(d)/'state.json')
   s.update(last_profile='strata-3', enabled=False)
   self.assertEqual(m.Settings(s.path).read()['last_profile'],'strata-3')
   self.assertFalse(m.Settings(s.path).read()['enabled'])
   s.update(enabled=True)
   self.assertEqual(s.read()['last_profile'],'strata-3')
if __name__=='__main__':unittest.main()
