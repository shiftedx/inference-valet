"""One desktop picker and stop action for the installed Strata server."""
import argparse,contextlib,json,msvcrt,os,pathlib,queue,secrets,socket,subprocess,sys,threading,time,urllib.request
import psutil
from concurrent.futures import ThreadPoolExecutor

ROOT=pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ai_telemetry import Collector,PerformancePanel,THEME,strata_listener
from ai_widgets import Surface,Button,Switch,ProfileSelect,ui_font
from ai_idle import Settings,IdlePolicy,GameDetector,idle_seconds,IDLE_MINUTES
from ai_recovery import RecoveryPolicy,listener_present
from ai_issues import record_issue,failure_code
from ai_config import CONFIG,STRATA_ROOT,STRATA_PYTHON,STATE_DIR,WINDOWS_ROOT
def taskbar_position(monitor,work,size):
 left,top,right,bottom=work;width,height=size;margin=12
 x=right-width-margin;y=bottom-height-margin
 if top>monitor[1]:y=top+margin
 elif left>monitor[0]:x=left+margin
 return max(left,min(x,right-width)),max(top,min(y,bottom-height))

def popup_size(work,scale,content_height):
 """Fit a logical-width flyout into a physical-pixel work area."""
 width=max(1,work[2]-work[0]-24);height=max(1,work[3]-work[1]-24)
 return min(width,round(380*scale)),min(height,round(content_height*scale))

def enable_dpi_awareness():
 """Let Tk and Win32 use the same physical pixels on scaled Windows displays."""
 import ctypes
 try:
  user=ctypes.windll.user32
  user.SetProcessDpiAwarenessContext.argtypes=[ctypes.c_void_p]
  user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
 except (OSError,AttributeError):pass
def native_window_style(window):
 """Use Windows' dark title bar and rounded corners when the OS supports them."""
 import ctypes
 from ctypes import wintypes
 try:
  window.update_idletasks();user=ctypes.windll.user32;user.GetParent.restype=wintypes.HWND
  hwnd=user.GetParent(window.winfo_id()) or window.winfo_id()
  def colorref(hex_color):
   red,green,blue=bytes.fromhex(hex_color.lstrip('#'));return red|(green<<8)|(blue<<16)
  for attribute,value in [(20,1),(33,2),(34,colorref(THEME['bg'])),(35,colorref(THEME['bg'])),(36,colorref(THEME['text']))]:
   data=ctypes.c_int(value);ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd),attribute,ctypes.byref(data),ctypes.sizeof(data))
 except (OSError,AttributeError):pass
STRATA=STRATA_ROOT
PY=STRATA_PYTHON
PS=WINDOWS_ROOT/'System32/WindowsPowerShell/v1.0/powershell.exe'
LOGS=STATE_DIR
IDLE_SETTINGS=Settings(LOGS/'idle-settings.json')
HIDDEN=subprocess.CREATE_NO_WINDOW
from ai_profiles import ProfileStore
PROFILE_STORE=ProfileStore(STRATA,LOGS)
PROFILES={};PROFILE_NAMES={}
def reload_profiles():
 global PROFILES,PROFILE_NAMES
 profiles=PROFILE_STORE.descriptors(PY,CONFIG)
 PROFILES=profiles;PROFILE_NAMES={key:cfg['name'] for key,cfg in profiles.items()}
reload_profiles()

def same(a,b):return pathlib.Path(a).resolve()==pathlib.Path(b).resolve()
# Names only shortlist candidates; executable and script paths still establish ownership.
SERVER_NAMES={'strata.exe','strata-vision.exe',PY.name.lower(),PY.with_name('pythonw.exe').name.lower(),pathlib.Path(sys.executable).name.lower(),'python.exe','pythonw.exe'}

def classify(exe,args):
 if pathlib.Path(exe).name.lower() not in SERVER_NAMES:return None
 for name,kind in [('strata.exe','strata-engine'),('strata-vision.exe','strata-vision')]:
  if same(exe,STRATA/'Strata/engine'/name):return kind
 interpreters=[PY,PY.with_name('pythonw.exe'),pathlib.Path(psutil.Process().exe()).with_name('python.exe'),pathlib.Path(psutil.Process().exe()).with_name('pythonw.exe')]
 if len(args)>1 and any(same(exe,p) for p in interpreters):
  for script,kind in [('launch_strata_profile.py','strata-launcher'),('managed_strata_server.py','strata-server'),('Strata/serve/server.py','strata-server')]:
   if same(args[1],STRATA/script):return kind
 return None

def servers():
 found=[]
 for p in psutil.process_iter(['name']):
  try:
   if (p.info['name'] or '').lower() not in SERVER_NAMES:continue
   exe=p.exe()
   if exe and (kind:=classify(exe,p.cmdline() or [])):found.append((p,kind))
  except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):pass
 return found

def validate_profile(key):
 cfg=PROFILES[key]
 if not pathlib.Path(cfg['command'][0]).is_file():raise ValueError('Strata Python is missing. Check strata_python in config.json.')
 c=json.loads((STRATA/'profiles'/(cfg['profile']+'.json')).read_text(encoding='utf-8-sig'));a=c['args']
 if int(a[a.index('--max-context')+1])!=cfg['context'] or c['parallel']!=cfg['slots']:
  raise ValueError('The profile changed externally. Restart Valet to refresh its settings.')
 if not c.get('vision',{}).get('gpu') or '--vision' not in a:raise ValueError('This Strata profile requires GPU vision support.')
 for flag in ['--pack','--native','--ple-gguf','--mtp']:
  if not pathlib.Path(a[a.index(flag)+1]).exists():raise ValueError(f'Missing model path for {flag}. Check the Strata profile file.')
 return cfg

@contextlib.contextmanager
def control_lock(timeout=150):
 LOGS.mkdir(parents=True,exist_ok=True)
 with (LOGS/'control.lock').open('a+b') as f:
  f.seek(0);f.write(b'0');f.flush();deadline=time.monotonic()+timeout
  while True:
   try:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
   except OSError:
    if time.monotonic()>deadline:raise RuntimeError('Another AI start/stop action is still busy.')
    time.sleep(.2)
  try:yield
  finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def terminate_verified(p,kind):
 try:
  # Re-check the actual process immediately before stopping it; psutil also detects reused PIDs.
  if classify(p.exe(),p.cmdline())!=kind:raise RuntimeError('Process identity changed; nothing stopped.')
  p.terminate()
 except psutil.NoSuchProcess:pass

def stop_all(report=lambda _:None):
 LOGS.mkdir(parents=True,exist_ok=True);stamp=LOGS/'last-stop.txt';tmp=stamp.with_suffix('.tmp');tmp.write_text(str(time.monotonic_ns()));tmp.replace(stamp)
 report('Stopping current AI servers...')
 owned=servers();state=STRATA/'profile-logs/active-profile.json'
 if state.exists() and any(k.startswith('strata-') for p,k in owned):
  r=subprocess.run([str(PY),str(STRATA/'stop_strata_profile.py')],cwd=STRATA,capture_output=True,text=True,creationflags=HIDDEN,timeout=150)
  if r.returncode:raise RuntimeError((r.stdout+r.stderr).strip())
  report(r.stdout.strip())
 # Installed direct-launch servers can lack a launcher PID record.
 # Stop only the verified executables/scripts, never another application using the port.
 remaining=servers()
 for kind in ['strata-server','strata-engine','strata-vision','strata-launcher']:
  for p,k in remaining:
   if k==kind:terminate_verified(p,k)
 gone,alive=psutil.wait_procs([p for p,k in remaining],timeout=30)
 if alive or servers():raise RuntimeError('An AI server is still stopping. Retry Stop AI before starting another profile.')
 report('AI servers stopped.' if owned else 'No Strata server was running.')

