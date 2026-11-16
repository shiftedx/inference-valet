"""Keep status punctuation readable and the complete label inside its row."""
import ast
import importlib.util
import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('status_text_launcher',ROOT/'ai-launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
from profile_fixtures import configure_launcher
configure_launcher(launcher)


class StatusTextTests(unittest.TestCase):
    def test_ui_literals_do_not_contain_misdecoded_utf8_punctuation(self):
        broken={char.encode('utf-8').decode('cp1252') for char in '\u2026\u00b7\u2019\u2014\u00d7\u2197'}
        for path in [ROOT/'ai-launcher.py',*ROOT.glob('ai_*.py')]:
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    self.assertFalse(any(bad in node.value for bad in broken),f'{path.name}:{node.lineno}')

    def test_loading_status_is_complete_at_common_display_scales(self):
        real_tk=tk.Tk
        for factor in (1,1.25,1.5,2):
            with self.subTest(scale=factor):
                def scaled_root():
                    root=real_tk();root.tk.call('tk','scaling',(96/72)*factor)
                    root.winfo_screenwidth=lambda:1024;root.winfo_screenheight=lambda:728
                    return root
                with patch.object(tk,'Tk',side_effect=scaled_root):
                    app=launcher.LauncherUI(enable_tray=False,observe=False)
                try:
                    app.active.add('start');app.refresh_display()
                    for _ in range(3):app.window.update()
                    panel=app.performance;label=panel.activity_title_label;header=panel.activity_header
                    self.assertEqual(panel.activity_title.get(),'Strata \u00b7 Loading model\u2026')
                    self.assertGreater(label.winfo_width(),0)
                    self.assertLessEqual(label.winfo_x()+label.winfo_width(),header.winfo_width()+2)
                    self.assertGreaterEqual(label.winfo_height(),label.winfo_reqheight())
                    self.assertLessEqual(label.winfo_y()+label.winfo_height(),header.winfo_height()+2)
                finally:
                    app.active.clear();app.quit()


if __name__=='__main__':unittest.main()
