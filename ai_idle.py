"""Windows idle reload policy and persistent controls for Inference Valet."""
import contextlib, ctypes, json, msvcrt, os, pathlib, re, time, winreg
import psutil

IDLE_MINUTES=(5,10,15,20,25,30)

def restore_minutes(value):
 return value if type(value) is int and value in IDLE_MINUTES else 20

class Settings:
 def __init__(self,path):self.path=pathlib.Path(path)
 def read(self):
  try:
   data=json.loads(self.path.read_text(encoding='utf-8'))
   if not isinstance(data,dict):raise ValueError('Settings must be an object')
   return dict(idle_minutes=restore_minutes(data.get('idle_minutes')),enabled=data.get('enabled',True) is True,last_profile=data.get('last_profile'),extra_games=data.get('extra_games',[]),demand_armed=data.get('demand_armed',True) is True)
  except FileNotFoundError:return dict(idle_minutes=20,enabled=True,last_profile=None,extra_games=[],demand_armed=True)
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
    temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2),encoding='utf-8');temp.replace(self.path)
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
  # This is an additional conservative guard, not the sole game detector.
  state=ctypes.c_int()
  hr=ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
  if hr!=0:raise OSError('Cannot check fullscreen activity')
  if state.value in [2,3,4]:found.append('fullscreen / presentation app')
  return sorted(set(found))
