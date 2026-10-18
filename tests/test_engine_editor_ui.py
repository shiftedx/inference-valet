"""Memory edits validate and stage profile files, without touching a backend."""
import json
import pathlib
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch

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

    def test_imported_agent_count_and_effort_remain_selectable(self):
        self.editor.window.destroy()
        data=json.loads(self.path.read_text());data.update(parallel=8,reasoning_effort='extended')
        self.path.write_text(json.dumps(data))
        self.editor=ProfileEditor(self.root,self.store,'strata-128k',self.callback,lambda window:None)
        for key,alternate,original in (('slots','4','8'),('effort','high','extended')):
            self.assertIn(original,self.editor.fields[key].cget('values'))
            self.editor.fields[key].set(alternate);self.editor.fields[key].set(original)
            self.assertEqual(self.editor.vars[key].get(),original)
        self.assertIn('',self.editor.fields['effort'].cget('values'))
        self.editor.vars['name'].set('Imported profile');self.editor.save()
        saved=json.loads(self.path.read_text())
        self.assertEqual(saved['parallel'],8);self.assertEqual(saved['reasoning_effort'],'extended')

    def test_renaming_profile_preserves_absent_reasoning_overrides(self):
        self.editor.window.destroy()
        data=json.loads(self.path.read_text());data.pop('reasoning_budget_tokens',None)
        self.path.write_text(json.dumps(data))
        self.editor=ProfileEditor(self.root,self.store,'strata-128k',self.callback,lambda window:None)
        self.assertEqual(self.editor.vars['effort'].get(),'')
        self.assertEqual(self.editor.vars['reasoning'].get(),'')
        self.editor.vars['name'].set('Backend defaults');self.editor.save()
        for path in self.store.paths('strata-128k')[:2]:
            saved=json.loads(path.read_text())
            self.assertNotIn('reasoning_effort',saved)
            self.assertNotIn('reasoning_budget_tokens',saved)

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
                        self.assertGreaterEqual(editor.save_button.winfo_rooty(),top)
                        self.assertLessEqual(editor.save_button.winfo_rooty()+editor.save_button.winfo_height(),bottom)
                        # Small hosted desktops intentionally scroll the page.
                        # Every field must become fully visible on keyboard focus.
                        for key,widget in editor.fields.items():
                            if editor.field_pages[key]!=name:continue
                            widget.focus_force();self.root.update()
                            self.assertGreaterEqual(widget.winfo_rooty(),editor.canvas.winfo_rooty())
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                                 editor.canvas.winfo_rooty()+editor.canvas.winfo_height())
                            self.assertGreaterEqual(widget.winfo_rootx(),editor.canvas.winfo_rootx())
                            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),
                                                 editor.canvas.winfo_rootx()+editor.canvas.winfo_width())
                        self.assertLessEqual(editor.window.winfo_height(),round(650*factor))
                        self.assertTrue(editor.save_button.winfo_ismapped())
                finally:editor.window.destroy()

    def test_small_work_area_keeps_footer_and_every_field_reachable(self):
        self.editor.window.destroy()
        for factor in (1,1.5,2):
            with self.subTest(scale=factor),patch('ai_profile_editor.monitor_work_area',return_value=(0,0,1024,728)):
                self.root.tk.call('tk','scaling',(96/72)*factor)
                # Force both right/bottom clamps; a centered parent near (0,0)
                # can conceal omitted native frame and title-bar insets.
                self.root.geometry('200x200+1000+1000');self.root.update()
                editor=ProfileEditor(self.root,self.store,'strata-128k',self.callback,lambda window:None)
                try:
                    for name in ('Profile','Memory','Engine'):
                        editor.select_page(name);self.root.update()
                        self.assertGreaterEqual(editor.window.winfo_rootx(),0)
                        self.assertGreaterEqual(editor.window.winfo_rooty(),0)
                        self.assertLessEqual(editor.window.winfo_rootx()+editor.window.winfo_width(),1024)
                        self.assertLessEqual(editor.window.winfo_rooty()+editor.window.winfo_height(),728)
                        border=editor.window.winfo_rootx()-editor.window.winfo_x()
                        caption=editor.window.winfo_rooty()-editor.window.winfo_y()
                        self.assertLessEqual(editor.window.winfo_x()+editor.window.winfo_width()+2*border,1024)
                        self.assertLessEqual(editor.window.winfo_y()+editor.window.winfo_height()+caption+border,728)
                        self.assertLessEqual(editor.save_button.winfo_rooty()+editor.save_button.winfo_height(),728)
                        for key,field in editor.fields.items():
                            if editor.field_pages[key]!=name:continue
                            field.focus_force();self.root.update()
                            self.assertGreaterEqual(field.winfo_rooty(),editor.canvas.winfo_rooty())
                            self.assertLessEqual(field.winfo_rooty()+field.winfo_height(),
                                                 editor.canvas.winfo_rooty()+editor.canvas.winfo_height())
                            self.assertGreaterEqual(field.winfo_rootx(),editor.canvas.winfo_rootx())
                            self.assertLessEqual(field.winfo_rootx()+field.winfo_width(),
                                                 editor.canvas.winfo_rootx()+editor.canvas.winfo_width())
                        self.assertTrue(editor.save_button.winfo_ismapped())
                        if factor>1:self.assertTrue(editor.scrollbar.winfo_ismapped())
                finally:editor.window.destroy()


if __name__=='__main__':unittest.main()
