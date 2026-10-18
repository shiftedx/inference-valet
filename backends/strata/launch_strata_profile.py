"""Interactive local Strata launcher: no automatic termination of other services."""
import argparse,json,os,pathlib,socket,subprocess,sys,time,urllib.request,threading,secrets,hashlib
import psutil
import ctypes
class Perf(ctypes.Structure):
    _fields_=[('cb',ctypes.c_ulong),('CommitTotal',ctypes.c_size_t),('CommitLimit',ctypes.c_size_t),('CommitPeak',ctypes.c_size_t),('PhysicalTotal',ctypes.c_size_t),('PhysicalAvailable',ctypes.c_size_t),('SystemCache',ctypes.c_size_t),('KernelTotal',ctypes.c_size_t),('KernelPaged',ctypes.c_size_t),('KernelNonpaged',ctypes.c_size_t),('PageSize',ctypes.c_size_t),('HandleCount',ctypes.c_ulong),('ProcessCount',ctypes.c_ulong),('ThreadCount',ctypes.c_ulong)]
def commit_headroom():
    p=Perf();p.cb=ctypes.sizeof(p)
    if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(p),p.cb):return (p.CommitLimit-p.CommitTotal)*p.PageSize/2**30
    return None
ROOT=pathlib.Path(__file__).resolve().parent
INSTALL=ROOT/'Strata'
PY=INSTALL/'.venv/Scripts/python.exe'
def fetch(path,base):return json.load(urllib.request.urlopen(base+path,timeout=10))
def profile_path(name):
    # Keep the standalone wrapper's filename contract aligned with Valet discovery.
    if (not isinstance(name,str) or not name or name.startswith('-') or name in ('.','..')
            or name!=name.rstrip(' .') or len(name)>180
            or any(ord(c)<32 or c in '<>:"/\\|?*' for c in name)
            or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
            or name.casefold().endswith('.shared-settings')):
        raise ValueError('Choose an existing profile filename stem.')
    directory=ROOT/'profiles'
    if directory.is_symlink() or directory.resolve().parent!=ROOT.resolve():raise ValueError('Profiles directory must stay inside the backend root.')
    path=directory/(name+'.json');shared=path.with_suffix('.shared-settings.json')
    for candidate in (path,shared):
        if candidate.is_symlink() or candidate.resolve().parent!=directory.resolve():raise ValueError('Profile and settings files must stay inside the profiles directory.')
    if not path.is_file():raise ValueError('Profile must be an existing JSON file inside the profiles directory.')
    return path

def profile_config(name):
    template=profile_path(name)
    cfg=json.loads(template.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg,dict):raise ValueError('Profile must be a JSON object.')
    cfg.setdefault('parallel',1)
    model=cfg.get('model_name') or cfg.get('model')
    if not isinstance(model,str) or not model.strip():raise ValueError('Profile requires a model_name or model identifier.')
    cfg['model_name']=model
    return template,cfg

