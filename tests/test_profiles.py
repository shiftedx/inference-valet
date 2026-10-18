import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_profiles import ProfileStore, argument

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        root=pathlib.Path(self.directory.name)
        self.store=ProfileStore(root/'backend',root/'state');self.key='strata-128k'
        self.path,self.shared,_=self.store.paths(self.key);self.path.parent.mkdir(parents=True)
        self.data=dict(exe='engine.exe',model_name='test-model',parallel=1,args=['--max-context','163840','--kv','int8',
            '--kv-resident','32768','--native','keep-model.gguf','--expert-cache','auto',
            '--prefill','8192','--spec','4'],vision={'gpu':True,'max_tokens':1024},
            env={'UNCHANGED':'yes'},launcher_min_available_ram_gib=26,fit_max_tokens=True)
        self.path.write_text(json.dumps(self.data),encoding='utf-8')
        self.shared.write_text(json.dumps(dict(max_tokens=73728,reasoning_budget_tokens=32768,
            reasoning_effort='high',temperature=.7)),encoding='utf-8')

    def test_save_updates_both_files_and_catalog_keeps_unexposed_settings(self):
        values,snapshot=self.store.load(self.key);before=self.path.read_bytes()
        values.update(name='Focused',context='131072',slots='2',kv='q4_0',max_tokens='60000',reasoning='30000',prefill='auto')
        backup=self.store.save(self.key,values,snapshot)
        saved=json.loads(self.path.read_text());shared=json.loads(self.shared.read_text())
        self.assertEqual(argument(saved['args'],'--max-context'),'131072')
        self.assertEqual(argument(saved['args'],'--prefill'),'auto')
        self.assertEqual(saved['parallel'],2);self.assertEqual(shared['max_tokens'],60000)
        self.assertEqual(saved['env'],self.data['env']);self.assertEqual(saved['vision'],self.data['vision'])
        self.assertEqual(saved['launcher_min_available_ram_gib'],26)
        self.assertEqual(argument(saved['args'],'--native'),'keep-model.gguf')
        self.assertEqual(shared['temperature'],.7)
        self.assertEqual((backup/self.path.name).read_bytes(),before)
        profiles=self.store.descriptors('python.exe',{'enabled_profiles':[self.key]})
        self.assertEqual(profiles[self.key]['name'],'Focused · 2 agents · 128K each')
        self.assertEqual(profiles[self.key]['model'],'test-model')
        self.assertEqual(self.store.load(self.key)[0]['context'],'131072')

    def test_validation_rejects_bad_values_without_writing(self):
        values,snapshot=self.store.load(self.key);before=[p.read_bytes() for p in (self.path,self.shared)]
        for field,value in [('name',''),('context','nan'),('slots','0'),('context','1024'),
                            ('max_tokens','200000'),('reasoning','-1'),('workers','-1'),
                            ('resident','NaN'),('pcie','1.1'),('kv','invented'),('effort','xhigh')]:
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):self.store.save(self.key,dict(values,**{field:value}),snapshot)
                self.assertEqual([p.read_bytes() for p in (self.path,self.shared)],before)

    def test_external_change_conflict_keeps_external_edit(self):
        values,snapshot=self.store.load(self.key)
        self.shared.write_text('{"max_tokens":1234}')
        with self.assertRaisesRegex(ValueError,'changed outside'):self.store.save(self.key,values,snapshot)
        self.assertEqual(json.loads(self.shared.read_text()),{'max_tokens':1234})

    def test_failed_second_replace_restores_all_original_bytes(self):
        values,snapshot=self.store.load(self.key)
        before=[path.read_bytes() for path in (self.path,self.shared)]
        replace=pathlib.Path.replace
        def fail_second(path,target):
            if target==self.shared:raise OSError('Disk unavailable')
            return replace(path,target)
        with patch.object(pathlib.Path,'replace',fail_second):
            with self.assertRaises(OSError):self.store.save(self.key,values,snapshot)
        self.assertEqual([path.read_bytes() for path in (self.path,self.shared)],before)
        self.assertFalse(self.store.names_path.exists())
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_clear_output_default_preserves_shared_sampling(self):
        values,snapshot=self.store.load(self.key);values['max_tokens']=''
        self.store.save(self.key,values,snapshot)
        shared=json.loads(self.shared.read_text());self.assertNotIn('max_tokens',shared)
        self.assertEqual(shared['temperature'],.7)

    def test_duplicate_display_names_remain_selectable(self):
        path=self.store.paths('strata-3')[0];path.write_text(json.dumps(self.data))
        profiles=self.store.descriptors('python.exe',{'enabled_profiles':[self.key,'strata-3']})
        self.assertEqual(len({row['name'] for row in profiles.values()}),2)

if __name__=='__main__':unittest.main()
