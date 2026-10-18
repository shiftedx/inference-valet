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

    def test_replacement_rejects_unknown_relevant_process_and_flagged_python(self):
        path=self.root/m.WRAPPERS[0];path.write_text('# original')
        for info in ({'name':'python.exe','exe':None,'cmdline':None},
                     {'name':'python.exe','exe':'python.exe','cmdline':['python.exe','-u',str(path)]}):
            with patch.object(m.psutil,'process_iter',return_value=[Mock(info=info)]):
                with self.assertRaises(ValueError):m.install(self.root,replace=True)
            self.assertEqual(path.read_text(),'# original')
        protected=Mock(info={'name':'System','exe':None,'cmdline':None})
        with patch.object(m.psutil,'process_iter',return_value=[protected]):m.install(self.root,replace=True)

    def test_live_or_uninspectable_ownership_prevents_replacement(self):
        path=self.root/m.WRAPPERS[0];path.write_text('# original')
        record=self.root/'profile-logs/active-profile.json';record.parent.mkdir()
        import json
        record.write_text(json.dumps(dict(launcher_pid=123,launcher_started=10,server_pid=124,server_started=11)))
        for process in (Mock(create_time=Mock(return_value=10)),
                        Mock(create_time=Mock(side_effect=m.psutil.AccessDenied(123)))):
            with patch.object(m.psutil,'Process',return_value=process):
                with self.assertRaises(ValueError):m.install(self.root,replace=True)
            self.assertEqual(path.read_text(),'# original')
        with patch.object(m.psutil,'Process',side_effect=m.psutil.NoSuchProcess(123)),patch.object(m.psutil,'process_iter',return_value=[]):
            m.install(self.root,replace=True)

    def test_failed_wrapper_replacement_rolls_back_written_files(self):
        for name in m.WRAPPERS:(self.root/name).write_text('# original '+name)
        original=m.pathlib.Path.replace
        def fail_second(path,target):
            if target.name==m.WRAPPERS[1]:raise OSError('simulated failure')
            return original(path,target)
        with patch.object(m.psutil,'process_iter',return_value=[]),patch.object(m.pathlib.Path,'replace',fail_second):
            with self.assertRaises(OSError):m.install(self.root,replace=True)
        for name in m.WRAPPERS:self.assertEqual((self.root/name).read_text(),'# original '+name)

if __name__=='__main__':unittest.main()
