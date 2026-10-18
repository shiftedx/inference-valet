"""Read-only NVIDIA tuning telemetry and session averages."""
import ctypes,math

def finite(value):
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

class Utilization(ctypes.Structure):
 _fields_=[('gpu',ctypes.c_uint),('memory',ctypes.c_uint)]

class GpuTelemetry:
 """Use the installed NVML driver; never change clocks, power or driver settings."""
 def __init__(self):self.lib=None;self.handle=None;self.attempted=False
 def _initialize(self):
  self.attempted=True
  try:
   lib=ctypes.WinDLL('nvml.dll')
   if lib.nvmlInit_v2()!=0:return
   handle=ctypes.c_void_p()
   lib.nvmlDeviceGetHandleByIndex_v2.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p)]
   if lib.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(handle))!=0:
    lib.nvmlShutdown();return
   self.lib=lib;self.handle=handle
  except (OSError,AttributeError):pass
 def _read(self,name,*args,kind=ctypes.c_uint):
  try:
   value=kind();fn=getattr(self.lib,name)
   fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*len(args)+[ctypes.POINTER(kind)]
   fn.restype=ctypes.c_int
   if fn(self.handle,*args,ctypes.byref(value))==0:return value
  except (OSError,AttributeError):pass
  return None
 def __call__(self):
  if not self.attempted:self._initialize()
  if not self.lib:return {}
  result={}
  for key,name,args,divisor in (
   ('gpu_clock','nvmlDeviceGetClockInfo',(0,),1),
   ('gpu_memory_clock','nvmlDeviceGetClockInfo',(2,),1),
   ('gpu_power','nvmlDeviceGetPowerUsage',(),1000),
   ('gpu_power_limit','nvmlDeviceGetPowerManagementLimit',(),1000),
   ('gpu_temp','nvmlDeviceGetTemperature',(0,),1)):
   value=self._read(name,*args)
   if value is not None:result[key]=value.value/divisor
  utilization=self._read('nvmlDeviceGetUtilizationRates',kind=Utilization)
  if utilization is not None:result.update(gpu_util=utilization.gpu,gpu_memory_busy=utilization.memory)
  return result

class ActivePowerAverage:
 """Mean of valid board-power samples during verified Strata activity."""
 def __init__(self):self.mean=None;self.count=0;self.last_sample=float('-inf')
 def sample(self,sampled,power,active):
  if finite(sampled) and sampled>self.last_sample:
   self.last_sample=sampled
   if active and finite(power) and power>=0:
    self.count+=1
    self.mean=power if self.mean is None else self.mean+(power-self.mean)/self.count
  return dict(average_watts=self.mean,samples=self.count)
