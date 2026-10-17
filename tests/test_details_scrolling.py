import importlib.util
import pathlib
import sys
import tkinter as tk
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_telemetry import PerformancePanel


class DetailsScrollingTests(unittest.TestCase):
 def setUp(self):
  self.root=tk.Tk()
  # Keep the standalone table mapped on hosted desktops with a short work area.
  self.root.maxsize(10000,10000);self.root.geometry('1000x1050')
  self.panel=PerformancePanel(self.root);self.panel.pack(fill='both',expand=True)
  self.groups=[{'title':'Engine settings','rows':[{'label':f'Setting {i}','value':'A very long value '+('setting '*30),'source':'Reported'} for i in range(70)]}]
  self.panel.update_engine_details(self.groups)
  self.panel.toggle_details();self.root.update()

 def tearDown(self):self.root.destroy()

 def wheel(self,table,delta):
  table.event_generate('<MouseWheel>',delta=delta);self.root.update()

 def test_tables_scroll_directly_without_scrollbar_widgets(self):
  self.assertEqual(len(self.panel.detail_tables),3)
  for table in self.panel.detail_tables:
   self.assertFalse(any('Scrollbar' in child.winfo_class() for child in table.master.winfo_children()))
  table=self.panel.engine_table
  self.wheel(table,-120)
  self.assertGreater(table.yview()[0],0)
  self.wheel(table,120)
  self.assertEqual(table.yview()[0],0)

 def test_high_resolution_wheel_accumulates_and_consumes_at_edges(self):
  table=self.panel.engine_table;bubbled=[]
  table.bind('<MouseWheel>',lambda event:bubbled.append(event.delta),add='+')
  for _ in range(3):self.wheel(table,-30)
  self.assertEqual(table.yview()[0],0)
  self.wheel(table,-30)
  self.assertGreater(table.yview()[0],0)
  table.yview_moveto(0);self.wheel(table,120)
  table.yview_moveto(1);self.wheel(table,-120)
  self.assertEqual(bubbled,[])

 def test_tabs_keep_independent_positions_and_refresh_preserves_engine_position(self):
  table=self.panel.engine_table;self.wheel(table,-120)
  position=table.yview();table.selection_set('12')
  self.panel.update_engine_details(self.groups);self.root.update()
  self.assertEqual(table.yview(),position)
  self.assertEqual(table.selection(),('12',))
  for title,other in [('Requests',self.panel.request_table),('Diagnostics',self.panel.process_table)]:
   self.panel.details_notebook.select(self.panel.detail_tabs[title]);self.root.update()
   for i in range(50):other.insert('','end',values=(str(i),'Example','—','—')[:len(other['columns'])])
   self.wheel(other,-120)
   self.assertGreater(other.yview()[0],0)
  self.panel.details_notebook.select(self.panel.detail_tabs['Engine']);self.root.update()
  self.assertEqual(table.yview(),position)

 def test_keyboard_paging_still_works(self):
  table=self.panel.engine_table;table.focus_force();table.selection_set('0');table.focus('0');self.root.update()
  table.event_generate('<Next>');self.root.update()
  self.assertGreater(table.yview()[0],0)
  table.event_generate('<Home>');self.root.update()
  self.assertEqual(table.yview()[0],0)
  table.event_generate('<End>');self.root.update()
  self.assertGreater(table.yview()[0],.5)

 def test_launcher_canvas_stays_still_when_table_scrolls(self):
  spec=importlib.util.spec_from_file_location('scrolling_launcher',pathlib.Path(__file__).resolve().parents[1]/'ai-launcher.py')
  launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
  app=launcher.LauncherUI(enable_tray=False,observe=False)
  try:
   app.performance.update_engine_details(self.groups);app.performance.toggle_details();app.window.update()
   table=app.performance.engine_table
   canvases=[]
   def visit(widget):
    if isinstance(widget,tk.Canvas):canvases.append(widget)
    for child in widget.winfo_children():visit(child)
   visit(app.window)
   positions={str(canvas):canvas.yview() for canvas in canvases}
   table.event_generate('<MouseWheel>',delta=-120);app.window.update()
   self.assertGreater(table.yview()[0],0)
   self.assertEqual({str(canvas):canvas.yview() for canvas in canvases},positions)
  finally:app.quit()


if __name__=='__main__':unittest.main()
