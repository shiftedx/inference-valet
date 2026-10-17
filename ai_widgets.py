"""Small, keyboard-accessible Tk surfaces shared by dashboard and tray."""
import tkinter as tk
import itertools
from tkinter import ttk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk

_FIELD_STYLES = itertools.count()

from ai_theme import THEME, FONT_SIZES, ui_font

CONTROL_HEIGHT = 34

FIELD_FONT = ui_font()


def scale(widget):
    return float(widget.tk.call('tk','scaling'))/(96/72)


def control_height(widget):
    factor=scale(widget)
    return max(round(CONTROL_HEIGHT*factor),tkfont.Font(root=widget,font=FIELD_FONT).metrics('linespace')+2*round(8*factor))


def rounded_image(widget, width, height, fill, outline, radius):
    """Antialias corners at the actual display size, without animation timers."""
    width=max(1,int(width));height=max(1,int(height));factor=3
    image=Image.new('RGB',(width*factor,height*factor),widget.master.cget('bg'))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((factor,factor,(width-1)*factor,(height-1)*factor),
                           radius=radius*factor,fill=fill,outline=outline,width=factor)
    return ImageTk.PhotoImage(image.resize((width,height),Image.Resampling.LANCZOS),master=widget)


class Surface(tk.Frame):
    def __init__(self,parent,fill=None,padding=(18,14),radius=14):
        super().__init__(parent,bg=parent.cget('bg'),bd=0)
        self.fill=fill or THEME['card'];self.radius=round(radius*scale(self))
        self.canvas=tk.Canvas(self,bg=self.cget('bg'),highlightthickness=0,bd=0)
        self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
        self.body=tk.Frame(self,bg=self.fill,bd=0)
        self.body.pack(fill='both',expand=True,padx=round(padding[0]*scale(self)),pady=round(padding[1]*scale(self)))
        self.canvas.bind('<Configure>',self._draw)
        self._size=None

    def _draw(self,event):
        size=(event.width,event.height)
        if size==self._size:return
        self._size=size
        self.image=rounded_image(self,*size,self.fill,THEME['line'],self.radius)
        self.canvas.delete('all');self.canvas.create_image(0,0,image=self.image,anchor='nw')


class Button(tk.Button):
    """Native Button semantics with a rounded, scale-aware visual treatment."""
    def __init__(self,parent,text,command,primary=False,quiet=False,selected=False):
        self.primary=primary;self.quiet=quiet;self.selected=bool(selected);self.hover=False;self.focused=False
        self.ready=False;self.factor=scale(parent);self._appearance=None
        super().__init__(parent,text=text,command=command,font=ui_font(bold=primary),
                         compound='center',bg=parent.cget('bg'),activebackground=parent.cget('bg'),
                         relief='flat',bd=0,highlightthickness=0,padx=0,pady=0,
                         cursor='hand2',takefocus=True)
        self.ready=True;self._paint()
        for event,flag,value in (('<Enter>','hover',True),('<Leave>','hover',False),
                                 ('<FocusIn>','focused',True),('<FocusOut>','focused',False)):
            self.bind(event,lambda e,f=flag,v=value:self._change(f,v),add='+')
        self.bind('<Return>',lambda event:self.invoke())
        self.bind('<Configure>',lambda event:self._paint(),add='+')

    def _change(self,flag,value):
        setattr(self,flag,value);self._paint()

    def set_selected(self,selected):
        """Keep persistent quiet-tab selection through hover and keyboard focus."""
        self.selected=bool(selected);self._paint()

    def configure(self,cnf=None,**kw):
        result=super().configure(cnf,**kw)
        if self.ready and (cnf or any(key in kw for key in ('text','state'))):self._paint()
        return result

    config=configure

    def _paint(self):
        disabled=self.cget('state')=='disabled'
        background=self.master.cget('bg')
        selected=self.selected and self.quiet and not self.primary
        if disabled:
            fill=THEME['raised'];ink=THEME['muted'];outline=THEME['line']
        elif self.primary:
            fill=THEME['primary_hover'] if self.hover else THEME['primary']
            ink=THEME['on_primary'];outline=fill
        elif selected:
            fill=THEME['selected'];ink=THEME['text']
            outline=THEME['primary_hover'] if self.hover else THEME['accent']
        else:
            fill=THEME['raised'] if self.hover or not self.quiet else background
            ink=THEME['text'];outline=fill if self.quiet else THEME['line']
        if self.focused:outline=THEME['focus']
        natural_width=tkfont.Font(font=self.cget('font')).measure(self.cget('text'))+round(30*self.factor)
        width=max(natural_width,self.winfo_width());height=control_height(self)
        appearance=(self.cget('text'),fill,ink,outline,width,height)
        if appearance==self._appearance:return
        self._appearance=appearance
        self.image=rounded_image(self,width,height,fill,outline,round(8*self.factor))
        super().configure(image=self.image,width=natural_width,height=height,fg=ink,activeforeground=ink,disabledforeground=ink)


