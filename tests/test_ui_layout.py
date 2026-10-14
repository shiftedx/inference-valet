import importlib.util
import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('launcher_ui_layout', ROOT / 'ai-launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LayoutTests(unittest.TestCase):
    def test_right_click_keeps_native_tray_menu_and_left_click_opens_flyout(self):
        import pystray
        with patch.object(pystray.Icon, 'run'), patch.object(pystray.Icon, 'stop'), \
             patch.object(pystray.Icon, '_on_notify') as native_menu:
            app = launcher.LauncherUI(enable_tray=True, observe=False)
            try:
                app.tray._on_notify(0, 0x205)
                native_menu.assert_called_once_with(0, 0x205)
                app.tray._on_notify(0, 0x202)
                kind, anchor = app.events.get_nowait()
                self.assertEqual(kind, 'popup')
                self.assertEqual(len(anchor), 2)
                self.assertFalse(app.active)
            finally:
                app.quit()

    def test_profile_menu_keeps_text_inset_and_native_keyboard_selection(self):
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
                    app.picker.current(0)
                    app.picker._open()
                    app.window.update()
                    popup = app.window.tk.call('ttk::combobox::PopdownWindow', app.picker._w)
                    menu = popup + '.f.l'
                    bounds = app.window.tk.call(menu, 'bbox', 0)
                    self.assertGreaterEqual(int(bounds[0]), round(10 * scale))
                    import ctypes
                    from ctypes import wintypes
                    user = ctypes.windll.user32
                    gdi = ctypes.windll.gdi32
                    user.GetParent.argtypes = [wintypes.HWND]
                    user.GetParent.restype = wintypes.HWND
                    hwnd = user.GetParent(int(str(app.window.tk.call('winfo', 'id', popup)), 0))
                    gdi.CreateRectRgn.argtypes = [ctypes.c_int] * 4
                    gdi.CreateRectRgn.restype = wintypes.HRGN
                    region = gdi.CreateRectRgn(0, 0, 0, 0)
                    try:
                        user.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN]
                        self.assertNotEqual(user.GetWindowRgn(hwnd, region), 0)
                        gdi.PtInRegion.argtypes = [wintypes.HRGN, ctypes.c_int, ctypes.c_int]
                        self.assertFalse(gdi.PtInRegion(region, 0, 0))
                        width, height = app.picker._popup_size
                        self.assertTrue(gdi.PtInRegion(region, width // 2, height // 2))
                    finally:
                        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
                        gdi.DeleteObject(region)
                    app.window.tk.call('focus', '-force', menu)
                    app.window.tk.call('event', 'generate', menu, '<KeyPress-Down>')
                    app.window.tk.call('event', 'generate', menu, '<KeyPress-Return>')
                    app.window.update()
                    self.assertEqual(app.picker.current(), 1)
                    self.assertFalse(app.active)
                    app.picker._open()
                    app.window.update()
                    app.window.tk.call('event', 'generate', menu, '<KeyPress-Escape>')
                    app.window.update()
                    self.assertFalse(int(app.window.tk.call('winfo', 'ismapped', popup)))
                    app.picker.configure(state='disabled')
                    app.picker._open()
                    app.window.update()
                    self.assertFalse(int(app.window.tk.call('winfo', 'ismapped', popup)))
                finally:
                    app.quit()

    def test_performance_plots_use_remaining_space_and_reset_for_new_backend(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            panel = app.performance
            panel.update({'sampled': 100, 'identity': (1,), 'last_speed': 42,
                          'hardware': {'gpu_util': 0, 'cpu': 20}})
            app.window.update()
            self.assertIsNone(panel.history[-1]['output'])
            self.assertEqual(panel.history[-1]['gpu'], 0)
            self.assertEqual(panel.history[-1]['cpu'], 20)
            # Hosted Windows desktops may be smaller than the simulated DPI size.
            # Give this geometry test an explicit canvas large enough to stretch.
            app.window.maxsize(10000,10000)
            minimum=app.dashboard_canvas.winfo_children()[0].winfo_reqheight()+round(80*app.ui_scale)
            app.window.geometry(f'{app.window.winfo_width()}x{max(minimum,app.window.winfo_height())}')
            app.window.update()
            height = panel.graph.winfo_height()
            app.window.geometry(f'{app.window.winfo_width()}x{app.window.winfo_height()+round(100*app.ui_scale)}')
            app.window.update()
            self.assertGreaterEqual(panel.graph.winfo_height()-height, round(90*app.ui_scale))
            self.assertFalse(hasattr(app, 'hide_button'))
            self.assertFalse(hasattr(app, 'exit_button'))
            panel.update({'sampled': 101, 'identity': (1,), 'live_speed': 5,
                          'hardware': {'gpu_util': 10, 'cpu': 30}})
            self.assertEqual(len(panel.history), 2)
            panel.update({'sampled': 102, 'identity': (2,), 'hardware': {}})
            self.assertEqual(len(panel.history), 1)
            self.assertIsNone(panel.history[0]['gpu'])
            self.assertIsNone(panel.history[0]['output'])
            app.close()
            self.assertEqual(app.window.state(), 'withdrawn')
            self.assertTrue(app.window.winfo_exists())
        finally:
            app.quit()

    def test_windows_receives_app_identity_and_window_icons(self):
        import ctypes
        from ctypes import wintypes
        from ai_branding import APP_ID
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.window.update()
            user = ctypes.windll.user32
            user.GetParent.argtypes = [wintypes.HWND]
            user.GetParent.restype = wintypes.HWND
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.SendMessageW.restype = ctypes.c_ssize_t
            hwnd = user.GetParent(app.window.winfo_id())
            for size in (0, 1):
                self.assertNotEqual(user.SendMessageW(hwnd, 0x007f, size, 0), 0)
            shell = ctypes.windll.shell32
            shell.GetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
            shell.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
            identity = ctypes.c_wchar_p()
            self.assertEqual(shell.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(identity)), 0)
            try:
                self.assertEqual(identity.value, APP_ID)
            finally:
                ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(identity, ctypes.c_void_p))
        finally:
            app.quit()

    def test_overview_separates_live_speed_from_completed_request_metrics(self):
        import time
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            panel = app.performance
            panel.update({'last_speed': 42.5, 'last_prefill': 1200,
                          'ttft_ms': 850, 'last_at': time.time() - 120,
                          'hardware': {'ram_used': 16 * 2**30, 'ram_total': 64 * 2**30,
                                       'ram_free_gib': 48}})
            self.assertEqual(panel.speed.get(), '42.5 tok/s')
            self.assertIn('Last request', panel.speed_note.get())
            self.assertEqual(panel.prompt_speed.get(), '1,200 tok/s')
            self.assertEqual(panel.first_token.get(), '850 ms')
            self.assertEqual(panel.ram_memory.get(), '16.0 / 64 GiB')
            self.assertIsNone(panel.samples[-1][1])
            panel.update({'live_speed': 0, 'prefill_speed': 0, 'last_speed': 42.5,
                          'last_prefill': 1200, 'hardware': {}})
            self.assertEqual(panel.speed.get(), '0.0 tok/s')
            self.assertEqual(panel.speed_note.get(), 'Live output')
            self.assertEqual(panel.prompt_speed.get(), '0 tok/s')
            self.assertEqual(panel.first_token.get(), '—')
            panel.update({'hardware': {}})
            self.assertEqual(panel.speed.get(), '—')
            self.assertEqual(panel.prompt_speed.get(), '—')
            self.assertEqual(panel.ram_memory.get(), '—')
        finally:
            app.quit()

    def test_popup_fits_work_area_at_common_display_scales(self):
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                width, height = launcher.popup_size((0, 0, 800, 600), scale, 410)
                self.assertLessEqual(width, 800 - 24)
                self.assertLessEqual(height, 600 - 24)
                self.assertLessEqual(width, round(380 * scale))
                self.assertGreater(width, 0)

    def test_dashboard_starts_with_technical_details_collapsed(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.window.update_idletasks()
            self.assertFalse(app.performance.details_expanded)
            self.assertFalse(app.performance.detail_container.winfo_ismapped())
            app.performance.toggle_details()
            app.window.update_idletasks()
            self.assertTrue(app.performance.detail_container.winfo_ismapped())
        finally:
            app.quit()

    def test_display_names_keep_all_profile_keys_selectable(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            self.assertEqual(set(launcher.PROFILE_NAMES), set(launcher.PROFILES))
            for key in launcher.PROFILES:
                with self.subTest(key=key):
                    app.selected.set(launcher.PROFILE_NAMES[key])
                    self.assertEqual(app.keys[app.picker.current()], key)
        finally:
            app.quit()

    def test_real_controls_fit_dashboard_and_flyout_at_common_scales(self):
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
                    app.window.update()
                    canvas_right = app.dashboard_canvas.winfo_rootx() + app.dashboard_canvas.winfo_width()
                    self.assertEqual(app.picker.winfo_height(),app.start_button.winfo_height())
                    self.assertEqual(app.picker.winfo_height(),app.stop_button.winfo_height())
                    tops=[widget.winfo_rooty() for widget in (app.picker,app.start_button,app.stop_button)]
                    self.assertEqual(len(set(tops)),1)
                    plots=list(app.performance.plots.values())
                    self.assertLessEqual(max(p.winfo_width() for p in plots)-min(p.winfo_width() for p in plots),1)
                    for control in (app.picker, app.start_button, app.stop_button):
                        self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), canvas_right)
                    app.dashboard_canvas.yview_moveto(1)
                    app.window.update()
                    canvas_bottom = app.dashboard_canvas.winfo_rooty() + app.dashboard_canvas.winfo_height()
                    self.assertLessEqual(app.performance.details_button.winfo_rooty() + app.performance.details_button.winfo_height(), canvas_bottom)
                    app.show_popup(anchor=(100, 100))
                    app.window.update()
                    popup_right = app.popup_canvas.winfo_rootx() + app.popup_canvas.winfo_width()
                    for control in (app.popup_picker, app.popup_start, app.popup_stop):
                        self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), popup_right)
                    self.assertTrue(app.popup_content.winfo_reqheight() <= app.popup_canvas.winfo_height()
                                    or app.popup_scroll.winfo_ismapped())
                finally:
                    app.quit()

    def test_font_roles_and_stretched_button_surfaces_are_consistent(self):
        from tkinter import font
        app=launcher.LauncherUI(enable_tray=False,observe=False)
        try:
            app.performance.update({'hardware':{}});app.show_popup(anchor=(100,100));app.window.update()
            controls=(app.picker,app.delay_picker,app.start_button,app.stop_button,app.auto_control,
                      app.popup_picker,app.popup_delay_picker,app.popup_start,app.popup_stop)
            for control in controls:
                actual=font.Font(root=app.window,font=control.cget('font')).actual()
                self.assertEqual(actual['family'],'Segoe UI');self.assertEqual(actual['size'],10)
            for reading in app.performance.metric_widgets.values():
                actual=font.Font(root=app.window,font=reading.cget('font')).actual()
                self.assertEqual(actual['size'],12);self.assertEqual(actual['weight'],'bold')
            buttons=[widget for widget in app.popup_content.winfo_children() if widget.winfo_class()=='Button']
            stretched=buttons[-1]
            self.assertEqual(stretched.image.width(),stretched.winfo_width())
            natural=stretched.winfo_reqwidth()
            app.popup.geometry(f'{app.popup.winfo_width()+100}x{app.popup.winfo_height()}');app.window.update()
            self.assertEqual(stretched.image.width(),stretched.winfo_width())
            self.assertEqual(stretched.winfo_reqwidth(),natural)
        finally:app.quit()

    def test_loading_copy_only_mentions_replacement_for_switches(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.active.add('start')
            app.current = None
            app.update_controls()
            self.assertNotIn('replaced', app.hero_note.get())
            app.current = 'strata-128k'
            app.update_controls()
            self.assertIn('replaced', app.hero_note.get())
        finally:
            app.active.clear()
            app.quit()

    def test_compact_dashboard_keeps_controls_and_six_metrics_visible_without_scroll(self):
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
                    app.current = 'strata-128k'
                    app.status.set('Running: Strata')
                    app.update_controls()
                    app.performance.update({'last_speed': 42.5, 'last_prefill': 1200,
                                            'ttft_ms': 850, 'running': 1, 'queued': 2,
                                            'hardware': {'gpu_mem_used': 12 * 2**30, 'gpu_mem_total': 24 * 2**30,
                                                         'ram_used': 16 * 2**30, 'ram_total': 64 * 2**30,
                                                         'ram_free_gib': 48}})
                    app.window.update()
                    self.assertLessEqual(app.window.winfo_height(), round(610 * scale))
                    top = app.dashboard_canvas.winfo_rooty()
                    bottom = top + app.dashboard_canvas.winfo_height()
                    readings = list(app.performance.metric_widgets.values())
                    self.assertEqual(len(readings), 6)
                    content=app.dashboard_canvas.winfo_children()[0]
                    fits=content.winfo_reqheight()<=app.dashboard_canvas.winfo_height()
                    for control in (app.picker, app.start_button, app.stop_button,
                                    app.auto_control, app.performance.graph,
                                    app.performance.details_button, *app.performance.plots.values(), app.performance.context_graph, *readings):
                        self.assertTrue(control.winfo_ismapped())
                        if fits:
                            self.assertGreaterEqual(control.winfo_rooty(), top)
                            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), bottom)
                    if fits:self.assertEqual(app.dashboard_canvas.yview(), (0.0, 1.0))
                    else:
                        self.assertLess(app.dashboard_canvas.yview()[1],1)
                        app.dashboard_canvas.yview_moveto(1);app.window.update()
                        self.assertLessEqual(app.performance.details_button.winfo_rooty()+app.performance.details_button.winfo_height(),bottom)
                        app.dashboard_canvas.yview_moveto(0)
                    app.status.set('Action failed: Free GPU memory and try loading this model again.')
                    app.update_controls()
                    app.performance.update({'hardware': {'ram_free_gib': 2, 'commit_free_gib': 3}})
                    app.window.update()
                    if content.winfo_reqheight()<=app.dashboard_canvas.winfo_height():
                        self.assertEqual(app.dashboard_canvas.yview(), (0.0, 1.0))
                    else:
                        app.dashboard_canvas.yview_moveto(1);app.window.update()
                        self.assertLessEqual(app.performance.details_button.winfo_rooty()+app.performance.details_button.winfo_height(),bottom)
                finally:
                    app.quit()

    def test_details_grow_window_and_restore_geometry(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.window.update()
            before = app.window.geometry()
            height = app.window.winfo_height()
            app.performance.toggle_details()
            app.window.update()
            if app.window.winfo_height()>height:self.assertEqual(app.dashboard_canvas.yview(), (0.0, 1.0))
            else:
                # A screen already at its native height limit must stay accessible.
                self.assertLess(app.dashboard_canvas.yview()[1],1)
                app.dashboard_canvas.yview_moveto(1);app.window.update()
            self.assertFalse(hasattr(app.performance, 'detail_canvas'))
            self.assertEqual(len(app.performance.details), 18)
            bottom = app.dashboard_canvas.winfo_rooty()+app.dashboard_canvas.winfo_height()
            for row in app.performance.technical_body.winfo_children():
                if row.winfo_ismapped():self.assertLessEqual(row.winfo_rooty()+row.winfo_height(), bottom)
            app.performance.toggle_details()
            app.window.update()
            self.assertEqual(app.window.geometry(), before)
        finally:
            app.quit()

    def test_timing_trends_record_requests_once_and_reset(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            panel = app.performance
            sample = dict(identity='one', last_at=10, last_prefill=0, ttft_ms=None)
            panel.update(sample);panel.update(sample)
            self.assertEqual(list(panel.request_history), [(0, None)])
            panel.update(dict(sample, last_at=11, last_prefill=1200, ttft_ms=850))
            self.assertEqual(panel.prompt_trend.points, [0, 1200])
            self.assertEqual(panel.token_trend.points, [None, 850])
            panel.update(dict(identity='two'))
            self.assertEqual(list(panel.request_history), [])
        finally:
            app.quit()

    def test_routine_status_is_hidden_but_game_and_errors_are_visible(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.status.set('Waiting for request');app.update_controls();app.window.update()
            self.assertFalse(app.attention_row.winfo_ismapped())
            app.auto_status.set('Auto reload blocked: game.exe');app.update_controls();app.window.update()
            self.assertTrue(app.attention_row.winfo_ismapped())
            self.assertIn('game.exe', app.hero_note.get())
            app.auto_status.set('');app.status.set('Action failed: Not enough GPU memory')
            app.update_controls();app.window.update()
            self.assertTrue(app.attention_row.winfo_ismapped())
            self.assertIn('GPU memory', app.hero_note.get())
        finally:
            app.quit()

    def test_restore_selector_persists_shared_choice(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.delay_var.set('5 min')
            with patch.object(launcher.IDLE_SETTINGS, 'update') as save:
                app.set_restore_delay()
                save.assert_called_once_with(idle_minutes=5)
            self.assertEqual(tuple(app.delay_picker.cget('values')), ('5 min','10 min','15 min','20 min','25 min','30 min'))
        finally:
            app.quit()

    def test_popup_scroll_and_mixed_dpi_buttons_keep_requested_width(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            real_size = launcher.popup_size
            with patch.object(launcher, 'popup_size', side_effect=lambda work, scale, content: real_size(work, 1, content)):
                app.show_popup(anchor=(100, 100))
            app.window.update()
            self.assertGreaterEqual(app.popup_start.winfo_width(), app.popup_start.winfo_reqwidth())
            self.assertGreaterEqual(app.popup_stop.winfo_width(), app.popup_stop.winfo_reqwidth())
            if not app.popup_scroll.winfo_ismapped():
                app.popup.geometry(f'{app.popup.winfo_width()}x250')
                app.popup_scroll.pack(side='right', fill='y')
                app.window.update()
            app.popup_canvas.yview_moveto(0)
            before = app.popup_canvas.yview()[0]
            app.popup_content.winfo_children()[0].event_generate('<MouseWheel>', delta=-120)
            app.window.update()
            self.assertGreater(app.popup_canvas.yview()[0], before)
            app.popup_canvas.yview_moveto(0)
            app.popup_content.winfo_children()[-1].event_generate('<FocusIn>')
            app.window.update()
            self.assertGreater(app.popup_canvas.yview()[0], 0)
        finally:
            app.quit()

    def test_narrow_popup_stacks_actions(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.show_popup(anchor=(100, 100))
            minimum = app.fit_popup_actions(320)
            app.window.update()
            self.assertLessEqual(minimum, 320)
            self.assertEqual(app.popup_start.pack_info()['side'], 'top')
            self.assertEqual(app.popup_stop.pack_info()['side'], 'top')
        finally:
            app.quit()

    def test_short_mixed_dpi_popup_keeps_scrollbar_and_actions_visible(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            with patch.object(launcher, 'popup_size', side_effect=lambda work, scale, content: (380, min(500, round(content * scale)))):
                app.show_popup(anchor=(100, 100))
            app.window.update()
            self.assertTrue(app.popup_scroll.winfo_ismapped())
            self.assertLessEqual(app.popup_canvas.winfo_width() + app.popup_scroll.winfo_width(), app.popup.winfo_width())
            self.assertGreaterEqual(app.popup_start.winfo_width(), app.popup_start.winfo_reqwidth())
            self.assertGreaterEqual(app.popup_stop.winfo_width(), app.popup_stop.winfo_reqwidth())
        finally:
            app.quit()

    def test_gpu_memory_meter_is_visible_inside_its_card(self):
        app = launcher.LauncherUI(enable_tray=False, observe=False)
        try:
            app.performance.update({'hardware': {'gpu_mem_used': 12 * 2**30, 'gpu_mem_total': 24 * 2**30}})
            app.window.update()
            card = app.performance.gpu_card
            meter = app.performance.gpu_meter
            self.assertTrue(meter.winfo_ismapped())
            self.assertEqual(meter.master, card)
            self.assertGreater(meter.winfo_width(), 0)
        finally:
            app.quit()


if __name__ == '__main__':
    unittest.main()
