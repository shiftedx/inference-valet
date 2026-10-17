"""Windows idle reload policy and persistent controls for Inference Valet."""
import contextlib, ctypes, json, msvcrt, os, pathlib, re, time, winreg
import psutil
from ai_issues import write_json

IDLE_MINUTES=(5,10,15,20,25,30)

def restore_minutes(value):
 return value if type(value) is int and value in IDLE_MINUTES else 20

class Settings:
 def __init__(self,path):self.path=pathlib.Path(path)
 @staticmethod
 def normalize(data):
  if not isinstance(data,dict):raise ValueError('Settings must be an object')
  games=data.get('extra_games',[]);profile=data.get('last_profile')
  if not isinstance(games,list) or any(not isinstance(game,str) for game in games):raise ValueError('extra_games must contain executable paths')
  if profile is not None and not isinstance(profile,str):raise ValueError('last_profile must be a profile ID')
  return dict(idle_minutes=restore_minutes(data.get('idle_minutes')),enabled=data.get('enabled',True) is True,last_profile=profile,extra_games=games,demand_armed=data.get('demand_armed',True) is True)
 def load(self,path):return self.normalize(json.loads(path.read_text(encoding='utf-8-sig')))
 def read(self):
  try:return self.load(self.path)
  except FileNotFoundError:
   if not self.path.with_suffix('.bak').exists():return self.normalize({})
  except (ValueError,UnicodeError):pass
  # A stale backup must never undo a manual Unload or rearm automatic loading.
  try:data=self.load(self.path.with_suffix('.bak'))
  except (OSError,ValueError,UnicodeError):data=self.normalize({})
  data.update(enabled=False,demand_armed=False)
  return data
 def update(self,**changes):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.path.with_suffix('.lock').open('a+b') as lock:
   lock.seek(0);lock.write(b'0');lock.flush();deadline=time.monotonic()+5
   while True:
    try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
    except OSError:
     if time.monotonic()>deadline:raise RuntimeError('Idle settings are busy')
     time.sleep(.05)
   try:
    data=self.read();data.update(changes)
    try:previous=self.load(self.path)
    except FileNotFoundError:previous=None
    except (ValueError,UnicodeError):
     # Preserve unreadable bytes before the first explicit preference update.
     damaged=self.path.with_name(self.path.stem+'.corrupt-'+str(time.time_ns())+self.path.suffix)
     with damaged.open('xb') as saved:saved.write(self.path.read_bytes());saved.flush();os.fsync(saved.fileno())
     previous=None
    if previous is not None:write_json(self.path.with_suffix('.bak'),previous)
    write_json(self.path,data)
    return data
   finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

class IdlePolicy:
 def __init__(self,now):self.blocked_at=now;self.had_game=False;self.retry_at=0
 def failed(self,now):self.retry_at=now+300
 def decide(self,now,idle,games,busy,enabled,profile,last_stop,idle_minutes=20):
  if games:self.blocked_at=now;self.had_game=True
  elif self.had_game:self.blocked_at=now;self.had_game=False
  if not enabled:return False,'Auto reload paused'
  if not profile:return False,'Auto reload: load a profile once to remember it'
  if games:return False,'Auto reload blocked: '+', '.join(games[:3])
  if busy:return False,'Auto reload: model running or action in progress'
  if now<self.retry_at:return False,'Auto reload: retry in '+str(int(self.retry_at-now)+1)+'s'
  # Ignore timestamps from before a reboot that lie in the future.
  stop=last_stop if 0<=last_stop<=now else 0
  delay=restore_minutes(idle_minutes)*60
  remaining=max(delay-idle,delay-(now-max(self.blocked_at,stop)),0)
  if remaining:return False,f'Auto reload: waiting {int(remaining)//60:02d}:{int(remaining)%60:02d} of idle time'
  return True,'Auto reload: restoring last profile'

def idle_seconds():
 from ctypes import wintypes
 class LastInput(ctypes.Structure):_fields_=[('cbSize',wintypes.UINT),('dwTime',wintypes.DWORD)]
 item=LastInput();item.cbSize=ctypes.sizeof(item)
 if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(item)):raise ctypes.WinError()
 ctypes.windll.kernel32.GetTickCount.restype=wintypes.DWORD
 return ((ctypes.windll.kernel32.GetTickCount()-item.dwTime)&0xffffffff)/1000

