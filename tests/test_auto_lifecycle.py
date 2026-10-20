import sys
import importlib.util,json,pathlib,sys,tempfile,time,unittest
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class AutomaticLifecycle(unittest.TestCase):
 def run_auto(self,cancel):
  with tempfile.TemporaryDirectory() as d:
   directory=pathlib.Path(d)
   config=dict(label='test',model='test-model',engine='strata',context=163840,slots=1,command=['unused'],cwd=d)
   sock=MagicMock();sock.__enter__.return_value.connect_ex.return_value=1
   def fetch(path):return {'data':[{'id':'test-model'}]} if path=='/v1/models' else {'loaded':True,'context':{'native':163840},'concurrency':{'serving':1}}
   with patch.object(a,'LOGS',directory),patch.object(a,'validate_profile',return_value=config),patch.object(a,'servers',return_value=[]),patch.object(a,'control_lock',side_effect=lambda:__import__('contextlib').nullcontext()),patch.object(a.socket,'socket',return_value=sock),patch.object(a.subprocess,'Popen') as launch,patch.object(a,'fetch',side_effect=fetch),patch.object(a,'stop_all') as stop,patch.object(a,'IDLE_SETTINGS') as settings:
    result=a.start_profile('strata-128k',automatic_guard=lambda:True,automatic_cancel=lambda:cancel)
    launch.assert_called_once();settings.update.assert_called_once_with(demand_armed=True)
    if cancel:self.assertTrue(result['cancelled']);stop.assert_called_once()
    else:self.assertEqual(result['model'],'test-model');self.assertEqual(result['profile'],'strata-128k');stop.assert_not_called()
    return launch.call_args.kwargs['env']
 def test_eligible_auto_load_reaches_health_without_unloading(self):self.run_auto(False)
 def test_game_launch_cancels_automatic_loading(self):self.run_auto(True)
 def test_configured_key_reaches_backend_without_a_command_line_secret(self):
  with patch.object(a,'CONFIG',dict(on_demand={'enabled':True},strata_api_key='fixture-key')):
   self.assertEqual(self.run_auto(False)['STRATA_API_KEY'],'fixture-key')
if __name__=='__main__':unittest.main()
