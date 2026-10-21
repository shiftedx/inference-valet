"""Exercise display transitions in one live Tk/controller instance, without changing Windows."""
import importlib.util
import pathlib
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_display import Display, fit_geometry, rescale_geometry, read_display
from profile_fixtures import configure_launcher
spec = importlib.util.spec_from_file_location('display_launcher', ROOT/'ai-launcher.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
configure_launcher(a)

WORK = (0, 0, 6000, 4000)


class GeometryTests(unittest.TestCase):
    def test_bounds_include_negative_origins_and_small_work_areas(self):
        self.assertEqual(fit_geometry((1000, 900), (-5000, 9000), (-1280, -100, 0, 700), 1),
                         '1000x728+-1264+-84')
        self.assertEqual(fit_geometry((760, 580), (0, 0), (0, 0, 1, 1), 2), '1x1+0+0')

    def test_collapsed_details_geometry_uses_the_new_scale_and_work_area(self):
        self.assertEqual(rescale_geometry('760x580-1100+30', 1.5, Display(144, (-2000, 0, 0, 1600))),
                         '1140x870+-1164+30')


class DisplayScalingTests(unittest.TestCase):
    def setUp(self):
        real_tk = tk.Tk
        def root():
            window = real_tk(); window.tk.call('tk', 'scaling', 96/72)
            return window
        with patch.object(tk, 'Tk', side_effect=root):
            self.app = a.LauncherUI(enable_tray=False, observe=False)
        self.app.window.update()
        self.app._display_work = WORK

    def tearDown(self):
        self.app.active.clear()
        self.app.quit()

    def change(self, dpi, work=WORK):
        with patch('ai_display.read_display', return_value=Display(dpi, work)):
            self.app.check_display_scale(force=True)
            self.app.window.update()

    def test_roundtrip_100_150_200_100_rebuilds_images_and_preserves_controller(self):
        app = self.app
        app.selected.set(a.PROFILE_NAMES[app.keys[1]])
        app.active.add('start')
        events = app.events; workers = (app.telemetry_worker, app.policy_worker)
        collector = app.collector; policy = app.idle_policy; root = app.window
        app.events.put(('status', 'Load remains in progress'))
        original_height = app.picker.winfo_height()
        original_font = int(root.tk.call('font', 'metrics', app.start_button.cget('font'), '-linespace'))
        with (patch.object(a, 'start_profile') as start, patch.object(a, 'stop_all') as stop,
              patch.object(a.IDLE_SETTINGS, 'update') as settings):
            for dpi in (144, 192, 96, 192, 96):
                with self.subTest(dpi=dpi):
                    previous = app.picker
                    self.change(dpi)
                    self.assertIsNot(app.picker, previous)
                    self.assertEqual(app.ui_scale, dpi/96)
                    self.assertAlmostEqual(app.picker.winfo_height()/original_height, dpi/96, delta=.1)
                    height = int(root.tk.call('font', 'metrics', app.start_button.cget('font'), '-linespace'))
                    self.assertAlmostEqual(height, original_font*dpi/96, delta=4)
                    self.assertEqual(app.selected.get(), a.PROFILE_NAMES[app.keys[1]])
                    self.assertEqual(str(app.start_button.cget('state')), 'disabled')
                    self.assertIs(app.window, root)
                    self.assertIs(app.events, events)
                    self.assertEqual((app.telemetry_worker, app.policy_worker), workers)
                    self.assertIs(app.collector, collector)
                    self.assertIs(app.idle_policy, policy)
            start.assert_not_called(); stop.assert_not_called(); settings.assert_not_called()
        app.poll()
        self.assertEqual(app.status.get(), 'Load remains in progress')
        app.active.clear()

    def test_open_editor_retains_unsaved_invalid_fields_and_snapshot(self):
        app = self.app
        app.edit_profile(initial_page='Memory'); app.window.update()
        editor = app.profile_editor
        editor.vars['resident'].set('not a number yet')
        editor.error.set('Draft validation message')
        snapshot = editor.snapshot; original = editor.original
        with patch.object(a.PROFILE_STORE, 'save') as save:
            self.change(192)
            rebuilt = app.profile_editor
            self.assertFalse(editor.window.winfo_exists())
            self.assertIs(rebuilt.snapshot, snapshot)
            self.assertIs(rebuilt.original, original)
            self.assertEqual(rebuilt.vars['resident'].get(), 'not a number yet')
            self.assertEqual(rebuilt.page, 'Memory')
            self.assertEqual(rebuilt.error.get(), 'Draft validation message')
            self.change(96)
            self.assertEqual(app.profile_editor.vars['resident'].get(), 'not a number yet')
            save.assert_not_called()

    def test_details_selection_history_and_collapsed_geometry_survive(self):
        app = self.app
        reading = dict(sampled=time.monotonic(), identity=('fixture',), hardware={},
                       activity=dict(state='ready', title='Ready'))
        app.latest_performance = reading
        app.performance.update(reading)
        app.performance.toggle_details()
        app.performance.details_notebook.select(app.performance.detail_tabs['Requests'])
        app.window.update()
        samples = list(app.performance.samples); history = list(app.performance.history)
        self.change(144)
        panel = app.performance
        self.assertTrue(panel.details_expanded)
        self.assertEqual(panel.details_notebook.tab(panel.details_notebook.select(), 'text'), 'Requests')
        self.assertEqual(list(panel.samples), samples)
        self.assertEqual(list(panel.history), history)
        self.assertIsNotNone(app.details_geometry)
        panel.toggle_details(); app.window.update()
        self.assertLessEqual(app.window.winfo_height(), round(650*1.5))

    def test_hidden_dashboard_and_visible_tray_popup_keep_visibility(self):
        app = self.app
        app.hide(); app.show_popup(anchor=(1500, 1000)); app.window.update()
        old_popup = app.popup
        self.change(192)
        self.assertEqual(app.window.state(), 'withdrawn')
        self.assertFalse(old_popup.winfo_exists())
        self.assertEqual(app.popup.state(), 'normal')
        # Tk derives scaling from the virtual display's rounded millimetre dimensions.
        self.assertAlmostEqual(app.popup_performance.scale, 2, delta=.02)
        self.change(96)
        self.assertEqual(app.window.state(), 'withdrawn')
        self.assertAlmostEqual(app.popup_performance.scale, 1, delta=.02)

    def test_poll_detects_change_and_stable_display_does_not_rebuild(self):
        app = self.app
        app.observe = True
        with patch('ai_display.read_display', return_value=Display(144, WORK)):
            app.poll()
            self.assertEqual(app.ui_scale, 1.5)
            picker = app.picker
            app.next_display_check = 0
            app.poll()
            self.assertIs(app.picker, picker)
        app.observe = False

    def test_resolution_change_clamps_window_without_rebuilding(self):
        picker = self.app.picker
        self.change(96, (-900, 0, 0, 700))
        self.assertIs(self.app.picker, picker)
        window = self.app.window
        self.assertGreaterEqual(window.winfo_x(), -900)
        self.assertLessEqual(window.winfo_x()+window.winfo_width(), 0)
        self.assertLessEqual(window.winfo_y()+window.winfo_height()+40, 700)

    def test_failed_probe_or_open_modal_defers_the_change(self):
        picker = self.app.picker
        with patch('ai_display.read_display', return_value=None):
            self.app.check_display_scale(force=True)
        self.assertIs(self.app.picker, picker)
        dialog = tk.Toplevel(self.app.window); dialog.grab_set()
        try:
            self.change(192)
            self.assertIs(self.app.picker, picker)
        finally:
            dialog.grab_release(); dialog.destroy()
        self.change(192)
        self.assertIsNot(self.app.picker, picker)

    def test_native_display_probe_reports_valid_dpi_and_work_area(self):
        display = read_display(self.app.window)
        self.assertIsNotNone(display)
        self.assertGreater(display.dpi, 0)
        left, top, right, bottom = display.work
        self.assertGreater(right, left); self.assertGreater(bottom, top)

    def test_chart_and_later_created_editor_use_the_new_font_scale(self):
        app = self.app
        def chart_height():
            canvas = app.performance.plots['output']
            text = next(item for item in canvas.find_all() if canvas.type(item) == 'text')
            return int(canvas.tk.call('font', 'metrics', canvas.itemcget(text, 'font'), '-linespace'))
        baseline = chart_height()
        self.change(192)
        self.assertGreaterEqual(chart_height(), baseline*1.8)
        app.edit_profile(); app.window.update()
        label = app.profile_editor.fields['name']
        self.assertGreaterEqual(int(label.tk.call('font', 'metrics', label.cget('font'), '-linespace')), baseline*1.8)
        self.change(96)
        self.assertAlmostEqual(chart_height(), baseline, delta=1)

    def test_new_tray_and_tooltip_do_not_replace_dashboard_style_fonts(self):
        from tkinter import ttk
        app = self.app
        self.change(192)
        style = ttk.Style(app.window)
        before = style.lookup('Valet.Treeview', 'font')
        app.show_context((1600, 1000)); app.window.update()
        self.assertEqual(style.lookup('Valet.Treeview', 'font'), before)
        app.hide_popup()
        tip = app.start_button.tooltip
        tip.show(); app.window.update()
        tip.hide(); app.window.update()
        self.assertEqual(style.lookup('Valet.Treeview', 'font'), before)
        self.assertGreater(int(app.window.tk.call('font', 'metrics', before, '-linespace')), 20)


if __name__ == '__main__':
    unittest.main()
