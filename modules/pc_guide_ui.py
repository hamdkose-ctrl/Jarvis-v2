"""Isolated desktop coach panel and click-through marker. JSON lines only on stdio."""
import ctypes
import json
import queue
import sys
import threading


def run():
    import tkinter as tk
    ctypes.windll.user32.SetProcessDPIAware()
    commands=queue.Queue()
    def read():
        try:
            for line in sys.stdin:commands.put(json.loads(line))
        except (ValueError,OSError):pass
        finally:commands.put({'action':'close'})
    threading.Thread(target=read,daemon=True).start()
    def emit(**data):
        print(json.dumps(data),flush=True)
    root=tk.Tk();root.title('Jarvis — PC Yardımı');root.attributes('-topmost',True)
    root.configure(bg='#10233b');root.resizable(False,False)
    width,height=root.winfo_screenwidth(),root.winfo_screenheight()
    root.geometry(f'380x235+{max(0,width-400)}+{max(0,height-300)}')
    text=tk.StringVar(value='Ekrana bakıyorum…')
    tk.Label(root,text='JARVIS · PC Yardımı',fg='#ffce52',bg='#10233b',font=('Arial',12,'bold')).pack(pady=(10,4))
    tk.Label(root,textvariable=text,fg='white',bg='#10233b',wraplength=355,justify='left',font=('Arial',11)).pack(fill='both',expand=True,padx=12)
    row=tk.Frame(root,bg='#10233b');row.pack(pady=8)
    for label,action in [('Yaptım / Kontrol et','check'),('Anlamadım','simpler'),('Dur','stop')]:
        tk.Button(row,text=label,command=lambda a=action:emit(event='action',action=a)).pack(side='left',padx=3)
    tk.Label(root,text='İşlemleri sen yaparsın · Ekran yalnız yardım sırasında incelenir',fg='#b7c7d8',bg='#10233b',wraplength=355,font=('Arial',8)).pack(pady=(0,8))
    root.protocol('WM_DELETE_WINDOW',lambda:emit(event='action',action='stop'))
    marker=tk.Toplevel(root);marker.overrideredirect(True);marker.attributes('-topmost',True)
    marker.configure(bg='#010203');marker.attributes('-transparentcolor','#010203')
    marker.geometry(f'{width}x{height}+0+0')
    canvas=tk.Canvas(marker,bg='#010203',highlightthickness=0);canvas.pack(fill='both',expand=True)
    marker.update_idletasks()
    from ctypes import wintypes
    user32=ctypes.windll.user32
    user32.GetParent.argtypes=[wintypes.HWND];user32.GetParent.restype=wintypes.HWND
    user32.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    user32.SetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.LONG]
    hwnd=user32.GetParent(marker.winfo_id()) or marker.winfo_id()
    style=user32.GetWindowLongW(hwnd,-20)
    # WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW.
    user32.SetWindowLongW(hwnd,-20,style|0x20|0x80000|0x8000000|0x80)
    clickthrough=bool(user32.GetWindowLongW(hwnd,-20)&0x20)
    panel=user32.GetParent(root.winfo_id()) or root.winfo_id()
    user32.SetWindowLongW(panel,-20,user32.GetWindowLongW(panel,-20)|0x8000000|0x80)
    marker.withdraw()
    root.withdraw()

    def tick():
        try:
            while True:
                item=commands.get_nowait();action=item.get('action')
                if action=='close':root.destroy();return
                if action=='hide':
                    marker.withdraw();root.withdraw();root.update_idletasks();emit(event='hidden')
                elif action=='show':
                    text.set(str(item.get('text',''))[:600]);root.deiconify()
                    canvas.delete('all');box=item.get('box')
                    if clickthrough and isinstance(box,list) and len(box)==4:
                        x1,y1,x2,y2=box[0]*width,box[1]*height,box[2]*width,box[3]*height
                        canvas.create_rectangle(x1,y1,x2,y2,outline='#ffce52',width=4)
                        marker.deiconify();root.lift()
                    else:marker.withdraw()
        except queue.Empty:pass
        root.after(50,tick)
    root.after(50,tick)
    root.mainloop()


if __name__=='__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    run()
