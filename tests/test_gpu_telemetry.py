import pathlib,sys,ctypes,unittest,tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_gpu import GpuTelemetry,ActivePowerAverage
from ai_telemetry import PerformancePanel

class GpuTelemetryTests(unittest.TestCase):
 def test_nvml_units_and_memory_activity_remain_distinct(self):
  probe=GpuTelemetry();probe.attempted=True;probe.lib=object()
  def read(name,*args,**kwargs):
   if name=='nvmlDeviceGetClockInfo':return ctypes.c_uint(17001 if args[0]==2 else 2805)
   values={'nvmlDeviceGetPowerUsage':450125,'nvmlDeviceGetPowerManagementLimit':600000,'nvmlDeviceGetTemperature':65}
   return SimpleNamespace(gpu=95,memory=82) if name=='nvmlDeviceGetUtilizationRates' else ctypes.c_uint(values[name])
  probe._read=read;result=probe()
  self.assertEqual(result['gpu_clock'],2805);self.assertEqual(result['gpu_memory_clock'],17001)
  self.assertEqual(result['gpu_power'],450.125);self.assertEqual(result['gpu_power_limit'],600)
  self.assertEqual(result['gpu_memory_busy'],82);self.assertNotIn('gpu_bandwidth',result)
 def test_unsupported_fields_do_not_become_zero(self):
  probe=GpuTelemetry();probe.attempted=True;probe.lib=object();probe._read=lambda *args,**kwargs:None
  self.assertEqual(probe(),{})
 def test_missing_driver_is_only_initialized_once(self):
  with patch('ai_gpu.ctypes.WinDLL',side_effect=OSError) as load:
   probe=GpuTelemetry();self.assertEqual(probe(),{});self.assertEqual(probe(),{});load.assert_called_once()
 def test_average_excludes_idle_invalid_and_duplicate_samples(self):
  avg=ActivePowerAverage()
  self.assertIsNone(avg.sample(1,60,False)['average_watts'])
  self.assertEqual(avg.sample(2,300,True)['average_watts'],300)
  avg.sample(2,900,True);avg.sample(3,float('nan'),True);avg.sample(4,-20,True);avg.sample(5,True,True)
  avg.sample(6,60,False);result=avg.sample(7,500,True)
  self.assertEqual(result,dict(average_watts=400,samples=2))
  self.assertEqual(avg.sample(6,900,True),result)

class GpuTuningLayoutTests(unittest.TestCase):
 def test_main_and_tray_readouts_fit_at_common_scales_and_stale_values_clear(self):
  hardware=dict(gpu_clock=2805,gpu_memory_clock=17001,gpu_memory_busy=82,gpu_power=450,gpu_power_limit=600,gpu_temp=65)
  for factor in (1,1.5,2):
   for compact in (False,True):
    with self.subTest(scale=factor,compact=compact):
     root=tk.Tk();root.tk.call('tk','scaling',(96/72)*factor);root.maxsize(10000,10000)
     root.geometry(f'{round((344 if compact else 724)*factor)}x{round(650*factor)}')
     try:
      panel=PerformancePanel(root,compact=compact);panel.pack(fill='both',expand=True)
      panel.update({'hardware':hardware,'power_stats':{'average_watts':410,'samples':12}});root.update()
      tuning=panel.gpu_tuning
      self.assertTrue(tuning.winfo_ismapped());self.assertEqual(len(tuning.visible),6)
      for key in tuning.visible:
       group=tuning.groups[key]
       self.assertGreaterEqual(group.winfo_width(),group.winfo_reqwidth())
       self.assertLessEqual(group.winfo_x()+group.winfo_width(),tuning.winfo_width())
      for i,left_key in enumerate(tuning.visible):
       left=tuning.groups[left_key]
       for right_key in tuning.visible[i+1:]:
        right=tuning.groups[right_key]
        if left.winfo_y()==right.winfo_y():self.assertLessEqual(left.winfo_x()+left.winfo_width(),right.winfo_x())
      self.assertEqual(tuning.values['gpu_temp'].get(),'65 °C')
      root.geometry(f'{round((344 if compact else 564)*factor)}x{round(650*factor)}');root.update()
      for key in tuning.visible:
       self.assertGreaterEqual(tuning.groups[key].winfo_width(),tuning.groups[key].winfo_reqwidth())
      panel.mark_stale();root.update()
      self.assertEqual(tuning.values['gpu_clock'].get(),'—')
      self.assertEqual(tuning.values['average_watts'].get(),'410 W')
      panel.update({'hardware':{}});root.update();self.assertFalse(tuning.winfo_ismapped())
     finally:root.destroy()
