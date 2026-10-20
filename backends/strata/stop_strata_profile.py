"""Stop only a verified managed Strata instance; never kill by name or shared port."""
import hashlib,json,pathlib,socket,sys,time,urllib.request,psutil
root=pathlib.Path(__file__).resolve().parent;logs=root/'profile-logs';state_path=logs/'active-profile.json'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(pid,created,script):
    try:
        p=psutil.Process(pid)
        if abs(p.create_time()-created)>.01:raise RuntimeError('PID was reused')
        if pathlib.Path(p.exe()).resolve()!=pathlib.Path(psutil.Process().exe()).resolve():raise RuntimeError('Unexpected Python executable')
        args=p.cmdline()
        if len(args)<2 or pathlib.Path(args[1]).resolve()!=script.resolve():raise RuntimeError('Unexpected process script')
        if script==root/'launch_strata_profile.py' and p.cwd().lower()!=str(root).lower():raise RuntimeError('Unexpected launcher working directory')
        return p
    except psutil.NoSuchProcess:return None
def main():
    try:state=json.loads(state_path.read_text())
    except FileNotFoundError:state=None
    # The local ownership record works before the HTTP server is ready, too.
    # Never use a shared port or readiness as proof of process ownership.
    if not state:print('No managed Strata server is running.');return 0
    if state['launcher_sha256']!=digest(root/'launch_strata_profile.py') or state['server_sha256']!=digest(root/'managed_strata_server.py'):raise RuntimeError('Managed script provenance changed')
    launcher=identity(state['launcher_pid'],state['launcher_started'],root/'launch_strata_profile.py')
    if launcher is None:raise RuntimeError('Stale launcher ownership record')
    server=psutil.Process(state['server_pid'])
    if abs(server.create_time()-state['server_started'])>.01:raise RuntimeError('Server PID reused')
    children=launcher.children(recursive=True)
    if not any(p.pid==server.pid for p in children):raise RuntimeError('Server is not owned by the verified launcher')
    server_scripts=[]
    for p in [server,*server.children(recursive=True)]:
        try:
            if p.name().lower() not in ('python.exe','pythonw.exe'):continue
            args=p.cmdline()
            if len(args)>1 and pathlib.Path(args[1]).resolve()==(root/'managed_strata_server.py').resolve():server_scripts.append(p)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    if not server_scripts:raise RuntimeError('Server is not the verified managed script')
    path=logs/state['stop_file']
    if path.parent!=logs or path.name!='stop-'+state['token']+'.request':raise RuntimeError('Invalid stop request path')
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'token':state['token']}));tmp.replace(path)
    print('Requested graceful Strata shutdown; waiting for the server and GPU engine...',flush=True)
    for _ in range(480):
        if not launcher.is_running() and not server.is_running():
            print('Strata stopped.');return 0
        time.sleep(.25)
    print('Shutdown did not finish within 120 seconds. Check the launch window; nothing was force-killed.');return 1
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('Refused to stop: '+str(e));sys.exit(2)
