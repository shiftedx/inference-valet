"""Read-only performance sampling and the native AI launcher dashboard."""
import ctypes,math,subprocess,time
from collections import deque
import psutil
from ai_config import NVIDIA_SMI

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

class Collector:
 def __init__(self,fetch,servers):self.fetch=fetch;self.servers=servers
 def collect(self):
  sampled=time.monotonic();hardware=host_hardware();out={'state':'no model loaded','slots':[],'live_speed':None,'hardware':hardware};identity=None
  try:
   processes=list(self.servers());identity=tuple(sorted((p.pid,p.create_time()) for p,k in processes))
   if any(k=='strata-server' for p,k in processes):
    out=normalize_strata(self.fetch('/metrics'))
    status=self.fetch('/v1/status');out['context']=status.get('context',{}).get('native',out.get('context'))
    last=status.get('last_timings') or {}
    if last:
     out['last_prefill']=last.get('prompt_per_second',out.get('last_prefill'));out['last_speed']=last.get('predicted_per_second',out.get('last_speed'))
    out['vision']=status.get('vision',{}).get('enabled');out['capacity']=status.get('concurrency',{}).get('serving',1)
    if not status.get('loaded'):out['state']='unloaded · reloads on next request';out['live_speed']=None
   elif processes:out['state']='loading'
  except (OSError,ValueError,KeyError,IndexError,psutil.Error):
   out={'state':'telemetry unavailable · retrying','slots':[],'live_speed':None,'hardware':{}}
  # Driver telemetry also works when the model is unloaded; never spawn a visible console.
  if not out.get('hardware',{}).get('gpu_mem_total'):
   try:
    run=subprocess.run([NVIDIA_SMI,'--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,creationflags=subprocess.CREATE_NO_WINDOW)
    vals=[float(x.strip()) for x in run.stdout.splitlines()[0].split(',')]
    hardware.update(gpu_util=vals[0],gpu_mem_used=vals[1]*2**20,gpu_mem_total=vals[2]*2**20,gpu_temp=vals[3],gpu_power=vals[4])
   except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):pass
  out['hardware']={**out.get('hardware',{}),**hardware};out.update(sampled=sampled,identity=identity)
  return out

from ai_widgets import THEME,Button,ui_font

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
  self.delete('all');color=THEME['amber'] if self.meter_style.startswith('Warn') else THEME['violet'] if self.meter_style.startswith('Memory') else THEME['teal']
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
  self.hide_tip();self.tip=tk.Toplevel(self);self.tip.overrideredirect(True)
  self.tip.geometry(f'+{event.x_root+12}+{event.y_root+12}')
  tk.Label(self.tip,text='Recent completed requests · up to 12\nTrend uses its observed range',bg=THEME['card'],fg=THEME['muted'],font=ui_font('caption'),padx=8,pady=4,justify='left').pack()
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

class PerformancePanel:
 def __init__(self, parent, compact=False):
  from tkinter import ttk
  self.compact=compact;self.samples=deque(maxlen=120);self.history=deque(maxlen=120);self.identity=None;self.latest={};self.on_layout=lambda:None;self.on_details=lambda expanded:None;self.request_history=deque(maxlen=12);self.last_request=None
  self.scale=float(parent.tk.call('tk','scaling'))/(96/72)
  self.frame=tk.Frame(parent,bg=THEME['bg'])
  self.warning=tk.StringVar(value='')
  self.gpu_memory=tk.StringVar(value='—')
  self.speed=tk.StringVar(value='—');self.speed_note=tk.StringVar(value='No completed request')
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
   self.technical_body=None;self.details_expanded=False
   return
  self.warning_label=self._label(self.frame,variable=self.warning,size='body',color=THEME['amber'],wrap=690)
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
  for title,key,var in (('Output','speed',self.speed),('Prompt','prompt_speed',self.prompt_speed)):
   row=tk.Frame(throughput,bg=THEME['bg']);row.pack(fill='x',pady=(0,5))
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   label=self._label(row,variable=var,size='metric',bold=True);label.pack(side='right');self.metric_widgets[key]=label
   if key=='prompt_speed':
    self.prompt_trend=RequestTrend(row,self.scale,THEME['teal']);self.prompt_trend.pack(side='left',fill='x',expand=True,padx=6)
  self.throughput_source=tk.StringVar(value='No completed request')
  source_label=self._label(throughput,variable=self.throughput_source,size='caption',color=THEME['muted']);source_label.pack(anchor='w')
  throughput.bind('<Configure>',lambda event:source_label.configure(wraplength=event.width))
  for title,key,var in (('GPU','gpu_memory',self.gpu_memory),('RAM','ram_memory',self.ram_memory)):
   group=tk.Frame(memory,bg=THEME['bg']);group.pack(fill='x',pady=(0,8))
   row=tk.Frame(group,bg=THEME['bg']);row.pack(fill='x')
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   label=self._label(row,variable=var,size='metric',bold=True);label.pack(side='right');self.metric_widgets[key]=label
   meter=Meter(group,style='Memory.Horizontal.TProgressbar',segmented=True,height=7);meter.pack(fill='x',pady=(5,0))
   if key=='gpu_memory':self.gpu_card=group;self.gpu_meter=meter
   else:self.ram_meter=meter
  request_row=tk.Frame(requests,bg=THEME['bg']);request_row.pack(fill='x')
  label=self._label(request_row,variable=self.requests,size='metric',bold=True);label.pack(side='left');self.metric_widgets['requests']=label
  self._label(request_row,variable=self.requests_note,size='caption',color=THEME['muted']).pack(side='right')
  self.agent_activity=tk.Canvas(requests,height=round(22*self.scale),bg=THEME['bg'],highlightthickness=0)
  self.agent_activity.pack(fill='x',pady=(4,2));self.agent_activity.bind('<Configure>',lambda event:self.draw_agents())
  token_row=tk.Frame(requests,bg=THEME['bg']);token_row.pack(fill='x')
  self._label(token_row,'First token','caption',color=THEME['muted']).pack(side='left')
  label=self._label(token_row,variable=self.first_token,size='metric',bold=True);label.pack(side='right');self.metric_widgets['first_token']=label
  self.token_trend=RequestTrend(token_row,self.scale,THEME['violet']);self.token_trend.pack(side='left',fill='x',expand=True,padx=6)
  self._label(requests,variable=self.first_token_note,size='caption',color=THEME['muted']).pack(anchor='w',pady=(3,0))
  self.charts=tk.Frame(self.frame,bg=THEME['bg']);self.charts.pack(fill='both',expand=True,pady=(12,0))
  self.plots={};self.plot_values={}
  for col,key,title,color in ((0,'output','Output',THEME['teal']),(1,'gpu','GPU use',THEME['amber']),(2,'cpu','CPU use',THEME['violet'])):
   group=tk.Frame(self.charts,bg=THEME['bg']);group.grid(row=0,column=col*2,sticky='nsew')
   self.charts.columnconfigure(col*2,weight=1,uniform='charts')
   if col<2:self.charts.columnconfigure(col*2+1,minsize=round(20*self.scale))
   row=tk.Frame(group,bg=THEME['bg']);row.pack(fill='x')
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   value=tk.StringVar(value='—');self.plot_values[key]=value;self._label(row,variable=value,size='caption',bold=True,color=color).pack(side='right')
   plot=tk.Canvas(group,height=round(60*self.scale),bg=THEME['bg'],highlightthickness=0)
   plot.pack(fill='both',expand=True);plot.bind('<Configure>',lambda event:self.draw());self.plots[key]=plot
  self.charts.rowconfigure(0,weight=1);self.graph=self.plots['output']
  self.context_summary=tk.StringVar(value='Context · waiting for model telemetry')
  context_header=tk.Frame(self.frame,bg=THEME['bg']);context_header.pack(fill='x',pady=(9,0))
  self._label(context_header,variable=self.context_summary,size='caption',color=THEME['muted']).pack(side='left')
  self.environment=tk.StringVar(value='');self._label(context_header,variable=self.environment,size='caption',color=THEME['muted']).pack(side='right')
  self.context_graph=tk.Canvas(self.frame,height=round(42*self.scale),bg=THEME['bg'],highlightthickness=0)
  self.context_graph.pack(fill='x');self.context_graph.bind('<Configure>',lambda event:self.draw_context())
  self.details_expanded=False
  self.details_button=Button(self.frame,text='Technical details  ▾',command=self.toggle_details,quiet=True)
  self.details_button.pack(anchor='w',pady=(4,0))
  self.detail_container=tk.Frame(self.frame,bg=THEME['bg'])
  self.technical_body=tk.Frame(self.detail_container,bg=THEME['bg']);self.technical_body.pack(fill='x')
  for col in range(2):self.technical_body.columnconfigure(col,weight=1,uniform='details')
  index=0
  self.details={}
  for title,key in (
   ('Model activity','model'),('Context per agent','context'),('Prompt speed','prefill'),
   ('Time to first token','ttft'),('Last request','last'),('Last prompt speed','last_prefill'),
   ('Prompt read','prompt_read'),('Output tokens','generated'),('Vision','vision'),('System memory','ram'),
   ('System commit','commit'),('GPU use','gpu_use'),('CPU use','cpu'),
   ('GPU temperature / power','gpu_environment'),('Prefix reuse','reuse'),
   ('Expert cache','expert'),('PCIe transfer','pcie'),('Draft acceptance','draft')):
   row=tk.Frame(self.technical_body,bg=THEME['bg']);row.grid(row=index%9,column=index//9,sticky='ew',padx=(0,round(8*self.scale)) if index<9 else (round(8*self.scale),0),pady=3);index+=1
   self._label(row,title,'caption',color=THEME['muted']).pack(side='left')
   value=tk.StringVar(value='—');self.details[key]=value
   reading=self._label(row,variable=value,size='caption',color=THEME['text'],wrap=180);reading.pack(side='right')
   row.bind('<Configure>',lambda event,reading=reading:reading.configure(wraplength=max(80,event.width//2)))
  self.slot_rows=[]
  for i in range(4):
   value=tk.StringVar(value='')
   label=self._label(self.technical_body,variable=value,size='caption',color=THEME['muted'])
   self.slot_rows.append((label,value))

 def _label(self,parent,text='',size='body',bold=False,color=None,variable=None,wrap=0):
  return tk.Label(parent,text=text,textvariable=variable,bg=parent.cget('bg'),fg=color or THEME['text'],
                  font=ui_font(size,bold),anchor='w',justify='left',wraplength=wrap,bd=0)

 def pack(self,**kwargs):self.frame.pack(**kwargs)

 def toggle_details(self):
  if self.compact:return
  self.details_expanded=not self.details_expanded
  if self.details_expanded:
   self.detail_container.pack(fill='x',pady=(7,0))
   self.details_button.configure(text='Technical details  ▴')
  else:
   self.detail_container.pack_forget()
   self.details_button.configure(text='Technical details  ▾')
  self.frame.after_idle(lambda:self.on_details(self.details_expanded))
  self.frame.after_idle(self.on_layout)

 def update(self,s):
  now=s.get('sampled',time.monotonic());identity=s.get('identity')
  if identity!=self.identity:self.samples.clear();self.history.clear();self.request_history.clear();self.last_request=None;self.identity=identity
  self.latest=s
  if not self.samples or self.samples[-1][0]!=now:self.samples.append((now,number(s.get('live_speed'))))
  while self.samples and now-self.samples[0][0]>60:self.samples.popleft()
  h=s.get('hardware') or {}
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
  sources=list(dict.fromkeys((self.speed_note.get(),self.prompt_note.get())))
  self.throughput_source.set(sources[0] if len(sources)==1 else 'Output: '+sources[0]+' · Prompt: '+sources[1])
  self.first_token.set(fmt(s.get('ttft_ms'),' ms',0))
  self.first_token_note.set(last_note if number(s.get('ttft_ms')) is not None else 'Not reported by backend' if age is not None or number(last_speed) is not None else 'No completed request')
  self.ram_memory.set(self._memory(h.get('ram_used'),h.get('ram_total')))
  self.ram_meter['value']=min(100,max(0,ratio(h.get('ram_used'),h.get('ram_total'),100) or 0))
  self.ram_note.set(fmt(h.get('ram_free_gib'),' GiB available') if number(h.get('ram_free_gib')) is not None else 'Not available')
  self.requests.set(f"{fmt(s.get('running'),digits=0)} active")
  self.requests_note.set(f"{fmt(s.get('queued'),digits=0)} waiting")
  self.plot_values['output'].set(fmt(speed,' tok/s'))
  self.plot_values['gpu'].set(fmt(h.get('gpu_util'),'%',0));self.plot_values['cpu'].set(fmt(h.get('cpu'),'%',0))
  self.environment.set(' · '.join(value for value in (fmt(h.get('gpu_temp'),' °C',0) if number(h.get('gpu_temp')) is not None else '',fmt(h.get('gpu_power'),' W',0) if number(h.get('gpu_power')) is not None else '') if value))
  if self.environment.get():self.environment.set('GPU · '+self.environment.get())
  self.context_summary.set('Context · per agent' if s.get('slots') else 'Context · live occupancy unavailable')
  self.context_graph.configure(height=round(42*self.scale) if s.get('slots') else 0)
  warnings=[]
  if number(h.get('commit_free_gib')) is not None and h['commit_free_gib']<4:warnings.append('Low commit headroom may affect loading or generation')
  if number(h.get('ram_free_gib')) is not None and h['ram_free_gib']<4:warnings.append('Low available system memory')
  self.warning.set(' · '.join(warnings))
  if warnings:self.warning_label.pack(fill='x',pady=(0,10),before=self.overview)
  else:self.warning_label.pack_forget()
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
   c.create_oval(x,y-4*self.scale,x+8*self.scale,y+4*self.scale,fill=THEME['teal'] if index<active else THEME['line'],outline='')
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
   if percent is not None:c.create_rectangle(x,6*self.scale,x+cell*min(1,max(0,percent)),11*self.scale,fill=THEME['teal'],outline='')
   tokens=lambda value:'—' if value is None else f'{value/1024:.0f}K' if value>=1024 else f'{value:.0f}'
   text=f"Agent {index+1} · {tokens(used)} / {tokens(limit)} tokens"
   c.create_text(x,24*self.scale,text=text,anchor='w',fill=THEME['muted'],font=ui_font('caption'))

 def draw(self):
  if self.compact:return
  for key,color in (('output',THEME['teal']),('gpu',THEME['amber']),('cpu',THEME['violet'])):
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
     c.create_polygon(points[0],bottom,*points,points[-2],bottom,fill='#2d3430' if key=='output' else '#34312b' if key=='gpu' else '#2d3034',outline='')
     c.create_line(*points,fill=color,width=max(1,1.5*self.scale))
    elif points:c.create_oval(points[0]-2,points[1]-2,points[0]+2,points[1]+2,fill=color,outline='')
   for entry in self.history:
    value=entry[key]
    if value is None:paint(segment);segment=[];continue
    x=max(left,min(right,left+(right-left)*(1-(end-entry['time'])/60)))
    y=bottom-min(maximum,max(0,value))/maximum*(bottom-top);segment.extend((x,y))
   paint(segment)
  self.draw_agents();self.draw_context()
