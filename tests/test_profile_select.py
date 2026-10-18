import pathlib
import sys
import tkinter as tk
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_widgets import ProfileSelect,THEME


class ProfileSelectTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.configure(bg=THEME['bg'])
        self.picker=ProfileSelect(self.root,values=('First profile','Second profile'),state='readonly')
        self.picker.pack();self.picker.current(0)
        self.blank=tk.Label(self.root,text='Other area',bg=THEME['bg']);self.blank.pack()
        self.root.update()

    def tearDown(self):self.root.destroy()

    def test_outside_click_and_focus_loss_clear_text_highlight_without_changing_value(self):
        self.picker.focus_force();self.root.update()
        self.picker.selection_range(0,'end');self.assertTrue(self.picker.selection_present())
        self.blank.event_generate('<ButtonPress-1>');self.root.update()
        self.assertFalse(self.picker.selection_present())
        self.assertEqual(self.picker.get(),'First profile')
        self.assertEqual(self.root.focus_get(),self.picker)
        self.assertTrue(self.picker.instate(['focus']))
        self.picker.selection_range(0,'end');self.blank.focus_force();self.root.update()
        self.assertFalse(self.picker.selection_present())
        self.assertEqual(self.picker.current(),0)

    def test_native_keyboard_choice_keeps_menu_selection_and_clears_only_closed_field(self):
        self.picker._open();self.root.update()
        menu=self.picker._popup+'.f.l'
        self.assertEqual(tuple(self.root.tk.call(menu,'curselection')),(0,))
        self.root.tk.call('focus','-force',menu)
        self.root.tk.call('event','generate',menu,'<KeyPress-Down>')
        self.root.tk.call('event','generate',menu,'<KeyPress-Return>');self.root.update()
        self.assertEqual(self.picker.current(),1)
        self.assertFalse(self.picker.selection_present())
        self.assertEqual(self.root.focus_get(),self.picker)
        self.assertTrue(self.picker.instate(['focus']))
        self.picker._open();self.root.update()
        self.assertEqual(tuple(self.root.tk.call(menu,'curselection')),(1,))
        self.root.tk.call('event','generate',menu,'<KeyPress-Escape>');self.root.update()
        self.assertEqual(self.picker.current(),1)
        self.assertFalse(self.picker.selection_present())

    def test_destroy_unregisters_shared_owner_binding(self):
        self.picker.destroy();self.root.update()
        self.assertIsNone(self.picker._selection_binding)
        self.blank.event_generate('<ButtonPress-1>');self.root.update()

    def test_application_selection_callback_does_not_override_field_cleanup(self):
        selected=[]
        self.picker.bind('<<ComboboxSelected>>',lambda event:selected.append(self.picker.get()))
        self.root.tk.call('ttk::combobox::SelectEntry',str(self.picker),1);self.root.update()
        self.assertEqual(selected,['Second profile'])
        self.assertFalse(self.picker.selection_present())
        self.assertEqual(self.picker.current(),1)


if __name__=='__main__':unittest.main()
