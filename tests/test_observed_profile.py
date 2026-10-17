import sys
import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class ObservedProfile(unittest.TestCase):
 def test_edited_live_profile_keeps_runtime_identity_and_pending_settings(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'profile-logs').mkdir()
   (root/'profile-logs/active-profile.json').write_text(json.dumps(dict(server_pid=42,server_started=100,profile='quality-iq3-xxs')))
   process=Mock(pid=42);process.create_time.return_value=100
   process.net_connections.return_value=[Mock(status=a.psutil.CONN_LISTEN,laddr=Mock(ip='127.0.0.1',port=8080))]
   def fetch(path):return {'data':[{'id':'qwen3.8-flash-next-iq3_xxs'}]} if path=='/v1/models' else {'loaded':True,'context':{'native':131072},'concurrency':{'serving':1}}
   with patch.object(a,'STRATA',root),patch.object(a,'servers',return_value=[(process,'strata-server')]),patch.object(a,'read_demand_status',return_value={}),patch.object(a,'fetch',side_effect=fetch):
    key,status=a.observed_profile()
    self.assertIsNone(key);self.assertIn('128K',status);self.assertIn('saved changes pending',status)
 def test_external_profile_switch_is_remembered(self):
  with tempfile.TemporaryDirectory() as d:
   settings=a.Settings(pathlib.Path(d)/'settings.json');settings.update(last_profile='strata-128k')
   with patch.object(a,'IDLE_SETTINGS',settings):
    app=a.LauncherUI(enable_tray=False,observe=False);app.hide();app.performance=None;app.initial_snapshot=False
    try:
     app.events.put(('snapshot',(app.epoch,('strata-256k','Running Strata'),{})));app.poll()
     self.assertEqual(settings.read()['last_profile'],'strata-256k')
    finally:app.quit()
if __name__=='__main__':unittest.main()
