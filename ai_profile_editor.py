"""A compact native editor for installed Strata profiles."""
import tkinter as tk
from tkinter import ttk, messagebox
from ai_branding import apply_window_icon
from ai_widgets import THEME, Button, ProfileSelect, TextField, Tooltip, scale, ui_font

class ProfileEditor:
    def __init__(self, parent, store, key, on_save, style_window, initial_page='Profile'):
        self.store=store;self.key=key;self.on_save=on_save
        values,self.snapshot=store.load(key)
        self.window=tk.Toplevel(parent);self.window.title('Edit Strata profile')
        self.window.configure(bg=THEME['bg']);self.window.transient(parent)
        self.factor=scale(parent);apply_window_icon(self.window);style_window(self.window)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda event:self.close())
        self.vars={key:tk.StringVar(self.window,value=str(value)) for key,value in values.items()}
        self.original={key:var.get() for key,var in self.vars.items()}
        self.fields={};self.field_pages={};self.error=tk.StringVar(self.window,value='')
        body=tk.Frame(self.window,bg=THEME['bg']);body.pack(fill='both',expand=True,padx=round(18*self.factor),pady=round(14*self.factor))
        tk.Label(body,text='Profile settings',bg=THEME['bg'],fg=THEME['text'],font=ui_font('heading',True),anchor='w').pack(fill='x')
        self.apply_note=tk.StringVar(self.window,value='Changes apply on the next model load.')
        tk.Label(body,textvariable=self.apply_note,bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),anchor='w').pack(fill='x',pady=(round(4*self.factor),round(12*self.factor)))
        tabs=tk.Frame(body,bg=THEME['bg']);tabs.pack(anchor='center')
        self.pages={};self.tab_buttons={}
        for index,name in enumerate(('Profile','Memory','Engine')):
            button=Button(tabs,text=name,command=lambda name=name:self.select_page(name),quiet=True)
            tabs.columnconfigure(index,weight=1,uniform='editor_tabs')
            button.grid(row=0,column=index,sticky='ew',padx=round(2*self.factor));self.tab_buttons[name]=button
        tk.Frame(body,bg=THEME['line'],height=1).pack(fill='x',pady=(round(8*self.factor),round(12*self.factor)))
        content=tk.Frame(body,bg=THEME['bg']);content.pack(fill='both',expand=True)
        for name in ('Profile','Memory','Engine'):
            self.pages[name]=tk.Frame(content,bg=THEME['bg'])
        self.pages['Profile'].columnconfigure(0,weight=1)
        self.pages['Profile'].columnconfigure(1,minsize=round(190*self.factor))
        self.field_labels={}
        self.field('Profile','name','Profile name',hint='Name shown in the model selector')
        self.field('Profile','context','Context per agent',hint='Tokens · includes prompt, reasoning and output')
        self.field('Profile','slots','Agents',choices=('1','2','3','4'),hint='Parallel requests')
        self.field('Profile','max_tokens','Maximum output',hint='Tokens · blank uses the backend default')
        self.field('Profile','effort','Reasoning effort',choices=('none','low','medium','high'))
        self.field('Profile','reasoning','Reasoning budget',hint='Tokens · 0 uses no fixed budget')
        self.field('Profile','kv','KV format',choices=tuple(dict.fromkeys(('int8','q4_0','k8v4','fp16',values['kv']))),hint='Memory / quality tradeoff')
        self.field('Memory','ple_io','Engram / PLE placement',choices=('', 'direct', 'mmap', 'ram'),
                   hint='Blank: engine default · direct / mmap: disk · ram: system RAM')
        self.field('Memory','expert_cache','GPU expert cache',hint='Slots · auto: fit · 0: off · blank: engine default')
        self.field('Memory','resident','Resident expert RAM budget',hint='GiB · greater than 0 · blank: engine default')
        self.field('Memory','reserve','VRAM reserve',hint='MiB · blank: engine default')
        self.field('Memory','kv_resident','Resident KV tokens',hint='Tokens per agent · blank: engine default')
        tk.Label(self.pages['Memory'],text='RAM placement keeps the Engram table in system memory. Strata checks load headroom.',
                 bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),anchor='w',justify='left',
                 wraplength=round(560*self.factor)).grid(row=3,column=0,columnspan=2,sticky='ew',pady=(round(8*self.factor),0))
        for key,label,hint in (
            ('prefill','Prompt batch','Positive tokens or auto'),
            ('workers','CPU workers','Threads · 0: automatic'),('spec','Draft tokens','2–8 tokens for serving'),
            ('spec_min','Draft minimum probability','0–1'),('pcie','PCIe fraction','0–1 · blank keeps the default')):
            self.field('Engine',key,label,hint=hint)
        # The footer stays outside the pages so validation and Save remain visible.
        tk.Label(body,textvariable=self.error,bg=THEME['bg'],fg=THEME['error'],font=ui_font('caption'),
                 wraplength=round(560*self.factor),anchor='w',justify='left').pack(fill='x',pady=(round(8*self.factor),round(4*self.factor)))
        footer=tk.Frame(body,bg=THEME['bg']);footer.pack(fill='x')
        self.save_button=Button(footer,text='Save for next load',primary=True,command=self.save);self.save_button.pack(side='right')
        Button(footer,text='Cancel',command=self.close,quiet=True).pack(side='right',padx=(0,round(8*self.factor)))
        self.select_page('Profile')
        self.window.update_idletasks()
        # Reserve enough height for either tab; selecting Engine never resizes the dialog.
        height=max(page.winfo_reqheight() for page in self.pages.values())+body.winfo_reqheight()-self.pages['Profile'].winfo_reqheight()+round(36*self.factor)
        width=round(620*self.factor)
        self.window.geometry(f'{width}x{height}')
        self.window.resizable(True,False);self.window.minsize(round(520*self.factor),height)
        self.window.update_idletasks()
        x=parent.winfo_rootx()+(parent.winfo_width()-width)//2;y=parent.winfo_rooty()+round(32*self.factor)
        self.window.geometry(f'+{max(0,x)}+{max(0,min(y,parent.winfo_screenheight()-height-60))}')
        self.select_page(initial_page if initial_page in self.pages else 'Profile')
        style_window(self.window);self.window.lift()
        self.fields['ple_io' if self.page=='Memory' else 'prefill' if self.page=='Engine' else 'name'].focus_set()

    def field(self,page,key,label,choices=None,hint=''):
        frame=self.pages[page]
        index=sum(field==page for field in self.field_pages.values())
        self.field_pages[key]=page
        if page!='Profile':
            line=tk.Frame(frame,bg=THEME['bg'])
            half_gap=round(8*self.factor)
            line.grid(row=index//2,column=index%2,sticky='nsew',padx=(0,half_gap) if index%2==0 else (half_gap,0),pady=round(6*self.factor))
            frame.columnconfigure(index%2,weight=1,uniform='engine')
        else:
            line=frame
            frame.rowconfigure(index,minsize=round(44*self.factor),uniform='profile-rows')
        labels=tk.Frame(line,bg=THEME['bg']);self.field_labels[key]=labels
        if page!='Profile':labels.pack(fill='x')
        else:labels.grid(row=index,column=0,sticky='w',padx=(0,round(16*self.factor)),pady=round(4*self.factor))
        tk.Label(labels,text=label,bg=THEME['bg'],fg=THEME['text'],font=ui_font('body'),anchor='w').pack(fill='x')
        tk.Label(labels,text=hint,bg=THEME['bg'],fg=THEME['muted'],font=ui_font('caption'),anchor='w',justify='left',
                 height=2 if page!='Profile' else 1,
                 wraplength=round(260*self.factor) if page!='Profile' else 0).pack(fill='x')
        if choices:
            field=ProfileSelect(line,textvariable=self.vars[key],values=choices,state='readonly',width=16)
        else:
            field=TextField(line,textvariable=self.vars[key],width=16)
        if page!='Profile':field.pack(fill='x',pady=(round(5*self.factor),0))
        else:field.grid(row=index,column=1,sticky='ew',pady=round(4*self.factor))
        help_text={
            'name':self.vars[key],
            'context':'Larger windows can require more memory.',
            'max_tokens':'Includes reasoning; capped by remaining context.',
            'reasoning':'Counts toward Maximum output.',
            'expert_cache':'Auto fits experts within available VRAM.',
            'reserve':'Higher values leave less room for cached experts.'
        }.get(key)
        if help_text is not None:Tooltip(field,help_text)
        self.fields[key]=field

    def select_page(self,name):
        self.apply_note.set('Save, then load this profile to apply profile changes.' if name=='Profile' else 'Changes apply on the next model load.')
        for key,page in self.pages.items():
            page.pack_forget()
            self.tab_buttons[key].set_selected(key==name)
        self.pages[name].pack(fill='both',expand=True)
        self.page=name

    def save(self):
        if all(var.get()==self.original[key] for key,var in self.vars.items()):
            self.window.destroy();return
        try:
            values={key:var.get() for key,var in self.vars.items()}
            self.store.prepare(self.snapshot,values)
            self.on_save(self.key,values,self.snapshot)
        except (ValueError,OSError,RuntimeError,KeyError) as exc:
            self.error.set(str(exc));return
        self.window.destroy()

    def close(self):
        if any(var.get()!=self.original[key] for key,var in self.vars.items()):
            if not messagebox.askyesno('Discard changes?','Close without saving this profile?',parent=self.window):return
        self.window.destroy()
