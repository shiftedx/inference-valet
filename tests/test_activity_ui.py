import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_telemetry import PerformancePanel, THEME


class ActivityPanelTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        # Standalone panel tests need their requested workspace even on the
        # smaller desktop used by hosted Windows runners.
        self.root.maxsize(10000, 10000)
        self.root.geometry('760x650')

    def tearDown(self):
        self.root.destroy()

    def test_activity_visible_and_request_history_excludes_payloads(self):
        panel = PerformancePanel(self.root)
        panel.pack(fill='both', expand=True)
        panel.update({'activity': {
            'state': 'reading', 'title': 'Reading prompt', 'detail': '1 active · 2 waiting',
            'gpu_note': '12 GiB available', 'blockers': ['Other GPU users: game.exe'],
            'gpu_processes': [{'pid': 123, 'name': 'C:\\private\\comfy\n.exe', 'memory_mib': None},
                              {'pid': 456, 'name': 'worker.exe', 'memory_mib': 1024}],
            'comfy': {'state': 'busy', 'title': 'Generating', 'detail': '1 running · 0 queued'},
            'recent': [{'time': 1700000000, 'finish': 'stop', 'tokens': 42,
                        'duration_s': 2, 'prompt': 'private prompt', 'response': 'private response'}]}})
        self.root.update()
        self.assertTrue(panel.activity_header.winfo_ismapped())
        self.assertIn('Reading prompt', panel.activity_title.get())
        self.assertIn('ComfyUI: Generating', panel.activity_note.get())
        self.assertFalse(panel.details_expanded)
        self.root.geometry('900x950')
        panel.toggle_details()
        panel.details_notebook.select(panel.detail_tabs['Requests'])
        self.root.update()
        self.assertTrue(panel.request_table.winfo_ismapped())
        values = [panel.request_table.item(item, 'values') for item in panel.request_table.get_children()]
        self.assertEqual(values[0][1:], ('Completed', '42', '2.0 s'))
        self.assertIn('game.exe', panel.blocker_summary.get())
        self.assertIn('1 running', panel.comfy_summary.get())
        self.assertFalse(panel.process_table.winfo_ismapped())
        panel.details_notebook.select(panel.detail_tabs['Diagnostics'])
        self.root.update()
        self.assertTrue(panel.process_table.winfo_ismapped())
        processes = [panel.process_table.item(item, 'values') for item in panel.process_table.get_children()]
        self.assertEqual(processes, [('comfy.exe', '123', '—'), ('worker.exe', '456', '1,024 MiB')])
        self.assertIn('not confirmed blockers', panel.process_note.get())
        self.assertEqual(panel.process_note.get().count('Windows'), 1)
        text = str(values) + str(processes)
        self.assertNotIn('private prompt', text)
        self.assertNotIn('private response', text)
        self.assertNotIn('private', str(processes))
        self.assertEqual(len(panel.metric_widgets), 6)

    def test_compact_unavailable_does_not_claim_idle(self):
        panel = PerformancePanel(self.root, compact=True)
        panel.pack(fill='x')
        panel.update({'activity': {'state': 'unavailable', 'title': 'State unavailable',
                                  'detail': 'Retrying', 'comfy': {'state': 'not_configured'}}})
        self.root.update()
        self.assertIn('State unavailable', panel.activity_title.get())
        self.assertNotIn('Idle', panel.activity_title.get())
        self.assertNotIn('ComfyUI', panel.activity_note.get())
        self.assertEqual(panel.activity_title_label.cget('fg'), THEME['amber'])

    def test_legacy_payload_hides_activity_and_stale_is_explicit(self):
        panel = PerformancePanel(self.root)
        panel.pack(fill='both', expand=True)
        panel.update({'activity': {'state': 'stale', 'title': 'Reading is stale',
                                  'detail': 'Retrying', 'gpu_note': 'GPU reading unavailable'}})
        self.root.update()
        self.assertIn('stale', panel.activity_title.get())
        self.assertEqual(panel.activity_title_label.cget('fg'), THEME['amber'])
        panel.update({})
        self.root.update()
        self.assertFalse(panel.activity_header.winfo_ismapped())

    def test_stale_reading_clears_live_claims_and_preserves_history(self):
        panel = PerformancePanel(self.root)
        panel.pack(fill='both', expand=True)
        panel.update({'identity': 'one', 'live_speed': 30, 'last_speed': 42,
                      'last_prefill': 1200, 'last_at': 1700000000,
                      'running': 1, 'queued': 2, 'activity': {'state': 'generating', 'title': 'Generating'}})
        panel.mark_stale()
        self.assertEqual(panel.activity_title.get(), 'Status unavailable')
        self.assertIn('stale', panel.activity_note.get())
        self.assertEqual(panel.requests.get(), '— active')
        self.assertEqual(panel.requests_note.get(), '— waiting')
        self.assertEqual(panel.speed.get(), '42.0 tok/s')
        self.assertIn('Last completed request', panel.speed_note.get())
        self.assertEqual(len(panel.request_history), 1)
        self.assertEqual(panel.identity, 'one')
        self.assertIsNone(panel.latest['live_speed'])

    def test_activity_preserves_six_metrics_at_common_scales(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('activity_layout_launcher', pathlib.Path(__file__).resolve().parents[1] / 'ai-launcher.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        real_tk = tk.Tk
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                def scaled_root():
                    root = real_tk()
                    root.tk.call('tk', 'scaling', (96 / 72) * scale)
                    return root
                with patch.object(tk, 'Tk', side_effect=scaled_root):
                    app = launcher.LauncherUI(enable_tray=False, observe=False)
                try:
                    app.performance.update({'ttft_ms': 850, 'activity': {
                        'state': 'blocked', 'title': 'Waiting for resources',
                        'detail': 'GPU memory headroom is below the load limit',
                        'gpu_note': 'No other compute processes reported on GPU 0',
                        'comfy': {'state': 'unavailable', 'title': 'Unavailable'}}})
                    app.window.update()
                    top = app.dashboard_canvas.winfo_rooty()
                    bottom = top + app.dashboard_canvas.winfo_height()
                    widgets = (*app.performance.metric_widgets.values(), app.performance.details_button,
                               app.performance.activity_header)
                    content = app.dashboard_canvas.winfo_children()[0]
                    fits = content.winfo_reqheight() <= app.dashboard_canvas.winfo_height()
                    for widget in widgets:
                        self.assertTrue(widget.winfo_ismapped())
                        if fits:
                            self.assertGreaterEqual(widget.winfo_rooty(), top)
                            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
                    if fits:
                        self.assertEqual(app.dashboard_canvas.yview(), (0.0, 1.0))
                    else:
                        # A DPI simulation can exceed the runner's actual work
                        # area. Verify every control remains reachable by scroll.
                        self.assertLess(app.dashboard_canvas.yview()[1], 1)
                        for widget in widgets:
                            offset = widget.winfo_rooty() - content.winfo_rooty()
                            app.dashboard_canvas.yview_moveto(offset / content.winfo_height())
                            app.window.update()
                            self.assertGreaterEqual(widget.winfo_rooty(), top)
                            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
                        app.dashboard_canvas.yview_moveto(0)
                finally:
                    app.quit()


if __name__ == '__main__':
    unittest.main()
