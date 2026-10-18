import importlib.util,json,os,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
class PackageTests(unittest.TestCase):
 def test_config_paths_and_external_backend(self):
  import ai_config as c
  self.assertTrue(c.STRATA_ROOT.is_absolute())
  self.assertTrue(c.STATE_DIR.is_absolute())
  self.assertNotEqual(c.STATE_DIR,ROOT/'launcher-logs')
 def test_importable_launcher_from_checkout(self):
  spec=importlib.util.spec_from_file_location('packaged_launcher',ROOT/'ai-launcher.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertEqual(module.PROFILES,module.PROFILE_STORE.descriptors(module.PY,module.CONFIG))
  self.assertEqual(module.GUI_PIPE,r'\\.\pipe\AI-Profiles')
 def test_missing_backend_profiles_list_and_ui_check_are_usable(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);config=root/'config.json'
   config.write_text(json.dumps(dict(strata_root=str(root/'absent-backend'),state_dir=str(root/'state'))))
   env={**os.environ,'AI_PROFILES_CONFIG':str(config)}
   for flag,expected in (('--list','{}'),('--check-ui','0')):
    result=subprocess.run([sys.executable,str(ROOT/'ai-launcher.py'),flag],capture_output=True,text=True,env=env,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    self.assertEqual(result.returncode,0,result.stderr)
    self.assertEqual(result.stdout.strip(),expected)
if __name__=='__main__':unittest.main()
