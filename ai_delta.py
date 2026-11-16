"""Local Delta/DeepSeek adapter; fixed loopback, context and owned launch contract."""
import hashlib
import json
import pathlib
import re
import tempfile


RESERVED = {'-m','--model','--ctx','--serve','--gpus','--model-url','--rpc'}


def validate(entry):
    if entry.get('slots',1) != 1:
        raise ValueError('Delta supports one serving slot')
    for name in ('server_python','server_script','tokenizer'):
        path = pathlib.Path(entry.get(name,''))
        if not path.is_absolute():raise ValueError('Delta requires absolute '+name)
    if pathlib.Path(entry['server_script']).name != 'serve_ds41.py':
        raise ValueError('Delta requires its serve_ds41.py adapter')
    env = entry.get('env',{})
    if not isinstance(env,dict) or any(not isinstance(k,str) or not isinstance(v,str)
            or k=='STRATA_API_KEY' or not (k.startswith('STRATA_') or k in ('PYTHONPATH','CUDA_DEVICE_ORDER','CUDA_VISIBLE_DEVICES')) for k,v in env.items()):
        raise ValueError('Invalid Delta launch environment')
    args = entry.get('args',[])
    if not isinstance(args,list) or any(not isinstance(a,str) or a.partition('=')[0] in RESERVED for a in args):
        raise ValueError('Delta args must not override model, context or transport')


def verify_assets(profile):
    settings=profile['delta']
    for name in ('server_python','server_script'):
        if not pathlib.Path(settings[name]).is_file():raise ValueError('Missing Delta '+name)
    if not (pathlib.Path(settings['tokenizer'])/'vocab.json').is_file():
        raise ValueError('Missing Delta tokenizer')
    model=pathlib.Path(profile['artifact'])
    split=re.fullmatch(r'(.*)-(\d{5})-of-(\d{5})\.gguf',model.name)
    if split:
        for number in range(1,int(split[3])+1):
            shard=model.with_name(f'{split[1]}-{number:05d}-of-{split[3]}.gguf')
            if not shard.is_file():raise ValueError('Missing Delta model shard: '+shard.name)
    draft=settings.get('env',{}).get('STRATA_SERVE_DSPARK')
    if draft and not pathlib.Path(draft).is_file():raise ValueError('Missing Delta drafter')


def launch(profile, state_dir):
    settings=profile['delta']
    cfg=dict(exe=str(profile['exe']),args=['-m',str(profile['artifact']),'--ctx',str(profile['context']),*profile['args']],
        cwd=str(pathlib.Path(settings['server_script']).parents[3]),tokenizer=settings['tokenizer'],
        model_name=profile['model'],parallel=1,host='127.0.0.1',port=8080,engine_ready_s=600,
        max_tokens=32768,reasoning_effort='high',reasoning_budget_tokens=32768,
        sampling=dict(temperature=1.0,top_p=1.0,top_k=64,min_p=0.0),open_browser=False,api_monitor=False)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json',prefix='delta-run-',dir=state_dir,delete=False) as stream:
        path=pathlib.Path(stream.name)
        cfg['log']=str(path.with_suffix('.engine.log'))
        json.dump(cfg,stream,indent=2)
    command=[settings['server_python'],settings['server_script'],'--engine','strata','--config',str(path),
             '--host','127.0.0.1','--port','8080']
    return command,path,dict(settings.get('env',{}))


def fingerprint(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def matching_record(record,command):
    return (command==record.get('command') and fingerprint(record['runtime_config'])==record.get('runtime_sha256'))


def matching_profile(record,profile,command):
    if not matching_record(record,command):return False
    settings=profile['delta'];cfg=json.loads(pathlib.Path(record['runtime_config']).read_text())
    return (pathlib.Path(command[0]).resolve()==pathlib.Path(settings['server_python']).resolve()
        and pathlib.Path(command[1]).resolve()==pathlib.Path(settings['server_script']).resolve()
        and pathlib.Path(cfg['exe']).resolve()==pathlib.Path(profile['exe']).resolve()
        and cfg['args']==['-m',str(profile['artifact']),'--ctx',str(profile['context']),*profile['args']]
        and cfg['model_name']==profile['model'] and cfg['tokenizer']==settings['tokenizer']
        and record.get('settings_sha256')==hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest())


def ready(profile,fetch):
    status=fetch('/v1/status')
    return (status.get('loaded') is True and status.get('model')==profile['model']
        and status.get('context',{}).get('native')==profile['context']
        and status.get('concurrency',{}).get('serving')==1
        and fetch('/health').get('status')=='ok')
