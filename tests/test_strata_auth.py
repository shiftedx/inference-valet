import importlib.util,io,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('auth_launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class StrataAuthTests(unittest.TestCase):
 def check_fetch(self,config,environment,expected):
  def reply(request,timeout):
   self.assertEqual(request.full_url,'http://127.0.0.1:8080/v1/status')
   self.assertEqual(request.get_header('Authorization'),expected)
   return io.BytesIO(b'{"loaded":true}')
  with patch.object(a,'CONFIG',config),patch.dict(a.os.environ,environment,clear=True),patch.object(a.urllib.request,'urlopen',side_effect=reply):
   self.assertEqual(a.fetch('/v1/status'),{'loaded':True})
 def test_config_key_authenticates_telemetry(self):
  self.check_fetch({'strata_api_key':'fixture-key'},{},'Bearer fixture-key')
 def test_environment_key_works_for_an_external_launch(self):
  self.check_fetch({}, {'STRATA_API_KEY':'environment-key'},'Bearer environment-key')
 def test_existing_keyless_local_server_remains_supported(self):
  self.check_fetch({}, {},None)
if __name__=='__main__':unittest.main()
