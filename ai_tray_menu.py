"""Valet's compact context menu; constructed only after a user tray click."""
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, font as tkfont
from ai_widgets import Button, Tooltip, THEME, ui_font, scale, monitor_work_area


@dataclass
class MenuItem:
    label: str
    command: object = None
    enabled: object = True
    checked: object = False
    children: object = None
    tooltip: str = ''
    close_on_activate: bool = True

    def available(self):
        return bool(self.enabled() if callable(self.enabled) else self.enabled)

    def selected(self):
        return bool(self.checked() if callable(self.checked) else self.checked)


def menu_bounds(anchor, size, work, margin=8):
    left, top, right, bottom = work
    margin = min(margin, max(0, (right-left-1)//2), max(0, (bottom-top-1)//2))
    width = min(size[0], max(1, right-left-2*margin))
    height = min(size[1], max(1, bottom-top-2*margin))
    return (width, height, max(left+margin, min(anchor[0]-width, right-margin-width)),
            max(top+margin, min(anchor[1]-height, bottom-margin-height)))


def anchor_work_area(anchor, owner):
    import ctypes
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    user = ctypes.windll.user32
    user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user.MonitorFromPoint.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
    info = Info();info.size = ctypes.sizeof(info)
    monitor = user.MonitorFromPoint(wintypes.POINT(*anchor), 2)
    if user.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
        return info.work.left, info.work.top, info.work.right, info.work.bottom
    return monitor_work_area(owner)


class TrayContextMenu:
    def __init__(self, owner, items):
        self.items = items;self.factor = scale(owner);self.rows = [];self.buttons = []
        self.pending = None;self.anchor = (0, 0);self.page = False
        self.window = tk.Toplevel(owner);self.window.withdraw()
        self.window.overrideredirect(True);self.window.attributes('-topmost', True)
        self.window.configure(bg=THEME['line'])
        self.viewport = tk.Frame(self.window, bg=THEME['bg'])
        self.viewport.pack(fill='both', expand=True, padx=1, pady=1)
        self.scrollbar = ttk.Scrollbar(self.viewport, orient='vertical')
        self.canvas = tk.Canvas(self.viewport, bg=THEME['bg'], bd=0, highlightthickness=0,
                                yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.configure(command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=THEME['bg'], padx=round(8*self.factor), pady=round(8*self.factor))
        self.body_id = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.canvas.bind('<Configure>', lambda event:self.canvas.itemconfigure(self.body_id, width=event.width))
        self.body.bind('<Configure>', lambda event:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        for key, delta in (('<Up>', -1), ('<Down>', 1), ('<Tab>', 1), ('<Shift-Tab>', -1)):
            self.window.bind(key, lambda event,d=delta:self.move(d))
        self.window.bind('<Home>', lambda event:self.edge(False))
        self.window.bind('<End>', lambda event:self.edge(True))
        self.window.bind('<Escape>', lambda event:self.hide())
        self.window.bind('<Left>', lambda event:self.back() if self.page else 'break')
        self.window.bind('<Right>', self.open_focused)
        self.window.bind('<FocusOut>', self.defer_dismiss)
        self.window.bind('<MouseWheel>', self.scroll)

    def show(self, anchor):
        self.anchor = anchor;self.render(self.items())
        self.window.deiconify();self.window.lift();self.edge(False)

    def render(self, items, page=False):
        for child in self.body.winfo_children():child.destroy()
        self.rows = [];self.buttons = [];self.page = page
        if page:items = [MenuItem('‹ Back', self.back, close_on_activate=False), None, *items]
        for item in items:
            if item is None:
                tk.Frame(self.body, bg=THEME['line'], height=1).pack(fill='x', pady=round(4*self.factor))
                continue
            button = Button(self.body, text=item.label, command=lambda row=item:self.invoke(row), quiet=True)
            button.pack(fill='x', pady=round(2*self.factor))
            if item.tooltip:Tooltip(button, item.tooltip)
            self.rows.append(item);self.buttons.append(button)
        self.canvas.yview_moveto(0);self.refresh(fit=False);self.fit()

    def refresh(self, fit=True):
        for item, button in zip(self.rows, self.buttons):
            label = ('✓  ' if item.selected() else '') + item.label + ('  ›' if item.children is not None else '')
            button.configure(text=label, state='normal' if item.available() else 'disabled')
            button.set_selected(item.selected())
        if fit:self.fit()

    def fit(self):
        self.window.update_idletasks()
        work = anchor_work_area(self.anchor, self.window)
        width = min(round(360*self.factor), max(round(220*self.factor), self.body.winfo_reqwidth()+2))
        width, height, x, y = menu_bounds(self.anchor, (width, self.body.winfo_reqheight()+2), work)
        overflow = self.body.winfo_reqheight()+2 > height
        if overflow:self.scrollbar.pack(side='right', fill='y')
        else:self.scrollbar.pack_forget()
        self.window.geometry(f'{width}x{height}+{x}+{y}')
        self.window.update_idletasks()
        # Ellipsize long profile names; the full name remains in its tooltip.
        font = tkfont.Font(root=self.window, font=ui_font())
        available = max(1, width-round(48*self.factor)-(self.scrollbar.winfo_reqwidth() if overflow else 0))
        for item, button in zip(self.rows, self.buttons):
            label = button.cget('text')
            full = label
            while len(label)>1 and font.measure(label)>available:label = label[:-2]+'…'
            button.configure(text=label)
            if label!=full and not hasattr(button,'tooltip'):Tooltip(button, item.label)

    def invoke(self, item):
        if not item.available():return 'break'
        if item.children is not None:
            self.render(item.children(), page=True);self.edge(False)
        else:
            if item.close_on_activate:self.hide()
            if item.command:item.command()
        return 'break'

    def back(self):
        self.render(self.items());self.edge(False);return 'break'

    def open_focused(self, event=None):
        focus = self.window.focus_get()
        for item, button in zip(self.rows, self.buttons):
            if button == focus and item.children is not None:return self.invoke(item)
        return 'break'

    def focus(self, button):
        button.focus_force();self.window.update_idletasks()
        top = button.winfo_y();bottom = top+button.winfo_height()
        visible_top = self.canvas.canvasy(0);height = self.canvas.winfo_height()
        target = top if top<visible_top else bottom-height if bottom>visible_top+height else visible_top
        extent = max(1, self.body.winfo_height())
        self.canvas.yview_moveto(max(0, target)/extent)
        return 'break'

    def move(self, delta):
        enabled = [button for button in self.buttons if button.cget('state')!='disabled']
        if enabled:
            focus = self.window.focus_get()
            index = enabled.index(focus) if focus in enabled else (-1 if delta>0 else 0)
            self.focus(enabled[(index+delta)%len(enabled)])
        return 'break'

    def edge(self, last):
        enabled = [button for button in self.buttons if button.cget('state')!='disabled']
        if enabled:self.focus(enabled[-1] if last else enabled[0])
        return 'break'

    def scroll(self, event):
        self.canvas.yview_scroll(-1 if event.delta>0 else 1, 'units');return 'break'

    def defer_dismiss(self, event=None):
        if self.window.state()=='withdrawn':return
        if self.pending:self.window.after_cancel(self.pending)
        self.pending = self.window.after(100, self.dismiss_outside)

    def dismiss_outside(self):
        self.pending = None
        focus = self.window.focus_displayof()
        if focus is None or focus.winfo_toplevel()!=self.window:self.hide()

    def hide(self):
        if self.pending:self.window.after_cancel(self.pending);self.pending = None
        for button in self.buttons:
            if hasattr(button,'tooltip'):button.tooltip.hide()
        self.window.withdraw();return 'break'
