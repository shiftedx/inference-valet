import contextlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('editor_launcher',ROOT/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
from ai_profiles import ProfileStore

class EditorTests(unittest.TestCase):
    def make_store(self,root):
        store=ProfileStore(root/'backend',root/'state');path=store.paths('strata-128k')[0]
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(parallel=1,model_name='fixture',args=['--max-context','163840',
            '--kv','int8','--kv-resident','32768','--prefill','8192'],reasoning_budget_tokens=32768)))
        return store

    def test_editor_tabs_and_actions_fit_at_common_scales(self):
        real_tk=tk.Tk
        with tempfile.TemporaryDirectory() as directory:
            store=self.make_store(pathlib.Path(directory))
            for factor in (1,1.5,2):
                with self.subTest(scale=factor):
                    def root():
                        window=real_tk();window.tk.call('tk','scaling',(96/72)*factor);return window
                    with patch.object(tk,'Tk',side_effect=root),patch.object(a,'PROFILE_STORE',store):
                        app=a.LauncherUI(enable_tray=False,observe=False)
                        try:
                            app.edit_profile();editor=app.profile_editor
                            app.edit_profile();self.assertIs(app.profile_editor,editor)
                            for page in ('Profile','Engine'):
                                editor.select_page(page);app.window.update()
                                top=editor.window.winfo_rooty();bottom=top+editor.window.winfo_height()
                                for widget in (editor.save_button,*editor.fields.values()):
                                    if widget.winfo_ismapped():
                                        self.assertGreaterEqual(widget.winfo_rooty(),top)
                                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
                                self.assertLessEqual(editor.window.winfo_height(),round(650*factor))
                                fields=[widget for key,widget in editor.fields.items() if editor.field_pages[key]==page]
                                self.assertEqual(len({widget.winfo_height() for widget in fields}),1)
                                if page=='Profile':
                                    self.assertEqual(len({widget.winfo_rootx() for widget in fields}),1)
                                    self.assertEqual(len({widget.winfo_width() for widget in fields}),1)
                                    labels=[editor.field_labels[key] for key in editor.fields if editor.field_pages[key]==page]
                                    steps=[b.winfo_rooty()-a.winfo_rooty() for a,b in zip(labels,labels[1:])]
                                    self.assertLessEqual(max(steps)-min(steps),1)
                                    # Resizing keeps one shared column instead of individual widget widths.
                                    editor.window.geometry(f'{round(680*factor)}x{editor.window.winfo_height()}')
                                    app.window.update()
                                    self.assertEqual(len({widget.winfo_rootx() for widget in fields}),1)
                                    self.assertEqual(len({widget.winfo_width() for widget in fields}),1)
                                else:
                                    self.assertLessEqual(max(w.winfo_width() for w in fields)-min(w.winfo_width() for w in fields),1)
                                    for left,right in zip(fields[::2],fields[1::2]):
                                        self.assertEqual(left.winfo_rooty(),right.winfo_rooty())
                        finally:app.quit()

    def test_save_persists_and_updates_selector_without_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            store=self.make_store(pathlib.Path(directory))
            with patch.object(a,'PROFILE_STORE',store),patch.object(a,'control_lock',side_effect=lambda **kwargs:contextlib.nullcontext()),patch.object(a,'start_profile') as start,patch.object(a,'stop_all') as stop:
                app=a.LauncherUI(enable_tray=False,observe=False)
                try:
                    app.edit_profile();editor=app.profile_editor
                    editor.vars['name'].set('Writing');editor.vars['context'].set('131072')
                    editor.save();app.window.update()
                    self.assertFalse(editor.window.winfo_exists())
                    self.assertEqual(app.selected.get(),'Writing · 1 agent · 128K')
                    self.assertEqual(app.picker.current(),app.keys.index('strata-128k'))
                    self.assertEqual(a.PROFILES['strata-128k']['context'],131072)
                    start.assert_not_called();stop.assert_not_called()
                finally:
                    app.quit()
            a.reload_profiles()

    def test_invalid_save_keeps_editor_and_files_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            store=self.make_store(pathlib.Path(directory));path=store.paths('strata-128k')[0];before=path.read_bytes()
            with patch.object(a,'PROFILE_STORE',store):
                app=a.LauncherUI(enable_tray=False,observe=False)
                try:
                    app.edit_profile();editor=app.profile_editor
                    editor.vars['context'].set('invalid');editor.save()
                    self.assertTrue(editor.window.winfo_exists());self.assertIn('whole number',editor.error.get())
                    self.assertEqual(path.read_bytes(),before)
                    with patch('ai_profile_editor.messagebox.askyesno',return_value=False):editor.close()
                    self.assertTrue(editor.window.winfo_exists())
                    with patch('ai_profile_editor.messagebox.askyesno',return_value=True):editor.close()
                    self.assertFalse(editor.window.winfo_exists())
                finally:app.quit()

if __name__=='__main__':unittest.main()
