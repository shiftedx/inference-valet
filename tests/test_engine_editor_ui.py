"""Memory edits validate and stage profile files, without touching a backend."""
import json
import pathlib
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_profile_editor import ProfileEditor
from ai_profiles import ProfileStore


class EngineEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        directory=pathlib.Path(self.temp.name)
        self.store=ProfileStore(directory/'backend',directory/'state')
        self.path=self.store.paths('strata-128k')[0]
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(dict(parallel=1,args=[
            '--max-context','163840','--kv','int8','--ple-io','direct',
            '--expert-cache','auto','--resident-budget-gib','12.00',
            '--kv-resident','32768','--vram-reserve-mib','512'],
            reasoning_budget_tokens=32768)))
        self.root=tk.Tk()
        self.callback=Mock(side_effect=self.store.save)
        self.editor=ProfileEditor(self.root,self.store,'strata-128k',self.callback,
                                  lambda window:None,initial_page='Memory')
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def test_memory_shortcut_and_default_options(self):
        editor=self.editor
        self.assertEqual(editor.page,'Memory')
        self.assertEqual(tuple(editor.fields['ple_io'].cget('values')),('', 'direct','mmap','ram'))
        for key in ('ple_io','expert_cache','resident','reserve','kv_resident'):
            self.assertEqual(editor.field_pages[key],'Memory')
            self.assertTrue(editor.fields[key].winfo_ismapped())
        self.assertEqual(editor.save_button.cget('text'),'Save for next load')

    def test_no_op_save_does_not_rewrite_calibrated_values(self):
        before=self.path.read_bytes()
        self.editor.save()
        self.assertEqual(self.path.read_bytes(),before)
        self.callback.assert_not_called()
        self.assertFalse(self.editor.window.winfo_exists())

    def test_memory_edits_persist_only_on_save(self):
        before=self.path.read_bytes()
        for key,value in dict(ple_io='ram',expert_cache='9000',resident='8.5',reserve='1024').items():
            self.editor.vars[key].set(value)
        self.assertEqual(self.path.read_bytes(),before)
        self.editor.save()
        self.callback.assert_called_once()
        self.assertFalse(self.editor.window.winfo_exists())
        values,_=self.store.load('strata-128k')
        self.assertEqual(values['ple_io'],'ram')
        self.assertEqual(values['expert_cache'],'9000')
        self.assertEqual(values['resident'],'8.5')
        self.assertEqual(values['reserve'],'1024')

    def test_invalid_budget_retains_dialog_and_profile(self):
        before=self.path.read_bytes()
        self.editor.vars['resident'].set('0')
        self.editor.save()
        self.assertTrue(self.editor.window.winfo_exists())
        self.assertTrue(self.editor.error.get())
        self.callback.assert_not_called()
        self.assertEqual(self.path.read_bytes(),before)

    def test_clear_override_uses_backend_default(self):
        self.editor.vars['ple_io'].set('')
        self.editor.vars['expert_cache'].set('')
        self.editor.save()
        args=json.loads(self.path.read_text())['args']
        self.assertNotIn('--ple-io',args)
        self.assertNotIn('--expert-cache',args)

    def test_each_tab_and_save_fit_at_common_scales(self):
        self.editor.window.destroy()
        for factor in (1,1.5,2):
            with self.subTest(scale=factor):
                self.root.tk.call('tk','scaling',(96/72)*factor)
                editor=ProfileEditor(self.root,self.store,'strata-128k',self.callback,lambda window:None)
                try:
                    for name in ('Profile','Memory','Engine'):
                        editor.select_page(name)
                        self.root.update()
                        top=editor.window.winfo_rooty()
                        bottom=top+editor.window.winfo_height()
                        for widget in (editor.save_button,*editor.fields.values()):
                            if widget.winfo_ismapped():
                                self.assertGreaterEqual(widget.winfo_rooty(),top)
                                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
                        self.assertLessEqual(editor.window.winfo_height(),round(650*factor))
                        self.assertTrue(editor.save_button.winfo_ismapped())
                finally:editor.window.destroy()


if __name__=='__main__':unittest.main()