def fetch(path):
 with urllib.request.urlopen('http://127.0.0.1:8080'+path,timeout=3) as r:return json.load(r)

def start_profile(key,report=lambda _:None,automatic_guard=None,automatic_cancel=None):
 with control_lock():
  cfg=validate_profile(key)
  if automatic_guard:
   if servers() or not automatic_guard():return dict(profile=key,cancelled=True)
  else:stop_all(report)
  with socket.socket() as sock:
   if sock.connect_ex(('127.0.0.1',8080))==0:raise RuntimeError('Port 8080 belongs to another application. It was not stopped.')
  LOGS.mkdir(parents=True,exist_ok=True);log=LOGS/(time.strftime('%Y%m%d-%H%M%S')+'-'+key+'.log')
  env=dict(os.environ);env.pop('STRATA_LAUNCH_VERIFY',None);env['PYTHONFAULTHANDLER']='1'
  if CONFIG.get('on_demand',{}).get('enabled'):
   env['STRATA_VALET_ROOT']=str(ROOT)
   if CONFIG.get('on_demand',{}).get('listen_host'):
    env['STRATA_VALET_BIND']=CONFIG['on_demand']['listen_host']
  with log.open('w') as output:
   started=time.monotonic_ns()
   proc=subprocess.Popen(cfg['command'],cwd=cfg['cwd'],env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=HIDDEN)
  if not automatic_guard:IDLE_SETTINGS.update(last_profile=key)
  if CONFIG.get('on_demand',{}).get('enabled'):IDLE_SETTINGS.update(demand_armed=True)
 report('Loading '+cfg['label']+' ...')
 deadline=time.monotonic()+600;next_game_check=0
 while time.monotonic()<deadline:
  if (LOGS/'last-stop.txt').exists() and int((LOGS/'last-stop.txt').read_text())>started:
   report('Startup cancelled by Stop AI or a profile switch.');return dict(profile=key,cancelled=True)
  if automatic_cancel and time.monotonic()>=next_game_check:
   next_game_check=time.monotonic()+10
   try:cancel=automatic_cancel()
   except Exception:cancel=True # If game detection fails during automatic loading, free the GPU.
   if cancel:
    with control_lock():
     if not (LOGS/'last-stop.txt').exists() or int((LOGS/'last-stop.txt').read_text())<=started:stop_all(report)
    report('Automatic startup cancelled by game activity.');return dict(profile=key,cancelled=True)

  try:
   models=fetch('/v1/models')
   if cfg['model'] in [x['id'] for x in models.get('data',[])]:
    if cfg['engine']=='strata':
     status=fetch('/v1/status')
     if CONFIG.get('on_demand',{}).get('enabled') and not status.get('loaded'):
      fetch('/health');report('Waiting for request: '+cfg['label']);return dict(profile=key,model=cfg['model'],log=str(log))
     if not status.get('loaded') or status['context']['native']!=cfg['context'] or status['concurrency']['serving']!=cfg['slots']:raise ValueError('Still loading')
    fetch('/health');report('Ready: '+cfg['label']+' — http://127.0.0.1:8080');return dict(profile=key,model=cfg['model'],log=str(log))
  except (OSError,ValueError,KeyError):pass
  if proc.poll() is not None:
   if not servers():raise RuntimeError('Startup stopped. '+log.read_text(errors='replace')[-1800:])
   if proc.returncode:raise RuntimeError(log.read_text(errors='replace')[-1800:])
  time.sleep(1)
 raise RuntimeError('Startup did not become ready. Check '+str(log))

GUI_PIPE=r'\\.\pipe\AI-Profiles'
GUI_STATE=LOGS/'gui-session.json'

class GuiMailbox:
 """Authenticated local messages; JSON only, never unpickle IPC payloads."""
 def __init__(self,events,address=GUI_PIPE,state_file=GUI_STATE):
  from multiprocessing.connection import Listener
  self.events=events;self.state_file=pathlib.Path(state_file);self.key=secrets.token_bytes(32);self.closed=threading.Event()
  self.listener=Listener(address,family='AF_PIPE',authkey=self.key)
  p=psutil.Process();state=dict(pid=p.pid,created=p.create_time(),exe=p.exe(),script=str(pathlib.Path(__file__).resolve()),address=address,key=self.key.hex())
  self.state_file.parent.mkdir(parents=True,exist_ok=True);tmp=self.state_file.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.replace(self.state_file)
  threading.Thread(target=self.listen,daemon=True).start()
 def listen(self):
  from multiprocessing import AuthenticationError
  while not self.closed.is_set():
   try:
    with self.listener.accept() as conn:
     if conn.poll(2):
      message=json.loads(conn.recv_bytes(4096));command=message.get('command');key=message.get('profile')
      if command in ['show','popup','stop','quit'] or (command=='start' and key in PROFILES):self.events.put((command,key))
   except (OSError,EOFError,ValueError,AuthenticationError):pass
 def close(self):
  self.closed.set();self.listener.close()
  try:
   if json.loads(self.state_file.read_text())['key']==self.key.hex():self.state_file.unlink()
  except (OSError,ValueError,KeyError):pass

def send_gui_command(command,profile=None,state_file=GUI_STATE):
 from multiprocessing.connection import Client
 from multiprocessing import AuthenticationError
 if command not in ['show','popup','stop','quit','start'] or (command=='start' and profile not in PROFILES):return False
 try:
  state=json.loads(pathlib.Path(state_file).read_text());p=psutil.Process(state['pid'])
  if abs(p.create_time()-state['created'])>.01 or not same(p.exe(),state['exe']) or not same(state['script'],__file__):return False
  with Client(state['address'],family='AF_PIPE',authkey=bytes.fromhex(state['key'])) as conn:conn.send_bytes(json.dumps(dict(command=command,profile=profile)).encode())
  return True
 except (OSError,EOFError,ValueError,KeyError,psutil.NoSuchProcess,psutil.AccessDenied,AuthenticationError):return False

def tray_menu(send,busy,current,auto_enabled=lambda:False):
 import pystray
 item=pystray.MenuItem
 def profile_item(key,profile):
  def load(icon,entry):send('start',key)
  def checked(entry):return current()==key
  return item(lambda entry:PROFILE_NAMES[key],load,enabled=lambda entry:not busy(),checked=checked,radio=True)
 profiles=[profile_item(k,p) for k,p in PROFILES.items()]
 return pystray.Menu(item('Open dashboard',lambda icon,entry:send('show'),default=True),item('Load model',pystray.Menu(*profiles),enabled=lambda entry:not busy()),item('Unload model',lambda icon,entry:send('stop')),item('Restore when idle',lambda icon,entry:send('auto-toggle'),checked=lambda entry:auto_enabled()),pystray.Menu.SEPARATOR,item('Exit Valet (keep model running)',lambda icon,entry:send('quit'),enabled=lambda entry:not busy()))

def read_demand_status():
 """Accept status only from a fresh, verified current server identity."""
 try:
  demand=json.loads((LOGS/'demand-status.json').read_text())
  age=time.time()-demand['checked_at']
  if not 0<=age<5:return {}
  p=psutil.Process(demand['owner_pid'])
  if abs(p.create_time()-demand['owner_created'])>.01 or classify(p.exe(),p.cmdline())!='strata-server':return {}
  return demand
 except (OSError,ValueError,KeyError,TypeError,psutil.NoSuchProcess,psutil.AccessDenied):return {}

