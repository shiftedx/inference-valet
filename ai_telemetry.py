"""Read-only performance sampling and the native AI launcher dashboard."""
import ctypes,math,socket,subprocess,time
from collections import deque
import psutil
from ai_config import NVIDIA_SMI, CONFIG, STRATA_ROOT
from ai_gpu import GpuTelemetry,ActivePowerAverage

GIB=2**30
def number(value):
 return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None
def ratio(n,d,scale=1):
 return n/d*scale if number(n) is not None and number(d) is not None and d>0 else None
def fmt(value,suffix='',digits=1):
 return f'{value:,.{digits}f}{suffix}' if number(value) is not None else '—'

def normalize_strata(metrics):
 live=metrics.get('live') or {};engine=metrics.get('engine') or {}
 last=next(iter(metrics.get('requests') or []),{})
 state=live.get('state','unavailable');limit=engine.get('max_context');slots=[]
 for row in live.get('slots') or []:
  idle=row.get('state')=='idle';used=row.get('held_tokens') if idle else (row.get('prompt_tokens') or 0)+(row.get('generated') or 0)
  slots.append({'slot':row.get('slot',len(slots)),'state':'cached' if idle and used else row.get('state','unknown'),'used':used,'limit':limit,'speed':row.get('tok_s') if not idle else None})
 if not slots:
  used=(live.get('prompt_tokens') or 0)+(live.get('generated') or 0) if state in ('reading','generating') else None
  slots=[{'slot':0,'state':state,'used':used,'limit':limit,'speed':live.get('tok_s') if state=='generating' else None}]
 prompt=last.get('prompt_tokens');prefill=last.get('prefill_tok_s')
 if prefill is None:prefill=ratio(last.get('prompt_read'),last.get('prompt_ms'),1000)
 return {'state':state,'context':limit,'vision':engine.get('images'),'slots':slots,
         'live_speed':live.get('tok_s') if state=='generating' else None,
         'prefill_speed':live.get('prefill_tok_s_mean') if state in ('reading','generating') else None,
         'last_speed':last.get('decode_tok_s'),'last_prefill':prefill,'ttft_ms':last.get('ttft_ms'),
         'reuse':ratio(last.get('reused'),prompt,100),'generated':live.get('generated') if state in ('reading','generating') else None,
         'running':live.get('running',int(state in ('reading','generating'))),'queued':live.get('queued'),
         'prompt_read':live.get('prompt_read'),'prompt_total':live.get('prompt_total'),
         'last_at':last.get('time'),'expert_hits':ratio(last.get('hit_rate'),1,100),'pcie_share':ratio(last.get('pcie_share'),1,100),
         'draft_acceptance':ratio(last.get('drafts_accepted'),last.get('drafts_offered'),100),'hardware':metrics.get('hardware') or {}}

class Perf(ctypes.Structure):
 _fields_=[('cb',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable','SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+[(k,ctypes.c_ulong) for k in ('HandleCount','ProcessCount','ThreadCount')]
def host_hardware():
 vm=psutil.virtual_memory();out={'cpu':psutil.cpu_percent(interval=.1),'ram_used':vm.total-vm.available,'ram_total':vm.total,'ram_free_gib':vm.available/GIB}
 perf=Perf();perf.cb=ctypes.sizeof(perf)
 if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf),perf.cb):
  out.update(commit_free_gib=(perf.CommitLimit-perf.CommitTotal)*perf.PageSize/GIB,commit_used=perf.CommitTotal*perf.PageSize,commit_total=perf.CommitLimit*perf.PageSize)
 return out

def strata_listener(processes):
 """Return the verified server that actually owns the local API listener."""
 for process,kind in processes:
  if kind!='strata-server':continue
  try:
   if any(c.status==psutil.CONN_LISTEN and c.laddr.port==8080 and c.laddr.ip in ('127.0.0.1','0.0.0.0') for c in process.net_connections(kind='tcp')):return process
  except (OSError,psutil.Error):continue
 return None

