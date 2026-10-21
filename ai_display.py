"""Read effective Windows DPI and keep client geometry inside a display's work area."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Display:
    dpi: int
    work: tuple
    chrome: tuple = (0, 40)

    @property
    def scale(self):
        return self.dpi / 96


def read_display(window, anchor=None):
    """Query the current display, not Tk's cached startup scaling."""
    import ctypes
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    try:
        user = ctypes.windll.user32
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user.MonitorFromPoint.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
        user.GetDpiForWindow.argtypes = [wintypes.HWND]
        user.GetDpiForWindow.restype = wintypes.UINT
        hwnd = user.GetAncestor(window.winfo_id(), 2)
        user.IsWindowEnabled.argtypes = [wintypes.HWND]
        user.IsWindowEnabled.restype = wintypes.BOOL
        if not user.IsWindowEnabled(hwnd):
            return None # A native modal dialog is still using this view.
        monitor = (user.MonitorFromPoint(wintypes.POINT(*anchor), 2) if anchor is not None
                   else user.MonitorFromWindow(hwnd, 2))
        info = Info(); info.size = ctypes.sizeof(info)
        if not monitor or not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        if anchor is None:
            dpi = user.GetDpiForWindow(hwnd)
        else:
            x = wintypes.UINT(); y = wintypes.UINT()
            get_dpi = ctypes.windll.shcore.GetDpiForMonitor
            get_dpi.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
            if get_dpi(monitor, 0, ctypes.byref(x), ctypes.byref(y)) != 0:
                return None
            dpi = x.value
        if not 48 <= dpi <= 768:
            return None
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        outer = wintypes.RECT(); client = wintypes.RECT()
        chrome = (0, 40)
        if user.GetWindowRect(hwnd, ctypes.byref(outer)) and user.GetClientRect(hwnd, ctypes.byref(client)):
            chrome = (max(0, outer.right-outer.left-client.right),
                      max(0, outer.bottom-outer.top-client.bottom))
        return Display(dpi, (info.work.left, info.work.top, info.work.right, info.work.bottom), chrome)
    except (AttributeError, OSError):
        return None


def fit_geometry(size, position, work, scale, chrome=(0, 40)):
    left, top, right, bottom = work
    margin = min(round(16*scale), max(0, (right-left-1)//2), max(0, (bottom-top-1)//2))
    width = max(1, min(round(size[0]), right-left-2*margin-chrome[0]))
    height = max(1, min(round(size[1]), bottom-top-2*margin-chrome[1]))
    x = max(left+margin, min(round(position[0]), right-margin-width-chrome[0]))
    y = max(top+margin, min(round(position[1]), bottom-margin-height-chrome[1]))
    # Tk's bare -N means an offset from the right/bottom edge. +-N is an
    # absolute negative desktop coordinate, needed for left/upper monitors.
    return f'{width}x{height}+{x}+{y}'


def rescale_geometry(geometry, ratio, display):
    match = re.fullmatch(r'(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)', geometry)
    if match is None or not math.isfinite(ratio) or ratio <= 0:
        return geometry
    width, height = map(int, match.groups()[:2])
    x, y = (int(value[1:] if value.startswith('+') else value) for value in match.groups()[2:])
    return fit_geometry((width*ratio, height*ratio), (x, y), display.work, display.scale, display.chrome)


def destroy_view(widget):
    """Cancel callbacks owned by a retired view, including delayed tooltip/layout work."""
    commands = set()
    def visit(child):
        commands.update(child._tclCommands or ())
        if hasattr(child, 'tooltip'):
            child.tooltip.hide()
        for item in child.winfo_children():
            visit(item)
    visit(widget)
    for timer in widget.tk.call('after', 'info'):
        script = widget.tk.call('after', 'info', timer)[0]
        parts = widget.tk.splitlist(script)
        if parts and parts[0] in commands:
            widget.after_cancel(timer)
    widget.destroy()


def refresh_fonts(window):
    """Replace Tk 8.6's cached anonymous fonts with fresh, interpreter-owned fonts."""
    from tkinter import Canvas, ttk, font as tkfont
    from ai_theme import ui_font
    fonts = {}
    def fresh(spec):
        key = str(spec)
        if key not in fonts:
            fonts[key] = tkfont.Font(root=window, font=spec)
        return fonts[key]
    def visit(widget):
        if 'font' in widget.keys():
            font = fresh(widget.cget('font'))
            widget.configure(font=font)
            if 'style' in widget.keys() and widget.cget('style'):
                ttk.Style(widget).configure(widget.cget('style'), font=font)
            if hasattr(widget, '_popup'):
                widget.tk.call(widget._popup+'.f.l', 'configure', '-font', font)
            if hasattr(widget, '_paint'):
                widget._appearance = None
                widget._paint()
        if isinstance(widget, ttk.Notebook) and widget.cget('style') == 'Valet.TNotebook':
            ttk.Style(widget).configure('Valet.TNotebook.Tab', font=fresh(ui_font('caption')))
        if isinstance(widget, ttk.Treeview):
            name = widget.cget('style')
            if name:
                ttk.Style(widget).configure(name, font=fresh(ui_font('caption')))
                ttk.Style(widget).configure(name+'.Heading', font=fresh(ui_font('caption')))
            for tag in widget.tk.call(widget._w, 'tag', 'names'):
                spec = widget.tag_configure(tag, 'font')
                if spec:
                    widget.tag_configure(tag, font=fresh(spec))
        if isinstance(widget, Canvas):
            for item in widget.find_all():
                if widget.type(item) == 'text':
                    widget.itemconfigure(item, font=fresh(widget.itemcget(item, 'font')))
        for child in widget.winfo_children():
            visit(child)
    visit(window)
    # Keep Font objects alive until the next rebuilt view has released them.
    return fonts
