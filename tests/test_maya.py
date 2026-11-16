import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

import ai_maya


class MayaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.settings=dict(server_python=sys.executable,server_script=str(self.root/'serve/server.py'),
            tokenizer=str(self.root/'tokenizer'),pack=str(self.root/'pack'),env={'MAYA_DS4_DISK_SKIP_W':'0'})
        self.profile=dict(exe=self.root/'ds41_generate.exe',artifact=self.root/'model.gguf',
            model='deepseek',context=65536,slots=1,args=['--experts','6','--vision','on'],maya=self.settings)

    def test_launch_pins_model_context_transport_and_keeps_secrets_out(self):
        command,path,env=ai_maya.launch(self.profile,self.root)
        cfg=json.loads(path.read_text())
        self.assertEqual(cfg['args'][:4],['--pack',self.settings['pack'],'--max-context','65536'])
        self.assertEqual(command[-4:],['--host','127.0.0.1','--port','8080'])
        self.assertEqual(cfg['parallel'],1)
        self.assertEqual(cfg['model_name'],'deepseek')
        self.assertNotIn('api_key',cfg)
        self.assertEqual(env,self.settings['env'])

    def test_runtime_and_profile_tampering_are_rejected(self):
        command,path,_=ai_maya.launch(self.profile,self.root)
        record=dict(command=command,runtime_config=str(path),runtime_sha256=ai_maya.fingerprint(path),
            settings_sha256=hashlib.sha256(json.dumps(self.settings,sort_keys=True).encode()).hexdigest())
        self.assertTrue(ai_maya.matching_profile(record,self.profile,command))
        self.assertFalse(ai_maya.matching_profile(record,{**self.profile,'context':32768},command))
        self.assertFalse(ai_maya.matching_record(record,command+['--open']))
        path.write_text('{}')
        self.assertFalse(ai_maya.matching_record(record,command))

    def test_model_and_context_override_aliases_are_rejected(self):
        entry={**self.settings,'slots':1,'args':[]}
        ai_maya.validate(entry)
        for args in [['--ctx','1'],['--model=other'],['-m','other'],['--serve'],['--rpc','host']]:
            with self.subTest(args=args),self.assertRaises(ValueError):ai_maya.validate({**entry,'args':args})
        with self.assertRaises(ValueError):ai_maya.validate({**entry,'slots':2})
        for name in ('STRATA_API_KEY','MAYA_API_KEY'):
            with self.assertRaises(ValueError):ai_maya.validate({**entry,'env':{name:'secret'}})

    def test_readiness_requires_live_model_context_slot_and_health(self):
        status=dict(service='maya',model='deepseek',context={'native':65536},concurrency={'serving':1})
        fetch=lambda path:status if path=='/v1/status' else [{'n_ctx':65536}] if path=='/slots' else {'status':'ok','unloaded':False}
        self.assertTrue(ai_maya.ready(self.profile,fetch))
        for change in [{'service':'other'},{'model':'other'},{'context':{'native':8192}},{'concurrency':{'serving':2}}]:
            bad={**status,**change}
            self.assertFalse(ai_maya.ready(self.profile,lambda path:bad if path=='/v1/status' else fetch(path)))

    def test_missing_split_shard_fails_preflight(self):
        script=pathlib.Path(self.settings['server_script']);script.parent.mkdir();script.touch()
        tok=pathlib.Path(self.settings['tokenizer']);tok.mkdir();(tok/'vocab.json').write_text('{}')
        pack=self.root/'pack';pack.mkdir()
        for name in ('ds4.txt','tensors.txt','engram.bin'):(pack/name).touch()
        model=self.root/'test-00001-of-00002.gguf';model.touch()
        with self.assertRaisesRegex(ValueError,'Missing Maya model shard'):
            ai_maya.verify_assets({**self.profile,'artifact':model})
        (self.root/'test-00002-of-00002.gguf').touch()
        ai_maya.verify_assets({**self.profile,'artifact':model})



    def test_missing_packed_vision_fails_before_switch(self):
        script=pathlib.Path(self.settings['server_script']);script.parent.mkdir();script.touch()
        tok=self.root/'tokenizer';tok.mkdir();(tok/'vocab.json').touch()
        model=self.root/'model.gguf';model.touch()
        pack=self.root/'pack';pack.mkdir();(pack/'engram.bin').touch()
        (pack/'ds4.txt').write_text('model_dir '+str(self.root)+'\n')
        (pack/'tensors.txt').write_text('file 0 missing-vision.bin\n')
        with self.assertRaisesRegex(ValueError,'Missing Maya packed asset'):
            ai_maya.verify_assets(self.profile)

    def test_unloaded_or_dead_engine_is_not_ready(self):
        status=dict(service='maya',model='deepseek',context={'native':65536},concurrency={'serving':1})
        for health,slots in [({'status':'ok','unloaded':True},[{'n_ctx':65536}]),({'status':'ok','unloaded':False},[])]:
            self.assertFalse(ai_maya.ready(self.profile,lambda path:status if path=='/v1/status' else slots if path=='/slots' else health))


    def test_catalog_capacity_and_explicit_vision(self):
        from ai_provider_runtime import catalog
        profile={**self.profile,'engine':'maya'}
        result=catalog({'maya':profile},None)['maya']
        self.assertEqual(result['kv_cache_tokens'],65536)
        self.assertEqual(result['kv_cache_tokens_per_slot'],65536)
        self.assertIsNone(result['default_max_output_tokens'])
        self.assertEqual(result['max_output_tokens'],65536)
        self.assertTrue(result['output_tokens_share_context'])
        self.assertTrue(result['supports_vision'])
        profile['args']=['--vision','off']
        self.assertFalse(catalog({'maya':profile},None)['maya']['supports_vision'])

if __name__=='__main__':unittest.main()
