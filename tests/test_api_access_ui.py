import importlib.util,pathlib,sys,tkinter as tk,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('api_access_launcher',ROOT/'ai-launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
from profile_fixtures import configure_launcher
configure_launcher(launcher)

class ApiAccessTests(unittest.TestCase):
    def test_mask_reveal_copy_and_tab_leave_at_all_scales(self):
        real_tk=tk.Tk
        for scale in (1,1.5,2):
            with self.subTest(scale=scale):
                def scaled_root():
                    root=real_tk();root.tk.call('tk','scaling',96/72*scale);return root
                with patch.object(tk,'Tk',side_effect=scaled_root),patch.object(launcher,'strata_api_key',return_value='fixture-api-token'):
                    app=launcher.LauncherUI(enable_tray=False,observe=False)
                try:
                    panel=app.api_access;notebook=app.performance.details_notebook
                    app.performance.toggle_details();notebook.select(app.performance.detail_tabs['API access']);app.window.update()
                    self.assertEqual(panel.value.get(),'fixture-api-token');self.assertTrue(panel.field.cget('show'))
                    panel.eye.invoke();self.assertEqual(panel.field.cget('show'),'')
                    panel.copy_button.invoke();self.assertEqual(app.window.clipboard_get(),'fixture-api-token')
                    self.assertNotIn('fixture-api-token',panel.note.get())
                    notebook.select(app.performance.detail_tabs['Engine']);app.window.update()
                    self.assertTrue(panel.field.cget('show'))
                    notebook.select(app.performance.detail_tabs['API access']);app.window.update()
                    for control in (panel.field,panel.eye,panel.copy_button):
                        self.assertGreaterEqual(control.winfo_width(),control.winfo_reqwidth())
                        self.assertLessEqual(control.winfo_rootx()+control.winfo_width(),notebook.winfo_rootx()+notebook.winfo_width())
                    app.hide();app.window.update();self.assertTrue(panel.field.cget('show'))
                finally:app.window.clipboard_clear();app.quit()
    def test_no_key_disables_reveal_copy(self):
        with patch.object(launcher,'strata_api_key',return_value=''):
            app=launcher.LauncherUI(enable_tray=False,observe=False)
        try:
            self.assertEqual(app.api_access.eye.cget('state'),'disabled')
            self.assertEqual(app.api_access.copy_button.cget('state'),'disabled')
            self.assertIn('No API token',app.api_access.note.get())
        finally:app.quit()
if __name__=='__main__':unittest.main()
