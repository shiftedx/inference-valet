import importlib.util,pathlib,tempfile,unittest
from unittest.mock import Mock,patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('integration_install',ROOT/'scripts/install-strata-integration.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=pathlib.Path(self.directory.name);server=self.root/'Strata/serve/server.py'
        server.parent.mkdir(parents=True);server.write_text('# simulated backend')

    def test_examples_and_wrappers_are_idempotent_and_preserve_existing_profiles(self):
        result=m.install(self.root,True);self.assertEqual(result['created_profiles'],4)
        profile=self.root/'profiles/quality-iq3-xxs.json';profile.write_text('{"calibrated":true}')
        result=m.install(self.root,True)
        self.assertEqual(result['created_profiles'],0);self.assertEqual(profile.read_text(),'{"calibrated":true}')
        self.assertEqual((self.root/m.WRAPPERS[0]).read_bytes(),(m.SOURCE/m.WRAPPERS[0]).read_bytes())

    def test_conflicting_wrapper_requires_explicit_replace_and_stopped_backend(self):
        path=self.root/m.WRAPPERS[0];path.write_text('# keep original')
        with self.assertRaisesRegex(ValueError,'Existing wrappers'):m.install(self.root)
        self.assertFalse((self.root/m.WRAPPERS[1]).exists())
        proc=Mock(info={'exe':'python.exe','cmdline':['python.exe',str(path)]})
        with patch.object(m.psutil,'process_iter',return_value=[proc]):
            with self.assertRaisesRegex(ValueError,'running'):m.install(self.root,replace=True)
        self.assertEqual(path.read_text(),'# keep original')
        with patch.object(m.psutil,'process_iter',return_value=[]):result=m.install(self.root,replace=True)
        self.assertEqual((pathlib.Path(result['backup'])/path.name).read_text(),'# keep original')

if __name__=='__main__':unittest.main()
