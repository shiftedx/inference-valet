"""Public wrapper profile selection uses external files without model presets."""
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('managed_profile_launcher',ROOT/'backends/strata/launch_strata_profile.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class WrapperProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);(self.root/'profiles').mkdir()
        self.patch=patch.object(launcher,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)

    def test_arbitrary_existing_profile_preserves_user_settings(self):
        name='My everyday coding model'
        data=dict(exe='user-engine.exe',model='user-chosen-model',args=['--max-context','12345'],
                  launcher_min_available_ram_gib=7,launcher_estimated_commit_gib=9)
        path=self.root/'profiles'/f'{name}.json';path.write_text(json.dumps(data),encoding='utf-8')
        before=path.read_bytes();template,cfg=launcher.profile_config(name)
        self.assertEqual(template,path)
        self.assertEqual(cfg['model_name'],'user-chosen-model');self.assertEqual(cfg['parallel'],1)
        self.assertEqual(cfg['launcher_min_available_ram_gib'],7)
        self.assertEqual(cfg['launcher_estimated_commit_gib'],9)
        self.assertNotIn('launcher_max_vram_used_mib',cfg)
        self.assertEqual(path.read_bytes(),before)

    def test_invalid_stems_never_inspect_or_launch_backend(self):
        for name in ('../outside',r'..\outside','C:/outside','', '..','work.shared-settings','work.SHARED-SETTINGS','missing','-bad','bad.','bad ','bad\nname','CON','nul.notes','COM1'):
            with self.subTest(name=name),patch.object(launcher.sys,'argv',['launcher',name]),patch.object(launcher.psutil,'process_iter') as inspect,patch.object(launcher.subprocess,'Popen') as spawn,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):launcher.main()
                inspect.assert_not_called();spawn.assert_not_called()

    def test_symlink_cannot_escape_profile_directory(self):
        outside=self.root/'external.json';outside.write_text('{}')
        link=self.root/'profiles/linked.json'
        try:link.symlink_to(outside)
        except OSError:self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):launcher.profile_path('linked')

    def test_missing_model_identifier_is_rejected(self):
        (self.root/'profiles/unnamed.json').write_text('{"args":[]}')
        with self.assertRaisesRegex(ValueError,'identifier'):launcher.profile_config('unnamed')

    def test_shared_settings_and_profile_directory_links_are_rejected(self):
        profile=self.root/'profiles/valid.json';profile.write_text('{"model":"user-model"}')
        external=self.root/'external';external.mkdir();settings=external/'settings.json';settings.write_text('{}')
        shared=profile.with_suffix('.shared-settings.json')
        try:shared.symlink_to(settings)
        except OSError:self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):launcher.profile_path('valid')
        shared.unlink();profile.unlink();(self.root/'profiles').rmdir()
        (external/'valid.json').write_text('{"model":"user-model"}')
        (self.root/'profiles').symlink_to(external,target_is_directory=True)
        with self.assertRaises(ValueError):launcher.profile_path('valid')

if __name__=='__main__':unittest.main()