def main():
    ap=argparse.ArgumentParser();ap.add_argument('profile',help='Existing profile JSON filename stem');ap.add_argument('--verify',action='store_true');ap.add_argument('--on-demand',action='store_true');a=ap.parse_args()
    a.verify=a.verify or os.environ.get('STRATA_LAUNCH_VERIFY')=='1'
    try:template,cfg=profile_config(a.profile)
    except ValueError as exc:ap.error(str(exc))
    maximum=cfg.pop('launcher_max_vram_used_mib',None)
    bind=os.environ.get('STRATA_VALET_BIND',cfg.get('host','127.0.0.1'));port=int(cfg.get('port',8080));base=f'http://127.0.0.1:{port}'
    conflicts=[]
    for p in psutil.process_iter(['name']):
        if (p.info['name'] or '').lower() in ('strata.exe',):conflicts.append(f"{p.info['name']} (PID {p.pid})")
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:conflicts.append(f'port {port} is already occupied')
    try:
        used=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True,timeout=10).strip().splitlines()[0])
        if maximum is not None and used>maximum:conflicts.append(f'GPU already uses {used/1024:.1f} GiB; stop the GPU workload first')
    except Exception as exc:print('Cannot verify GPU availability:',exc);return 1
    if a.on_demand:conflicts=[c for c in conflicts if 'port ' in c or 'strata' in c.lower()]
    if conflicts:
        print('Strata was not started. Resource conflict: '+ '; '.join(conflicts))
        print('Stop the active workload, then try again. This launcher never kills unrelated services.')
        return 2
    minimum=cfg.pop('launcher_min_available_ram_gib',0)
    estimated=cfg.pop('launcher_estimated_commit_gib',0)
    available=psutil.virtual_memory().available/2**30
    if not a.on_demand and available<minimum:print(f'Strata was not started: {available:.1f} GiB RAM available; this profile requires at least {minimum} GiB before loading.');return 2
    headroom=commit_headroom()
    print(f'Preflight: {available:.1f} GiB RAM available; Windows commit headroom {headroom:.1f} GiB.' if headroom is not None else f'Preflight: {available:.1f} GiB RAM available; commit counter unavailable.')
    if not a.on_demand and headroom is not None and headroom<estimated:
        print(f'Strata was not started: this profile needs approximately {estimated} GiB additional Windows commit. Close memory-heavy apps and try again. No pagefile settings were changed.');return 2
    logs=ROOT/'profile-logs';logs.mkdir(exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S');cfg['log']=str(logs/f'{a.profile}-{stamp}-engine.log')
    cfg['host']=bind;cfg['port']=port;cfg['open_browser']=False
    if a.on_demand:cfg['lazy_load']=True
    run=logs/f'{a.profile}-{stamp}.json';run.write_text(json.dumps(cfg,indent=2))
    shared=template.with_suffix('.shared-settings.json')
    if shared.exists():
        defaults=json.loads(shared.read_text(encoding='utf-8-sig'))
        run.with_suffix('.shared-settings.json').write_text(json.dumps(defaults,indent=2))
    print(f"Starting {a.profile}: {cfg['parallel']} agent(s), total window {cfg['args'][cfg['args'].index('--max-context')+1]} tokens per agent")
    print(f'Local API: {base}/v1   Web UI: {base}   Bind: {bind}:{port}')
    if bind=='0.0.0.0':print(f'LAN API: http://{socket.gethostname()}:{port}/v1 (or this PC\'s LAN IP); unauthenticated, subject to the existing firewall.')
    print('Press Ctrl+C in this window to stop gracefully. Logs:',logs)
    token=secrets.token_hex(24);stopfile=logs/('stop-'+token+'.request');statefile=logs/'active-profile.json'
    env=dict(os.environ,STRATA_LOCAL_STOP_FILE=str(stopfile),STRATA_LOCAL_STOP_TOKEN=token)
    if a.on_demand:
        env['STRATA_VALET_ROOT']=os.environ['STRATA_VALET_ROOT']
        env['STRATA_ENGINE_READY_S']='300'
        env['STRATA_VISION_READY_S']='120'
    wrapper=ROOT/'managed_strata_server.py'
    child=subprocess.Popen([str(PY),str(wrapper),'--engine','strata','--config',str(run),'--host',bind,'--port',str(port)],cwd=INSTALL,env=env)
    state=dict(profile=a.profile,model=cfg['model_name'],port=port,bind=bind,launcher_pid=os.getpid(),launcher_started=psutil.Process().create_time(),server_pid=child.pid,server_started=psutil.Process(child.pid).create_time(),token=token,stop_file=stopfile.name,config=str(run),launcher_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),server_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest())
    tmp=statefile.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2));tmp.replace(statefile)
    def clear_state():
        try:
            if json.loads(statefile.read_text()).get('token')==token:statefile.unlink()
        except (OSError,ValueError):pass
        stopfile.unlink(missing_ok=True)
    done=threading.Event();rejected=threading.Event()
    def guard():
        low=None
        while not done.wait(.5) and child.poll() is None:
            margin=commit_headroom();ram=psutil.virtual_memory().available/2**30
            if margin is None:
                risky=True
            else:risky=margin<2 or ram<4
            if a.on_demand:
                try:risky=risky and fetch('/health',base).get('loaded',False)
                except Exception:risky=False
            if risky and low is None:low=time.monotonic()
            if not risky:low=None
            if (not a.on_demand and margin is not None and margin<1) or (low is not None and time.monotonic()-low>=3):
                rejected.set();print(f'MEMORY GUARD: stopping this Strata server. Commit headroom {margin} GiB, RAM {ram:.2f} GiB.',flush=True)
                try:
                    req=urllib.request.Request(base+'/unload',data=b'{}',headers={'Content-Type':'application/json','Origin':base})
                    urllib.request.urlopen(req,timeout=5).close()
                except Exception:pass
                try:
                    children=psutil.Process(child.pid).children(recursive=True)
                    for p in children:
                        if p.is_running() and p.name().lower()=='strata.exe':p.terminate()
                    if child.poll() is None:child.terminate()
                except psutil.NoSuchProcess:pass
                return
    threading.Thread(target=guard,daemon=True).start()
    if a.verify:
        try:
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                if child.poll() is not None:raise RuntimeError('server exited before readiness')
                try:
                    h=fetch('/health',base);status=fetch('/v1/status',base)
                    if h.get('loaded'):
                        serving=status.get('concurrency',{}).get('serving',1)
                        if serving!=cfg['parallel']:raise RuntimeError(f'Expected {cfg["parallel"]} slots, got {serving}')
                        evidence=dict(health=h,status=status,bind=bind,port=port,models=fetch('/v1/models',base))
                        lan=os.environ.get('STRATA_VERIFY_LAN_IP')
                        if lan:
                            lanbase=f'http://{lan}:{port}'
                            evidence['lan']=dict(url=lanbase,health=fetch('/health',lanbase),models=fetch('/v1/models',lanbase))
                            body=dict(model=cfg['model_name'],messages=[dict(role='user',content='Reply with only the digit 4.')],max_tokens=8,temperature=0,enable_thinking=False,chat_template_kwargs={'enable_thinking':False})
                            req=urllib.request.Request(lanbase+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':lanbase})
                            answer=json.load(urllib.request.urlopen(req,timeout=60))
                            evidence['lan']['same_origin_inference']=dict(model=answer.get('model'),content=answer['choices'][0]['message']['content'])
                            evidence['lan']['same_origin_pass']=answer['choices'][0]['message']['content'].strip()=='4'
                            if not evidence['lan']['same_origin_pass']:raise RuntimeError('LAN inference smoke test failed')
                            try:
                                req=urllib.request.Request(lanbase+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':'https://example.invalid'})
                                urllib.request.urlopen(req,timeout=10).close();raise RuntimeError('Foreign browser Origin was unexpectedly allowed')
                            except urllib.error.HTTPError as e:
                                evidence['lan']['foreign_origin_status']=e.code
                                if e.code!=403:raise
                            listeners=[]
                            for p in [psutil.Process(child.pid),*psutil.Process(child.pid).children(recursive=True)]:
                                try:
                                    for c in p.net_connections(kind='tcp'):
                                        if c.status=='LISTEN' and c.laddr.port==port:listeners.append(dict(pid=p.pid,address=c.laddr.ip,port=c.laddr.port))
                                except (psutil.AccessDenied,psutil.NoSuchProcess):pass
                            evidence['listeners']=listeners
                        print('LAUNCH VERIFIED',json.dumps(evidence))
                        (logs/f'{a.profile}-{stamp}-verification.json').write_text(json.dumps(evidence,indent=2))
                        req=urllib.request.Request(base+'/unload',data=b'{}',headers={'Content-Type':'application/json','Origin':base})
                        print('Graceful engine unload:',urllib.request.urlopen(req,timeout=60).read().decode())
                        return 0
                except RuntimeError:raise
                except Exception:pass
                time.sleep(2)
            raise RuntimeError('readiness timeout')
        finally:
            done.set()
            # Verification only: engine was unloaded through its API before ending our idle server.
            if child.poll() is None:child.terminate();child.wait(timeout=30)
            clear_state()
    try:
        result=child.wait();return 3 if rejected.is_set() else result
    except KeyboardInterrupt:
        print('\nWaiting for Strata to stop gracefully...')
        try:child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            print('Strata is still stopping. Press Ctrl+C in its window again if you want to force its own shutdown.');return 1
        return 0
    finally:done.set();clear_state()
if __name__=='__main__':sys.exit(main())
