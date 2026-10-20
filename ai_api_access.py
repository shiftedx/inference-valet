"""Compact API credential display; values never enter telemetry or status text."""
import tkinter as tk
from ai_widgets import Button,TextField,Tooltip,scale
from ai_theme import THEME,ui_font
from PIL import ImageDraw,ImageTk

class RevealButton(Button):
    """Shared button treatment with a crisp eye icon at every display scale."""
    def _paint(self):
        super()._paint()
        if getattr(self,'_eye_appearance',None)==self._appearance:return
        self._eye_appearance=self._appearance
        image=ImageTk.getimage(self.image);draw=ImageDraw.Draw(image)
        factor=self.factor;cx=round(19*factor);cy=image.height//2
        rx=round(7*factor);ry=round(4*factor);ink=self.cget('fg');width=max(1,round(factor))
        draw.line([(cx-rx,cy),(cx-round(3*factor),cy-ry),(cx+round(3*factor),cy-ry),(cx+rx,cy),(cx+round(3*factor),cy+ry),(cx-round(3*factor),cy+ry),(cx-rx,cy)],fill=ink,width=width)
        radius=max(1,round(2*factor));draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=ink)
        self.image=ImageTk.PhotoImage(image,master=self)
        self.configure(image=self.image)

class ApiAccessPanel(tk.Frame):
    def __init__(self,parent,key_provider):
        super().__init__(parent,bg=THEME['bg'])
        self.key_provider=key_provider;self.revealed=False;factor=scale(self)
        tk.Label(self,text='API token',bg=THEME['bg'],fg=THEME['text'],font=ui_font(bold=True)).pack(anchor='w')
        row=tk.Frame(self,bg=THEME['bg']);row.pack(fill='x',pady=(round(8*factor),0))
        row.columnconfigure(0,weight=1)
        self.value=tk.StringVar();self.note=tk.StringVar()
        self.field=TextField(row,textvariable=self.value,show='\u2022',state='readonly',width=12)
        self.field.grid(row=0,column=0,sticky='ew')
        self.eye=RevealButton(row,text='     Show',command=self.toggle)
        self.eye.grid(row=0,column=1,padx=(round(8*factor),0))
        self.copy_button=Button(row,text='Copy',command=self.copy)
        self.copy_button.grid(row=0,column=2,padx=(round(8*factor),0))
        Tooltip(self.eye,lambda:'Hide API token' if self.revealed else 'Show API token')
        Tooltip(self.copy_button,'Copy API token to the clipboard')
        self.helper=tk.Label(self,textvariable=self.note,bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),anchor='w',justify='left',wraplength=400)
        self.helper.pack(fill='x',pady=(round(8*factor),0))
        self.bind('<Configure>',lambda event:self.helper.configure(wraplength=max(100,event.width)))
        self.field.bind('<Unmap>',lambda event:self.mask())
        self.bind('<Map>',self.refresh)
        self.refresh()
    def mask(self):
        self.revealed=False;self.field.configure(show='\u2022');self.eye.configure(text='     Show')
    def refresh(self,event=None):
        self.mask();self.value.set(self.key_provider())
        state='normal' if self.value.get() else 'disabled'
        self.eye.configure(state=state);self.copy_button.configure(state=state)
        self.note.set('Configured in Valet. Client services can use this token.' if self.value.get() else 'No API token configured in Valet. Set strata_api_key or STRATA_API_KEY, then restart Valet.')
    def toggle(self):
        if not self.value.get():return
        self.revealed=not self.revealed
        self.field.configure(show='' if self.revealed else '\u2022')
        self.eye.configure(text='     Hide' if self.revealed else '     Show')
    def copy(self):
        if not self.value.get():return
        try:
            self.clipboard_clear();self.clipboard_append(self.value.get())
            self.note.set('API token copied to clipboard.')
        except tk.TclError:self.note.set('Clipboard unavailable. Try Copy again.')
