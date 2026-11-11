"""Copyable profile ID and masked API credentials, separate from telemetry."""
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
    def __init__(self,parent,key_provider,model_provider=lambda:None,loaded_provider=lambda:None):
        super().__init__(parent,bg=THEME['bg'])
        self.key_provider=key_provider;self.revealed=False;factor=scale(self)
        self.model_provider=model_provider;self.loaded_provider=loaded_provider;self.model_state=None
        tk.Label(self,text='Model ID',bg=THEME['bg'],fg=THEME['text'],font=ui_font(bold=True)).pack(anchor='w')
        model_row=tk.Frame(self,bg=THEME['bg']);model_row.pack(fill='x',pady=(round(8*factor),0))
        model_row.columnconfigure(0,weight=1)
        self.model_id=tk.StringVar();self.model_note=tk.StringVar()
        self.model_field=TextField(model_row,textvariable=self.model_id,state='readonly',width=12)
        self.model_field.grid(row=0,column=0,sticky='ew')
        self.model_copy_button=Button(model_row,text='Copy',command=self.copy_model)
        self.model_copy_button.grid(row=0,column=1,padx=(round(8*factor),0))
        Tooltip(self.model_copy_button,'Copy the selected Valet profile ID for the request model')
        self.model_helper=tk.Label(self,textvariable=self.model_note,bg=THEME['bg'],fg=THEME['muted'],
                                   font=ui_font('caption'),anchor='w',justify='left',wraplength=400)
        self.model_helper.pack(fill='x',pady=(round(8*factor),round(16*factor)))
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
        self.bind('<Configure>',self.resize_helpers)
        self.field.bind('<Unmap>',lambda event:self.mask())
        self.bind('<Map>',self.refresh)
        self.refresh()
    def mask(self):
        self.revealed=False;self.field.configure(show='\u2022');self.eye.configure(text='     Show')
    def destroy(self):
        self.model_provider=lambda:None;self.loaded_provider=lambda:None
        super().destroy()
    def refresh(self,event=None):
        self.refresh_model()
        self.mask();self.value.set(self.key_provider())
        state='normal' if self.value.get() else 'disabled'
        self.eye.configure(state=state);self.copy_button.configure(state=state)
        self.note.set('Configured in Valet. Client services can use this token.' if self.value.get() else 'No API token configured in Valet. Set strata_api_key or STRATA_API_KEY, then restart Valet.')
    def resize_helpers(self,event):
        for helper in (self.helper,self.model_helper):helper.configure(wraplength=max(100,event.width))
    def refresh_model(self):
        selected=self.model_provider() or '';loaded=self.loaded_provider() or ''
        state=(selected,loaded)
        if state==self.model_state:return
        self.model_state=state;self.model_id.set(selected)
        self.model_copy_button.configure(state='normal' if selected else 'disabled')
        if not selected:note='Choose a profile to copy its model ID.'
        elif loaded==selected:note='Selected profile is loaded. Use this ID as model in Valet API requests.'
        elif loaded:note='Selected profile. Loaded profile: '+loaded+'. Requests using this ID switch profiles.'
        else:note='Selected profile. Use this ID as model in Valet API requests.'
        self.model_note.set(note)
    def copy_model(self):
        self.refresh_model()
        if not self.model_id.get():return
        try:
            self.clipboard_clear();self.clipboard_append(self.model_id.get())
            self.model_note.set('Model ID copied. '+self.model_note.get().removeprefix('Model ID copied. '))
        except tk.TclError:self.model_note.set('Clipboard unavailable. Try Copy again.')
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