class Collector:
 def __init__(self,fetch,servers,demand=None,gpu_probe=None):
  from ai_runtime_details import RuntimeDetailsReader
  self.fetch=fetch;self.servers=servers;self.demand=demand or (lambda:{})
  self.gpu_probe=gpu_probe if gpu_probe is not None else GpuTelemetry();self.active_power=ActivePowerAverage()
  self.gpu_reading={};self.gpu_checked=float('-inf')
  self.runtime_details=RuntimeDetailsReader(STRATA_ROOT)
 def collect(self):return self._collect(True)
 def summary(self):return self._collect(False)
 def _collect(self,detailed):
  from ai_activity import build_activity,read_comfy,read_gpu_processes
  from ai_demand import DEFAULTS
  sampled=time.monotonic();hardware=host_hardware() if detailed else {};out={'state':'no model loaded','slots':[],'live_speed':None,'hardware':hardware};identity=None
  processes=[];status=None;metrics=None;health=None;verified=False;demand={};listener=None;shared_settings=None
  try:
   processes=list(self.servers());identity=tuple(sorted((p.pid,p.create_time()) for p,k in processes))
   # A known script somewhere on the PC does not establish ownership of port 8080.
   listener=strata_listener(processes);verified=listener is not None
   if verified:
    demand=self.demand()
    if demand.get('owner_pid')!=listener.pid or demand.get('owner_created')!=listener.create_time():demand={}
    try:health=self.fetch('/health')
    except (OSError,ValueError):pass
    try:metrics=self.fetch('/metrics')
    except (OSError,ValueError):pass
    try:status=self.fetch('/v1/status')
    except (OSError,ValueError):pass
    if detailed:
     try:shared_settings=self.fetch('/settings')
     except (OSError,ValueError,KeyError):pass
    if not listener.is_running() or strata_listener([(listener,'strata-server')]) is None:
     verified=False;status=None;metrics=None;health=None;demand={};shared_settings=None
   else:
    try:
     with socket.create_connection(('127.0.0.1',8080),timeout=.2):health={'status':'unverified'}
    except OSError:pass
   if isinstance(metrics,dict):out=normalize_strata(metrics)
   if isinstance(status,dict):
    out['context']=status.get('context',{}).get('native',out.get('context'))
    last=status.get('last_timings') or {}
    if last:
     out['last_prefill']=last.get('prompt_per_second',out.get('last_prefill'));out['last_speed']=last.get('predicted_per_second',out.get('last_speed'))
    out['vision']=status.get('vision',{}).get('enabled');out['capacity']=status.get('concurrency',{}).get('serving',1)
    if status.get('loaded') is False:
     out.update(state='unloaded · reloads on next request',live_speed=None,prefill_speed=None,slots=[],generated=None)
   elif processes:out['state']='loading'
  except (OSError,ValueError,KeyError,IndexError,TypeError,psutil.Error):
   out={'state':'telemetry unavailable · retrying','slots':[],'live_speed':None,'hardware':{}}
  hardware.update(self.gpu_probe())
  # Driver telemetry also works when the model is unloaded; never spawn a visible console.
  if detailed and not out.get('hardware',{}).get('gpu_mem_total'):
   try:
    run=subprocess.run([NVIDIA_SMI,'--id=0','--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,clocks.current.graphics,clocks.current.memory,utilization.memory,power.limit','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,creationflags=subprocess.CREATE_NO_WINDOW)
    vals=run.stdout.splitlines()[0].split(',')
    for raw,key,multiplier in zip(vals,('gpu_util','gpu_mem_used','gpu_mem_total','gpu_temp','gpu_power','gpu_clock','gpu_memory_clock','gpu_memory_busy','gpu_power_limit'),(1,2**20,2**20,1,1,1,1,1,1)):
     try:value=float(raw.strip())
     except ValueError:continue
     if number(value) is not None and value>=0:hardware[key]=value*multiplier
   except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):pass
  out['hardware']={**out.get('hardware',{}),**hardware};out.update(sampled=sampled,identity=identity)
  if detailed and sampled-self.gpu_checked>=10:
   self.gpu_reading=read_gpu_processes(NVIDIA_SMI);self.gpu_checked=sampled
  gpu_reading=self.gpu_reading if sampled-self.gpu_checked<12 else {'available':False,'processes':[]}
  activity=build_activity(status,metrics,demand,out['hardware'],gpu_reading,
                         {p.pid for p,k in processes},verified=verified,health=health,
                         options={**DEFAULTS,**CONFIG.get('on_demand',{})})
  activity['comfy']=read_comfy(CONFIG.get('activity',{}).get('comfyui_url'))
  comfy=activity['comfy']
  # Queue activity alone does not prove GPU use or grant admission priority.
  admission_url=CONFIG.get('on_demand',{}).get('comfyui_url')
  observed_url=CONFIG.get('activity',{}).get('comfyui_url')
  if comfy.get('state')=='busy' and admission_url and admission_url.rstrip('/')==(observed_url or '').rstrip('/') and status and status.get('loaded') is False:
   activity['blockers'].append('ComfyUI generation has configured admission priority')
   if activity['state']=='unloaded':
    activity.update(state='blocked',title='Waiting for GPU',detail='ComfyUI generation has configured admission priority')
  native_live=metrics.get('live') if isinstance(metrics,dict) else None
  native_work=isinstance(native_live,dict) and native_live.get('state') in ('reading','generating','loading')
  active=verified and isinstance(status,dict) and (activity['state'] in ('reading','generating','loading','busy') or status.get('loaded') is True and native_work)
  out['power_stats']=self.active_power.sample(sampled,out['hardware'].get('gpu_power'),active)
  out['activity']=activity;out['state']=activity['title'].lower()
  out['running']=activity.get('running');out['queued']=activity.get('queued')
  if activity['state'] in ('offline','unavailable'):
   out.update(live_speed=None,prefill_speed=None,slots=[],generated=None,running=None,queued=None)
  if detailed:
   from ai_engine_details import build_engine_details,parse_startup_facts
   runtime_config,log_text=self.runtime_details.read(processes,listener) if verified and status else (None,'')
   out['engine_details']=build_engine_details(metrics if verified else None,status if verified else None,
                                             runtime_config,parse_startup_facts(log_text),shared_settings)
   out['memory_settings_pending']=self.runtime_details.pending_memory(runtime_config) if runtime_config else None
  return out

from ai_widgets import THEME,Button,Tooltip,ui_font,reveal_tooltip

import tkinter as tk

class Meter(tk.Canvas):
 """A small native canvas rail; ttk's Windows progress element has fixed height."""
 def __init__(self,parent,maximum=100,length=130,style='Live.Horizontal.TProgressbar',segmented=False,height=4):
  self.bar_height=max(4,round(height*float(parent.tk.call('tk','scaling'))/(96/72)))
  self.segmented=segmented
  super().__init__(parent,width=length,height=self.bar_height,bg=parent.cget('bg') if segmented else THEME['line'],highlightthickness=0,bd=0)
  self.value=0;self.meter_style=style;self.bind('<Configure>',lambda event:self.redraw())
 def __setitem__(self,key,value):
  if key=='value':self.value=value;self.redraw()
  else:super().__setitem__(key,value)
 def __getitem__(self,key):
  return self.value if key=='value' else super().__getitem__(key)
 def configure(self,cnf=None,**kw):
  if 'style' in kw:self.meter_style=kw.pop('style');self.redraw()
  if cnf or kw:return super().configure(cnf,**kw)
 def redraw(self):
  self.delete('all');color=THEME['warning'] if self.meter_style.startswith('Warn') else THEME['meter_ram'] if self.meter_style.startswith('Memory.RAM') else THEME['meter_gpu'] if self.meter_style.startswith('Memory') else THEME['chart_output']
  if self.segmented:
   width=max(1,self.winfo_width());gap=2;step=width/24;limit=width*min(100,max(0,self.value))/100
   for index in range(24):
    left=index*step;right=max(left+1,(index+1)*step-gap)
    self.create_rectangle(left,0,right,self.bar_height,fill=THEME['line'],outline='')
    if limit>left:self.create_rectangle(left,0,min(right,limit),self.bar_height,fill=color,outline='')
   return
  if self.value:self.create_rectangle(0,0,max(1,self.winfo_width()*self.value/100),self.bar_height,fill=color,outline='')

class RequestTrend(tk.Canvas):
 def __init__(self,parent,scale,color):
  super().__init__(parent,width=round(48*scale),height=round(20*scale),bg=THEME['bg'],highlightthickness=0)
  self.points=[];self.color=color;self.scale=scale;self.tip=None
  self.bind('<Configure>',lambda event:self.draw())
  self.bind('<Enter>',self.show_tip);self.bind('<Leave>',self.hide_tip)
 def show_tip(self,event):
  self.hide_tip();self.tip=tk.Toplevel(self);self.tip.withdraw();self.tip.overrideredirect(True)
  self.tip.geometry(f'+{event.x_root+12}+{event.y_root+12}')
  tk.Label(self.tip,text='Up to 12 completed requests; scale fits the values.',bg=THEME['card'],fg=THEME['muted'],font=ui_font('caption'),padx=8,pady=4,justify='left').pack()
  reveal_tooltip(self.tip,self)
 def hide_tip(self,event=None):
  if self.tip:self.tip.destroy();self.tip=None
 def draw(self):
  self.delete('all');w=self.winfo_width();h=self.winfo_height();pad=3*self.scale
  self.create_line(pad,h-pad,w-pad,h-pad,fill=THEME['line'])
  values=[v for v in self.points if v is not None]
  if not values:return
  peak=max(values) or 1;previous=None
  for i,value in enumerate(self.points):
   if value is None:previous=None;continue
   x=w-pad if len(self.points)==1 else pad+(w-2*pad)*i/(len(self.points)-1);y=h-pad-(h-2*pad)*value/peak
   if previous:self.create_line(*previous,x,y,fill=self.color,width=max(1,round(self.scale)))
   self.create_oval(x-self.scale,y-self.scale,x+self.scale,y+self.scale,fill=self.color,outline='')
   previous=(x,y)

class StatusMark(tk.Label):
 """Compact readout with the same explanation on hover and keyboard focus."""
 def __init__(self,parent,description,**kwargs):
  super().__init__(parent,bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),takefocus=True,highlightthickness=1,highlightbackground=THEME['bg'],highlightcolor=THEME['accent'],**kwargs)
  self.description=description;self.tip=None
  self.bind('<Enter>',self.show_tip);self.bind('<FocusIn>',self.show_tip)
  self.bind('<Leave>',self.hide_tip);self.bind('<FocusOut>',self.hide_tip)
  self.bind('<Escape>',self.hide_tip);self.bind('<Destroy>',self.hide_tip)
 def show_tip(self,event=None):
  self.hide_tip()
  text=self.description.get()
  if not text:return
  self.tip=tk.Toplevel(self);self.tip.withdraw();self.tip.overrideredirect(True)
  anchor=getattr(self,'anchor_widget',self)
  self.tip.geometry(f'+{anchor.winfo_rootx()}+{anchor.winfo_rooty()+anchor.winfo_height()+4}')
  tk.Label(self.tip,text=text,bg=THEME['card'],fg=THEME['text'],font=ui_font('caption'),padx=8,pady=5,wraplength=360,justify='left').pack()
  reveal_tooltip(self.tip,anchor)
 def hide_tip(self,event=None):
  if self.tip:self.tip.destroy();self.tip=None

