"""The public assets and Windows renderers share the approved folded-V identity."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from PIL import Image
import ai_branding as branding
from ai_theme import THEME


class BrandingTests(unittest.TestCase):
    def test_app_identity_and_palette_are_shared(self):
        self.assertEqual(branding.APP_ID, 'Household.InferenceValet.Desktop')
        self.assertEqual((branding.BACKGROUND, branding.ACCENT, branding.INK),
                         (THEME['bg'], THEME['accent'], THEME['text']))

    def test_app_render_uses_approved_master_at_every_window_size(self):
        with Image.open(branding.ICON_MASTER) as master:
            for size in (16, 24, 32, 48, 64, 128, 256, 512):
                with self.subTest(size=size):
                    expected = master.convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)
                    actual = branding.icon_image(size)
                    self.assertEqual(actual.size, (size, size))
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertLessEqual(actual.getpixel((0, 0))[3], 2)

    def test_tray_keeps_transparency_and_both_ribbons_at_small_sizes(self):
        for size in (16, 24, 32, 64):
            with self.subTest(size=size):
                mark = branding.icon_image(size, tray=True)
                self.assertEqual(mark.mode, 'RGBA')
                self.assertEqual(mark.size, (size, size))
                self.assertEqual(mark.getpixel((0, 0))[3], 0)
                pixels = [mark.getpixel((x, y)) for y in range(size) for x in range(size)]
                self.assertTrue(any(r > 180 and 60 < g < 180 and b < 150 and a > 180
                                    for r, g, b, a in pixels))
                self.assertTrue(any(r > 210 and g > 200 and b > 170 and a > 180
                                    for r, g, b, a in pixels))
                self.assertGreater(sum(a > 0 for *_, a in pixels), size*size*.15)
                self.assertLess(sum(a > 0 for *_, a in pixels), size*size*.8)

    def test_checked_assets_match_deterministic_generator_and_preserve_masters(self):
        masters = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (branding.ICON_MASTER, branding.LOGO_MASTER)}
        with tempfile.TemporaryDirectory() as temporary:
            branding.write_assets(temporary)
            root = Path(temporary)
            for name in ('icon.png', 'tray-icon.png', 'inference-valet.ico', 'icon.svg', 'logo.png'):
                with self.subTest(name=name):
                    self.assertEqual((root/name).read_bytes(), (branding.ASSETS/name).read_bytes())
            with Image.open(root/'inference-valet.ico') as ico:
                self.assertEqual(ico.ico.sizes(), {(n, n) for n in branding.ICO_SIZES})
                for size in branding.ICO_SIZES:
                    frame = ico.ico.getimage((size, size))
                    self.assertEqual(frame.mode, 'RGBA')
                    self.assertEqual(frame.tobytes(), branding.icon_image(size).tobytes())
            with Image.open(root/'tray-icon.png') as tray:
                self.assertEqual(tray.tobytes(), branding.icon_image(32, tray=True).tobytes())
            self.assertEqual((root/'logo.png').read_bytes(), branding.LOGO_MASTER.read_bytes())
            branding.write_assets(temporary)
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['icon.png', 'icon.svg', 'inference-valet.ico', 'logo.png', 'tray-icon.png'])
        self.assertEqual(masters, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in masters})

    def test_invalid_render_sizes_fail_clearly(self):
        for size in (0, -1, 1.5, True):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    branding.icon_image(size)


if __name__ == '__main__':
    unittest.main()
