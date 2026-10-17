import pathlib
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_telemetry import PerformancePanel


class OptionalMetricTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = PerformancePanel(self.root)
        self.panel.pack(fill='both', expand=True)

    def tearDown(self):
        self.root.destroy()

    def test_first_token_starts_hidden_without_reserved_row_or_note(self):
        group = self.panel.first_token_group
        self.assertEqual(group.winfo_manager(), '')
        self.assertNotIn(group, group.master.pack_slaves())
        self.panel.update({'last_speed': 150, 'last_at': 100, 'hardware': {}})
        self.assertEqual(group.winfo_manager(), '')
        self.assertEqual(self.panel.first_token_note.get(), '')

    def test_real_backend_timing_appears_and_disappears_when_unavailable(self):
        group = self.panel.first_token_group
        self.panel.update({'ttft_ms': 850, 'last_at': 100, 'hardware': {}})
        self.root.update_idletasks()
        self.assertEqual(group.winfo_manager(), 'pack')
        self.assertEqual(self.panel.first_token.get(), '850 ms')
        self.assertIn('Last request', self.panel.first_token_note.get())
        visible_children = group.master.pack_slaves()
        self.panel.update({'ttft_ms': 900, 'hardware': {}})
        self.root.update_idletasks()
        self.assertEqual(group.master.pack_slaves(), visible_children)
        self.panel.update({'ttft_ms': None, 'hardware': {}})
        self.root.update_idletasks()
        self.assertEqual(group.winfo_manager(), '')
        self.assertNotIn(group, group.master.pack_slaves())
        self.assertEqual(group.master.pack_slaves(), [child for child in visible_children if child != group])

    def test_invalid_backend_timings_stay_hidden(self):
        for value in (None, True, False, -1, float('nan'), float('inf'), '850'):
            with self.subTest(value=value):
                self.panel.update({'ttft_ms': value, 'hardware': {}})
                self.assertEqual(self.panel.first_token_group.winfo_manager(), '')
                self.assertEqual(self.panel.first_token.get(), '—')
                self.assertEqual(self.panel.first_token_note.get(), '')
        self.panel.update({'ttft_ms': 0, 'hardware': {}})
        self.assertEqual(self.panel.first_token_group.winfo_manager(), 'pack')
        self.assertEqual(self.panel.first_token.get(), '0 ms')


if __name__ == '__main__':
    unittest.main()
