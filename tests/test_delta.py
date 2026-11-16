import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

import ai_delta


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.settings=dict(server_python=sys.executable,server_script=str(self.root/'serve_ds41.py'),
            tokenizer=str(self.root/'tokenizer'),env={'STRATA_ARENA_PIN_GIB':'20'})
        self.profile=dict(exe=self.root/'ds41_generate.exe',artifact=self.root/'model.gguf',
            model='deepseek',context=65536,slots=1,args=['--route-bias','0','--arena-gib','26'],delta=self.settings)

    def test_launch_pins_model_context_transport_and_keeps_secrets_out(self):
        command,path,env=ai_delta.launch(self.profile,self.root)
        cfg=json.loads(path.read_text())
        self.assertEqual(cfg['args'][:4],['-m',str(self.profile['artifact']),'--ctx','65536'])
        self.assertEqual(command[-4:],['--host','127.0.0.1','--port','8080'])
        self.assertEqual(cfg['parallel'],1)
        self.assertEqual(cfg['model_name'],'deepseek')
        self.assertNotIn('api_key',cfg)
        self.assertEqual(env,self.settings['env'])

    def test_runtime_and_profile_tampering_are_rejected(self):
        command,path,_=ai_delta.launch(self.profile,self.root)
        record=dict(command=command,runtime_config=str(path),runtime_sha256=ai_delta.fingerprint(path),
            settings_sha256=hashlib.sha256(json.dumps(self.settings,sort_keys=True).encode()).hexdigest())
        self.assertTrue(ai_delta.matching_profile(record,self.profile,command))
        self.assertFalse(ai_delta.matching_profile(record,{**self.profile,'context':32768},command))
        self.assertFalse(ai_delta.matching_record(record,command+['--open']))
        path.write_text('{}')
        self.assertFalse(ai_delta.matching_record(record,command))

    def test_model_and_context_override_aliases_are_rejected(self):
        entry={**self.settings,'slots':1,'args':[]}
        ai_delta.validate(entry)
        for args in [['--ctx','1'],['--model=other'],['-m','other'],['--serve'],['--rpc','host']]:
            with self.subTest(args=args),self.assertRaises(ValueError):ai_delta.validate({**entry,'args':args})
        with self.assertRaises(ValueError):ai_delta.validate({**entry,'slots':2})
        with self.assertRaises(ValueError):ai_delta.validate({**entry,'env':{'STRATA_API_KEY':'secret'}})

    def test_readiness_requires_live_model_context_slot_and_health(self):
        status=dict(loaded=True,model='deepseek',context={'native':65536},concurrency={'serving':1})
        fetch=lambda path:status if path=='/v1/status' else {'status':'ok'}
        self.assertTrue(ai_delta.ready(self.profile,fetch))
        for change in [{'loaded':False},{'model':'other'},{'context':{'native':8192}},{'concurrency':{'serving':2}}]:
            bad={**status,**change}
            self.assertFalse(ai_delta.ready(self.profile,lambda path:bad if path=='/v1/status' else {'status':'ok'}))

    def test_missing_split_shard_fails_preflight(self):
        script=pathlib.Path(self.settings['server_script']);script.touch()
        tok=pathlib.Path(self.settings['tokenizer']);tok.mkdir();(tok/'vocab.json').write_text('{}')
        model=self.root/'test-00001-of-00002.gguf';model.touch()
        with self.assertRaisesRegex(ValueError,'Missing Delta model shard'):
            ai_delta.verify_assets({**self.profile,'artifact':model})
        (self.root/'test-00002-of-00002.gguf').touch()
        ai_delta.verify_assets({**self.profile,'artifact':model})


if __name__=='__main__':unittest.main()