def observed_profile():
 """Read-only status; refreshing never loads or unloads a model."""
 try:
  owned=servers()
  listener=strata_listener(owned)
  if listener is None:return None,'API unavailable: listener ownership could not be verified' if owned else 'No model loaded.'
  model=fetch('/v1/models')['data'][0]['id']
  s=fetch('/v1/status');demand=read_demand_status()
  if not listener.is_running() or strata_listener([(listener,'strata-server')]) is None:return None,'API unavailable: listener changed during status check'
  if demand.get('owner_pid')!=listener.pid:demand={}
  if demand.get('games') or demand.get('unknown') or demand.get('load_issue'):return None,demand['reason']
  if not s.get('loaded'):return None,demand.get('reason','Waiting for request')
  context=s['context']['native'];slots=s['concurrency']['serving']
  try:
   state=json.loads((STRATA/'profile-logs/active-profile.json').read_text(encoding='utf-8-sig'))
   verified=any(kind=='strata-server' and p.pid==state['server_pid'] and abs(p.create_time()-state['server_started'])<.01 for p,kind in owned)
   saved=next((k for k,p in PROFILES.items() if p['profile']==state['profile']),None) if verified else None
   if saved:
    cfg=PROFILES[saved]
    if cfg['model']==model and cfg['context']==context and cfg['slots']==slots:return saved,'Running: '+cfg['label']
    from ai_profiles import profile_name
    return None,'Running: '+profile_name('Strata',context,slots)+' · saved changes pending'
  except (OSError,ValueError,KeyError,TypeError,psutil.Error):pass
  key=next((k for k,p in PROFILES.items() if p['model']==model and p['context']==context and p['slots']==slots),None)
  return key,'Running: '+(PROFILES[key]['label'] if key else model)
 except (OSError,ValueError,KeyError,IndexError,StopIteration,psutil.NoSuchProcess,psutil.AccessDenied):
  return None,'API unavailable: owned process alive; inspect startup log' if servers() else 'No model loaded.'

def diagnose():
 owned=[dict(pid=p.pid,kind=k,created=p.create_time()) for p,k in servers()]
 result=dict(processes=owned,listener=listener_present(socket),demand=read_demand_status())
 try:result['health']=fetch('/health')
 except (OSError,ValueError) as exc:result['health_error']=str(exc)
 for name in ('last-issue','idle-status','recovery-state'):
  try:result[name]=json.loads((LOGS/(name+'.json')).read_text())
  except (OSError,ValueError):pass
 return result

