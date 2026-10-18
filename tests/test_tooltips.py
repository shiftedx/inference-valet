import pathlib,sys,tkinter as tk,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_widgets import Tooltip,Button,THEME
class TooltipTests(unittest.TestCase):
 def setUp(self):
  self.root=tk.Tk();self.root.configure(bg=THEME['bg'])
 def tearDown(self):self.root.destroy()
 def test_dynamic_help_preserves_focus_and_button_activation(self):
  clicked=[];button=Button(self.root,text='Edit',command=lambda:clicked.append(True));button.pack()
  detail=tk.StringVar(self.root,value='Selected profile details');tip=Tooltip(button,detail)
  self.root.update();button.focus_force();self.root.update();focus=self.root.focus_get()
  tip.show();self.root.update()
  self.assertEqual(self.root.focus_get(),focus)
  self.assertEqual(tip.tip.winfo_children()[0].cget('text'),detail.get())
  button.event_generate('<Return>');self.root.update();self.assertEqual(clicked,[True])
  detail.set('Changed profile');tip.show();self.assertEqual(tip.tip.winfo_children()[0].cget('text'),'Changed profile')
  button.event_generate('<Leave>');self.root.update();self.assertIsNone(tip.tip)
 def test_cancelled_hover_and_destroy_remove_pending_help(self):
  button=Button(self.root,text='Edit',command=lambda:None);button.pack();self.root.update()
  tip=Tooltip(button,'Help');tip.schedule();self.assertIsNotNone(tip.pending)
  button.event_generate('<Leave>');self.root.update();self.assertIsNone(tip.pending)
  tip.show();self.assertIsNotNone(tip.tip)
  button.destroy();self.root.update();self.assertIsNone(tip.tip);self.assertIsNone(tip.pending)

 def test_status_and_control_help_stay_above_topmost_owner_without_taking_focus(self):
  import ctypes
  from ctypes import wintypes
  from ai_telemetry import StatusMark
  self.root.attributes('-topmost',True)
  button=Button(self.root,text='Edit',command=lambda:None);button.pack()
  mark=StatusMark(self.root,tk.StringVar(self.root,value='15 other GPU compute processes'),text='15');mark.pack()
  self.root.update();button.focus_force();self.root.update()
  focus=self.root.focus_get()
  user=ctypes.windll.user32
  user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
  user.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT];user.GetWindow.restype=wintypes.HWND
  owner=user.GetParent(self.root.winfo_id())
  control_tip=Tooltip(button,'Edit this profile')
  for show,hide,get_tip in ((control_tip.show,control_tip.hide,lambda:control_tip.tip),(mark.show_tip,mark.hide_tip,lambda:mark.tip)):
   show();self.root.update();tip=get_tip()
   self.assertEqual(self.root.focus_get(),focus)
   self.assertTrue(tip.attributes('-topmost'))
   handle=user.GetParent(tip.winfo_id())
   self.assertEqual(user.GetWindow(handle,4),owner)
   above=user.GetWindow(owner,3);found=False
   for _ in range(2000):
    if not above:break
    if above==handle:found=True;break
    above=user.GetWindow(above,3)
   self.assertTrue(found,'Tooltip must be above its owning topmost window')
   hide()

 def test_owner_move_hide_and_interaction_dismiss_help(self):
  button=Button(self.root,text='Edit',command=lambda:None);button.pack();self.root.update()
  tip=Tooltip(button,'Help')
  for action in (lambda:self.root.geometry('+200+200'),lambda:self.root.event_generate('<FocusOut>'),lambda:self.root.withdraw()):
   tip.show();self.root.update();self.assertIsNotNone(tip.tip)
   action();self.root.update();self.assertIsNone(tip.tip);self.assertIsNone(tip.pending)
  self.root.deiconify();self.root.update();tip.schedule();self.root.withdraw();self.root.update()
  self.assertIsNone(tip.pending)

 def test_profile_menu_grab_suppresses_delayed_help(self):
  from ai_widgets import ProfileSelect
  picker=ProfileSelect(self.root,values=['First','Second'],state='readonly');picker.pack();self.root.update()
  tip=Tooltip(picker,'Selected profile')
  self.root.tk.call('ttk::combobox::Post',str(picker));self.root.update()
  try:
   tip.show();self.root.update();self.assertIsNone(tip.tip)
  finally:self.root.tk.call('ttk::combobox::Unpost',str(picker))
  self.root.update();tip.show();self.assertIsNotNone(tip.tip)
  picker.destroy();self.root.update();self.assertEqual(tip.owner_bindings,[])

 def test_descendant_and_unchanged_owner_configuration_keep_help_visible(self):
  button=Button(self.root,text='Edit',command=lambda:None);button.pack();self.root.update()
  tip=Tooltip(button,'Help');tip.show();self.root.update()
  self.assertIsNotNone(tip.tip)
  button.event_generate('<Configure>');self.root.event_generate('<Configure>');self.root.update()
  self.assertIsNotNone(tip.tip)
  self.root.geometry('+240+240');self.root.update();self.assertIsNone(tip.tip)

 def test_modal_owner_allows_help_but_blocks_background_help(self):
  button=Button(self.root,text='Edit',command=lambda:None);button.pack()
  dialog=tk.Toplevel(self.root);dialog.configure(bg=THEME['bg'])
  field=Button(dialog,text='Save',command=lambda:None);field.pack();self.root.update()
  dialog.grab_set();self.root.update()
  background=Tooltip(button,'Background help');foreground=Tooltip(field,'Dialog help')
  try:
   background.show();self.assertIsNone(background.tip)
   foreground.show();self.assertIsNotNone(foreground.tip)
  finally:dialog.grab_release();dialog.destroy()

 def test_help_stays_within_owner_monitor_work_area(self):
  button=Button(self.root,text='Edit',command=lambda:None);button.pack();self.root.update()
  tip=Tooltip(button,'Help on this monitor')
  # Simulate a display to the left of the primary; absolute negative origins
  # require Tk's +negative geometry form, not its right-edge offset syntax.
  with patch('ai_widgets.monitor_work_area',return_value=(-1200,0,-200,900)):
   tip.show();self.root.update()
   self.assertGreaterEqual(tip.tip.winfo_rootx(),-1200)
   self.assertLessEqual(tip.tip.winfo_rootx()+tip.tip.winfo_width(),-200)
