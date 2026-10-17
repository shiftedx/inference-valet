import gc
import pathlib
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_theme import THEME, ui_font
from ai_widgets import Button, TextField, ProfileSelect, Switch


def contrast(a, b):
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722)))
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class BrandThemeTests(unittest.TestCase):
    def tearDown(self):
        # Destroyed Tk widgets can still form Python callback/image cycles.
        # Finalize them here on the UI thread, before HTTP worker tests run.
        gc.collect()

    def test_text_and_action_contrast(self):
        for surface in ('bg', 'card', 'raised', 'selected'):
            for text in ('text', 'muted'):
                with self.subTest(surface=surface, text=text):
                    self.assertGreaterEqual(contrast(THEME[text], THEME[surface]), 4.5)
        for surface in ('primary', 'primary_hover'):
            self.assertGreaterEqual(contrast(THEME['on_primary'], THEME[surface]), 4.5)
        for surface in ('bg', 'card', 'raised'):
            self.assertGreaterEqual(contrast(THEME['focus'], THEME[surface]), 3)
        for status in ('success', 'warning', 'error', 'info'):
            self.assertGreaterEqual(contrast(THEME[status], THEME['card']), 4.5)

    def test_controls_keep_native_keyboard_and_readable_states(self):
        root = tk.Tk()
        try:
            root.configure(bg=THEME['bg'])
            button = Button(root, 'Load model', lambda: None, primary=True)
            entry = TextField(root)
            selector = ProfileSelect(root, values=['Default', 'Coding'], state='readonly')
            enabled = tk.BooleanVar(root)
            switch = Switch(root, 'Auto load', enabled, lambda: None)
            for control in (button, entry, selector, switch):
                control.pack(); root.update_idletasks()
            self.assertEqual(button.cget('fg'), THEME['on_primary'])
            self.assertEqual(switch.cget('highlightcolor'), THEME['focus'])
            self.assertEqual(button.cget('takefocus'), 1)
            button.configure(state='disabled')
            self.assertEqual(button.cget('disabledforeground'), THEME['muted'])
            self.assertGreaterEqual(button.winfo_height(), 34)
            self.assertEqual(ui_font()[0], 'Segoe UI')
        finally:
            root.destroy()

    def test_quiet_selection_survives_pointer_focus_and_disable(self):
        root = tk.Tk()
        try:
            root.configure(bg=THEME['bg'])
            actions = []
            tab = Button(root, 'Memory', lambda: actions.append('memory'), quiet=True)
            tab.pack(); root.update()
            tab.set_selected(True)
            self.assertEqual(tab._appearance[1:4], (THEME['selected'], THEME['text'], THEME['accent']))
            tab.event_generate('<Enter>'); root.update()
            self.assertEqual(tab._appearance[1], THEME['selected'])
            tab.event_generate('<FocusIn>'); root.update()
            self.assertEqual(tab._appearance[3], THEME['focus'])
            root.focus_force(); tab.focus_set(); root.update()
            tab.event_generate('<Return>'); root.update()
            self.assertEqual(actions, ['memory'])
            tab.configure(state='disabled')
            self.assertEqual(tab.cget('disabledforeground'), THEME['muted'])
            tab.configure(state='normal')
            tab.event_generate('<FocusOut>'); tab.event_generate('<Leave>'); root.update()
            self.assertEqual(tab._appearance[1:4], (THEME['selected'], THEME['text'], THEME['accent']))
            tab.set_selected(False)
            self.assertEqual(tab._appearance[1], THEME['bg'])
            primary = Button(root, 'Save', lambda: None, primary=True, selected=True)
            self.assertEqual(primary._appearance[1:3], (THEME['primary'], THEME['on_primary']))
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