class LauncherUI:
 def __init__(self,events=None,enable_tray=True,observe=True,stop=False,hidden=False):
  enable_dpi_awareness()
  import tkinter as tk
  from tkinter import ttk
  from PIL import ImageTk
  from ai_branding import icon_image,apply_window_icon,set_app_identity
  set_app_identity()
  self.closing=False
  # Separate single-worker lanes keep slow telemetry from delaying recovery checks.
  self.telemetry_worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='Valet-telemetry')
  self.policy_worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='Valet-recovery')
  self.events=events or queue.Queue();self.active=set();self.current=None;self.tray=None;self.stop_only=stop;self.observe=observe;self.refreshing=False;self.epoch=0;self.initial_snapshot=True
  self.window=tk.Tk();self.window.title('Inference Valet');self.window.configure(bg=THEME['bg'])
  self.ui_scale=float(self.window.tk.call('tk','scaling'))/(96/72)
  screen_w=self.window.winfo_screenwidth();screen_h=self.window.winfo_screenheight()
  self.window.geometry(f"{min(round(760*self.ui_scale),screen_w-80)}x{min(round(580*self.ui_scale),screen_h-100)}")
  self.window.minsize(min(round(600*self.ui_scale),screen_w),min(round(450*self.ui_scale),screen_h))
  native_window_style(self.window);apply_window_icon(self.window)
  self.idle_policy=IdlePolicy(time.monotonic());self.game_detector=GameDetector();self.auto_checking=False;self.recovery_policy=RecoveryPolicy(path=LOGS/'recovery-state.json');self.notified_issue=None
  self.auto_enabled=IDLE_SETTINGS.read()['enabled'];self.auto_status=tk.StringVar(value='Checking restore status…')
  self.status=tk.StringVar(value='Checking model…');self.hero_state=tk.StringVar(value='Checking model…')
  self.hero_profile=tk.StringVar(value='');self.hero_note=tk.StringVar(value='')
  self.popup=None;self.popup_performance=None;self.popup_start=None;self.popup_stop=None;self.popup_picker=None
  self.profile_editor=None
  self.keys=list(PROFILES);self.selected=tk.StringVar(value=PROFILE_NAMES[self.keys[0]])
  self.auto_var=tk.BooleanVar(value=self.auto_enabled)
  self.delay_var=tk.StringVar(value=f"{IDLE_SETTINGS.read()['idle_minutes']} min")
  style=ttk.Style(self.window);style.theme_use('clam')
  style.configure('Vertical.TScrollbar',background=THEME['line'],troughcolor=THEME['bg'],bordercolor=THEME['bg'],lightcolor=THEME['bg'],darkcolor=THEME['bg'],arrowcolor=THEME['muted'])
  style.map('Vertical.TScrollbar',background=[('pressed',THEME['accent']),('active',THEME['raised'])])
  self.window.option_add('*TCombobox*Listbox.background',THEME['card']);self.window.option_add('*TCombobox*Listbox.foreground',THEME['text'])
  self.window.option_add('*TCombobox*Listbox.selectBackground',THEME['selected']);self.window.option_add('*TCombobox*Listbox.selectForeground',THEME['text'])
  canvas=tk.Canvas(self.window,bg=THEME['bg'],highlightthickness=0)
  scrollbar=ttk.Scrollbar(self.window,orient='vertical',command=canvas.yview)
  canvas.configure(yscrollcommand=scrollbar.set)
  canvas.pack(side='left',fill='both',expand=True)
  frame=tk.Frame(canvas,bg=THEME['bg'],padx=round(18*self.ui_scale),pady=round(12*self.ui_scale))
  window_item=canvas.create_window((0,0),window=frame,anchor='nw')
  fitting=False
  def fit_dashboard(event=None):
   nonlocal fitting
   if fitting:return
   fitting=True
   try:
    frame.update_idletasks()
    canvas.itemconfigure(window_item,height=max(canvas.winfo_height(),frame.winfo_reqheight()))
    canvas.configure(scrollregion=canvas.bbox('all'))
    if frame.winfo_reqheight()>canvas.winfo_height():scrollbar.pack(side='right',fill='y',before=canvas)
    else:scrollbar.pack_forget()
   finally:fitting=False
  frame.bind('<Configure>',fit_dashboard)
  canvas.bind('<Configure>',lambda event:(canvas.itemconfigure(window_item,width=event.width),fit_dashboard()))
  canvas.bind('<MouseWheel>',lambda event:canvas.yview_scroll(-int(event.delta/120),'units'))
  self.dashboard_canvas=canvas
  hero=tk.Frame(frame,bg=THEME['bg']);hero.pack(fill='x')
  controls=tk.Frame(hero,bg=hero.cget('bg'));controls.pack(fill='x',pady=(10,0))
  picker_group=tk.Frame(controls,bg=hero.cget('bg'));picker_group.pack(side='left',fill='x',expand=True,padx=(0,10))
  selector_header=tk.Frame(picker_group,bg=THEME['bg']);selector_header.pack(fill='x',pady=(0,3))
  self._text(selector_header,'Model profile','body',color=THEME['muted']).pack(side='left')
  self.edit_button=tk.Button(selector_header,text='Edit profile',command=self.edit_profile,font=ui_font('body'),bg=THEME['bg'],fg=THEME['muted'],activebackground=THEME['bg'],activeforeground=THEME['text'],relief='flat',bd=0,padx=0,pady=0,cursor='hand2',takefocus=True)
  self.edit_button.pack(side='right');self.edit_button.bind('<Return>',lambda event:self.edit_profile())
  self.picker=ProfileSelect(picker_group,width=16,textvariable=self.selected,values=[PROFILE_NAMES[k] for k in self.keys],state='readonly')
  self.picker.pack(fill='x')
  actions=tk.Frame(controls,bg=hero.cget('bg'));actions.pack(side='right',anchor='s')
  self.start_button=Button(actions,text='Load model',primary=True,command=lambda:self.begin('start'));self.start_button.pack(side='left')
  self.stop_button=Button(actions,text='Unload model',command=lambda:self.begin('stop'));self.stop_button.pack(side='left',padx=(6,0))
  self.attention_row=tk.Frame(hero,bg=THEME['bg'])
  self.state_dot=self._text(self.attention_row,'●','caption',color=THEME['warning']);self.state_dot.pack(side='left',padx=(0,5))
  self.state_label=self._text(self.attention_row,variable=self.hero_state,size='caption',bold=True);self.state_label.pack(side='left',padx=(0,8))
  self.note_label=self._text(self.attention_row,variable=self.hero_note,size='caption',color=THEME['muted']);self.note_label.pack(side='left',fill='x',expand=True)
  self.model_divider=tk.Frame(hero,bg=THEME['line'],height=1);self.model_divider.pack(fill='x',pady=(10,8))
  auto_row=tk.Frame(hero,bg=hero.cget('bg'));auto_row.pack(fill='x')
  self.auto_explanation=tk.StringVar(value='')
  self.auto_control=Switch(auto_row,text='Restore when idle',variable=self.auto_var,command=self.toggle_auto)
  self.auto_control.pack(side='left')
  self.delay_picker=ProfileSelect(auto_row,width=8,textvariable=self.delay_var,values=[f'{minutes} min' for minutes in IDLE_MINUTES],state='readonly')
  self.delay_picker.pack(side='left',padx=(8,0));self.delay_picker.bind('<<ComboboxSelected>>',self.set_restore_delay)
  self.auto_note=self._text(auto_row,variable=self.auto_explanation,size='caption',color=THEME['muted'],wrap=350)
  self.auto_note.pack(side='right',padx=(12,0))
  auto_row.bind('<Configure>',lambda event:self.auto_note.configure(wraplength=max(120,event.width-self.auto_control.winfo_reqwidth()-self.delay_picker.winfo_reqwidth()-24)))
  tk.Frame(frame,bg=THEME['line'],height=1).pack(fill='x',pady=(12,0))
  performance_header=tk.Frame(frame,bg=THEME['bg']);performance_header.pack(fill='x',pady=(12,7))
  self._text(performance_header,'Performance','heading',True).pack(side='left')
  self._text(performance_header,'Activity · past minute','caption',color=THEME['muted']).pack(side='right')
  self.performance=PerformancePanel(frame) if not stop else None
  self.collector=Collector(fetch,servers,read_demand_status);self.latest_performance={}
  if self.performance:
   self.performance.on_layout=fit_dashboard
   self.performance.on_edit_engine=lambda:self.edit_profile(initial_page='Memory')
   self.performance.pack(fill='both',expand=True)
  def wrap_hero(event):
   self.note_label.configure(wraplength=max(180,event.width-self.state_label.winfo_reqwidth()-24))
  hero.bind('<Configure>',wrap_hero,add='+')
  self._bind_scroll_region(frame,canvas)
  if self.performance:self.performance.on_details=self.resize_details
  self.details_geometry=None
  self.window.protocol('WM_DELETE_WINDOW',self.close)
  self.window.bind('<Unmap>',lambda event:self.hide() if event.widget==self.window and self.window.state()=='iconic' else None)
  self.window.bind('<Escape>',lambda event:self.hide())
  self.update_controls()
  if enable_tray and not stop:
   import pystray
   image=icon_image(64,tray=True)
   events=self.events
   class VisualTrayIcon(pystray.Icon):
    def _on_notify(icon,wparam,lparam):
     if lparam==0x202:
      import ctypes
      from ctypes import wintypes
      point=wintypes.POINT();ctypes.windll.user32.GetPhysicalCursorPos(ctypes.byref(point))
      events.put(('popup',(point.x,point.y)))
     else:super()._on_notify(wparam,lparam)
   self.tray=VisualTrayIcon('Inference Valet',image,'Inference Valet',tray_menu(lambda action,key=None:self.events.put((action,key)),lambda:bool(self.active),lambda:self.current,lambda:self.auto_enabled))
   threading.Thread(target=self.tray.run,daemon=True).start()
  self.poll_timer=self.window.after(100,self.poll)
  self.refresh_timer=None
  if observe:self.refresh_timer=self.window.after(200,self.refresh)
  self.auto_timer=None
  if observe and not stop:self.auto_timer=self.window.after(1000,self.check_auto)
  if stop:self.window.after(50,lambda:self.begin('stop'))
  self.window.update_idletasks()
  self.window.geometry(f"{self.window.winfo_width()}x{min(screen_h-100,max(round(580*self.ui_scale),frame.winfo_reqheight()))}")
  self.window.update_idletasks()
  native_window_style(self.window)
  if hidden:self.hide()
 def edit_profile(self,initial_page='Profile'):
  from tkinter import messagebox
  from ai_profile_editor import ProfileEditor
  if self.profile_editor and self.profile_editor.window.winfo_exists():
   self.profile_editor.select_page(initial_page)
   self.profile_editor.window.lift();self.profile_editor.window.focus_force();return
  if self.active:return
  key=self.keys[self.picker.current()]
  try:self.profile_editor=ProfileEditor(self.window,PROFILE_STORE,key,self.save_profile,native_window_style,initial_page=initial_page)
  except (OSError,ValueError,KeyError) as exc:messagebox.showerror('Profile unavailable',str(exc),parent=self.window)
 def save_profile(self,key,values,snapshot):
  if self.active:raise RuntimeError('Wait for the current model action to finish, then save again.')
  with control_lock(timeout=1):
   PROFILE_STORE.save(key,values,snapshot);reload_profiles()
  self.keys=list(PROFILES);self.picker.configure(values=[PROFILE_NAMES[k] for k in self.keys])
  if self.popup_picker:self.popup_picker.configure(values=[PROFILE_NAMES[k] for k in self.keys])
  self.selected.set(PROFILE_NAMES[key]);self.update_controls()
  if self.performance:self.performance.engine_settings_note.set('Saved · changes apply on the next model load')
 def resize_details(self,expanded):
  self.window.update_idletasks()
  if not expanded:
   if self.details_geometry:
    geometry,state=self.details_geometry;self.window.geometry(geometry)
    if state=='zoomed':self.window.state(state)
   self.details_geometry=None;return
  self.details_geometry=(self.window.geometry(),self.window.state())
  if self.window.state()=='zoomed':return
  import ctypes
  from ctypes import wintypes
  class Info(ctypes.Structure):_fields_=[('cbSize',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
  user=ctypes.windll.user32;user.GetParent.restype=wintypes.HWND
  user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];user.MonitorFromWindow.restype=wintypes.HANDLE
  user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
  hwnd=user.GetParent(self.window.winfo_id());monitor=user.MonitorFromWindow(hwnd,2)
  info=Info();info.cbSize=ctypes.sizeof(info);rect=wintypes.RECT()
  if not user.GetMonitorInfoW(monitor,ctypes.byref(info)):return
  user.GetWindowRect(hwnd,ctypes.byref(rect))
  decoration=rect.bottom-rect.top-self.window.winfo_height()
  # A work-area-filling foreground window can trigger Windows' presentation
  # state, which the existing game guard correctly treats as a GPU blocker.
  margin=round(16*self.ui_scale)
  height=min(self.window.winfo_height()+self.performance.detail_container.winfo_reqheight()+7,info.work.bottom-info.work.top-decoration-2*margin)
  y=max(info.work.top+margin,min(rect.top,info.work.bottom-margin-height-decoration))
  self.window.geometry(f'{self.window.winfo_width()}x{height}+{rect.left}+{y}')
  self.dashboard_canvas.yview_moveto(0)
 def _text(self,parent,text='',size='body',bold=False,color=None,variable=None,wrap=0):
  import tkinter as tk
  return tk.Label(parent,text=text,textvariable=variable,bg=parent.cget('bg'),fg=color or THEME['text'],font=ui_font(size,bold),anchor='w',justify='left',wraplength=wrap,bd=0)
 def _bind_scroll_region(self,root,canvas,skip=()):
  def on_wheel(event):
   if event.delta:
    step=max(1,round(abs(event.delta)/120))
    canvas.yview_scroll(-step if event.delta>0 else step,'units')
   return 'break'
  def on_focus(event):
   self._reveal_focus(event.widget,canvas)
  def visit(widget):
   if widget in skip:return
   if widget.winfo_class() not in ('TCombobox','TScrollbar','Scrollbar','Treeview'):
    widget.bind('<MouseWheel>',on_wheel,add='+')
   widget.bind('<FocusIn>',on_focus,add='+')
   for child in widget.winfo_children():visit(child)
  visit(root)
 def _reveal_focus(self,widget,canvas):
  if not canvas.winfo_ismapped():return
  canvas.update_idletasks()
  viewport=canvas.winfo_height();margin=max(8,round(8*self.ui_scale))
  top=widget.winfo_rooty()-canvas.winfo_rooty();bottom=top+widget.winfo_height()
  shift=bottom-viewport+margin if bottom>viewport-margin else top-margin if top<margin else 0
  if not shift:return
  region=canvas.bbox('all')
  if not region:return
  extent=max(1,region[3]-region[1]);current=canvas.canvasy(0)-region[1]
  canvas.yview_moveto(max(0,min(extent-viewport,current+shift))/extent)
 def hide(self):self.window.withdraw()
 def close(self):self.hide()
 def show(self):
  self.hide_popup()
  self.window.deiconify();self.window.lift();self.window.focus_force()
  if self.observe:self.refresh()
 def hide_popup(self):
  if self.popup:self.popup.withdraw()
 def show_popup(self,anchor=None):
  import tkinter as tk
  from tkinter import ttk
  from PIL import ImageTk
  from ai_branding import icon_image
  if self.popup is None:
   self.popup=tk.Toplevel(self.window,bg=THEME['bg']);self.popup.withdraw();self.popup.overrideredirect(True);self.popup.attributes('-topmost',True)
   outer=tk.Frame(self.popup,bg=THEME['line'],padx=1,pady=1);outer.pack(fill='both',expand=True)
   self.popup_canvas=tk.Canvas(outer,bg=THEME['bg'],highlightthickness=0)
   self.popup_scroll=ttk.Scrollbar(outer,orient='vertical',command=self.popup_canvas.yview)
   self.popup_canvas.configure(yscrollcommand=self.popup_scroll.set)
   self.popup_canvas.pack(side='left',fill='both',expand=True)
   content=tk.Frame(self.popup_canvas,bg=THEME['bg'],padx=17,pady=15)
   self.popup_window_item=self.popup_canvas.create_window((0,0),window=content,anchor='nw')
   self.popup_content=content
   content.bind('<Configure>',lambda event:self.popup_canvas.configure(scrollregion=self.popup_canvas.bbox('all')))
   self.popup_canvas.bind('<Configure>',lambda event:self.popup_canvas.itemconfigure(self.popup_window_item,width=event.width))
   self.popup_canvas.bind('<MouseWheel>',lambda event:self.popup_canvas.yview_scroll(-int(event.delta/120),'units'))
   header=tk.Frame(content,bg=THEME['bg']);header.pack(fill='x',pady=(0,14))
   self.popup_brand_image=ImageTk.PhotoImage(icon_image(round(28*self.ui_scale)))
   tk.Label(header,image=self.popup_brand_image,bg=THEME['bg'],bd=0).pack(side='left',padx=(0,8))
   self._text(header,'Inference Valet','heading',True).pack(side='left')
   tk.Button(header,text='×',command=self.hide_popup,bg=THEME['bg'],fg=THEME['muted'],activebackground=THEME['card'],activeforeground=THEME['text'],bd=0,font=ui_font('heading'),takefocus=True).pack(side='right')
   hero_surface=Surface(content,padding=(14,12));hero_surface.pack(fill='x')
   hero=hero_surface.body
   self.popup_state=self._text(hero,variable=self.hero_state,size='body',bold=True,color=self.state_label.cget('fg'));self.popup_state.pack(anchor='w')
   self.popup_profile=self._text(hero,variable=self.hero_profile,size='heading',bold=True,wrap=round(325*self.ui_scale));self.popup_profile.pack(anchor='w',pady=(3,0))
   self.popup_note=self._text(hero,variable=self.hero_note,size='caption',color=THEME['muted'],wrap=325);self.popup_note.pack(anchor='w',pady=(4,0))
   self._text(content,'Model profile','body',color=THEME['muted']).pack(anchor='w',pady=(15,6))
   self.popup_picker=ProfileSelect(content,textvariable=self.selected,values=[PROFILE_NAMES[k] for k in self.keys],state='readonly')
   self.popup_picker.pack(fill='x')
   actions=tk.Frame(content,bg=THEME['bg']);actions.pack(fill='x',pady=(10,0))
   self.popup_start=Button(actions,text='Load model',primary=True,command=lambda:self.begin('start'));self.popup_start.pack(side='left')
   self.popup_stop=Button(actions,text='Unload',command=lambda:self.begin('stop'));self.popup_stop.pack(side='left',padx=(8,0))
   tk.Frame(content,bg=THEME['line'],height=1).pack(fill='x',pady=(15,10))
   restore_row=tk.Frame(content,bg=THEME['bg']);restore_row.pack(fill='x')
   Switch(restore_row,text='Restore when idle',variable=self.auto_var,command=self.toggle_auto).pack(side='left')
   self.popup_delay_picker=ProfileSelect(restore_row,width=8,textvariable=self.delay_var,values=[f'{minutes} min' for minutes in IDLE_MINUTES],state='readonly');self.popup_delay_picker.pack(side='right');self.popup_delay_picker.bind('<<ComboboxSelected>>',self.set_restore_delay)
   self.popup_auto_note=self._text(content,variable=self.auto_explanation,size='caption',color=THEME['muted'],wrap=340);self.popup_auto_note.pack(anchor='w',pady=(2,0))
   tk.Frame(content,bg=THEME['line'],height=1).pack(fill='x',pady=(15,10))
   self.popup_performance=PerformancePanel(content,compact=True);self.popup_performance.pack(fill='x')
   Button(content,text='Open dashboard  ↗',primary=True,command=self.show).pack(fill='x',pady=(16,0))
   self._bind_scroll_region(content,self.popup_canvas)
   self.popup.bind('<Escape>',lambda event:self.hide_popup())
   self.popup.bind('<Return>',lambda event:self.show() if event.widget==self.popup else None)
   def dismiss(event):
    def check():
     if self.popup and self.popup.state()!='withdrawn' and not str(self.window.tk.call('focus')).startswith(str(self.popup)):self.hide_popup()
    self.popup.after(180,check)
   self.popup.bind('<FocusOut>',dismiss)
  if self.latest_performance:self.popup_performance.update(self.latest_performance)
  import ctypes
  from ctypes import wintypes
  point=wintypes.POINT();ctypes.windll.user32.GetPhysicalCursorPos(ctypes.byref(point))
  self.popup_monitor_anchor=anchor or (point.x,point.y)
  self.position_popup();self.popup.lift();self.popup.focus_force();self.update_controls()
  if self.observe:self.refresh()
 def fit_popup_actions(self,available_width):
  start_width=self.popup_start.winfo_reqwidth();stop_width=self.popup_stop.winfo_reqwidth()
  side_by_side=start_width+stop_width+44
  if available_width<side_by_side:
   if self.popup_start.pack_info()['side']!='top':
    self.popup_start.pack_forget();self.popup_stop.pack_forget()
    self.popup_start.pack(fill='x');self.popup_stop.pack(fill='x',pady=(8,0))
   return max(start_width,stop_width)+36
  if self.popup_start.pack_info()['side']!='left':
   self.popup_start.pack_forget();self.popup_stop.pack_forget()
   self.popup_start.pack(side='left');self.popup_stop.pack(side='left',padx=(8,0))
  return side_by_side
 def position_popup(self):
  import ctypes
  from ctypes import wintypes
  class MonitorInfo(ctypes.Structure):_fields_=[('cbSize',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
  user=ctypes.windll.user32
  user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p];user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
  previous=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
  try:
   user.MonitorFromPoint.argtypes=[wintypes.POINT,wintypes.DWORD];user.MonitorFromPoint.restype=wintypes.HANDLE
   monitor=user.MonitorFromPoint(wintypes.POINT(*self.popup_monitor_anchor),2)
   info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
   if not user.GetMonitorInfoW(wintypes.HANDLE(monitor),ctypes.byref(info)):raise OSError('Cannot read display bounds')
   work=(info.work.left,info.work.top,info.work.right,info.work.bottom)
   bounds=(info.monitor.left,info.monitor.top,info.monitor.right,info.monitor.bottom)
   xdpi=wintypes.UINT();ydpi=wintypes.UINT()
   try:
    hr=ctypes.windll.shcore.GetDpiForMonitor(wintypes.HANDLE(monitor),0,ctypes.byref(xdpi),ctypes.byref(ydpi))
    scale=xdpi.value/96 if hr==0 and xdpi.value else 1
   except (OSError,AttributeError):scale=1
   width,_=popup_size(work,scale,1)
   available_width=max(1,work[2]-work[0]-24)
   action_width=self.fit_popup_actions(available_width)
   width=min(available_width,max(width,action_width))
   self.popup_canvas.itemconfigure(self.popup_window_item,width=width-2)
   self.popup_note.configure(wraplength=max(140,width-round(48*self.ui_scale)))
   self.popup_profile.configure(wraplength=max(140,width-round(48*self.ui_scale)))
   self.popup_auto_note.configure(wraplength=max(140,width-48))
   self.popup.update_idletasks()
   natural_height=max(1,self.popup_content.winfo_reqheight()+2)
   _,height=popup_size(work,scale,natural_height/scale)
   overflow=natural_height>height
   if overflow:
    scrollbar_width=self.popup_scroll.winfo_reqwidth()
    width=min(available_width,max(width,action_width+scrollbar_width))
    self.popup_canvas.itemconfigure(self.popup_window_item,width=width-scrollbar_width-2)
    self.popup_note.configure(wraplength=max(140,width-scrollbar_width-round(48*self.ui_scale)))
    self.popup_profile.configure(wraplength=max(140,width-scrollbar_width-round(48*self.ui_scale)))
    self.popup_auto_note.configure(wraplength=max(140,width-scrollbar_width-48))
    self.popup.update_idletasks()
    natural_height=max(1,self.popup_content.winfo_reqheight()+2)
    _,height=popup_size(work,scale,natural_height/scale)
    overflow=natural_height>height
   if overflow:self.popup_scroll.pack(side='right',fill='y',before=self.popup_canvas)
   else:self.popup_scroll.pack_forget()
   x,y=taskbar_position(bounds,work,(width,height))
   self.popup.geometry(f'{width}x{height}+{x}+{y}')
   self.popup.deiconify();self.popup.update_idletasks();native_window_style(self.popup)
  finally:
   if previous:user.SetThreadDpiAwarenessContext(previous)
 def quit(self):
  if self.active:return False
  self.closing=True
  self.telemetry_worker.shutdown(wait=False,cancel_futures=True)
  self.policy_worker.shutdown(wait=False,cancel_futures=True)
  for timer in (self.poll_timer,self.refresh_timer,self.auto_timer):
   if timer:
    try:self.window.after_cancel(timer)
    except Exception:pass
  if self.tray:
   self.tray.visible=False
   self.tray.stop()
  # Release callbacks that point back to this UI while Tcl still belongs to the
  # main thread; an in-flight worker may otherwise keep the whole UI alive.
  for panel in (self.performance,self.popup_performance):
   if panel:
    panel.on_edit_engine=lambda:None;panel.on_layout=lambda:None;panel.on_details=lambda expanded:None
  if self.profile_editor:self.profile_editor.on_save=lambda *args:None
  self.window.update_idletasks()
  self.window.destroy();return True
 def refresh_display(self):
  reason=self.auto_status.get()
  if not self.auto_enabled:explanation='Automatic restore is paused.'
  elif 'blocked:' in reason:explanation='Waiting for your game to close before restoring.'
  elif 'waiting ' in reason:
   remaining=reason.split('waiting ',1)[1].split(' ',1)[0]
   explanation=f'{remaining} remaining before restore.'
  elif 'load a profile once' in reason:explanation='Load a model once to remember it for next time.'
  elif 'failed' in reason.lower():explanation='Restore check failed. Retrying automatically.'
  elif 'API recovery' in reason:explanation=reason
  else:explanation=''
  self.auto_explanation.set(explanation)
  status=self.status.get()
  if 'start' in self.active:
   title='Loading model…';profile=PROFILE_NAMES.get(self.keys[self.picker.current()],'')
   note='Your current model will be replaced.' if self.current or status.startswith('Running: ') else 'Preparing your model…'
  elif 'stop' in self.active:title='Unloading model…';profile='';note='GPU memory will be freed.'
  elif status.startswith('Action failed:'):title='Action failed';profile='';note=status.removeprefix('Action failed: ')
  elif any(word in status for word in ('VRAM headroom','Strata load failed','Insufficient RAM','Resource state unknown','API recovery paused','API unavailable')):title='Strata needs attention';profile='';note=status
  elif self.current in PROFILE_NAMES:
   title='Ready';profile=PROFILE_NAMES[self.current];note='Your model is loaded and available.'
  elif status.startswith('Running: '):title='Model running';profile=status.removeprefix('Running: ');note='The active model is available.'
  elif status.startswith('Checking model'):title='Checking model…';profile='';note='Reading the current model state.'
  elif 'loading' in status.lower():title='Loading model…';profile='';note='Checking the model server.'
  elif 'unavailable' in status.lower():title='Status unavailable';profile='';note='Retrying the model status check.'
  elif status.startswith('Gaming busy:'):title='Gaming priority';profile='';note=status.removeprefix('Gaming busy:').strip() or 'New inference is paused while your game is running.'
  elif status.startswith('Game state unknown:'):title='Game status unavailable';profile='';note='New inference is paused until game activity can be checked.'
  elif status.startswith('Waiting for request'):title='Waiting for request';profile='';note='The next request loads Strata when the GPU is available.'
  elif not self.auto_enabled:title='Restore paused';profile='No model loaded';note='Load a model whenever you need it.'
  else:
   title='No model loaded'
   remembered=IDLE_SETTINGS.read()['last_profile']
   profile='Last used: '+PROFILE_NAMES[remembered] if remembered in PROFILE_NAMES else ''
   note=explanation if remembered in PROFILE_NAMES else 'Choose a profile to load it.'
  reading=self.latest_performance
  activity=reading.get('activity') or {}
  if activity and not self.active and not status.startswith('Action failed:'):
   if time.monotonic()-reading.get('sampled',0)>15:
    title='Status unavailable';note='Last reading is stale · checking again'
   else:
    title=activity['title'];note=activity.get('detail','')
  fallback='Choose a model' if title=='No model loaded' else 'Model unavailable' if title in ('Action failed','Strata needs attention','Status unavailable') else 'Local model'
  self.hero_state.set(title);self.hero_profile.set(profile or fallback);self.hero_note.set(note)
  color=THEME['success'] if title in ('Ready','Model running') else THEME['warning'] if any(word in title.lower() for word in ('failed','attention','unavailable','priority')) else THEME['info']
  self.state_dot.configure(fg=color);self.state_label.configure(fg=color)
  if 'blocked:' in reason and title in ('Ready','Model running','No model loaded','Waiting for request'):
   self.hero_state.set('Game priority');self.hero_note.set(reason.split('blocked:',1)[1].strip());color=THEME['warning'];self.state_label.configure(fg=color);self.state_dot.configure(fg=color);title='Game priority'
  if title in ('Ready','Model running','Checking model…','No model loaded','Waiting for request','Restore paused'):self.attention_row.pack_forget()
  else:self.attention_row.pack(fill='x',pady=(6,0),before=self.model_divider)
  if self.popup:self.popup_state.configure(fg=color)
 def update_controls(self):
  self.refresh_display()
  load_label='Switch model' if self.current or self.status.get().startswith('Running: ') or 'start' in self.active else 'Load model'
  self.start_button.configure(text=load_label)
  self.start_button.configure(state='disabled' if self.active else 'normal')
  self.stop_button.configure(state='disabled' if 'stop' in self.active else 'normal')
  self.picker.configure(state='disabled' if self.active else 'readonly')
  self.edit_button.configure(state='disabled' if self.active else 'normal')
  if self.popup_start:
   self.popup_start.configure(text=load_label,state='disabled' if self.active else 'normal');self.popup_stop.configure(state='disabled' if 'stop' in self.active else 'normal');self.popup_picker.configure(state='disabled' if self.active else 'readonly')
  if self.tray:
   reading=self.latest_performance;speed=reading.get('live_speed') if time.monotonic()-reading.get('sampled',0)<=15 else None;extra=f" · {speed:.1f} tok/s" if isinstance(speed,(int,float)) else ''
   self.tray.title=('Inference Valet · '+reading.get('state','')+extra+' · '+self.status.get())[:127];self.tray.update_menu()
 def begin(self,action,key=None,automatic=False,recovery=False):
  if action in self.active or (action=='start' and self.active):return
  key=key or self.keys[self.picker.current()]
  if action=='start':self.selected.set(PROFILE_NAMES[key])
  if recovery and not self.recovery_policy.begin(time.time()):return
  if recovery:self.notify_issue(record_issue('listener_down','Strata API listener disappeared; restoring unloaded listener',profile=key))
  if action=='start' and not automatic:self.recovery_policy.reset()
  if action=='stop':IDLE_SETTINGS.update(demand_armed=False)
  self.active.add(action);self.epoch+=1;self.status.set('Preparing profile switch...' if action=='start' else 'Unloading model...');self.update_controls()
  def work():
   try:
    result=None
    if action=='start':result=start_profile(key,lambda text:self.events.put(('status',text)),automatic_guard=(lambda:IDLE_SETTINGS.read()['demand_armed'] and IDLE_SETTINGS.read()['last_profile']==key) if recovery else ((lambda:self.auto_sample(True)[0] and IDLE_SETTINGS.read()['last_profile']==key) if automatic else None),automatic_cancel=(lambda:bool(self.game_detector.running(IDLE_SETTINGS.read()['extra_games'],strict=True))) if automatic and not recovery else None)
    else:
     with control_lock():stop_all(lambda text:self.events.put(('status',text)))
    self.events.put(('done',(action,key,result)))
   except Exception as exc:self.events.put(('error',(action,str(exc),automatic)))
  threading.Thread(target=work,daemon=True).start()
 def poll(self):
  from tkinter import messagebox
  if self.poll_timer:
   self.window.after_cancel(self.poll_timer);self.poll_timer=None
  while not self.events.empty():
   kind,payload=self.events.get()
   if kind in ['start','stop']:self.begin(kind,payload)
   elif kind=='auto-toggle':self.toggle_auto()
   elif kind=='auto-sample':
    if 'API recovery paused:' in payload['reason']:
     self.notify_issue(dict(code='recovery_paused',message=payload['reason']))
    self.auto_enabled=payload['enabled'];self.auto_var.set(self.auto_enabled);self.auto_status.set(payload['reason']);self.update_controls()
    if payload.get('recover') and not self.active:self.begin('start',payload['profile'],automatic=True,recovery=True)
    elif payload['due'] and not self.active:self.begin('start',payload['profile'],automatic=True)
   elif kind=='show':self.show()
   elif kind=='popup':self.show_popup(payload)
   elif kind=='quit':
    if self.quit():return
   elif kind=='status':self.status.set(payload);self.update_controls()
   elif kind=='snapshot':
    self.refreshing=False
    if payload[0]==self.epoch:
     self.reading_stale=False
     self.latest_performance=payload[2]
     if self.performance and self.window.state()!='withdrawn':self.performance.update(payload[2])
     if self.popup_performance and self.popup.state()!='withdrawn':self.popup_performance.update(payload[2])
     if not self.active:
      self.current,text=payload[1];self.status.set(text)
      remembered=IDLE_SETTINGS.read()['last_profile']
      if self.current and self.current!=remembered:
       IDLE_SETTINGS.update(last_profile=self.current);remembered=self.current;self.selected.set(PROFILE_NAMES[self.current])
      if self.initial_snapshot and remembered in PROFILES:self.selected.set(PROFILE_NAMES[remembered])
      self.initial_snapshot=False
     issue=read_demand_status().get('load_issue')
     if issue:self.notify_issue(issue)
     self.update_controls()
     if self.popup and self.popup.state()!='withdrawn':self.position_popup()
   elif kind in ['done','error']:
    action=payload[0];self.active.discard(action)
    if action=='start':self.recovery_policy.finished()
    if kind=='error':
     issue=record_issue(failure_code(payload[1]),payload[1],action=action)
     self.notify_issue(issue);self.status.set('Action failed: '+payload[1][:500])
     if len(payload)>2 and payload[2]:
      self.idle_policy.failed(time.monotonic());self.auto_status.set('Auto reload failed; retry in 5 minutes')
      with (LOGS/'idle-errors.log').open('a',encoding='utf-8') as log:log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+payload[1]+'\n')
     else:self.show();messagebox.showerror('Inference Valet',payload[1],parent=self.window)
    elif action=='stop':self.current=None
    elif not (payload[2] or {}).get('cancelled'):self.current=payload[1]
    self.update_controls()
    if self.stop_only and not self.active and self.quit():return
  if self.latest_performance.get('activity') and time.monotonic()-self.latest_performance.get('sampled',0)>15 and not getattr(self,'reading_stale',False):
   self.reading_stale=True
   if self.performance:self.performance.mark_stale()
   if self.popup_performance:self.popup_performance.mark_stale()
   self.update_controls()
  visible=self.window.state()!='withdrawn' or (self.popup is not None and self.popup.state()!='withdrawn')
  self.poll_timer=self.window.after(100 if visible or self.active else 250,self.poll)
 def notify_issue(self,issue):
  signature=(issue.get('code'),issue.get('message'))
  if signature==self.notified_issue:return
  self.notified_issue=signature
  if self.tray:
   try:self.tray.notify(issue['message'][:240],'Inference Valet')
   except Exception:pass
 def set_restore_delay(self,event=None):
  minutes=int(self.delay_var.get().split()[0])
  if minutes not in IDLE_MINUTES:return
  IDLE_SETTINGS.update(idle_minutes=minutes);self.update_controls()
  if self.observe and not self.stop_only:
   if self.auto_timer:self.window.after_cancel(self.auto_timer)
   self.auto_timer=self.window.after(1,self.check_auto)
 def toggle_auto(self):
  self.auto_enabled=not IDLE_SETTINGS.read()['enabled'];IDLE_SETTINGS.update(enabled=self.auto_enabled)
  self.auto_var.set(self.auto_enabled);self.auto_status.set('Auto reload enabled' if self.auto_enabled else 'Auto reload paused');self.update_controls()
 def auto_sample(self,ignore_action=False):
  settings=IDLE_SETTINGS.read();profile=settings['last_profile'];idle=idle_seconds();demand=CONFIG.get('on_demand',{}).get('enabled',False)
  live=read_demand_status() if demand else {}
  try:games=(['game state unavailable'] if live.get('unknown') else live.get('games',[])) if live else self.game_detector.running(settings['extra_games'],strict=bool(demand))
  except Exception:
   if not demand:raise
   games=['game state unavailable']
  stamp=LOGS/'last-stop.txt';stop=int(stamp.read_text())/1e9 if stamp.exists() else 0
  owned=bool(live) or bool(servers());busy=owned or (bool(self.active) and not ignore_action)
  due,reason=self.idle_policy.decide(time.monotonic(),idle,games,busy,settings['enabled'],profile if profile in PROFILES else None,stop,settings.get('idle_minutes',20))
  recover=False
  if demand and profile in PROFILES and PROFILES[profile]['engine']=='strata':
   recover,recovery_reason=self.recovery_policy.decide(time.time(),settings['demand_armed'],owned,listener_present(socket) if not owned else True,games,bool(self.active) and not ignore_action)
   if settings['demand_armed']:due=False
   if not owned and settings['demand_armed']:reason=recovery_reason
  reading=dict(due=due,recover=recover,reason=reason,enabled=settings['enabled'],profile=profile,idle_seconds=round(idle,1),games=games,pid=os.getpid(),checked_at=time.time())
  return due,reading
 def check_auto(self):
  if self.closing:return
  if not self.auto_checking and not self.active:
   self.auto_checking=True
   def sample():
    try:
     _,reading=self.auto_sample()
     LOGS.mkdir(parents=True,exist_ok=True);temp=LOGS/'idle-status.tmp';temp.write_text(json.dumps(reading,indent=2),encoding='utf-8');temp.replace(LOGS/'idle-status.json')
     self.events.put(('auto-sample',reading))
    except Exception as exc:
     self.idle_policy.failed(time.monotonic());self.events.put(('auto-sample',dict(due=False,reason='Auto reload check failed: '+str(exc),enabled=self.auto_enabled,profile=None)))
    finally:self.auto_checking=False
   self.policy_worker.submit(sample)
  self.auto_timer=self.window.after(10000,self.check_auto)
 def refresh(self):
  if self.closing:return
  if self.refresh_timer:self.window.after_cancel(self.refresh_timer)
  visible=self.window.state()!='withdrawn' or (self.popup is not None and self.popup.state()!='withdrawn')
  if not self.refreshing:
   self.refreshing=True;epoch=self.epoch
   def sample():
    try:reading=self.collector.collect() if visible else self.collector.summary();profile=observed_profile()
    except Exception:
     reading={'sampled':time.monotonic(),'state':'telemetry unavailable · retrying','slots':[],'live_speed':None,'hardware':{},'activity':{'state':'unavailable','title':'Status unavailable','detail':'The observation failed · checking again','blockers':[],'recent':[]}}
     profile=(None,'Telemetry unavailable; retrying.')
    self.events.put(('snapshot',(epoch,profile,reading)))
   self.telemetry_worker.submit(sample)
  self.refresh_timer=self.window.after(2000 if visible else 10000,self.refresh)

def gui(stop=False,check=False,hidden=False):
 if check:
  app=LauncherUI(enable_tray=False,observe=False);app.hide();count=len(app.picker['values']);app.quit();return count
 if send_gui_command('stop' if stop else 'show'):return
 if stop:
  app=LauncherUI(enable_tray=False,observe=False,stop=True);app.window.mainloop();return
 events=queue.Queue()
 try:mailbox=GuiMailbox(events)
 except OSError:
  for _ in range(20):
   if send_gui_command('show'):return
   time.sleep(.1)
  raise RuntimeError('The tray app is already starting. Try Start AI again shortly.')
 try:
  app=LauncherUI(events,hidden=hidden);app.window.mainloop()
 finally:mailbox.close()

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--start',choices=list(PROFILES));ap.add_argument('--stop',action='store_true');ap.add_argument('--gui-stop',action='store_true');ap.add_argument('--tray',action='store_true');ap.add_argument('--diagnose',action='store_true');ap.add_argument('--list',action='store_true');ap.add_argument('--check-ui',action='store_true');a=ap.parse_args()
 def report(text):
  if sys.stdout:print(text,flush=True)
 if a.diagnose:report(json.dumps(diagnose(),indent=2))
 elif a.list:
  for k,v in PROFILES.items():validate_profile(k)
  report(json.dumps({k:{f:p[f] for f in ['label','engine','context','slots']} for k,p in PROFILES.items()},indent=2))
 elif a.check_ui:report(str(gui(check=True)))
 elif a.start:report(json.dumps(start_profile(a.start,report)))
 elif a.stop:
  IDLE_SETTINGS.update(demand_armed=False)
  with control_lock():stop_all(report)
 else:gui(stop=a.gui_stop,hidden=a.tray)
if __name__=='__main__':
 try:main()
 except Exception as e:
  try:record_issue(failure_code(e),e)
  except OSError:pass
  if sys.stderr:print(str(e),file=sys.stderr)
  sys.exit(1)
