import importlib.util
import pathlib
import tempfile
import unittest
import zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_builder',ROOT/'scripts/build-release.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
VERSION=(ROOT/'VERSION').read_text().strip()


class ReleaseTests(unittest.TestCase):
    def test_version_readme_badge_and_changelog_agree(self):
        version=(ROOT/'VERSION').read_text().strip()
        self.assertRegex(version,r'^\d+\.\d+\.\d+$')
        self.assertIn('Version '+version,(ROOT/'README.md').read_text(encoding='utf-8'))
        self.assertIn('releases/tag/v'+version,(ROOT/'README.md').read_text(encoding='utf-8'))
        self.assertIn('version: '+version,(ROOT/'docs/assets/version.svg').read_text())
        self.assertIn('## '+version,(ROOT/'CHANGELOG.md').read_text())
        self.assertIn('git switch --detach v'+version,(ROOT/'docs/SETUP.md').read_text(encoding='utf-8'))
        from PIL import Image
        with Image.open(ROOT/'docs/assets/version.png') as badge:self.assertEqual(badge.info.get('Version'),version)

    def archive(self,extra=None,version=None):
        version=version or VERSION
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        path=pathlib.Path(directory.name)/'fixture.zip';prefix='inference-valet-'+version+'/'
        with zipfile.ZipFile(path,'w') as z:
            for name in ['VERSION','README.md','docs/assets/version.svg','ai_capabilities.py','ai_provider.py','ai_dsv41.py','tests/test_capabilities.py']:
                z.write(ROOT/name,prefix+name)
            for name,value in (extra or {}).items():z.writestr(prefix+name,value)
        return path

    def test_sanitized_versioned_archive_passes(self):
        self.assertGreater(builder.audit_archive(self.archive(),VERSION),0)

    def test_credentials_runtime_files_and_personal_paths_are_rejected(self):
        examples=[{'config.json':'{}'},{'logs/request.jsonl':'{}'},{'engine/model.gguf':'data'},
                  {'fixture.py':'ghp_'+'x'*40},{'fixture.md':'C:'+ '/Users/'+'PrivateUser/project'},
                  {'fixture.md':'git.'+'private'+'.'+'local'}]
        for extra in examples:
            with self.subTest(names=list(extra)),self.assertRaises(ValueError):
                builder.audit_archive(self.archive(extra),VERSION)

    def test_mislabeled_archive_is_rejected(self):
        with self.assertRaises(ValueError):builder.audit_archive(self.archive(version='999.0.0'),'999.0.0')


if __name__=='__main__':unittest.main()
