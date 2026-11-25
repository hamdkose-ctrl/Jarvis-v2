"""Masaüstü küçük Jarvis: durumunu animasyonla gösteren saydam masaüstü robotu.

- Durum alanına tıkla: Jarvis seni dinler (ad söylemeden).
- ⤢ düğmesi: Komut Merkezi'ni açar.  🎤 düğmesi: mikrofonu açar/kapatır.
- Sürükleyerek istediğin yere taşı (yer hatırlanır). Sağ tık: menü.
Yalnızca tkinter + Pillow kullanır (ikisi de zaten kurulu).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import functools
import queue
import time
from typing import Callable

KEY = (1, 2, 3)                      # saydam sayılacak renk (pencerenin görünmeyen kısmı)
KEY_HEX = "#010203"
COLORS = {
    "idle": "#63daf5", "listening": "#7de6ad", "thinking": "#ffcb7b", "working": "#ffcb7b",
    "speaking": "#82dfff", "muted": "#f6a696", "sleep": "#aebac5",
}
SHORT = {"idle": "Hazır", "listening": "Dinliyor…", "thinking": "Düşünüyor…", "speaking": "Konuşuyor…",
         "working": "Çalışıyor…", "muted": "Sessiz", "sleep": "Uykuda"}


@functools.lru_cache(maxsize=32)
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Widget:
    W, H = 152, 181

    def __init__(self, get_state: Callable[[], tuple[str, dict]], actions: dict[str, Callable[[], None]],
                 pos: tuple[int, int] | None = None,
                 save_pos: Callable[[int, int], None] | None = None,
                 main_open: Callable[[], bool] | None = None, visible: bool = True):
        self.get_state = get_state
        self.actions = actions
        self.pos = pos
        self.save_pos = save_pos
        self.main_open = main_open      # büyük pencere ekrandaysa küçük Jarvis saklanır
        self._shown = False
        self._last_check = 0.0
        self._main_is_open = False
        self.cmds: queue.Queue = queue.Queue()
        self.visible = visible
        self._drag = None
        self._moved = False
        self._last_key = None           # en son çizilen görüntünün anahtarı (boştayken boşuna yeniden çizmemek için)
        self._frames = {}

    # ---------------------------------------------------------------- dışarıdan (başka iş parçacığı) güvenli çağrılar
    def toggle(self) -> None:
        self.cmds.put("toggle")

    def is_visible(self) -> bool:
        return self.visible

    # ---------------------------------------------------------------- çizim
    def _render(self, state: str, flags: dict, phase: int = 0):
        """Masaüstünde saydam arka planla görünen robotu ve denetimlerini çiz."""
        from PIL import Image, ImageDraw

        scale = self.scale
        size = int(self.W * scale), int(self.H * scale)
        unit = scale * 2
        im = Image.new("RGBA", (size[0] * 2, size[1] * 2))
        draw = ImageDraw.Draw(im)
        color = COLORS.get(state, COLORS["idle"])

        def xy(*values):
            return tuple(round(value * unit) for value in values)

        def box(bounds, radius, fill, outline=None):
            draw.rounded_rectangle(xy(*bounds), radius=round(radius * unit),
                                   fill=fill, outline=outline, width=max(1, round(unit)))

        def stroke(points, fill, width=1):
            draw.line(xy(*points), fill=fill, width=max(1, round(width * unit)), joint="curve")

        def arc(bounds, start, end, fill, width=1):
            draw.arc(xy(*bounds), start, end, fill=fill, width=max(1, round(width * unit)))

        # Ayaklar ve gövde kabuğu
        box((51, 122, 69, 138), 6, "#142630", "#456171")
        box((83, 122, 101, 138), 6, "#142630", "#456171")
        box((45, 133, 70, 144), 5, "#284452", "#597981")
        box((82, 133, 107, 144), 5, "#284452", "#597981")
        stroke((51, 137, 63, 137), "#95b4bd", 1.5)
        stroke((89, 137, 101, 137), "#95b4bd", 1.5)
        box((33, 101, 52, 123), 8, "#1e3643", "#5b7a87")
        box((100, 101, 119, 123), 8, "#1e3643", "#5b7a87")
        box((45, 92, 107, 130), 17, "#203b49", "#63838f")
        box((49, 95, 103, 123), 13, "#2d4c5a")
        box((62, 102, 90, 121), 6, "#10212c", "#4d6b77")
        draw.ellipse(xy(72, 107, 80, 115), fill=color)
        stroke((56, 120, 61, 123), "#688b97")
        stroke((91, 123, 96, 120), "#688b97")

        # Kulak modülleri, mat metal kabuk ve koyu yüz ekranı
        arc((31, 12, 121, 70), 194, 346, "#172f3c", 6)
        arc((32, 13, 120, 69), 195, 345, color, 2)
        box((20, 55, 43, 91), 9, "#152a36", "#557b89")
        box((109, 55, 132, 91), 9, "#152a36", "#557b89")
        box((25, 63, 31, 82), 3, color)
        box((121, 63, 127, 82), 3, color)
        box((31, 32, 121, 102), 24, "#203845", "#668b9a")
        box((35, 35, 117, 96), 21, "#476a78")
        arc((38, 36, 73, 69), 194, 274, "#a6c2cc", 1.5)
        box((39, 42, 113, 91), 16, "#07141e", "#252f3b")
        stroke((55, 47, 97, 47), "#203645")
        stroke((60, 96, 92, 96), "#74939e")

        if state == "sleep" or phase == -1:
            for x in (58, 94):
                arc((x - 6, 64, x + 6, 72), 0, 180, color, 2)
        else:
            for x in (58, 94):
                box((x - 8, 57, x + 8, 74), 7, "#102e3d")
                box((x - 5, 59, x + 5, 72), 5, color)
                box((x - 2, 60, x + 1, 64), 2, "#ebfbff")

        if state == "speaking":
            for i, x in enumerate((66, 71, 76, 81, 86)):
                h = (2, 5, 8, 5, 2, 4, 6, 3)[(phase + i) % 8]
                box((x - 1, 81 - h / 2, x + 1, 81 + h / 2), 1, color)
        elif state in ("thinking", "working"):
            for i, x in enumerate((68, 76, 84)):
                dot = color if i == phase // 2 % 3 else "#355266"
                draw.ellipse(xy(x - 2, 80, x + 2, 84), fill=dot)
        elif state == "listening":
            arc((39, 18, 113, 69), 212 + phase * 8, 248 + phase * 8, color, 2)
            box((71, 80, 81, 84), 2, color)
        else:
            arc((68, 76, 84, 85), 12, 168, color, 2)

        # Her zeminde okunabilen kompakt durum ve düğme çubuğu
        cy = 161
        box((8, 147, 144, 175), 11, "#101e29", "#466371")
        box((11, 150, 39, 172), 8, "#223a49")
        box((113, 150, 141, 172), 8, "#223a49")
        label = SHORT.get(state, SHORT["idle"])
        draw.text(xy(76, cy), label, font=_font(round(10 * unit), True),
                  fill=color, anchor="mm")
        stroke((21, 165, 21, 156, 29, 156, 29, 165, 21, 165), "#d3e4eb", 1.4)
        stroke((24, 165, 24, 160, 29, 160), "#d3e4eb")

        mic_on = bool(flags.get("mic", True)) and not flags.get("sleep")
        ink = color if mic_on else "#8196a2"
        box((125, 154, 129, 162), 2, ink)
        arc((122, 157, 132, 165), 0, 180, ink, 1.4)
        stroke((127, 165, 127, 168), ink, 1.4)
        if not mic_on:
            stroke((121, 155, 133, 167), "#f6a696", 1.5)

        im = im.resize(size, Image.LANCZOS)
        background = Image.new("RGBA", size, KEY + (255,))
        self._hit_mask = im.getchannel("A").point(lambda value: 255 if value > 40 else 0)
        return Image.composite(Image.alpha_composite(background, im),
                               background, self._hit_mask).convert("RGB")

    @staticmethod
    def _phase(state: str, now: float) -> int:
        if state in ("thinking", "working", "listening", "speaking"):
            return int(now * 8) % 8
        return -1 if state == "idle" and now % 5 < .22 else 0

    # ---------------------------------------------------------------- olaylar
    def _hit_test(self, x: float, y: float) -> str | None:
        mask = getattr(self, "_hit_mask", None)
        if mask is None or not (0 <= x < mask.width and 0 <= y < mask.height):
            return None
        if not mask.getpixel((int(x), int(y))):
            return None
        lx, ly = x / self.scale, y / self.scale
        if 147 <= ly <= 175:
            if 8 <= lx <= 41:
                return "home"
            if 111 <= lx <= 144:
                return "mic"
        return "orb"

    def _press(self, e) -> None:
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._moved = False

    def _motion(self, e) -> None:
        if not self._drag:
            return
        dx, dy = e.x_root - self._drag[0], e.y_root - self._drag[1]
        if abs(dx) + abs(dy) > 4:
            self._moved = True
        if self._moved:
            self.root.geometry(f"+{self._drag[2] + dx}+{self._drag[3] + dy}")

    def _release(self, e) -> None:
        if self._moved:
            if self.save_pos:
                try:
                    self.save_pos(self.root.winfo_x(), self.root.winfo_y())
                except Exception:       # noqa: BLE001
                    _record_failure('modules/widget.py:_release')
                    pass
        else:
            what = self._hit_test(e.x, e.y)
            act = {"orb": "talk", "home": "open", "mic": "mic"}.get(what or "")
            if act and act in self.actions:
                self.actions[act]()
        self._drag = None

    def _menu(self, e) -> None:
        import tkinter as tk
        m = tk.Menu(self.root, tearoff=0)
        state, flags = self.get_state()
        m.add_command(label="Komut Merkezi'ni aç", command=self.actions.get("open"))
        m.add_command(label="Konuş", command=self.actions.get("talk"))
        m.add_separator()
        m.add_command(label=("Mikrofonu kapat" if flags.get("mic", True) else "Mikrofonu aç"), command=self.actions.get("mic"))
        m.add_command(label=("Uyandır" if flags.get("sleep") else "Hazırda bekle (uyku)"), command=self.actions.get("sleep"))
        m.add_separator()
        m.add_command(label="Küçük Jarvis'i gizle", command=self.toggle)
        if "quit" in self.actions:
            m.add_command(label="Jarvis'i tamamen kapat", command=self.actions["quit"])
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ---------------------------------------------------------------- döngü
    def _tick(self) -> None:
        from PIL import ImageTk
        try:
            while True:
                c = self.cmds.get_nowait()
                if c == "toggle":
                    self.visible = not self.visible
        except queue.Empty:
            pass
        now = time.monotonic()
        if self.main_open and now - self._last_check > .5:
            self._last_check = now
            try:
                self._main_is_open = bool(self.main_open())
            except Exception:       # noqa: BLE001
                _record_failure('modules/widget.py:_tick')
                self._main_is_open = False
        want = self.visible and not self._main_is_open
        if want != self._shown:
            self._shown = want
            if want:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
            else:
                self.root.withdraw()
        delay = 125
        if want:
            try:
                state, flags = self.get_state()
                phase = self._phase(state, now)
                key = (state, bool(flags.get("mic", True)), bool(flags.get("sleep")), phase)
                if key != self._last_key or self.label.image is None:
                    if self._last_key is None or key[:3] != self._last_key[:3]:
                        self._frames.clear()
                    if phase not in self._frames:
                        img = ImageTk.PhotoImage(self._render(state, flags, phase))
                        self._frames[phase] = img, self._hit_mask
                    img, self._hit_mask = self._frames[phase]
                    self.label.configure(image=img)
                    self.label.image = img
                    self._last_key = key
            except Exception:           # noqa: BLE001 - çizim hatası Jarvis'i durdurmasın
                _record_failure('modules/widget.py:_tick')
                pass
        else:
            self._last_key = None       # yeniden görünürse ilk karede çizilsin
            self._frames.clear()
            delay = 200
        self.root.after(delay, self._tick)

    def run(self) -> None:
        """Ana iş parçacığında çağrılır; pencere kapanana kadar döner."""
        import tkinter as tk
        self.root = root = tk.Tk()
        root.withdraw()
        try:
            self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.scale = 1.0
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY_HEX)
        try:
            root.attributes("-transparentcolor", KEY_HEX)
        except tk.TclError:
            pass
        w, h = int(self.W * self.scale), int(self.H * self.scale)
        if self.pos:
            x, y = self.pos
        else:
            x = root.winfo_screenwidth() - w - int(24 * self.scale)
            y = root.winfo_screenheight() - h - int(64 * self.scale)
        x = min(max(0, x), max(0, root.winfo_screenwidth() - w))
        y = min(max(0, y), max(0, root.winfo_screenheight() - h))
        root.geometry(f"{w}x{h}+{x}+{y}")
        self.label = tk.Label(root, bd=0, bg=KEY_HEX, highlightthickness=0)
        self.label.image = None
        self.label.pack()
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._motion)
        root.bind("<ButtonRelease-1>", self._release)
        root.bind("<Button-3>", self._menu)
        self._tick()
        root.mainloop()


def available() -> bool:
    try:
        import tkinter  # noqa: F401
        from PIL import ImageTk  # noqa: F401
        return True
    except Exception:       # noqa: BLE001
        _record_failure('modules/widget.py:available')
        return False
