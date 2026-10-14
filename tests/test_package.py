import importlib.util,pathlib,sys,unittest
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
  self.assertEqual(len(module.PROFILES),5)
  self.assertEqual(module.GUI_PIPE,r'\\.\pipe\AI-Profiles')
if __name__=='__main__':unittest.main()
