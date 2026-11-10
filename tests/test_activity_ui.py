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

    def test_numeric_request_metrics_remain_accessible_at_each_scale(self):
        for scale in (1,1.5,2):
            with self.subTest(scale=scale):
                self.root.tk.call('tk','scaling',(96/72)*scale)
                self.root.geometry(f'760x{round(1500*scale)}')
                panel=PerformancePanel(self.root)
                panel.pack(fill='both',expand=True)
                panel.update({'activity':{'state':'ready','engine':'llamacpp','title':'Ready','recent':[
                    dict(time=1700000000,finish='stop',tokens=40,duration_s=2,prefill_tok_s=2000,
                         decode_tok_s=200,ttft_ms=250,reuse_percent=90,draft_percent=80)]}})
                panel.toggle_details();panel.details_notebook.select(panel.detail_tabs['Requests'])
                self.root.update()
                row=panel.request_table.item(panel.request_table.get_children()[0],'values')
                self.assertEqual(row[4:],('2,000','200.0','250','90.0','80.0'))
                self.assertTrue(panel.request_table.winfo_ismapped())
                panel.request_table.xview_moveto(1);self.root.update()
                self.assertEqual(panel.request_table.xview()[1],1)
                panel.frame.destroy()

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
        self.assertEqual(panel.activity_note.get(),'Other GPU users: game.exe')
        self.assertEqual(panel.comfy_observation.get(),'1 running · 0 queued')
        self.assertFalse(panel.details_expanded)
        self.root.geometry('900x950')
        panel.toggle_details()
        panel.details_notebook.select(panel.detail_tabs['Requests'])
        self.root.update()
        self.assertTrue(panel.request_table.winfo_ismapped())
        values = [panel.request_table.item(item, 'values') for item in panel.request_table.get_children()]
        self.assertEqual(values[0][1:4], ('Completed', '42', '2.0 s'))
        self.assertEqual(values[0][4:], ('—',)*5)
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

    def test_activity_prefix_uses_reported_backend(self):
        panel=PerformancePanel(self.root,compact=True)
        for engine,prefix in (('infernix','Infernix · '),('ninfer','NInferEZ · '),('strata','Strata · '),(None,'')):
            panel.update({'activity':{'engine':engine,'state':'loading','title':'Loading model'}})
            self.assertEqual(panel.activity_title.get(),prefix+'Loading model')

    def test_request_counts_distinguish_inflight_from_occupied_slots(self):
        panel=PerformancePanel(self.root)
        panel.pack(fill='both',expand=True)
        self.root.update_idletasks()
        for capacity,occupied,inflight,outside in ((4,4,6,2),(8,6,6,0)):
            panel.update({'running':inflight,'queued':0,'capacity':capacity,
                          'occupied_slots':occupied,'outside_slots':outside})
            self.root.update_idletasks()
            self.assertEqual(panel.requests.get(),f'{inflight} in flight')
            labels=[panel.agent_activity.itemcget(i,'text') for i in panel.agent_activity.find_all()
                    if panel.agent_activity.type(i)=='text']
            self.assertIn(f'{occupied} / {capacity} slots',labels[0])
            self.assertNotIn('agents',labels[0])
            if outside:self.assertIn(f'{outside} outside',labels[0])
        panel.mark_stale()
        self.assertIsNone(panel.latest['occupied_slots'])

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
        self.assertEqual(panel.requests.get(), '— in flight')
        self.assertEqual(panel.requests_note.get(), '— queued')
        self.assertEqual(panel.speed.get(), '42.0 tok/s')
        self.assertIn('Last completed request', panel.speed_note.get())
        self.assertEqual(len(panel.request_history), 1)
        self.assertEqual(panel.identity, 'one')
        self.assertIsNone(panel.latest['live_speed'])
        self.assertIn('stale', panel.source_marks['speed'].cget('text'))

    def test_strip_uses_full_process_count_and_mixed_throughput_sources(self):
        import time
        strip = tk.Frame(self.root)
        strip.pack(fill='x')
        panel = PerformancePanel(self.root, status_parent=strip)
        panel.pack(fill='both', expand=True)
        panel.update({'last_at': time.time()-51, 'last_speed': 215.7, 'prefill_speed': 0,
                      'activity': {'state': 'reading', 'title': 'Reading prompt',
                                   'gpu_process_count': 14, 'gpu_processes': [{}]*8,
                                   'gpu_note': '14 other compute processes reported on GPU 0',
                                   'comfy': {'state': 'unavailable', 'title': 'Unavailable'}}})
        self.root.update()
        self.assertEqual(panel.activity_header.master, strip)
        self.assertEqual(panel.gpu_mark.cget('text'), '▣ 14')
        self.assertEqual(panel.source_marks['speed'].cget('text'), '◷ 51s')
        self.assertEqual(panel.source_marks['prompt_speed'].cget('text'), '▶')
        self.assertFalse(panel.activity_note_label.winfo_ismapped())
        self.assertEqual(panel.activity_note.get(),'')
        panel.activity_tip.show_tip()
        self.assertIsNone(panel.activity_tip.tip)
        panel.mark_stale()
        self.assertEqual(panel.gpu_mark.cget('text'), '▣ —')

    def test_short_state_keeps_details_on_hover_and_only_detected_comfy_visible(self):
        strip=tk.Frame(self.root);strip.pack(fill='x')
        panel=PerformancePanel(self.root,status_parent=strip);panel.pack(fill='both',expand=True)
        activity={'state':'unloaded','title':'Unloaded','detail':'Model will load on the next admitted request','gpu_process_count':15}
        for state,visible in (('unavailable',False),('not_configured',False),('idle',True),('busy',True),('unavailable',False)):
            panel.update({'activity':{**activity,'comfy':{'state':state,'title':state}}})
            self.root.update()
            self.assertEqual(panel.activity_title.get(),'Strata · Unloaded')
            self.assertIn('next admitted request',panel.activity_note.get())
            self.assertEqual(panel.gpu_mark.cget('text'),'▣ 15')
            self.assertEqual(panel.gpu_observation.get(),'15 other GPU processes')
            self.assertEqual(bool(panel.comfy_mark.winfo_ismapped()),visible)
            self.assertGreaterEqual(panel.activity_marks.winfo_rootx(),panel.activity_title_label.winfo_rootx())
        panel.mark_stale();self.root.update()
        self.assertFalse(panel.comfy_mark.winfo_ismapped())

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
