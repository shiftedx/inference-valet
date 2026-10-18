"""Discovery uses real external JSON, never fabricated model presets."""
import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_profiles import ProfileStore

class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=pathlib.Path(self.temp.name);self.store=ProfileStore(self.root/'backend',self.root/'state')
 def profile(self,stem,**extra):
  path=self.store.paths(stem)[0];path.parent.mkdir(parents=True,exist_ok=True)
  data=dict(exe='engine.exe',model_name='arbitrary-local-model',parallel=2,args=['--max-context','98304']);data.update(extra)
  path.write_text(json.dumps(data),encoding='utf-8');return path
 def test_diagnostics_explain_catalog_root_count_and_invalid_profiles_without_backend(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('diagnostic_launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py')
  launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
  self.profile('valid');self.profile('bad-context',args=[])
  self.profile('bad-model',model_name='');self.profile('bad-exe',exe='')
  (self.store.root/'profiles'/'broken.json').write_text('{broken')
  rows=self.store.descriptors('python.exe',{})
  with patch.object(launcher,'PROFILE_STORE',self.store),patch.object(launcher,'PROFILES',rows),patch.object(launcher,'CONFIG',{}),patch.object(launcher,'LOGS',self.root/'state'),patch.object(launcher,'servers',return_value=[]),patch.object(launcher,'listener_present',return_value=False),patch.object(launcher,'read_demand_status',return_value={}),patch.object(launcher,'fetch',side_effect=OSError('offline')):
   catalog=launcher.diagnose()['profile_catalog']
  self.assertEqual(catalog['backend_root'],str(self.store.root))
  self.assertEqual(catalog['directory'],str(self.store.root/'profiles'))
  self.assertTrue(catalog['directory_exists']);self.assertEqual(catalog['count'],1)
  self.assertEqual(len(catalog['discovery_errors']),4)
  for marker in ('bad-context','--max-context','bad-model','model_name','bad-exe','exe','broken'):
   self.assertIn(marker,' '.join(catalog['discovery_errors']))
 def test_actual_models_windows_concurrency_and_labels_are_discovered(self):
  self.profile('my coder',label='Desk coder');self.profile('tiny',model_name='another-model',parallel=1,args=['--max-context','8192'])
  rows=self.store.descriptors('python.exe',{})
  self.assertEqual(set(rows),{'my coder','tiny'})
  self.assertEqual(rows['my coder']['name'],'Desk coder · 2 agents · 96K each')
  self.assertEqual(rows['tiny']['context'],8192);self.assertEqual(rows['tiny']['model'],'another-model')
  self.assertEqual(rows['my coder']['command'][-1],'my coder')
 def test_shared_and_support_json_are_ignored_without_inventing_missing_values(self):
  path=self.profile('valid');path.with_suffix('.shared-settings.json').write_text('{"args":[],"max_tokens":64}')
  (path.parent/'support.json').write_text('{"temperature":0.5}')
  self.profile('missing-model',model_name='');self.profile('missing-context',args=[])
  self.assertEqual(set(self.store.descriptors('python.exe',{})),{'valid'})
  self.assertEqual(len(self.store.discovery_errors),2)
 def test_allowlist_accepts_filestems_and_legacy_ids_without_manufacturing_profiles(self):
  self.profile('custom');legacy=self.profile('strata-128k')
  self.assertEqual(legacy.stem,'quality-iq3-xxs')
  rows=self.store.descriptors('python.exe',{'enabled_profiles':['custom','strata-128k','missing']})
  self.assertEqual(list(rows),['custom','strata-128k'])
  self.assertEqual(self.store.descriptors('python.exe',{'enabled_profiles':[]}),{})
 def test_unsafe_ids_and_shared_settings_cannot_be_loaded_or_saved(self):
  for key in ('../outside','a/b','C:drive','x\\y','..','a.shared-settings','trailing.','bad\nname'):
   with self.subTest(key=key),self.assertRaises(ValueError):self.store.paths(key)
 def test_symlinked_profile_and_settings_files_are_rejected(self):
  real=self.profile('valid');outside=self.root/'outside.json';outside.write_text(real.read_text())
  link=real.parent/'linked.json'
  try:link.symlink_to(outside)
  except OSError:self.skipTest('Symbolic links unavailable')
  self.assertEqual(set(self.store.descriptors('python.exe',{})),{'valid'})
  with self.assertRaises(ValueError):self.store.load('linked')
  real.with_suffix('.shared-settings.json').symlink_to(outside)
  with self.assertRaises(ValueError):self.store.load('valid')
 def test_imported_concurrency_and_absent_reasoning_defaults_survive_noop_save(self):
  self.profile('many-workers',parallel=12)
  values,snapshot=self.store.load('many-workers')
  self.assertEqual(values['slots'],'12');self.assertEqual(values['reasoning'],'');self.assertEqual(values['effort'],'')
  self.store.save('many-workers',values,snapshot)
  for obj in (json.loads(self.store.paths('many-workers')[0].read_text()),json.loads(self.store.paths('many-workers')[1].read_text())):
   self.assertNotIn('reasoning_budget_tokens',obj);self.assertNotIn('reasoning_effort',obj)
  self.assertEqual(self.store.descriptors('python.exe',{})['many-workers']['slots'],12)
 def test_long_imported_model_name_survives_other_edits_but_new_long_names_are_rejected(self):
  model='organization/'+('long-model-component-'*6)
  self.profile('long-model',model_name=model)
  values,snapshot=self.store.load('long-model');self.assertEqual(values['name'],model)
  values['context']='65536'
  self.store.save('long-model',values,snapshot)
  self.assertEqual(self.store.load('long-model')[0]['name'],model)
  values,snapshot=self.store.load('long-model');values['name']='new '+('x'*65)
  with self.assertRaisesRegex(ValueError,'1–64'):self.store.save('long-model',values,snapshot)
 def test_argument_like_and_windows_device_stems_are_rejected(self):
  for key in ('--help','-p','CON','nul.txt','COM1','LPT9.test'):
   with self.subTest(key=key),self.assertRaises(ValueError):self.store.paths(key)
 def test_nonexecutable_json_does_not_become_a_profile(self):
  self.profile('support',exe='')
  self.assertEqual(self.store.descriptors('python.exe',{}),{})
 def test_empty_missing_and_invalid_directories_return_empty_catalog(self):
  self.assertEqual(self.store.descriptors('python.exe',{}),{})
  directory=self.store.root/'profiles';directory.mkdir(parents=True)
  self.assertEqual(self.store.descriptors('python.exe',{}),{})
  (directory/'broken.json').write_text('{broken')
  self.assertEqual(self.store.descriptors('python.exe',{}),{})
 def test_arbitrary_profile_roundtrip_preserves_backup_and_stale_guard(self):
  self.profile('my-model',args=['--max-context','98304','--kv','int8'])
  values,snapshot=self.store.load('my-model');values.update(name='Workstation',context='65536',reasoning='0',effort='none')
  backup=self.store.save('my-model',values,snapshot)
  self.assertTrue((backup/'my-model.json').exists())
  self.assertEqual(self.store.descriptors('python.exe',{})['my-model']['name'],'Workstation · 2 agents · 64K each')
  with self.assertRaisesRegex(ValueError,'changed outside'):self.store.save('my-model',values,snapshot)

if __name__=='__main__':unittest.main()
