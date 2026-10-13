"""User-selected desktop screenshot; the selector runs outside the widget's Tk thread."""
from pathlib import Path
import io
import subprocess
import sys
import tempfile
import threading
import uuid
import base64

_LOCK = threading.Lock()


def selection_box(start, end, size):
    x1, x2 = sorted((max(0, min(size[0], int(start[0]))), max(0, min(size[0], int(end[0])))))
    y1, y2 = sorted((max(0, min(size[1], int(start[1]))), max(0, min(size[1], int(end[1])))))
    return (x1, y1, x2, y2) if x2 - x1 >= 3 and y2 - y1 >= 3 else None


def _select_region(destination):
    if sys.platform.startswith('win'):
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    import tkinter as tk
    from PIL import ImageGrab, ImageTk
    image = ImageGrab.grab()  # primary screen; taken before the selector exists
    root = tk.Tk()
    chosen = []
    try:
        root.attributes('-fullscreen', True)
        root.attributes('-topmost', True)
        root.title('Jarvis — Alan seç; Esc ile iptal')
        canvas = tk.Canvas(root, highlightthickness=0, cursor='crosshair')
        canvas.pack(fill='both', expand=True)
        photo = ImageTk.PhotoImage(image, master=root)
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.create_text(20, 20, text='Alanı sürükleyerek seç · Esc: iptal', anchor='nw', fill='white', font=('Arial', 16), tags='hint')
        start = []
        rectangle = [None]

        def begin(event):
            start[:] = [event.x, event.y]
            if rectangle[0] is not None:
                canvas.delete(rectangle[0])
            rectangle[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#ffce52', width=3)

        def move(event):
            if start:
                canvas.coords(rectangle[0], *start, event.x, event.y)

        def finish(event):
            if not start:
                return
            box = selection_box(start, (event.x, event.y), image.size)
            if box:
                chosen.append(box)
                root.quit()

        canvas.bind('<ButtonPress-1>', begin)
        canvas.bind('<B1-Motion>', move)
        canvas.bind('<ButtonRelease-1>', finish)
        root.bind('<Escape>', lambda event: root.quit())
        root.protocol('WM_DELETE_WINDOW', root.quit)
        root.after(110_000, root.quit)
        root.after(100, root.focus_force)
        root.mainloop()
    finally:
        root.destroy()
    if not chosen:
        return False
    image.crop(chosen[0]).save(destination, 'PNG')
    return True


def capture(runtime):
    if not runtime.sys.platform.startswith('win'):
        raise ValueError('Alan seçimi Windows masaüstü uygulamasında kullanılabilir.')
    if not _LOCK.acquire(blocking=False):
        raise ValueError('Ekran seçimi zaten açık.')
    hidden = False
    try:
        hidden = runtime._win_action('hide')
        if not hidden:
            raise ValueError('Jarvis penceresi gizlenemedi; ekran görüntüsü alınmadı.')
        runtime.time.sleep(0.25)
        with tempfile.TemporaryDirectory(prefix='jarvis-screen-') as folder:
            destination = Path(folder) / 'selection.png'
            try:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--select', str(destination)],
                                        capture_output=True, timeout=120,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Alan seçimi zaman aşımına uğradı; tekrar deneyebilirsin.') from exc
            if result.returncode == 2:
                return {'cancelled': True}
            if result.returncode or not destination.is_file():
                raise ValueError('Ekran seçimi tamamlanamadı; Jarvis geri açıldı.')
            from PIL import Image
            from modules import nxapi
            with Image.open(destination) as original:
                image = original.convert('RGB')
                image.thumbnail((1200, 800))
                stream = io.BytesIO()
                image.save(stream, 'PNG')
            saved = nxapi.save_upload('ekran-' + uuid.uuid4().hex[:12] + '.png', destination.read_bytes())
            return {'path': str(saved), 'name': saved.name,
                    'preview': 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()}
    finally:
        try:
            if hidden:
                runtime._win_action('show')
        finally:
            _LOCK.release()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--select':
        raise SystemExit(1)
    raise SystemExit(0 if _select_region(sys.argv[2]) else 2)
