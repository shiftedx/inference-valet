import importlib.util
import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_telemetry import PerformancePanel

class DetailsLayoutTests(unittest.TestCase):
 def test_engine_default_and_sources_preserved(self):
  root=tk.Tk();root.geometry('900x950')
  try:
   panel=PerformancePanel(root);panel.pack(fill='both',expand=True)
   rows=[{'label':'GPU expert slots','value':'13,501 slots','source':'Reported'}, {'label':'PLE / engram placement','value':'SSD / direct file reads','source':'Startup log'}, {'label':'Speculation','value':'DFlash','source':'Active configuration'}]
   panel.update({'engine_details':[{'title':'Model memory','rows':rows}]})
   panel.toggle_details();root.update()
   self.assertEqual(panel.details_notebook.tab(panel.details_notebook.select(),'text'),'Engine')
   values=[panel.engine_table.item(item,'values') for item in panel.engine_table.get_children()]
   self.assertEqual(values,[('Model memory','','')]+[('  '+r['label'],r['value'],r['source']) for r in rows])
   self.assertTrue(panel.engine_table.winfo_ismapped())
   self.assertFalse(panel.process_table.winfo_ismapped())
   self.assertFalse(hasattr(panel,'activity_details_label'))
   self.assertIn('group',panel.engine_table.item('0','tags'))
  finally:root.destroy()

 def test_long_engine_values_are_elided_and_full_evidence_retained(self):
  root=tk.Tk();root.geometry('900x950')
  try:
   panel=PerformancePanel(root);panel.pack(fill='both',expand=True)
   raw='Qwen-model-'+('very-long-filename-'*8)+'.gguf'
   panel.update_engine_details([{'title':'Memory','rows':[{'label':'Engram table','value':raw,'source':'Startup log'}]}])
   panel.toggle_details();root.update()
   self.assertEqual(panel.engine_rows[1][1],raw)
   shown=panel.engine_table.item('1','values')
   self.assertTrue(shown[1].endswith('…'))
   self.assertLess(len(shown[1]),len(raw))
   self.assertEqual(shown[2],'Startup log')
   from tkinter import ttk
   style=ttk.Style(root)
   for name in ('Valet.TNotebook','Valet.TNotebook.Tab','Valet.Treeview','Valet.Treeview.Heading'):
    self.assertNotEqual(style.lookup(name,'bordercolor'),'white')
  finally:root.destroy()

 def test_refresh_preserves_table_scroll_and_selection(self):
  root=tk.Tk()
  try:
   panel=PerformancePanel(root)
   groups=[{'title':'Engine settings','rows':[{'label':str(i),'value':'Measured value','source':'Reported'} for i in range(30)]}]
   panel.update_engine_details(groups)
   panel.engine_table.selection_set('15');panel.engine_table.yview_moveto(.5)
   old_children=panel.engine_table.get_children();position=panel.engine_table.yview()
   panel.update_engine_details(groups)
   self.assertEqual(panel.engine_table.get_children(),old_children)
   self.assertEqual(panel.engine_table.selection(),('15',))
   self.assertEqual(panel.engine_table.yview(),position)
  finally:root.destroy()

 def test_tab_workspace_is_bounded_at_all_scales(self):
  spec=importlib.util.spec_from_file_location('details_launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py')
  launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
  real_tk=tk.Tk
  for scale in (1,1.5,2):
   with self.subTest(scale=scale):
    def scaled_root():
     root=real_tk();root.tk.call('tk','scaling',(96/72)*scale);return root
    with patch.object(tk,'Tk',side_effect=scaled_root):app=launcher.LauncherUI(enable_tray=False,observe=False)
    try:
     panel=app.performance
     panel.update({'engine_details':[{'title':'Settings','rows':[{'label':'Setting '+str(i),'value':'Value '+str(i),'source':'Reported'} for i in range(45)]}], 'activity':{'title':'Ready','state':'ready','gpu_processes':[{'name':'process.exe','pid':i} for i in range(25)]}})
     panel.toggle_details();app.window.update()
     notebook_height=panel.details_notebook.winfo_height()
     self.assertLessEqual(notebook_height,round(345*scale))
     for title in ('Requests','Engine','Diagnostics'):
      panel.details_notebook.select(panel.detail_tabs[title]);app.window.update()
      self.assertEqual(panel.details_notebook.winfo_height(),notebook_height)
      table={'Requests':panel.request_table,'Engine':panel.engine_table,'Diagnostics':panel.process_table}[title]
      self.assertTrue(table.winfo_ismapped())
      self.assertLessEqual(table.winfo_rooty()+table.winfo_height(),panel.detail_tabs[title].winfo_rooty()+panel.detail_tabs[title].winfo_height())
      for child in panel.detail_tabs[title].winfo_children():
       if child.winfo_ismapped():self.assertLessEqual(child.winfo_rooty()+child.winfo_height(),panel.detail_tabs[title].winfo_rooty()+panel.detail_tabs[title].winfo_height())
      self.assertEqual(len(panel.metric_widgets),6)
    finally:app.quit()

if __name__=='__main__':unittest.main()