class GpuTuningPanel(tk.Frame):
 """Small tuning readouts; unsupported driver metrics take no space."""
 def __init__(self,parent,compact=False):
  super().__init__(parent,bg=THEME['bg'])
  self.factor=float(self.tk.call('tk','scaling'))/(96/72);self.compact=compact
  self.groups={};self.values={};self.visible=[];self.layout_key=None;self.bind('<Configure>',lambda event:self._layout());self.average_help=tk.StringVar(value='')
  for key,title in (('gpu_clock','Core clock'),('gpu_memory_clock','Memory clock'),('gpu_memory_busy','Memory activity'),('gpu_temp','Temperature'),('gpu_power','Power'),('average_watts','Strata avg')):
   group=tk.Frame(self,bg=THEME['bg']);self.groups[key]=group
   tk.Label(group,text=title,bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),anchor='w').pack(fill='x')
   value=tk.StringVar(value='—');self.values[key]=value
   label=tk.Label(group,textvariable=value,bg=THEME['bg'],fg=THEME['text'],font=ui_font('caption',True),anchor='w');label.pack(fill='x')
   help_text={'gpu_memory_busy':'Percent of sampling time spent reading or writing VRAM.','gpu_power':'Whole-GPU draw / power limit.','average_watts':self.average_help}.get(key)
   if help_text is not None:Tooltip(group,help_text);Tooltip(label,help_text)
 def update_values(self,hardware,stats):
  available=[]
  for key in self.groups:
   value=number(stats.get(key) if key=='average_watts' else hardware.get(key))
   if value is None or value<0:
    self.groups[key].grid_remove();continue
   suffix=' MHz' if key.endswith('clock') else '%' if key=='gpu_memory_busy' else ' °C' if key=='gpu_temp' else ' W'
   text=fmt(value,suffix,0)
   limit=number(hardware.get('gpu_power_limit'))
   if key=='gpu_power' and limit is not None:text=f'{value:.0f} / {limit:.0f} W'
   self.values[key].set(text);available.append(key)
  self.average_help.set(f"Session average · {stats.get('samples',0)} active samples. Includes other GPU workloads.")
  self.visible=available;self._layout()
  return bool(available)
 def _layout(self):
  available=self.visible
  if not available:return
  gap=round(12*self.factor)
  columns=min(3 if self.compact else 6,len(available))
  needed=columns*max(self.groups[key].winfo_reqwidth() for key in available)+gap*(columns-1)
  if columns>3 and self.winfo_width()>1 and self.winfo_width()<needed:columns=3
  layout=(tuple(available),columns)
  if layout==self.layout_key:return
  self.layout_key=layout
  for col in range(6):self.columnconfigure(col,weight=0,minsize=0,uniform='')
  for col in range(columns):self.columnconfigure(col,weight=1,uniform='tuning')
  for index,key in enumerate(available):self.groups[key].grid(row=index//columns,column=index%columns,sticky='ew',padx=(0,gap) if index%columns<columns-1 else 0,pady=(0,round(8*self.factor)) if index//columns<(len(available)-1)//columns else 0)
 def mark_stale(self):
  for key in self.visible:
   if key!='average_watts':self.values[key].set('—')

class PerformancePanel:
 def __init__(self, parent, compact=False, status_parent=None):
  self.on_edit_engine=lambda:None
  from tkinter import ttk
  self.compact=compact;self.samples=deque(maxlen=120);self.history=deque(maxlen=120);self.identity=None;self.latest={};self.on_layout=lambda:None;self.on_details=lambda expanded:None;self.request_history=deque(maxlen=12);self.last_request=None
  self.scale=float(parent.tk.call('tk','scaling'))/(96/72)
  self.frame=tk.Frame(parent,bg=THEME['bg'])
  self.warning=tk.StringVar(value='')
  self.gpu_memory=tk.StringVar(value='—')
  self.speed=tk.StringVar(value='—');self.speed_note=tk.StringVar(value='No completed request')
  self.activity_title=tk.StringVar(value='Checking backend');self.activity_note=tk.StringVar(value='Waiting for a current reading')
  self.status_external=status_parent is not None
  self.activity_header=tk.Frame(status_parent if self.status_external else self.frame,bg=THEME['bg'])
  self.activity_header.columnconfigure(1,weight=1)
  self.status_dot=self._label(self.activity_header,'●','caption',color=THEME['muted']);self.status_dot.grid(row=0,column=0,padx=(0,round(8*self.scale)))
  self.gpu_observation=tk.StringVar(value='GPU observation unavailable');self.comfy_observation=tk.StringVar(value='ComfyUI state unavailable')
  self.activity_marks=tk.Frame(self.activity_header,bg=THEME['bg'])
  self.gpu_mark=StatusMark(self.activity_marks,self.gpu_observation,text='▣ —');self.gpu_mark.pack(side='left')
  self.comfy_mark=StatusMark(self.activity_marks,self.comfy_observation,text='')
  self.activity_title_label=self._label(self.activity_header,variable=self.activity_title,size='caption' if self.status_external else 'body',bold=True)
  self.activity_title_label.grid(row=0,column=1,sticky='ew')
  self.activity_note_label=self._label(self.activity_header,variable=self.activity_note,size='caption',color=THEME['muted'])
  self.activity_header.bind('<Configure>',lambda event:self._fit_activity_header())
  # Keep the full observation for Diagnostics and assistive hover text.
  self.activity_tip=StatusMark(self.activity_header,self.activity_note,text='')
  self.activity_tip.anchor_widget=self.activity_title_label
  self.activity_title_label.bind('<Enter>',self.activity_tip.show_tip)
  self.activity_title_label.bind('<Leave>',self.activity_tip.hide_tip)
  if compact:
   self.gpu_meter=Meter(self.frame,style='Memory.Horizontal.TProgressbar')
   row=tk.Frame(self.frame,bg=THEME['bg']);row.pack(fill='x',pady=(0,3))
   self._label(row,'GPU memory','body',color=THEME['muted']).pack(side='left')
   self._label(row,variable=self.gpu_memory,size='metric',bold=True,color=THEME['text']).pack(side='right')
   self.gpu_meter.pack(fill='x',pady=(0,2))
   speed_row=tk.Frame(self.frame,bg=THEME['bg']);speed_row.pack(fill='x',pady=(10,0))
   self._label(speed_row,'Output speed','body',color=THEME['muted']).pack(side='left')
   self._label(speed_row,variable=self.speed,size='metric',bold=True).pack(side='right')
   self._label(self.frame,variable=self.speed_note,size='caption',color=THEME['muted']).pack(anchor='e',pady=(2,0))
   self.gpu_tuning=GpuTuningPanel(self.frame,compact=True)
   self.technical_body=None;self.details_expanded=False
   return
  self.warning_label=self._label(self.frame,variable=self.warning,size='body',color=THEME['warning'],wrap=round(690*self.scale))
  self.warning_label.bind('<Configure>',lambda event:self.warning_label.configure(wraplength=max(80,event.width)))
  overview=tk.Frame(self.frame,bg=THEME['bg']);overview.pack(fill='x');self.overview=overview
  self.requests=tk.StringVar(value='— active');self.requests_note=tk.StringVar(value='— waiting')
  self.prompt_speed=tk.StringVar(value='—');self.prompt_note=tk.StringVar(value='No completed request')
  self.first_token=tk.StringVar(value='—');self.first_token_note=tk.StringVar(value='No completed request')
  self.ram_memory=tk.StringVar(value='—');self.ram_note=tk.StringVar(value='System memory')
  self.metric_widgets={}
  groups=[]
  for col,title in enumerate(('Throughput','Memory','Requests')):
   group=tk.Frame(overview,bg=THEME['bg']);group.grid(row=0,column=col*2,sticky='nsew')
   overview.columnconfigure(col*2,weight=1,uniform='overview');groups.append(group)
   if col<2:overview.columnconfigure(col*2+1,minsize=round(20*self.scale))
   self._label(group,title,'body',bold=True).pack(anchor='w',pady=(0,6))
  throughput,memory,requests=groups
  self.source_marks={}
  for title,key,var in (('Output','speed',self.speed),('Prompt','prompt_speed',self.prompt_speed)):
   row=tk.Frame(throughput,bg=THEME['bg']);row.pack(fill='x',pady=(0,5))
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   mark=StatusMark(row,self.speed_note if key=='speed' else self.prompt_note,text='—');mark.pack(side='left',padx=(4,0));self.source_marks[key]=mark
   label=self._label(row,variable=var,size='metric',bold=True);label.pack(side='right');self.metric_widgets[key]=label
   if key=='prompt_speed':
    self.prompt_trend=RequestTrend(row,self.scale,THEME['chart_output']);self.prompt_trend.pack(side='left',fill='x',expand=True,padx=6)
  self.throughput_source=tk.StringVar(value='No completed request')
  for title,key,var in (('GPU','gpu_memory',self.gpu_memory),('RAM','ram_memory',self.ram_memory)):
   group=tk.Frame(memory,bg=THEME['bg']);group.pack(fill='x',pady=(0,8))
   row=tk.Frame(group,bg=THEME['bg']);row.pack(fill='x')
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   label=self._label(row,variable=var,size='metric',bold=True);label.pack(side='right');self.metric_widgets[key]=label
   meter=Meter(group,style='Memory.GPU.Horizontal.TProgressbar' if key=='gpu_memory' else 'Memory.RAM.Horizontal.TProgressbar',segmented=True,height=7);meter.pack(fill='x',pady=(5,0))
   if key=='gpu_memory':self.gpu_card=group;self.gpu_meter=meter
   else:self.ram_meter=meter
  request_row=tk.Frame(requests,bg=THEME['bg']);request_row.pack(fill='x')
  label=self._label(request_row,variable=self.requests,size='metric',bold=True);label.pack(side='left');self.metric_widgets['requests']=label
  self._label(request_row,variable=self.requests_note,size='caption',color=THEME['muted']).pack(side='right')
  self.agent_activity=tk.Canvas(requests,height=round(22*self.scale),bg=THEME['bg'],highlightthickness=0)
  self.agent_activity.pack(fill='x',pady=(4,2));self.agent_activity.bind('<Configure>',lambda event:self.draw_agents())
  self.first_token_group=tk.Frame(requests,bg=THEME['bg'])
  token_row=tk.Frame(self.first_token_group,bg=THEME['bg']);token_row.pack(fill='x')
  self._label(token_row,'First token','caption',color=THEME['muted']).pack(side='left')
  label=self._label(token_row,variable=self.first_token,size='metric',bold=True);label.pack(side='right');self.metric_widgets['first_token']=label
  self.token_trend=RequestTrend(token_row,self.scale,THEME['info']);self.token_trend.pack(side='left',fill='x',expand=True,padx=6)
  self._label(self.first_token_group,variable=self.first_token_note,size='caption',color=THEME['muted']).pack(anchor='w',pady=(3,0))
  self.charts=tk.Frame(self.frame,bg=THEME['bg']);self.charts.pack(fill='both',expand=True,pady=(12,0))
  self.plots={};self.plot_values={}
  for col,key,title,color in ((0,'output','Output',THEME['chart_output']),(1,'gpu','GPU use',THEME['chart_gpu']),(2,'cpu','CPU use',THEME['chart_cpu'])):
   group=tk.Frame(self.charts,bg=THEME['bg']);group.grid(row=0,column=col*2,sticky='nsew')
   self.charts.columnconfigure(col*2,weight=1,uniform='charts')
   if col<2:self.charts.columnconfigure(col*2+1,minsize=round(20*self.scale))
   row=tk.Frame(group,bg=THEME['bg']);row.pack(fill='x')
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   value=tk.StringVar(value='—');self.plot_values[key]=value;self._label(row,variable=value,size='caption',bold=True,color=color).pack(side='right')
   plot=tk.Canvas(group,height=round(60*self.scale),bg=THEME['bg'],highlightthickness=0)
   plot.pack(fill='both',expand=True);plot.bind('<Configure>',lambda event:self.draw());self.plots[key]=plot
  self.charts.rowconfigure(0,weight=1);self.graph=self.plots['output']
  self.gpu_tuning=GpuTuningPanel(self.frame)
  self.context_summary=tk.StringVar(value='Context · waiting for model telemetry')
  context_header=tk.Frame(self.frame,bg=THEME['bg']);self.context_header=context_header;context_header.pack(fill='x',pady=(9,0))
  self._label(context_header,variable=self.context_summary,size='caption',color=THEME['muted']).pack(side='left')
  self.context_graph=tk.Canvas(self.frame,height=round(42*self.scale),bg=THEME['bg'],highlightthickness=0)
  self.context_graph.pack(fill='x');self.context_graph.bind('<Configure>',lambda event:self.draw_context())
  self.details_expanded=False
  self.details_button=Button(self.frame,text='Request activity & details  ▾',command=self.toggle_details,quiet=True)
  self.details_button.pack(anchor='center',pady=(round(8*self.scale),0))
  self.detail_container=tk.Frame(self.frame,bg=THEME['bg'])
  # Details stay a bounded workspace: switching tabs never grows the dashboard.
  style=ttk.Style(parent)
  style.configure('Valet.TNotebook',background=THEME['bg'],borderwidth=0,bordercolor=THEME['bg'],lightcolor=THEME['bg'],darkcolor=THEME['bg'],tabposition='n',tabmargins=(0,0,0,round(8*self.scale)))
  tab_padding=(round(16*self.scale),round(8*self.scale))
  style.configure('Valet.TNotebook.Tab',background=THEME['bg'],foreground=THEME['muted'],bordercolor=THEME['bg'],lightcolor=THEME['bg'],darkcolor=THEME['bg'],padding=tab_padding,font=ui_font('caption'),anchor='center',width=12)
  # Clam's inherited selected padding is asymmetric (6,4,6,2), which
  # moves the active label below its neighbours even with a base padding.
  style.map('Valet.TNotebook.Tab',padding=[('selected',tab_padding),('!selected',tab_padding)],expand=[('selected',(0,0,0,0))],background=[('selected',THEME['selected']),('active',THEME['raised'])],foreground=[('selected',THEME['text'])],bordercolor=[('selected',THEME['bg'])],lightcolor=[('selected',THEME['bg'])],darkcolor=[('selected',THEME['bg'])])
  style.configure('Valet.Treeview',background=THEME['card'],fieldbackground=THEME['card'],foreground=THEME['text'],font=ui_font('caption'),rowheight=round(24*self.scale),borderwidth=0,bordercolor=THEME['bg'],lightcolor=THEME['bg'],darkcolor=THEME['bg'])
  style.configure('Valet.Treeview.Heading',background=THEME['raised'],foreground=THEME['muted'],font=ui_font('caption'),relief='flat',bordercolor=THEME['bg'],lightcolor=THEME['bg'],darkcolor=THEME['bg'])
  style.map('Valet.Treeview',background=[('selected',THEME['selected'])],foreground=[('selected',THEME['text'])])
  style.map('Valet.Treeview.Heading',background=[('active',THEME['line'])])
  self.details_notebook=ttk.Notebook(self.detail_container,style='Valet.TNotebook',height=round(290*self.scale),takefocus=True)
  self.details_notebook.pack(fill='x')
  self.detail_tabs={};self.detail_tables=[]
  for title in ('Requests','Engine','Diagnostics'):
   tab=tk.Frame(self.details_notebook,bg=THEME['bg'],padx=round(8*self.scale),pady=round(8*self.scale))
   self.details_notebook.add(tab,text=title);self.detail_tabs[title]=tab
  self.details_notebook.enable_traversal()
  self.details_notebook.select(self.detail_tabs['Engine'])
  self.details={key:tk.StringVar(value='—') for key in ('model','context','prefill','ttft','last','last_prefill','prompt_read','generated','vision','ram','commit','gpu_use','cpu','gpu_environment','reuse','expert','pcie','draft')}
  self.activity_details=tk.StringVar(value='Waiting for request telemetry')
  self.technical_body=tk.Frame(self.detail_tabs['Requests'],bg=THEME['bg']);self.technical_body.pack(fill='x',pady=(0,8))
  self._detail_pairs(self.technical_body,(('Prompt read','prompt_read'),('Output tokens','generated'),('Prefix reuse','reuse'),('Draft acceptance','draft'),('Expert cache hits','expert'),('PCIe transfer','pcie')))
  self._label(self.detail_tabs['Requests'],'Recent requests','caption',bold=True).pack(anchor='w',pady=(0,5))
  self.request_table=self._table(self.detail_tabs['Requests'],(('time','Time',95),('outcome','Outcome',180),('tokens','Tokens',95),('duration','Duration',100)),5)
  self.request_note=tk.StringVar(value='No completed requests reported')
  self._label(self.detail_tabs['Requests'],variable=self.request_note,size='caption',color=THEME['muted']).pack(anchor='w',pady=(6,0))
  engine_header=tk.Frame(self.detail_tabs['Engine'],bg=THEME['bg']);engine_header.pack(fill='x',pady=(0,6))
  self.engine_settings_note=tk.StringVar(value='Changes apply on the next model load')
  self._label(engine_header,variable=self.engine_settings_note,size='caption',color=THEME['muted']).pack(side='left')
  self.edit_engine_button=Button(engine_header,text='Edit selected profile',quiet=True,command=lambda:self.on_edit_engine())
  self.edit_engine_button.pack(side='right')
  self.engine_table=self._table(self.detail_tabs['Engine'],(('setting','Setting',210),('value','Value',270),('source','Source',145)),8)
  self.engine_table.tag_configure('group',foreground=THEME['muted'],font=ui_font('caption',True))
  self.engine_table.bind('<Configure>',lambda event:self._fit_engine_values())
  self.engine_table.bind('<Motion>',self._engine_hover)
  self.engine_table.bind('<Leave>',self._hide_engine_tip)
  self.engine_table.bind('<ButtonPress>',self._hide_engine_tip)
  self.engine_table.bind('<KeyPress>',self._hide_engine_tip)
  self.engine_table.bind('<Destroy>',self._hide_engine_tip)
  self.gpu_summary=tk.StringVar(value='GPU observation unavailable')
  self.blocker_summary=tk.StringVar(value='No confirmed resource blockers reported')
  self.comfy_summary=tk.StringVar(value='ComfyUI · Not configured')
  diagnostic=self.detail_tabs['Diagnostics']
  self._label(diagnostic,variable=self.gpu_summary,size='caption',bold=True).pack(anchor='w')
  self._label(diagnostic,variable=self.blocker_summary,size='caption',color=THEME['muted']).pack(fill='x',pady=(2,0))
  self._label(diagnostic,variable=self.comfy_summary,size='caption',color=THEME['muted']).pack(fill='x',pady=(2,7))
  resource=tk.Frame(diagnostic,bg=THEME['bg']);resource.pack(fill='x',pady=(0,7))
  self._detail_pairs(resource,(('System memory','ram'),('System commit','commit'),('GPU use','gpu_use'),('CPU use','cpu')))
  self.process_table=self._table(diagnostic,(('process','Observed GPU process',300),('pid','PID',95),('memory','GPU memory',155)),4)
  self.process_note=tk.StringVar(value='Observations only; process presence does not confirm a blocker.')
  self._label(diagnostic,variable=self.process_note,size='caption',color=THEME['muted']).pack(anchor='w',pady=(5,0))
  self.slot_rows=[]

 def _detail_pairs(self,parent,pairs):
  for index,(title,key) in enumerate(pairs):
   col=index%2;row=tk.Frame(parent,bg=THEME['bg']);row.grid(row=index//2,column=col,sticky='ew',padx=(0,round(16*self.scale)) if not col else 0,pady=round(2*self.scale))
   parent.columnconfigure(col,weight=1,uniform='details')
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   self._label(row,variable=self.details[key],size='caption').pack(side='right')

 def _table(self,parent,columns,height):
  from tkinter import ttk
  holder=tk.Frame(parent,bg=THEME['bg']);holder.pack(fill='x')
  table=ttk.Treeview(holder,columns=[key for key,_,_ in columns],show='headings',height=height,style='Valet.Treeview',selectmode='browse',takefocus=True)
  for key,title,width in columns:
   alignment='e' if key in ('tokens','duration','pid','memory') else 'center' if key=='time' else 'w'
   table.heading(key,text=title,anchor=alignment);table.column(key,width=round(width*self.scale),minwidth=round(45*self.scale),anchor=alignment,stretch=True)
  table.pack(fill='x',expand=True)
  self.detail_tables.append(table)
  # A local tag runs before widget/Treeview/window bindings. Always consume wheel
  # input, including at the table edges, so it cannot scroll the dashboard.
  scroll_tag='ValetDetailsScroll'+str(id(table))
  table.bindtags((scroll_tag,)+table.bindtags())
  remainder={'vertical':0,'horizontal':0}
  def wheel(event):
   horizontal=bool(event.state & 0x0001)
   axis='horizontal' if horizontal else 'vertical'
   if getattr(event,'num',None) in (4,5):
    steps=-1 if event.num==4 else 1
   else:
    remainder[axis]-=event.delta
    steps=math.trunc(remainder[axis]/120)
    remainder[axis]-=steps*120
   if steps:
    self._hide_engine_tip()
    (table.xview_scroll if horizontal else table.yview_scroll)(steps*3,'units')
   return 'break'
  for sequence in ('<MouseWheel>','<Shift-MouseWheel>','<Button-4>','<Button-5>'):
   table.bind_class(scroll_tag,sequence,wheel)
  def edge(event,last=False):
   children=table.get_children()
   if children:
    item=children[-1] if last else children[0]
    table.focus(item);table.selection_set(item);table.see(item)
    self._hide_engine_tip()
   return 'break'
  table.bind_class(scroll_tag,'<Home>',edge)
  table.bind_class(scroll_tag,'<End>',lambda event:edge(event,True))
  return table

 @staticmethod
 def _replace_rows(table,rows):
  # Avoid rebuilding tables every second: preserve keyboard selection and scroll position.
  rows=[tuple(str(cell) for cell in row) for row in rows]
  current=[tuple(str(cell) for cell in table.item(item,'values')) for item in table.get_children()]
  if rows==current:return
  position=table.yview()[0];selection=table.selection()
  for item in table.get_children():table.delete(item)
  for index,row in enumerate(rows):table.insert('','end',iid=str(index),values=row)
  if selection and table.exists(selection[0]):table.selection_set(selection[0])
  table.yview_moveto(position)

 def update_engine_details(self,groups):
  rows=[]
  for group in groups or []:
   if not isinstance(group,dict):continue
   rows.append((str(group.get('title') or 'Engine'),'',''))
   for row in group.get('rows') or []:
    if isinstance(row,dict):rows.append(('  '+str(row.get('label') or 'Setting'),str(row.get('value') or '—'),str(row.get('source') or 'Not reported')))
  rows=rows or [('Engine details','Waiting for backend settings','Not reported')]
  if rows!=getattr(self,'engine_rows',None):
   self._hide_engine_tip();self.engine_rows=rows
   self._replace_rows(self.engine_table,rows)
  self._fit_engine_values()
  for item in self.engine_table.get_children():
   values=self.engine_table.item(item,'values');self.engine_table.item(item,tags=('group',) if len(values)>1 and not values[1] else ())

 def _fit_engine_values(self):
  import tkinter.font as tkfont
  table=self.engine_table;font=tkfont.Font(root=table,font=ui_font('caption'))
  for item,row in zip(table.get_children(),getattr(self,'engine_rows',[])):
   values=[]
   for column,value in zip(table['columns'],row):
    value=str(value);available=max(15,table.column(column,'width')-round(20*self.scale))
    if font.measure(value)>available:
     while value and font.measure(value+'…')>available:value=value[:-1]
     value+='…'
    values.append(value)
   table.item(item,values=values)

 def _hide_engine_tip(self,event=None):
  pending=getattr(self,'engine_tip_after',None)
  if pending:
   try:self.frame.after_cancel(pending)
   except tk.TclError:pass
  self.engine_tip_after=None;self.engine_tip_key=None
  tip=getattr(self,'engine_tip',None)
  if tip:
   try:tip.destroy()
   except tk.TclError:pass
  self.engine_tip=None

 def _engine_hover(self,event):
  table=self.engine_table;item=table.identify_row(event.y);column=table.identify_column(event.x)
  key=(item,column)
  if key==getattr(self,'engine_tip_key',None):return
  self._hide_engine_tip()
  if not item or not column:return
  index=int(item);col=int(column[1:])-1;rows=getattr(self,'engine_rows',[])
  if index>=len(rows) or col<0 or col>=3:return
  raw=str(rows[index][col]);shown=str(table.item(item,'values')[col])
  if raw==shown:return
  self.engine_tip_key=key
  def show():
   self.engine_tip_after=None
   tip=tk.Toplevel(table);self.engine_tip=tip;tip.withdraw();tip.overrideredirect(True)
   tip.configure(bg=THEME['line'])
   tk.Label(tip,text=raw,bg=THEME['card'],fg=THEME['text'],font=ui_font('caption'),padx=8,pady=5,wraplength=round(480*self.scale),justify='left').pack(padx=1,pady=1)
   tip.update_idletasks();x=min(event.x_root+12,tip.winfo_screenwidth()-tip.winfo_reqwidth()-10);y=min(event.y_root+18,tip.winfo_screenheight()-tip.winfo_reqheight()-10)
   tip.geometry(f'+{max(0,x)}+{max(0,y)}');reveal_tooltip(tip,table)
  self.engine_tip_after=self.frame.after(450,show)

 def _label(self,parent,text='',size='body',bold=False,color=None,variable=None,wrap=0):
  return tk.Label(parent,text=text,textvariable=variable,bg=parent.cget('bg'),fg=color or THEME['text'],
                  font=ui_font(size,bold),anchor='w',justify='left',wraplength=wrap,bd=0)

 def pack(self,**kwargs):self.frame.pack(**kwargs)

 def toggle_details(self):
  if self.compact:return
  self.details_expanded=not self.details_expanded
  if self.details_expanded:
   self.detail_container.pack(fill='x',pady=(7,0))
   self.details_button.configure(text='Request activity & details  ▴')
  else:
   self.detail_container.pack_forget()
   self.details_button.configure(text='Request activity & details  ▾')
  self.frame.after_idle(lambda:self.on_details(self.details_expanded))
  self.frame.after_idle(self.on_layout)

 def _fit_activity_header(self):
  header=self.activity_header;width=header.winfo_width()
  title_width=int(header.tk.call('font','measure',self.activity_title_label.cget('font'),self.activity_title.get()))
  gap=round(12*self.scale);dot_width=self.status_dot.winfo_reqwidth()+round(8*self.scale)
  marks_width=self.activity_marks.winfo_reqwidth()
  stacked=title_width+dot_width+marks_width+gap>width
  self.activity_marks.grid(row=1 if stacked else 0,column=1 if stacked else 2,columnspan=2 if stacked else 1,sticky='w' if stacked else 'e',padx=0 if stacked else (gap,0),pady=(round(4*self.scale),0) if stacked else 0)
  self.activity_title_label.configure(wraplength=max(80,width-dot_width-(0 if stacked else marks_width+gap)))

 def update_activity(self,activity):
  if not activity:
   self.activity_header.pack_forget()
   if not self.compact:
    self.activity_details.set('Waiting for request telemetry')
    self._replace_rows(self.request_table,[]);self._replace_rows(self.process_table,[])
    self.gpu_summary.set('GPU observation unavailable');self.blocker_summary.set('Waiting for resource telemetry')
    self.comfy_summary.set('ComfyUI · State unavailable');self.request_note.set('Waiting for request telemetry')
   return
  title=str(activity.get('title') or 'Backend state unavailable')
  detail=str(activity.get('detail') or '')
  gpu=str(activity.get('gpu_note') or '')
  blockers=[str(item) for item in activity.get('blockers') or []]
  comfy=activity.get('comfy') or {}
  self.activity_title.set('Strata · '+title)
  # Each tooltip explains its own indicator; avoid repeating neighboring badges.
  notes=[detail] if detail and activity.get('state') not in ('ready','reading','generating') and detail.casefold()!=title.casefold() else []
  for blocker in blockers:
   if blocker and not any(blocker.casefold() in part.casefold() for part in notes):notes.append(blocker)
  self.activity_note.set('\n'.join(notes))
  count=number(activity.get('gpu_process_count'))
  self.gpu_observation.set(f'{int(count)} other GPU process'+('es' if count!=1 else '') if count is not None else 'GPU process count unavailable')
  self.gpu_mark.configure(text='▣ '+(str(int(count)) if count is not None else '—'))
  self.comfy_observation.set(str(comfy.get('detail') or comfy.get('title') or 'Status unavailable'))
  self.comfy_mark.configure(text='Comfy '+{'busy':'▶','idle':'✓','ready':'✓'}.get(comfy.get('state'),'—'),fg=THEME['success'] if comfy.get('state')=='busy' else THEME['muted'])
  if comfy.get('state') in ('busy','idle','ready'):self.comfy_mark.pack(side='left',padx=(round(12*self.scale),0))
  else:self.comfy_mark.pack_forget()
  self.status_dot.configure(fg=THEME['success'] if activity.get('state') in ('ready','reading','generating') else THEME['warning'] if activity.get('state') in ('blocked','stale','error') else THEME['muted'])
  self.activity_title_label.configure(fg=THEME['error'] if activity.get('state')=='error' else THEME['warning'] if activity.get('state') in ('unavailable','stale','blocked') else THEME['text'])
  children=[child for child in self.frame.pack_slaves() if child!=self.activity_header]
  if self.status_external:self.activity_header.pack(fill='x',expand=True)
  elif children:self.activity_header.pack(fill='x',pady=(0,8),before=children[0])
  else:self.activity_header.pack(fill='x',pady=(0,8))
  self._fit_activity_header()
  if self.compact:return
  self.gpu_summary.set(gpu or 'GPU observation unavailable')
  self.blocker_summary.set('\n'.join(blockers[:2])+ (f' · {len(blockers)-2} more in backend status' if len(blockers)>2 else '') if blockers else 'No confirmed resource blockers reported')
  self.comfy_summary.set('ComfyUI · '+str(comfy.get('title') or 'Not configured')+(' · '+str(comfy['detail']) if comfy.get('detail') else ''))
  processes=[];missing_memory=False
  for row in activity.get('gpu_processes') or []:
   if not isinstance(row,dict):continue
   name=str(row.get('name') or 'Unknown process').replace('\\','/').rsplit('/',1)[-1]
   name=''.join(c for c in name if c.isprintable())[:80] or 'Unknown process'
   pid=number(row.get('pid'));memory=number(row.get('memory_mib'));missing_memory|=memory is None
   processes.append((name,fmt(pid,digits=0),fmt(memory,' MiB',0)))
  self._replace_rows(self.process_table,processes)
  self.process_note.set('Observed processes are not confirmed blockers.'+(' Windows may omit per-process memory (—).' if missing_memory else ''))
  recent=[]
  for row in (activity.get('recent') or [])[:12]:
   if not isinstance(row,dict):continue
   stamp=number(row.get('time'))
   when=time.strftime('%H:%M:%S',time.localtime(stamp)) if stamp is not None and 0<=stamp<=32503680000 else '—'
   finish={'stop':'Completed','complete':'Completed','completed':'Completed','eos':'Completed',
           'length':'Token limit reached','cancel':'Cancelled','cancelled':'Cancelled','canceled':'Cancelled',
           'error':'Failed','failed':'Failed'}.get(row.get('finish'),'Finished')
   recent.append((when,finish,fmt(row.get('tokens'),digits=0),fmt(row.get('duration_s'),' s')))
  self._replace_rows(self.request_table,recent)
  self.request_note.set('Backend timings · prompts are not stored' if recent else 'No completed requests reported · prompts are not stored')
  self.activity_details.set('\n'.join(' · '.join(row) for row in recent))

 def mark_stale(self):
  self.activity_title.set('Status unavailable')
  self.activity_note.set('Last reading is stale · checking again')
  self.activity_title_label.configure(fg=THEME['warning'])
  self.status_dot.configure(fg=THEME['warning'])
  self.gpu_mark.configure(text='▣ —');self.comfy_mark.pack_forget()
  self.gpu_observation.set('GPU observation is stale');self.comfy_observation.set('ComfyUI observation is stale')
  self.gpu_tuning.mark_stale()
  self.latest={**self.latest,'running':None,'queued':None,'live_speed':None,'prefill_speed':None}
  self.speed.set(fmt(self.latest.get('last_speed'),' tok/s'))
  self.speed_note.set('Last completed request · reading is stale' if number(self.latest.get('last_speed')) is not None else 'Live output unavailable')
  if self.compact:return
  self.prompt_speed.set(fmt(self.latest.get('last_prefill'),' tok/s',0))
  self.throughput_source.set('Last completed request · reading is stale')
  self.prompt_note.set('Last completed request · reading is stale')
  for mark in self.source_marks.values():mark.configure(text='◷ stale',fg=THEME['muted'])
  self.requests.set('— active');self.requests_note.set('— waiting')
  self.plot_values['output'].set('—');self.plot_values['gpu'].set('—');self.plot_values['cpu'].set('—')
  self.context_summary.set('Context · reading is stale')
  self.details['model'].set('Status unavailable · stale reading')
  self.draw_agents()

 def update(self,s):
  now=s.get('sampled',time.monotonic());identity=s.get('identity')
  if identity!=self.identity:self.samples.clear();self.history.clear();self.request_history.clear();self.last_request=None;self.identity=identity
  self.latest=s
  if not self.compact:
   self.engine_settings_note.set('Saved engine changes pending · next model load' if s.get('memory_settings_pending') else 'Changes apply on the next model load')
  self.update_activity(s.get('activity'))
  if not self.samples or self.samples[-1][0]!=now:self.samples.append((now,number(s.get('live_speed'))))
  while self.samples and now-self.samples[0][0]>60:self.samples.popleft()
  h=s.get('hardware') or {}
  if self.gpu_tuning.update_values(h,s.get('power_stats') or {}):
   if self.compact:self.gpu_tuning.pack(fill='x',pady=(round(8*self.scale),0))
   else:self.gpu_tuning.pack(fill='x',pady=(round(8*self.scale),0),before=self.context_header)
  else:self.gpu_tuning.pack_forget()
  if not self.history or self.history[-1]['time']!=now:self.history.append(dict(time=now,output=number(s.get('live_speed')),gpu=number(h.get('gpu_util')),cpu=number(h.get('cpu'))))
  while self.history and now-self.history[0]['time']>60:self.history.popleft()
  used=h.get('gpu_mem_used');total=h.get('gpu_mem_total')
  self.gpu_memory.set('—' if number(used) is None or number(total) is None else f'{used/GIB:.1f} / {total/GIB:.0f} GiB')
  percent=ratio(used,total,100)
  self.gpu_meter['value']=min(100,max(0,percent or 0))
  self.gpu_meter.configure(style=('Warn' if percent is not None and percent>=90 else 'Memory')+'.Horizontal.TProgressbar')
  age=max(0,time.time()-s['last_at']) if number(s.get('last_at')) is not None else None
  age_text='no completed request' if age is None else f'{age:.0f}s ago' if age<60 else f'{age/60:.0f}m ago' if age<3600 else f'{age/3600:.1f}h ago'
  last_note='Last request'+(' · '+age_text if age is not None else '')
  speed=s.get('live_speed')
  last_speed=s.get('last_speed')
  self.speed.set(fmt(speed if number(speed) is not None else last_speed,' tok/s'))
  self.speed_note.set('Live output' if number(speed) is not None else last_note if number(last_speed) is not None else 'No completed request')
  if self.compact:return
  completed=number(s.get('last_at'))
  if completed is not None and completed!=self.last_request:
   self.request_history.append((number(s.get('last_prefill')),number(s.get('ttft_ms'))));self.last_request=completed
  for trend,index in ((self.prompt_trend,0),(self.token_trend,1)):
   trend.points=[point[index] for point in self.request_history];trend.draw()
  prompt=s.get('prefill_speed');last_prompt=s.get('last_prefill')
  self.prompt_speed.set(fmt(prompt if number(prompt) is not None else last_prompt,' tok/s',0))
  self.prompt_note.set('Live prompt processing' if number(prompt) is not None else last_note if number(last_prompt) is not None else 'No completed request')
  for key,live,last in (('speed',speed,last_speed),('prompt_speed',prompt,last_prompt)):
   is_live=number(live) is not None
   short_age=age_text.replace(' ago','') if age is not None else ''
   self.source_marks[key].configure(text='▶' if is_live else '◷ '+short_age if number(last) is not None else '—',fg=THEME['success'] if is_live else THEME['muted'])
  sources=list(dict.fromkeys((self.speed_note.get(),self.prompt_note.get())))
  self.throughput_source.set(sources[0] if len(sources)==1 else 'Output: '+sources[0]+' · Prompt: '+sources[1])
  ttft=number(s.get('ttft_ms'))
  if ttft is not None and ttft<0:ttft=None
  self.first_token.set(fmt(ttft,' ms',0))
  self.first_token_note.set(last_note if ttft is not None else '')
  visible=bool(self.first_token_group.winfo_manager())
  if (ttft is not None)!=visible:
   if ttft is not None:self.first_token_group.pack(fill='x')
   else:self.first_token_group.pack_forget()
   self.frame.after_idle(self.on_layout)
  self.ram_memory.set(self._memory(h.get('ram_used'),h.get('ram_total')))
  self.ram_meter['value']=min(100,max(0,ratio(h.get('ram_used'),h.get('ram_total'),100) or 0))
  self.ram_note.set(fmt(h.get('ram_free_gib'),' GiB available') if number(h.get('ram_free_gib')) is not None else 'Not available')
  self.requests.set(f"{fmt(s.get('running'),digits=0)} active")
  self.requests_note.set(f"{fmt(s.get('queued'),digits=0)} waiting")
  self.plot_values['output'].set(fmt(speed,' tok/s'))
  self.plot_values['gpu'].set(fmt(h.get('gpu_util'),'%',0));self.plot_values['cpu'].set(fmt(h.get('cpu'),'%',0))
  self.context_summary.set('Context · per agent' if s.get('slots') else 'Context · live occupancy unavailable')
  self.context_graph.configure(height=round(42*self.scale) if s.get('slots') else 0)
  warnings=[]
  if number(h.get('commit_free_gib')) is not None and h['commit_free_gib']<4:warnings.append('Low commit headroom may affect loading or generation')
  if number(h.get('ram_free_gib')) is not None and h['ram_free_gib']<4:warnings.append('Low available system memory')
  self.warning.set(' · '.join(warnings))
  if warnings:self.warning_label.pack(fill='x',pady=(0,10),before=self.overview)
  else:self.warning_label.pack_forget()
  self.update_engine_details(s.get('engine_details'))
  self.details['model'].set(s.get('state','—').capitalize())
  self.details['context'].set(fmt(s.get('context'),' tokens',0))
  self.details['prefill'].set(fmt(s.get('prefill_speed'),' tok/s',0))
  self.details['ttft'].set(fmt(s.get('ttft_ms'),' ms',0))
  self.details['last'].set(f"{fmt(s.get('last_speed'),' tok/s')} · {age_text}")
  self.details['last_prefill'].set(fmt(s.get('last_prefill'),' tok/s',0))
  self.details['prompt_read'].set(f"{fmt(s.get('prompt_read'),digits=0)} / {fmt(s.get('prompt_total'),digits=0)} tokens")
  self.details['generated'].set(fmt(s.get('generated'),' tokens',0))
  self.details['vision'].set('On' if s.get('vision') is True else 'Off' if s.get('vision') is False else '—')
  self.details['ram'].set(self._memory(h.get('ram_used'),h.get('ram_total')))
  self.details['commit'].set(self._memory(h.get('commit_used'),h.get('commit_total')))
  self.details['gpu_use'].set(fmt(h.get('gpu_util'),'% ',0))
  self.details['cpu'].set(fmt(h.get('cpu'),'%'))
  self.details['gpu_environment'].set(f"{fmt(h.get('gpu_temp'),' °C',0)} · {fmt(h.get('gpu_power'),' W',0)}")
  self.details['reuse'].set(fmt(s.get('reuse'),'%'))
  self.details['expert'].set(fmt(s.get('expert_hits'),'%'))
  self.details['pcie'].set(fmt(s.get('pcie_share'),'%'))
  self.details['draft'].set(fmt(s.get('draft_acceptance'),'%'))
  slots=s.get('slots') or []
  for i,(label,value) in enumerate(self.slot_rows):
   if i>=len(slots):label.grid_remove();continue
   slot=slots[i];value.set(f"Agent {i+1} · {slot.get('state','unknown')} · {fmt(slot.get('used'),digits=0)} / {fmt(slot.get('limit'),digits=0)} tokens")
   label.grid(row=9+i//2,column=i%2,sticky='w',pady=2)
  self.draw()
  self.frame.after_idle(self.on_layout)

 @staticmethod
 def _memory(used,total):
  return '—' if number(used) is None or number(total) is None else f'{used/GIB:.1f} / {total/GIB:.0f} GiB'

 def draw_agents(self):
  if self.compact:return
  c=self.agent_activity;c.delete('all');s=self.latest
  capacity=number(s.get('capacity'));active=number(s.get('running'))
  if capacity is None or active is None:
   c.create_text(0,11*self.scale,text='Activity unavailable',anchor='w',fill=THEME['muted'],font=ui_font('caption'));return
  for index in range(min(4,int(capacity))):
   x=index*22*self.scale;y=11*self.scale
   c.create_oval(x,y-4*self.scale,x+8*self.scale,y+4*self.scale,fill=THEME['success'] if index<active else THEME['line'],outline='')
  label=f'{capacity:.0f} '+('agent' if capacity==1 else 'agents')
  c.create_text(min(4,int(capacity))*22*self.scale,11*self.scale,text=label,anchor='w',fill=THEME['muted'],font=ui_font('caption'))

 def draw_context(self):
  if self.compact:return
  c=self.context_graph;c.delete('all');slots=self.latest.get('slots') or []
  if not slots:return
  count=min(4,len(slots));width=max(1,c.winfo_width());gap=20*self.scale;cell=(width-gap*(count-1))/count
  for index,slot in enumerate(slots[:4]):
   x=index*(cell+gap);used=number(slot.get('used'));limit=number(slot.get('limit'));percent=ratio(used,limit)
   c.create_rectangle(x,6*self.scale,x+cell,11*self.scale,fill=THEME['line'],outline='')
   if percent is not None:c.create_rectangle(x,6*self.scale,x+cell*min(1,max(0,percent)),11*self.scale,fill=THEME['accent'],outline='')
   tokens=lambda value:'—' if value is None else f'{value/1024:.0f}K' if value>=1024 else f'{value:.0f}'
   text=f"Agent {index+1} · {tokens(used)} / {tokens(limit)} tokens"
   c.create_text(x,24*self.scale,text=text,anchor='w',fill=THEME['muted'],font=ui_font('caption'))

 def draw(self):
  if self.compact:return
  for key,color in (('output',THEME['chart_output']),('gpu',THEME['chart_gpu']),('cpu',THEME['chart_cpu'])):
   c=self.plots[key];c.delete('all');w=max(c.winfo_width(),80);h=max(c.winfo_height(),30)
   values=[entry[key] for entry in self.history if entry[key] is not None]
   maximum=max([10]+values)*1.15 if key=='output' else 100
   left=0;right=w-3*self.scale;bottom=h-23*self.scale;top=20*self.scale
   for fraction in (0,.5,1):
    y=bottom-(bottom-top)*fraction
    c.create_line(left,y,right,y,fill=THEME['line'],dash=(2,5))
   if values or key!='output':c.create_text(left,2*self.scale,text=f"{maximum:.0f}"+(' tok/s' if key=='output' else '%'),anchor='nw',fill=THEME['muted'],font=ui_font('caption'))
   c.create_text(left,h-2*self.scale,text='−60s',anchor='sw',fill=THEME['muted'],font=ui_font('caption'))
   c.create_text(right,h-2*self.scale,text='now',anchor='se',fill=THEME['muted'],font=ui_font('caption'))
   if not values:
    c.create_text(w/2,h/2,text='No live output' if key=='output' else 'Reading unavailable',fill=THEME['muted'],font=ui_font('caption'));continue
   end=self.history[-1]['time'];segment=[]
   def paint(points):
    if len(points)>=4:
     c.create_polygon(points[0],bottom,*points,points[-2],bottom,fill=THEME['chart_'+key+'_fill'],outline='')
     c.create_line(*points,fill=color,width=max(1,1.5*self.scale))
    elif points:c.create_oval(points[0]-2,points[1]-2,points[0]+2,points[1]+2,fill=color,outline='')
   for entry in self.history:
    value=entry[key]
    if value is None:paint(segment);segment=[];continue
    x=max(left,min(right,left+(right-left)*(1-(end-entry['time'])/60)))
    y=bottom-min(maximum,max(0,value))/maximum*(bottom-top);segment.extend((x,y))
   paint(segment)
  self.draw_agents();self.draw_context()
