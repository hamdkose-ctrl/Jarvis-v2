"""Masaüstü küçük Jarvis: sağ altta her zaman üstte duran, konuşma ve mikrofon düğmelerini gösteren ince şerit.

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
    "idle": "#f39b78", "listening": "#a5cbb3", "thinking": "#f5c995",
    "speaking": "#a7c6d8", "muted": "#b1bec5", "sleep": "#b1bec5",
}
SHORT = {"idle": "Hazır", "listening": "Dinliyor…", "thinking": "Düşünüyor…", "speaking": "Konuşuyor…",
         "muted": "Mikrofon kapalı", "sleep": "Uykuda"}   # şeritteki kısa durum yazısı


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
    W, H = 210, 46                   # mantıksal boyut (ekran ölçeğiyle çarpılır): ince şerit

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

    # ---------------------------------------------------------------- dışarıdan (başka iş parçacığı) güvenli çağrılar
    def toggle(self) -> None:
        self.cmds.put("toggle")

    def is_visible(self) -> bool:
        return self.visible

    # ---------------------------------------------------------------- çizim
    def _render(self, state: str, flags: dict):
        """Masaüstü çalışma alanının küçük denetimlerini çiz."""
        from PIL import Image, ImageDraw
        s, k = self.scale, 2
        W, H = int(self.W * s), int(self.H * s)
        im = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        u = s * k
        color = COLORS.get(state, COLORS["idle"])

        x0, y0, x1, y1 = 2 * u, 2 * u, (self.W - 2) * u, (self.H - 2) * u
        d.rounded_rectangle((x0, y0, x1, y1), radius=int(12 * u),
                            fill="#101e29", outline="#354a56", width=max(1, int(u)))
        cx, cy, radius = x0 + 20 * u, (y0 + y1) / 2, 14 * u
        d.rounded_rectangle((cx - radius, cy - radius, cx + radius, cy + radius),
                            radius=int(7 * u), fill=color)
        for offset, height in ((-5, 7), (0, 13), (5, 9)):
            x = cx + offset * u
            half = height * u / 2
            d.rounded_rectangle((x - u, cy - half, x + u, cy + half), radius=int(u), fill="#101e29")

        # durum yazısı (sığmazsa küçülür)
        txt = SHORT.get(state, SHORT["idle"])
        tx, room = cx + radius + 8 * u, (x1 - 66 * u) - (cx + radius + 8 * u)
        size = 13
        f = _font(int(size * u), True)
        while size > 9 and d.textlength(txt, font=f) > room:
            size -= 1
            f = _font(int(size * u), True)
        d.text((tx, cy), txt, font=f, fill="#f8f8f4", anchor="lm")

        # Komut Merkezi ve mikrofon
        bs = 13 * u                                        # yarı boy
        hx, hy = x1 - 50 * u, cy
        d.rounded_rectangle((hx - bs, hy - bs, hx + bs, hy + bs), radius=int(5 * u), fill="#243744")
        hc, hw = "#e5ecef", max(1, int(1.6 * u))
        d.line((hx - 6.5 * u, hy - .5 * u, hx, hy - 6.5 * u, hx + 6.5 * u, hy - .5 * u), fill=hc, width=hw, joint="curve")   # çatı
        d.line((hx - 4.5 * u, hy - 2 * u, hx - 4.5 * u, hy + 6 * u, hx + 4.5 * u, hy + 6 * u, hx + 4.5 * u, hy - 2 * u),
               fill=hc, width=hw, joint="curve")                                                                   # duvarlar
        d.rectangle((hx - 1.4 * u, hy + 1.5 * u, hx + 1.4 * u, hy + 6 * u), fill=hc)                               # kapı

        mx, my = x1 - 20 * u, cy
        mic_on = bool(flags.get("mic", True)) and not flags.get("sleep")
        d.rounded_rectangle((mx - bs, my - bs, mx + bs, my + bs), radius=int(5 * u),
                            fill=color if mic_on else "#243744")
        mc = "#101e29" if mic_on else "#e5ecef"
        d.rounded_rectangle((mx - 3 * u, my - 7 * u, mx + 3 * u, my + 2 * u), radius=int(3 * u), fill=mc)
        d.arc((mx - 6 * u, my - 5 * u, mx + 6 * u, my + 5 * u), 0, 180, fill=mc, width=max(1, int(1.5 * u)))
        d.line((mx, my + 5 * u, mx, my + 8 * u), fill=mc, width=max(1, int(1.5 * u)))
        if not mic_on:
            d.line((mx - 7 * u, my - 7 * u, mx + 7 * u, my + 7 * u), fill="#f39b78", width=max(2, int(2 * u)))

        # Tıklama alanları gerçek pencere pikselinde ve görsel düğmeden biraz büyük tutulur.
        # Özellikle Windows %125/%150 DPI'da küçük mikrofonun tıklaması eskiden şeridin
        # "konuş" alanına düşebiliyordu.
        pad = 5 * s
        self._hit_rect = {
            "mic": ((mx - bs) / k - pad, (my - bs) / k - pad, (mx + bs) / k + pad, (my + bs) / k + pad),
            "home": ((hx - bs) / k - pad, (hy - bs) / k - pad, (hx + bs) / k + pad, (hy + bs) / k + pad),
        }
        self._hit = {"orb": (0, 0, W)}

        im = im.resize((W, H), Image.LANCZOS)
        bg = Image.new("RGBA", im.size, KEY + (255,))
        out = Image.alpha_composite(bg, im)
        # Pencerenin saydam renk anahtarını yuvarlak köşelerde koru.
        a = im.split()[3].point(lambda v: 255 if v > 40 else 0)
        out = Image.composite(out, bg, a)
        return out.convert("RGB")

    # ---------------------------------------------------------------- olaylar
    def _hit_test(self, x: float, y: float) -> str | None:
        """Önce geniş düğme kutuları, sonra şeridin geri kalanı (konuş)."""
        rects = getattr(self, "_hit_rect", {})
        for name in ("mic", "home"):
            r = rects.get(name)
            if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return name
        return "orb" if getattr(self, "_hit", {}) else None

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
        now = time.time()
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
                key = (state, bool(flags.get("mic", True)), bool(flags.get("sleep")))
                if key != self._last_key or self.label.image is None:
                    img = ImageTk.PhotoImage(self._render(state, flags))
                    self.label.configure(image=img)
                    self.label.image = img
                    self._last_key = key
            except Exception:           # noqa: BLE001 - çizim hatası Jarvis'i durdurmasın
                _record_failure('modules/widget.py:_tick')
                pass
        else:
            self._last_key = None       # yeniden görünürse ilk karede çizilsin
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
        x = min(max(0, x), root.winfo_screenwidth() - 60)
        y = min(max(0, y), root.winfo_screenheight() - 60)
        root.geometry(f"{w}x{h}+{x}+{y}")
        self.label = tk.Label(root, bd=0, bg=KEY_HEX, highlightthickness=0)
        self.label.image = None
        self.label.pack()
        for wdg in (root, self.label):
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._motion)
            wdg.bind("<ButtonRelease-1>", self._release)
            wdg.bind("<Button-3>", self._menu)
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