class GameDetector:
 def __init__(self):self.roots=[];self.recorded=set();self.refreshed=-1000
 @staticmethod
 def valet_process(proc):
  # Match our actual interpreter and entry point, never a title or a shared
  # python.exe name. Other Python applications can legitimately be games.
  import sys
  base=pathlib.Path(__file__).resolve().parent
  interpreters={os.path.normcase(str(pathlib.Path(sys.executable).resolve()))}
  interpreters.update(os.path.normcase(str(base/'.venv/Scripts'/name)) for name in ('python.exe','pythonw.exe'))
  # Windows venv redirectors can expose the base interpreter as the real
  # process image, even though the command was launched through pythonw.exe
  # in our venv. Trust only that exact base installation, plus our entry point.
  base_executable=getattr(sys,'_base_executable',None)
  if base_executable:
   executable=pathlib.Path(base_executable).resolve()
   interpreters.update(os.path.normcase(str(executable.with_name(name))) for name in ('python.exe','pythonw.exe'))
  try:
   command=proc.cmdline()
   if os.path.normcase(proc.exe()) not in interpreters or len(command)<2:return False
   script=pathlib.Path(command[1])
   if not script.is_absolute():script=pathlib.Path(proc.cwd())/script
   return os.path.normcase(str(script.resolve()))==os.path.normcase(str(base/'ai-launcher.py'))
  except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):return False
 @staticmethod
 def foreground_fullscreen_process():
  from ctypes import wintypes
  class MonitorInfo(ctypes.Structure):
   _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
  user=ctypes.windll.user32
  # Handles are pointer-sized; default ctypes integer returns truncate on x64.
  user.GetForegroundWindow.restype=wintypes.HWND
  user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
  user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
  user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]
  user.MonitorFromWindow.restype=wintypes.HANDLE
  user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
  window=user.GetForegroundWindow()
  if not window:return None
  rect=wintypes.RECT();monitor=MonitorInfo();monitor.cbSize=ctypes.sizeof(monitor)
  if not user.GetWindowRect(window,ctypes.byref(rect)):return None
  handle=user.MonitorFromWindow(window,2)
  if not handle or not user.GetMonitorInfoW(handle,ctypes.byref(monitor)):return None
  bounds=monitor.rcMonitor
  if not (rect.left<=bounds.left and rect.top<=bounds.top and rect.right>=bounds.right and rect.bottom>=bounds.bottom):return None
  pid=wintypes.DWORD()
  if not user.GetWindowThreadProcessId(window,ctypes.byref(pid)) or not pid.value:return None
  try:return psutil.Process(pid.value)
  except psutil.NoSuchProcess:return None
 def fullscreen_game(self,state):
  # QUNS_BUSY (2) also describes ordinary apps, and PRESENTATION_MODE (4)
  # describes a notification policy. Neither identifies a game. Only exclusive
  # Direct3D (3), corroborated by a real fullscreen foreground window, adds a
  # fallback for games outside our known executable paths.
  if state!=3:return None
  proc=self.foreground_fullscreen_process()
  if proc is None or self.valet_process(proc):return None
  try:return 'Exclusive fullscreen: '+proc.name()
  except (psutil.NoSuchProcess,psutil.AccessDenied):return None
 def discover(self):
  roots=[];recorded=set()
  try:
   with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam') as key:steam=pathlib.Path(winreg.QueryValueEx(key,'SteamPath')[0])
   folders=[steam]
   vdf=steam/'steamapps/libraryfolders.vdf'
   if vdf.exists():folders.extend(pathlib.Path(p.replace('\\\\','\\')) for p in re.findall(r'"path"\s+"([^"]+)"',vdf.read_text(encoding='utf-8')))
   for folder in set(folders):
    for manifest in (folder/'steamapps').glob('appmanifest_*.acf'):
     content=manifest.read_text(encoding='utf-8');match=re.search(r'"installdir"\s+"([^"]+)"',content)
     if match and match[1].casefold() not in ['wallpaper_engine','steamworks shared']:roots.append(os.path.normcase(str(folder/'steamapps/common'/match[1]))+os.sep)
  except FileNotFoundError:pass
  try:
   with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'System\GameConfigStore\Children') as parent:
    for i in range(winreg.QueryInfoKey(parent)[0]):
     try:
      with winreg.OpenKey(parent,winreg.EnumKey(parent,i)) as child:path=winreg.QueryValueEx(child,'MatchedExeFullPath')[0]
      if path and 'wallpaper_engine' not in path.casefold():recorded.add(os.path.normcase(path))
     except FileNotFoundError:pass
  except FileNotFoundError:pass
  self.roots=roots;self.recorded=recorded;self.refreshed=time.monotonic()
 def running(self,extra=(),strict=False):
  if time.monotonic()-self.refreshed>60:self.discover()
  exact=self.recorded|{os.path.normcase(str(pathlib.Path(p).resolve())) for p in extra}
  found=[]
  interactive=None
  if strict:
   class Entry(ctypes.Structure):
    _fields_=[('session',ctypes.c_ulong),('pid',ctypes.c_ulong),('name',ctypes.c_wchar_p),('sid',ctypes.c_void_p)]
   entries=ctypes.POINTER(Entry)();count=ctypes.c_ulong();own=ctypes.c_ulong()
   if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(own)):raise OSError('Cannot inspect current session')
   if not ctypes.windll.wtsapi32.WTSEnumerateProcessesW(None,0,1,ctypes.byref(entries),ctypes.byref(count)):raise OSError('Cannot enumerate interactive processes')
   try:interactive={entries[i].pid for i in range(count.value) if entries[i].session==own.value}
   finally:ctypes.windll.wtsapi32.WTSFreeMemory(entries)
  for proc in psutil.process_iter(['exe','name']):
   try:
    exe=proc.info['exe']
    if not exe:
     if strict and proc.pid in interactive:
      try:proc.exe()
      except psutil.AccessDenied:raise OSError('Cannot inspect interactive process: '+(proc.info['name'] or str(proc.pid)))
     continue
    path=os.path.normcase(exe)
    if path in exact or any(path.startswith(root) for root in self.roots):found.append(proc.info['name'] or exe)
   except (psutil.NoSuchProcess,psutil.AccessDenied):continue
  # Known games above remain authoritative even when Valet has foreground focus.
  state=ctypes.c_int()
  hr=ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
  if hr!=0:raise OSError('Cannot check fullscreen activity')
  fullscreen=self.fullscreen_game(state.value)
  if fullscreen:found.append(fullscreen)
  return sorted(set(found))
