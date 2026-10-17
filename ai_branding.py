"""The folded-V identity, shared by Windows, the tray, and documentation."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw
from ai_theme import THEME

BACKGROUND = THEME['bg']
ACCENT = THEME['accent']
INK = THEME['text']
APP_ID = 'Household.InferenceValet.Desktop'
ASSETS = Path(__file__).parent / 'docs' / 'assets'
MASTERS = ASSETS / 'brand-held-token-20261017'
ICON_MASTER = MASTERS / 'inference-valet-app-icon.png'
LOGO_MASTER = MASTERS / 'inference-valet-logo-dark.png'
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def set_app_identity():
    """Keep Windows taskbar grouping separate from the hosting Python process."""
    import ctypes
    shell = ctypes.windll.shell32
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    if shell.SetCurrentProcessExplicitAppUserModelID(APP_ID) < 0:
        raise OSError('Cannot register Inference Valet app identity')


def _ribbon(draw, commands, fill, scale):
    """Flatten broad cubic paths at supersampled resolution for tiny tray sizes."""
    points = []
    current = None
    for command in commands:
        if command[0] == 'M' or command[0] == 'L':
            current = command[1:]
            points.append(current)
        else:
            x0, y0 = current
            x1, y1, x2, y2, x3, y3 = command[1:]
            for step in range(1, 25):
                t = step / 24
                u = 1 - t
                points.append((u**3*x0 + 3*u*u*t*x1 + 3*u*t*t*x2 + t**3*x3,
                               u**3*y0 + 3*u*u*t*y1 + 3*u*t*t*y2 + t**3*y3))
            current = (x3, y3)
    scaled = [(round(x*scale), round(y*scale)) for x, y in points]
    draw.polygon(scaled, fill=fill)
    # A thin aubergine edge holds the parchment shape on pale taskbars.
    draw.line(scaled + scaled[:1], fill=BACKGROUND, width=scale, joint='curve')


def icon_image(size=64, tray=False):
    """Use the approved app artwork; adapt its folded ribbons for tiny tray slots."""
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError('Icon size must be a positive integer')
    if not tray:
        with Image.open(ICON_MASTER) as master:
            return master.convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)
    scale = 8
    image = Image.new('RGBA', (96*scale, 96*scale))
    draw = ImageDraw.Draw(image)
    _ribbon(draw, [('M', 47, 58), ('L', 60, 51),
        ('C', 64, 47, 66, 35, 70, 31), ('C', 72, 28, 79, 27, 86, 24),
        ('C', 92, 21, 92, 26, 90, 31), ('L', 76, 69),
        ('C', 75, 73, 72, 76, 69, 78), ('L', 53, 86)], INK, scale)
    _ribbon(draw, [('M', 47, 58), ('L', 62, 54), ('L', 73, 69),
        ('C', 76, 73, 74, 77, 69, 80), ('L', 53, 86)], '#EBD3B1', scale)
    _ribbon(draw, [('M', 12, 16), ('L', 29, 16),
        ('C', 33, 16, 35, 17, 37, 22), ('L', 48, 49),
        ('C', 50, 54, 53, 56, 57, 59), ('L', 72, 69),
        ('C', 78, 73, 76, 77, 71, 81), ('L', 59, 89),
        ('C', 56, 91, 53, 91, 50, 89), ('L', 29, 73),
        ('C', 25, 70, 23, 67, 21, 63), ('L', 6, 25),
        ('C', 4, 20, 7, 16, 12, 16)], ACCENT, scale)
    draw.rounded_rectangle((44*scale, 34*scale, 65*scale, 43*scale),
        radius=4*scale, fill=INK, outline=BACKGROUND, width=scale)
    # Broad, slightly enlarged geometry leaves enough transparent breathing room.
    return image.resize((size, size), Image.Resampling.LANCZOS)


def apply_window_icon(window):
    """Retain Tk image references for title/taskbar icons for the window lifetime."""
    from PIL import ImageTk
    icons = [ImageTk.PhotoImage(icon_image(size), master=window)
             for size in (16, 32, 48, 64)]
    window.iconphoto(True, *icons)
    window._valet_icons = icons
    ico = ASSETS / 'inference-valet.ico'
    if ico.is_file():
        try:
            ico = taskbar_icon_path()
        except OSError:
            pass  # Keep the current icon usable when the local cache is unwritable.
        window.iconbitmap(str(ico))


def taskbar_icon_path(source=None, cache_dir=None):
    """Give Windows a new icon location whenever the artwork changes.

    Shell links and Tk use the same content-addressed local file, avoiding stale
    shell cache entries for the stable public asset path. Old files remain valid
    for pinned shortcuts until those shortcuts are refreshed.
    """
    source = Path(source) if source is not None else ASSETS / 'inference-valet.ico'
    if cache_dir is None:
        from ai_config import STATE_DIR
        cache_dir = STATE_DIR / 'icons'
    cache_dir = Path(cache_dir)
    content = source.read_bytes()
    target = cache_dir / ('inference-valet-' + hashlib.sha256(content).hexdigest() + '.ico')
    cache_dir.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_bytes() == content:
        return target
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def set_shortcut_app_id(path):
    """Stamp an existing Shell link with the same identity as the running app."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('data', ctypes.c_byte * 16)]
        def __init__(self, value):
            super().__init__()
            ctypes.memmove(ctypes.byref(self), uuid.UUID(value).bytes_le, 16)

    class PropertyKey(ctypes.Structure):
        _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]

    class CountedPointer(ctypes.Structure):
        _fields_ = [('count', wintypes.ULONG), ('pointer', ctypes.c_void_p)]

    class Value(ctypes.Union):
        _fields_ = [('string', ctypes.c_wchar_p), ('counted', CountedPointer)]

    class PropVariant(ctypes.Structure):
        _fields_ = [('vt', wintypes.WORD), ('reserved', wintypes.WORD * 3), ('value', Value)]

    def call(pointer, index, result, types, *args):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *types)(table[index])(pointer, *args)

    def check(hr):
        if hr < 0:
            raise OSError(f'Windows shortcut identity failed: 0x{hr & 0xffffffff:08x}')

    ole = ctypes.windll.ole32
    ole.CoInitialize.argtypes = [ctypes.c_void_p]
    ole.CoInitialize.restype = ctypes.c_long
    initialized = ole.CoInitialize(None)
    check(initialized)
    link = ctypes.c_void_p();persist = ctypes.c_void_p();store = ctypes.c_void_p()
    try:
        clsid = GUID('00021401-0000-0000-c000-000000000046')
        iid = GUID('000214f9-0000-0000-c000-000000000046')
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID),ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        ole.CoCreateInstance.restype = ctypes.c_long
        check(ole.CoCreateInstance(ctypes.byref(clsid),None,1,ctypes.byref(iid),ctypes.byref(link)))
        for identifier,pointer in [('0000010b-0000-0000-c000-000000000046',persist),('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99',store)]:
            interface = GUID(identifier)
            check(call(link,0,ctypes.c_long,[ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)],ctypes.byref(interface),ctypes.byref(pointer)))
        check(call(persist,5,ctypes.c_long,[ctypes.c_wchar_p,wintypes.DWORD],str(Path(path).resolve()),2))
        key = PropertyKey(GUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'),5)
        variant = PropVariant();variant.vt = 31;variant.value.string = APP_ID
        check(call(store,6,ctypes.c_long,[ctypes.POINTER(PropertyKey),ctypes.POINTER(PropVariant)],ctypes.byref(key),ctypes.byref(variant)))
        check(call(store,7,ctypes.c_long,[]))
        check(call(persist,6,ctypes.c_long,[ctypes.c_wchar_p,wintypes.BOOL],str(Path(path).resolve()),True))
    finally:
        for pointer in (store,persist,link):
            if pointer:call(pointer,2,wintypes.ULONG,[])
        ole.CoUninitialize()


def write_assets(directory):
    """Deterministically rebuild public assets without touching approved masters."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    icon_image(512).save(directory / 'icon.png')
    icon_image(256).save(directory / 'inference-valet.ico',
                         sizes=[(size, size) for size in ICO_SIZES],
                         append_images=[icon_image(size) for size in ICO_SIZES[:-1]])
    icon_image(32, tray=True).save(directory / 'tray-icon.png')
    (directory / 'logo.png').write_bytes(LOGO_MASTER.read_bytes())
    # Embed the exact approved artwork: portable SVG wrapper, no alternate mark.
    encoded = base64.b64encode(ICON_MASTER.read_bytes()).decode('ascii')
    (directory / 'icon.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        '<title>Inference Valet folded-V app icon</title>'
        '<image width="512" height="512" href="data:image/png;base64,' + encoded + '"/></svg>',
        encoding='utf-8')


if __name__ == '__main__':
    write_assets(ASSETS)