class TextField(ttk.Entry):
    """Inset text editing with the same rounded surface as profile selectors."""
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        factor=scale(self);style=ttk.Style(self);name='ValetEntry'+str(next(_FIELD_STYLES))
        self._images=[rounded_image(self,round(40*factor),control_height(self),THEME['card'],color,round(8*factor))
                      for color in (THEME['line'],THEME['focus'])]
        style.element_create(name+'.field','image',self._images[0],('focus',self._images[1]),
                             border=round(8*factor),sticky='nsew')
        style.layout(name+'.TEntry',[(name+'.field',{'sticky':'nsew','children':[
            ('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})]})])
        style.configure(name+'.TEntry',padding=(round(4*factor),0,round(4*factor),0),
                        foreground=THEME['text'],fieldbackground=THEME['card'],insertcolor=THEME['text'],
                        selectbackground=THEME['selected'],selectforeground=THEME['text'],font=FIELD_FONT)
        style.map(name+'.TEntry',foreground=[('disabled',THEME['muted'])],
                  selectbackground=[('!disabled',THEME['selected'])],
                  selectforeground=[('!disabled',THEME['text'])])
        self.configure(style=name+'.TEntry',font=FIELD_FONT)

class Switch(tk.Checkbutton):
    """A native checkbutton with a clear on/off switch and keyboard support."""
    def __init__(self,parent,text,variable,command):
        factor=scale(parent);images=[]
        for on in (False,True):
            image=Image.new('RGB',(round(52*factor*3),round(24*factor*3)),parent.cget('bg'))
            draw=ImageDraw.Draw(image);unit=factor*3
            box=lambda coords:tuple(round(value*unit) for value in coords)
            draw.rounded_rectangle(box((0,2,38,22)),radius=10*unit,
                                   fill=THEME['accent'] if on else THEME['line'])
            draw.ellipse(box((20 if on else 3,5,35 if on else 18,20)),
                         fill=THEME['on_accent'] if on else THEME['muted'])
            images.append(ImageTk.PhotoImage(image.resize((round(52*factor),round(24*factor)),Image.Resampling.LANCZOS),master=parent))
        self.images=images
        super().__init__(parent,text=text,variable=variable,command=command,image=images[0],selectimage=images[1],
                         indicatoron=False,compound='left',bg=parent.cget('bg'),fg=THEME['text'],
                         activebackground=parent.cget('bg'),activeforeground=THEME['text'],
                         selectcolor=parent.cget('bg'),font=ui_font(),
                         bd=0,relief='flat',offrelief='flat',padx=0,pady=0,
                         highlightthickness=1,highlightbackground=parent.cget('bg'),
                         highlightcolor=THEME['focus'],cursor='hand2',takefocus=True)
        self.bind('<Return>',lambda event:self.invoke())


class ProfileSelect(ttk.Combobox):
    """Rounded field and generous menu, retaining native combobox interaction."""
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        factor=scale(self);style=ttk.Style(self)
        name='ValetSelect'+str(next(_FIELD_STYLES))
        self._images=[]
        for fill,outline in ((THEME['card'],THEME['line']),
                             (THEME['card'],THEME['muted']),
                             (THEME['card'],THEME['focus']),
                             (THEME['bg'],THEME['line'])):
            self._images.append(rounded_image(self,round(36*factor),control_height(self),fill,outline,round(8*factor)))
        arrows=[]
        for disabled in (False,True):
            image=Image.new('RGB',(round(26*factor*3),round(16*factor*3)),THEME['bg'] if disabled else THEME['card'])
            draw=ImageDraw.Draw(image)
            draw.line(tuple((round(x*factor*3),round(y*factor*3)) for x,y in ((7,6),(12,11),(17,6))),
                      fill=THEME['muted'] if disabled else THEME['text'],width=max(2,round(1.4*factor*3)),joint='curve')
            arrows.append(ImageTk.PhotoImage(image.resize((round(26*factor),round(16*factor)),Image.Resampling.LANCZOS),master=self))
        self._images.extend(arrows)
        style.element_create(name+'.field','image',self._images[0],
                             ('disabled',self._images[3]),('focus',self._images[2]),('active',self._images[1]),
                             border=round(8*factor),sticky='nsew')
        style.element_create(name+'.downarrow','image',arrows[0],('disabled',arrows[1]),sticky='')
        style.layout(name+'.TCombobox',[(name+'.field',{'sticky':'nsew','children':[
            (name+'.downarrow',{'side':'right','sticky':'ns'}),
            ('Combobox.padding',{'sticky':'nsew','expand':True,'children':[
                ('Combobox.textarea',{'sticky':'nsew'})]})]})])
        style.configure(name+'.TCombobox',padding=(round(4*factor),0,0,0),
                        foreground=THEME['text'],fieldbackground=THEME['card'],font=FIELD_FONT)
        style.map(name+'.TCombobox',foreground=[('disabled',THEME['muted']),('readonly',THEME['text'])],
                  fieldbackground=[('disabled',THEME['bg']),('readonly',THEME['card'])],
                  selectbackground=[('readonly',THEME['selected'])],selectforeground=[('readonly',THEME['text'])])
        self.configure(style=name+'.TCombobox',cursor='hand2',font=FIELD_FONT)
        self.bind('<Return>',self._open,add='+')
        self.bind('<Enter>',lambda event:self.state(['active']),add='+')
        self.bind('<Leave>',lambda event:self.state(['!active']),add='+')
        # Configure the native popdown once; its placement, grab, scrolling and
        # keyboard selection remain managed by Tk across display scales.
        popup=self.tk.call('ttk::combobox::PopdownWindow',self._w)
        style.configure('Valet.Popdown.TFrame',background=THEME['card'],relief='flat',borderwidth=0)
        self.tk.call(popup+'.f','configure','-style','Valet.Popdown.TFrame')
        self.tk.call(popup+'.f.l','configure','-font',FIELD_FONT,'-background',THEME['card'],
                     '-foreground',THEME['text'],'-selectbackground',THEME['selected'],
                     '-selectforeground',THEME['text'],'-activestyle','none',
                     '-selectborderwidth',0,'-borderwidth',round(11*factor),'-relief','flat','-highlightthickness',0)
        # Tk recalculates grid padding when posting. Use the listbox's own flat
        # inset so alignment survives mouse and keyboard opens and scrollbars.
        self.tk.call('grid','configure',popup+'.f.l','-pady',0)
        self._popup=popup;self._popup_size=None;self._factor=factor
        round_command=self.register(self._round_popup)
        for event in ('<Map>','<Configure>'):
            self.tk.call('bind',popup,event,'+'+round_command)

    def _open(self,event=None):
        if not self.instate(['disabled']):self.tk.call('ttk::combobox::Post',self._w)
        return 'break'

    def _round_popup(self):
        """Clip native menu corners on Windows 10/11 without replacing its grab."""
        import ctypes
        from ctypes import wintypes
        width=int(self.tk.call('winfo','width',self._popup))
        height=int(self.tk.call('winfo','height',self._popup))
        if width<=1 or height<=1 or (width,height)==self._popup_size:return
        user=ctypes.windll.user32;gdi=ctypes.windll.gdi32
        user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
        handle=int(str(self.tk.call('winfo','id',self._popup)),0)
        handle=user.GetParent(handle) or handle
        gdi.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6;gdi.CreateRoundRectRgn.restype=wintypes.HRGN
        user.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HRGN,wintypes.BOOL]
        region=gdi.CreateRoundRectRgn(0,0,width+1,height+1,round(16*self._factor),round(16*self._factor))
        if not user.SetWindowRgn(handle,region,True):
            gdi.DeleteObject.argtypes=[wintypes.HANDLE];gdi.DeleteObject(region)
            raise OSError('Cannot round the profile menu')
        # Windows owns the region after SetWindowRgn succeeds.
        self._popup_size=(width,height)
