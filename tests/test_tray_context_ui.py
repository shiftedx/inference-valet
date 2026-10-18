"""Native menu checks for hosted Windows CI; do not run on a gaming desktop."""
import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_tray_menu import MenuItem,TrayContextMenu
from ai_widgets import THEME


class ContextUITests(unittest.TestCase):
    def test_shared_style_keyboard_profiles_and_scroll_fit_at_common_scales(self):
        for factor in (1,1.5,2):
            with self.subTest(scale=factor):
                root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',(96/72)*factor)
                calls=[]
                profiles=[MenuItem('User profile '+str(index)+' with a long model name '*4,
                                  lambda index=index:calls.append(index),checked=index==3) for index in range(30)]
                items=lambda:[MenuItem('Open dashboard',lambda:calls.append('open')),
                              MenuItem('Disabled',lambda:calls.append('disabled'),enabled=False),
                              MenuItem('Load model',children=lambda:profiles),
                              MenuItem('Restore when idle',checked=True),None,MenuItem('Exit Valet')]
                menu=TrayContextMenu(root,items)
                try:
                    with patch('ai_tray_menu.anchor_work_area',return_value=(0,0,1024,728)):
                        menu.show((1020,724));root.update()
                        self.assertEqual(menu.window.cget('bg'),THEME['line'])
                        self.assertEqual(menu.body.cget('bg'),THEME['bg'])
                        self.assertEqual(menu.buttons[0].cget('fg'),THEME['text'])
                        menu.move(1);self.assertEqual(menu.window.focus_get(),menu.buttons[2])
                        menu.invoke(menu.rows[1]);self.assertEqual(calls,[])
                        menu.open_focused();root.update()
                        self.assertTrue(menu.page);self.assertTrue(menu.buttons[4].selected)
                        self.assertTrue(menu.buttons[4].cget('text').startswith('✓'))
                        self.assertEqual(menu.scrollbar.winfo_manager(),'pack')
                        menu.edge(True);root.update()
                        last=menu.buttons[-1]
                        bottom=menu.canvas.winfo_rooty()+menu.canvas.winfo_height()
                        self.assertLessEqual(last.winfo_rooty()+last.winfo_height(),bottom+1)
                        self.assertLessEqual(menu.window.winfo_rootx()+menu.window.winfo_width(),1024)
                        self.assertLessEqual(menu.window.winfo_rooty()+menu.window.winfo_height(),728)
                        menu.invoke(menu.rows[-1]);self.assertEqual(calls,[29])
                        self.assertEqual(menu.window.state(),'withdrawn')
                        menu.show((1020,724));menu.invoke(menu.rows[2]);menu.invoke(menu.rows[0]);root.update()
                        self.assertFalse(menu.page)
                        self.assertNotEqual(menu.window.state(),'withdrawn')
                        menu.window.event_generate('<Escape>');root.update()
                        self.assertEqual(menu.window.state(),'withdrawn')
                finally:root.destroy()

    def test_outside_focus_and_stale_disabled_action_dismiss_safely(self):
        root=tk.Tk();root.withdraw();busy=[False];calls=[]
        row=MenuItem('Run',lambda:calls.append('run'),enabled=lambda:not busy[0])
        menu=TrayContextMenu(root,lambda:[row])
        try:
            with patch('ai_tray_menu.anchor_work_area',return_value=(0,0,1024,728)):
                menu.show((1000,700));root.update()
                busy[0]=True;menu.refresh();menu.invoke(row)
                self.assertEqual(calls,[])
                self.assertEqual(menu.buttons[0].cget('state'),'disabled')
                with patch.object(menu.window,'focus_displayof',return_value=root):menu.dismiss_outside()
                self.assertEqual(menu.window.state(),'withdrawn')
                self.assertIsNone(menu.pending)
        finally:root.destroy()


if __name__=='__main__':unittest.main()
