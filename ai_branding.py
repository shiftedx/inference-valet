"""Inference Valet's returning-key mark, shared by Windows and documentation."""
from pathlib import Path
from PIL import Image, ImageDraw

BACKGROUND = '#17191d'
ACCENT = '#a9caff'
INK = '#f4f6fa'
APP_ID = 'Household.InferenceValet.Desktop'


def set_app_identity():
    """Keep Windows taskbar grouping separate from the hosting Python process."""
    import ctypes
    shell = ctypes.windll.shell32
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    if shell.SetCurrentProcessExplicitAppUserModelID(APP_ID) < 0:
        raise OSError('Cannot register Inference Valet app identity')


def icon_image(size=64, tray=False):
    """Render a crisp mark at its actual display size; tray icons stay transparent."""
    scale = 4
    image = Image.new('RGBA', (96 * scale, 96 * scale))
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(round(value * scale) for value in values)
    def line(points, fill=INK, width=8):
        draw.line(box(points), fill=fill, width=width * scale, joint='curve')
    if not tray:
        draw.rounded_rectangle(box((3, 3, 93, 93)), radius=22 * scale,
                               fill=BACKGROUND, outline='#363a43', width=scale)
        draw.arc(box((14, 14, 82, 82)), start=184, end=333,
                 fill=ACCENT, width=5 * scale)
        draw.polygon(box((81, 40, 69, 34, 80, 27)), fill=ACCENT)
    # A generous bow and two short teeth survive the 16-pixel Windows tray.
    draw.ellipse(box((22, 28, 46, 52)), outline=INK, width=7 * scale)
    line((43, 49, 67, 73))
    line((54, 60, 61, 53))
    line((63, 69, 70, 62))
    if tray:
        image = image.crop(box((12, 20, 80, 88)))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def apply_window_icon(window):
    """Retain Tk image references for title/taskbar icons for the window lifetime."""
    from PIL import ImageTk
    icons = [ImageTk.PhotoImage(icon_image(size), master=window)
             for size in (16, 32, 48, 64)]
    window.iconphoto(True, *icons)
    window._valet_icons = icons
    ico = Path(__file__).parent / 'docs' / 'assets' / 'inference-valet.ico'
    if ico.is_file():
        window.iconbitmap(str(ico))


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
    """Rebuild checked-in assets from the same geometry used by the tray."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    icon_image(96).save(directory / 'icon.png')
    icon_image(256).save(directory / 'inference-valet.ico',
                         sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
    icon_image(32, tray=True).save(directory / 'tray-icon.png')
    (directory / 'icon.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">'
        '<rect x="3" y="3" width="90" height="90" rx="22" fill="#17191d" stroke="#363a43"/>'
        '<path d="M14.2 43.3A34 34 0 0 1 78.3 32.6" fill="none" stroke="#a9caff" stroke-width="5"/>'
        '<path d="M81 40L69 34L80 27Z" fill="#a9caff"/>'
        '<g fill="none" stroke="#f4f6fa" stroke-width="8" stroke-linejoin="round">'
        '<circle cx="34" cy="40" r="12" stroke-width="7"/>'
        '<path d="M43 49L67 73M54 60L61 53M63 69L70 62"/></g></svg>', encoding='utf-8')


if __name__ == '__main__':
    write_assets(Path(__file__).parent / 'docs' / 'assets')
