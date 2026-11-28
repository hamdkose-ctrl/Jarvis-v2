"""Primary Windows desktop mascot, using the existing Tk and WebP surfaces.

The mascot owns only presentation and input. Voice and job state come from
the current runtime. The tray and console use the same process and bridge.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import queue
import random
import sys
import threading
import time
from pathlib import Path

BASE_SIZE = (160, 206)          # mevcut webui kliplerinin kare boyutu
GREETING_SECS = 2.4             # açılışta bir kez selamlama; boştaysa
MAX_SCALE = 3.0
FPS = 30
KEY_HEX = "#010203"             # saydam sayılacak renk
KEY_RGB = (1, 2, 3)
ASSET_DIR = Path(__file__).resolve().parent.parent / "webui" / "mascot"
EXTRA_CLIPS = {"breathing": "nefes.webp", "looking": "bakis.webp",
               "happy": "memnun.webp", "talking": "konusma.webp"}
EXTRA_FPS = 8
CLIPS = {
    "idle": "bosta",
    "listening": "dinleme",
    "thinking": "dusunme",
    "working": "calisma",
    "speaking": "mutlu",
    "greeting": "selamlama",
}
STATES = tuple(CLIPS)
_STATE_POLL_MS = 120
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000


def clip_name(state: str) -> str:
    """Webui durum adını klip dosyasına eşler; bilinmeyen durum boşta sayılır."""
    name = str(state or "idle").strip().lower()
    return CLIPS.get(name, CLIPS["idle"])


def state_key(state: str) -> str:
    """preload() sözlüğünün anahtarı: bilinen durum adı, bilinmeyen boşta."""
    name = str(state or "idle").strip().lower()
    return name if name in CLIPS else "idle"


def frames_for(frames, state: str) -> list:
    """Bir durumun kareleri. preload() durum adıyla anahtarlar, klip adıyla değil."""
    frames = frames or {}
    return frames.get(state_key(state)) or frames.get("idle") or []


def display_state(state, flags=None) -> str:
    """Motor durumunu maskotun anlayacağı altı ada indirger (ikinci kaynak yok)."""
    flags = flags or {}
    if flags.get("sleep"):
        return "idle"
    name = str(state or "idle").strip().lower()
    return name if name in STATES else "idle"


def greeting_state(wanted: str, until: float, now: float) -> str:
    """Açılışta kısa selamlama. Yalnız boştayken; süre dolunca istenen duruma döner."""
    if wanted != "idle":
        return wanted
    if until and now < until:
        return "greeting"
    return wanted


def dpi_scale(ppi) -> float:
    """96 DPI = 1.0; 1.0–3.0 aralığına kelepçelenir."""
    try:
        value = float(ppi) / 96.0
    except (TypeError, ValueError):
        return 1.0
    return max(1.0, min(MAX_SCALE, round(value, 2)))


def window_size(scale: float, base=BASE_SIZE) -> tuple[int, int]:
    """Mantıksal kare boyutunu DPI ölçeğinde piksele çevirir."""
    value = max(1.0, min(MAX_SCALE, float(scale)))
    return (max(1, int(round(base[0] * value))), max(1, int(round(base[1] * value))))


def normalize_monitors(monitors) -> list[tuple[int, int, int, int]]:
    """(sol, üst, sağ, alt) dikdörtgenlerini doğrular; bozukları atar."""
    out: list[tuple[int, int, int, int]] = []
    for item in monitors or []:
        try:
            left, top, right, bottom = (int(v) for v in item)
        except (TypeError, ValueError):
            continue
        if right > left and bottom > top:
            out.append((left, top, right, bottom))
    return out


def _distance(rect, x, y, w, h) -> float:
    left, top, right, bottom = rect
    return (x + w / 2 - (left + right) / 2) ** 2 + (y + h / 2 - (top + bottom) / 2) ** 2


def clamp_position(x, y, w, h, monitors) -> tuple[int, int]:
    """Pencereyi en çok örtüştüğü (yoksa en yakın) monitörün içine tamamen alır."""
    rects = normalize_monitors(monitors)
    if not rects:
        return int(x), int(y)
    x, y, w, h = int(x), int(y), max(1, int(w)), max(1, int(h))
    best = None
    best_area = -1
    best_distance = None
    for rect in rects:
        left, top, right, bottom = rect
        overlap = max(0, min(x + w, right) - max(x, left)) * max(0, min(y + h, bottom) - max(y, top))
        distance = _distance(rect, x, y, w, h)
        if overlap > best_area or (overlap == best_area and (best_distance is None or distance < best_distance)):
            best, best_area, best_distance = rect, overlap, distance
    left, top, right, bottom = best
    return (min(max(x, left), max(left, right - w)),
            min(max(y, top), max(top, bottom - h)))


def reset_position(w, h, monitors, margin=24) -> tuple[int, int]:
    """Ana monitörün sağ alt köşesi (görev çubuğundan uzak)."""
    rects = normalize_monitors(monitors)
    if not rects:
        return 0, 0
    left, top, right, bottom = rects[0]
    return (max(left, right - w - margin), max(top, bottom - h - margin))


def restore_size(saved, scale: float) -> tuple[int, int]:
    """Kayıtlı boyutu yalnız makul ve en-boy oranına yakınsa kullan."""
    base = window_size(scale)
    try:
        width, height = int(saved[0]), int(saved[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return base
    if not (80 <= width <= 1200 and 80 <= height <= 1600):
        return base
    if abs(width / height - base[0] / base[1]) > 0.08:
        return base
    return width, height


def click_through_wanted(setting, state: str) -> bool:
    """Tıklama geçişi yalnız ayar açıkken ve maske boştayken istenir."""
    return bool(setting) and str(state or "").strip().lower() == "idle"


def click_style(style: int, enabled: bool) -> int:
    """Boştayken tıklamayı geçiren uzatılmış pencere stili (saf bit mantığı)."""
    if enabled:
        return int(style) | WS_EX_LAYERED | WS_EX_TRANSPARENT
    return int(style) & ~WS_EX_TRANSPARENT


def key_flat(image, size):
    """RGBA kareyi KEY/RGB düzlemine indirger; alfa eşiği dışında karıştırmaz.

    `alpha==0` tam `KEY_RGB` olur; `alpha>0` pikselin kaynak RGB'si aynen
    korunur. Böylece yarı saydam kenar KEY rengine karışıp siyah kontur
    üretmez. Dönen görüntü RGB'dir (Tk renk anahtarı alfayı kullanmaz).
    """
    from PIL import Image

    width, height = max(1, int(size[0])), max(1, int(size[1]))
    source = image.convert("RGBA")
    if source.size != (width, height):
        source = source.resize((width, height), Image.LANCZOS)
    mask = source.getchannel("A").point(lambda alpha: 255 if alpha else 0)
    background = Image.new("RGB", (width, height), KEY_RGB)
    return Image.composite(source.convert("RGB"), background, mask)


def load_frames(path) -> list:
    """Bir WebP/GIF klibinin tüm karelerini RGBA olarak okur."""
    from PIL import Image, ImageSequence

    frames = []
    with Image.open(path) as image:
        for frame in ImageSequence.Iterator(image):
            frames.append(frame.convert("RGBA").copy())
    return frames


def preload(directory=None) -> dict:
    """Tüm durum kliplerini bir kez okur; aynı dosya paylaşılır (bellek)."""
    root = Path(directory) if directory is not None else ASSET_DIR
    loaded: dict[str, list] = {}
    for name in sorted(set(CLIPS.values())):
        path = root / f"{name}.webp"
        if not path.exists():
            continue
        try:
            loaded[name] = load_frames(path)
        except Exception:       # noqa: BLE001 - bozuk kare maskotu düşürmesin
            _record_failure("modules/mascot_window.py:preload")
    return {state: loaded.get(clip, []) for state, clip in CLIPS.items()}


def frame_memory(frames) -> int:
    """RGBA karelerin yaklaşık baytı (PIL görüntü boyutundan)."""
    total = 0
    for frame in frames:
        try:
            total += int(frame.width) * int(frame.height) * 4
        except (AttributeError, TypeError, ValueError):
            continue
    return total


def photo_memory(count: int, size) -> int:
    """Bir durumun Tk fotoğrafları için üst sınır tahmini (RGBA)."""
    return max(0, int(count)) * max(1, int(size[0])) * max(1, int(size[1])) * 4


def available() -> bool:
    """Tk ve Pillow var mı (pencere açmadan)."""
    try:
        import tkinter  # noqa: F401
        from PIL import Image, ImageTk, ImageSequence  # noqa: F401
        return True
    except ImportError:
        return False


def windows_monitors(root=None) -> list[tuple[int, int, int, int]]:
    """Windows çalışma alanları; alınamazsa birincil ekran."""
    if not sys.platform.startswith("win"):
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                        ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        found: list[tuple[bool, tuple[int, int, int, int]]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                            ctypes.POINTER(RECT), wintypes.LPARAM)
        def collect(hmon, _hdc, _rect, _data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                work = info.rcWork
                found.append((bool(info.dwFlags & 1), (work.left, work.top, work.right, work.bottom)))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, collect, 0)
        if found:
            found.sort(key=lambda item: not item[0])     # ana monitör ilk sırada
            return [rect for _primary, rect in found]
    except Exception:       # noqa: BLE001
        _record_failure("modules/mascot_window.py:windows_monitors")
    if root is not None:
        try:
            return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
        except Exception:       # noqa: BLE001
            _record_failure("modules/mascot_window.py:windows_monitors_screen")
    return [(0, 0, 1920, 1080)]


def _set_window_style(window, update) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # 64 bit HWND int'e kırpılmasın: tutamaç tipleri açıkça bildirilir.
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        hwnd = user32.GetAncestor(wintypes.HWND(window.winfo_id()), 2) or window.winfo_id()  # GA_ROOT
        style = int(user32.GetWindowLongW(hwnd, -20))   # GWL_EXSTYLE
        user32.SetWindowLongW(hwnd, -20, update(style))
        return True
    except Exception:       # noqa: BLE001
        _record_failure("modules/mascot_window.py:set_window_style")
        return False


def set_click_through(window, enabled: bool) -> bool:
    return _set_window_style(window, lambda style: click_style(style, enabled))


def set_no_activate(window, enabled: bool) -> bool:
    return _set_window_style(window, lambda style: style | WS_EX_NOACTIVATE if enabled
                             else style & ~WS_EX_NOACTIVATE)


def reduce_motion() -> bool:
    if not sys.platform.startswith("win"):
        return False
    import ctypes
    from ctypes import wintypes

    enabled = wintypes.BOOL()
    return bool(ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)) and not enabled.value


class MascotWindow:
    """Tk Toplevel oynatıcı. Tüm Tk çağrıları kendi iş parçacığında kalır."""

    def __init__(self, runtime, *, base=BASE_SIZE, fps=FPS):
        self.runtime = runtime
        self.base = base
        self.fps = max(1, int(fps))
        self.root = None
        self.window = None
        self.label = None
        self.badge = None
        self.dock = None
        self.commands = queue.SimpleQueue()
        self.ready = None
        self.scale = 1.0
        self.size = base
        self._frames: dict = {}
        self._extra_frames: dict = {}
        self._photos: dict = {}
        self._state = "idle"
        self._greeting_until = 0.0
        self._frame_index = 0
        self._drag = None
        self._moved = False
        self._closed = False
        self._hidden = False
        self._next_idle = float("inf")
        self._idle_clip = None
        self._last_idle_clip = None
        self._celebrate_until = 0.0
        self._active_clip = "idle"
        self._reduced_motion = False
        self._click_through = None
        self._click_through_setting = (self._settings().get("mascot_click_through", False) is True)

    # ------------------------------------------------------------- ayarlar
    def _settings(self) -> dict:
        try:
            return dict(self.runtime.config.load_settings())
        except Exception:       # noqa: BLE001
            _record_failure("modules/mascot_window.py:_settings")
            return {}

    def _save(self, **values) -> None:
        try:
            self.runtime.config.save_settings(**values)
        except Exception:       # noqa: BLE001
            _record_failure("modules/mascot_window.py:_save")

    # ------------------------------------------------------------- açılış
    def open(self) -> bool:
        import tkinter as tk

        self._frames = preload()
        if not self._frames.get("idle") or _STOP.is_set():
            return False
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            self.scale = dpi_scale(self.root.winfo_fpixels("1i"))
        except tk.TclError:
            self.scale = 1.0
        settings = self._settings()
        self._click_through_setting = (settings.get("mascot_click_through", False) is True)
        self.size = restore_size(settings.get("mascot_size"), self.scale)
        monitors = windows_monitors(self.root)
        saved = settings.get("mascot_pos")
        try:
            pos = (int(saved[0]), int(saved[1]))
        except (TypeError, ValueError, IndexError, KeyError):
            pos = reset_position(self.size[0], self.size[1], monitors)
        pos = clamp_position(pos[0], pos[1], self.size[0], self.size[1], monitors)
        self._save(mascot_size=list(self.size), mascot_pos=list(pos))
        self.window = tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=KEY_HEX)
        try:
            self.window.attributes("-transparentcolor", KEY_HEX)
        except tk.TclError:
            pass
        self.window.geometry(f"{self.size[0]}x{self.size[1]}+{pos[0]}+{pos[1]}")
        self.label = tk.Label(self.window, bd=0, bg=KEY_HEX, highlightthickness=0)
        self.label.pack()
        self.badge = tk.Label(self.window, bg="#172634", fg="#8fe0e7", padx=8, pady=3,
                              font=("Segoe UI", 9, "bold"))
        self.badge.bind("<Button-1>", lambda _e: self.dock and self.dock.open_badge())
        set_no_activate(self.window, True)
        self._reduced_motion = reduce_motion()
        for slot, name in EXTRA_CLIPS.items():
            if self._reduced_motion and slot != "breathing":
                continue
            try:
                self._extra_frames[slot] = load_frames(ASSET_DIR / name)
            except OSError:
                _record_failure("modules/mascot_window.py:extra_clip")
        if self._extra_frames.get("breathing"):
            self._extra_frames["rest"] = self._extra_frames["breathing"][:1]
        self._hidden = settings.get("widget_on", True) is False and bool(self.runtime._tray)
        for widget in (self.window, self.label):
            widget.bind("<ButtonPress-1>", self._press)
            widget.bind("<B1-Motion>", self._motion)
            widget.bind("<ButtonRelease-1>", self._release)
            widget.bind("<Button-3>", self._menu)
        wanted = display_state(getattr(self.runtime.hub, "state", "idle"), {})
        self._greeting_until = 0 if self._reduced_motion else time.monotonic() + GREETING_SECS
        self._state = greeting_state(wanted, self._greeting_until, time.monotonic())
        self._show_clip(self._state)
        if _STOP.is_set() or not self._photos.get(self._active_clip):
            return False
        from modules.mascot_dock import MascotDock

        self.dock = MascotDock(self)
        if self._hidden:
            self.window.withdraw()
        self._apply_click_through()
        self.runtime._mascot = self
        if self.ready is not None:
            self.ready.set()
        self._next_idle = time.monotonic() + random.uniform(25, 55)
        if not self._hidden and self._state == "greeting":
            self.window.after(160, self._welcome)
        self._tick_state()
        self._tick_frame()
        self.root.mainloop()
        return True

    # ------------------------------------------------------------- oynatma
    def _welcome(self):
        if self._state == "greeting":
            self.dock.show_bubble("Merhaba, hoş geldin.", seconds=4, view=None)

    def _photo(self, frame):
        from PIL import ImageTk

        # master açıkça verilir: Tk kökü başka iş parçacığındaysa varsayılan kök yanlış yorumlayıcıya gider.
        return ImageTk.PhotoImage(key_flat(frame, self.size), master=self.window)

    def _show_clip(self, state: str) -> None:
        if state == "speaking" and self._extra_frames.get("talking"):
            state = "talking"
        elif state == "idle" and self._idle_clip is None and self._extra_frames.get("rest"):
            state = "rest"
        clip = state if state in self._extra_frames else state_key(state)
        self._active_clip = clip
        frames = self._extra_frames.get(clip) or frames_for(self._frames, state)
        if not frames:
            self.window.withdraw()
            return
        for key in list(self._photos):     # yalnız bulunulan durumun fotoğrafları
            if key != clip:
                self._photos.pop(key, None)
        if clip not in self._photos:
            try:
                selected = frames[:1] if self._reduced_motion else frames
                self._photos[clip] = [self._photo(frame) for frame in selected]
            except Exception:       # noqa: BLE001
                _record_failure("modules/mascot_window.py:_show_clip")
                self._photos[clip] = []
        self._frame_index = 0
        if not self._photos.get(clip):
            self.window.withdraw()
            return
        if not self._hidden and not self.window.winfo_viewable():
            self.window.deiconify()
        self.label.configure(image=self._photos[clip][0])

    def _tick_state(self) -> None:
        if self._closed or _STOP.is_set():
            self.close()
            return
        for _ in range(8):
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            if command == "card" and self.dock:
                self.show()
                self.dock.open(focus=True)
            elif command == "toggle":
                self.show() if self._hidden else self.hide()
            elif command == "show":
                self.show()
            elif command == "hide":
                self.hide()

        try:
            flags = dict(self.runtime.engine.flags)
            wanted = display_state(self.runtime.hub.state, flags)
            now = time.monotonic()
            if wanted != "idle":
                self._greeting_until = 0
            state = greeting_state(wanted, self._greeting_until, now)
            if state != self._state:
                self._state = state
                self._idle_clip = None
                self._next_idle = now + random.uniform(25, 55)
                self._show_clip(state)
                self._apply_click_through()
            if state == "idle" and not self._hidden and not self._reduced_motion and not flags.get("sleep"):
                if self._celebrate_until >= now and "happy" in self._extra_frames and self._idle_clip != "happy":
                    self._celebrate_until = 0
                    self._idle_clip = "happy"
                    self._show_clip("happy")
                elif self._idle_clip is None and now >= self._next_idle:
                    options = [name for name in ("breathing", "looking")
                               if self._extra_frames.get(name) and name != self._last_idle_clip]
                    if options:
                        self._idle_clip = self._last_idle_clip = random.choice(options)
                        self._show_clip(self._idle_clip)
                    self._next_idle = now + random.uniform(25, 55)
            if self.dock:
                self.dock.tick()
            if self.dock and self.dock.bubble_visible():
                self.set_badge("")
            elif flags.get("sleep"):
                self.set_badge("Uykuda")
            elif state == "listening":
                self.set_badge("Dinliyor")
            elif state in {"thinking", "working"}:
                self.set_badge("İşlem sürüyor")
            elif state == "speaking":
                self.set_badge("Konuşuyor")
            else:
                badge = self.dock.badge if self.dock else ""
                self.set_badge(badge or ("Mikrofon kapalı" if not flags.get("mic", True) else ""))
        except Exception:  # noqa: BLE001 - a stale UI event must not stop the loop
            _record_failure("modules/mascot_window.py:tick")
        self.window.after(_STATE_POLL_MS, self._tick_state)

    def _tick_frame(self) -> None:
        if self._closed:
            return
        photos = self._photos.get(self._active_clip) or []
        visible = not self._hidden and self.window.winfo_viewable()
        playing = not self._reduced_motion and visible and bool(photos) and (
            self._state != "idle" or self._idle_clip is not None)
        if playing and self._frame_index < len(photos):
            self.label.configure(image=photos[self._frame_index])
            self._frame_index += 1
        elif playing and self._idle_clip is not None:
            self._idle_clip = None
            self._show_clip("idle")
        fps = EXTRA_FPS if self._active_clip in self._extra_frames or self._active_clip == "greeting" else self.fps
        delay = max(10, int(1000 / fps)) if playing and self._frame_index < len(photos) else 150
        self.window.after(delay, self._tick_frame)

    def celebrate(self):
        if random.random() < .6:
            self._celebrate_until = time.monotonic() + 6

    def _apply_click_through(self) -> None:
        if self.window is None:
            return
        want = click_through_wanted(self._click_through_setting, self._state)
        if want == self._click_through:
            return
        if set_click_through(self.window, want):
            self._click_through = want

    # ------------------------------------------------------------- etkileşim
    def _press(self, event) -> None:
        self._drag = (event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y())
        self._moved = False

    def _motion(self, event) -> None:
        if not self._drag:
            return
        dx, dy = event.x_root - self._drag[0], event.y_root - self._drag[1]
        if not self._moved and abs(dx) + abs(dy) > 3:
            self._moved = True
            if self.dock:
                self.dock.dismiss_bubble()
        if self._moved:
            x, y = clamp_position(self._drag[2] + dx, self._drag[3] + dy,
                                  self.size[0], self.size[1], windows_monitors(self.root))
            self.window.geometry(f"+{x}+{y}")

    def _release(self, event) -> None:
        if self._moved:
            pos = clamp_position(self.window.winfo_x(), self.window.winfo_y(),
                                 self.size[0], self.size[1], windows_monitors(self.root))
            self.window.geometry(f"+{pos[0]}+{pos[1]}")
            self._save(mascot_pos=list(pos))
        self._drag = None

    def _menu(self, event) -> None:
        import tkinter as tk

        menu = tk.Menu(self.window, tearoff=0)
        if self.dock:
            menu.add_command(label="Yaz", command=lambda: self.dock.open(focus=True))
            if self.dock.last_reply:
                menu.add_command(label="Son yanıtı aç", command=self.dock.open_reply)
            menu.add_command(label="Mikrofonu aç/kapat", command=self.dock.toggle_mic)
            menu.add_command(label="Sesi kes", command=self.dock.stop_speech)
            menu.add_command(label="Kısayolu değiştir", command=self.dock.change_shortcut)
            menu.add_command(label="Komut Merkezi", command=self.dock.open_console)
            menu.add_separator()
        menu.add_command(label="Gizle", command=self.hide)
        menu.add_command(label="Konum sıfırla", command=self.reset_position)
        menu.add_separator()
        menu.add_command(label="Jarvis’i kapat", command=lambda: threading.Thread(
            target=self.runtime._shutdown, kwargs={"reason": "maskot menüsü"}, daemon=True).start())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def set_badge(self, text):
        if self.badge is None or self.badge.cget("text") == text:
            return
        self.badge.configure(text=text)
        if text:
            self.badge.place(relx=.5, rely=1, y=-1, anchor="s")
        else:
            self.badge.place_forget()

    def reveal_card(self):
        self.commands.put("card")

    def toggle(self):
        self.commands.put("toggle")

    def set_visible(self, visible):
        self.commands.put("show" if visible else "hide")

    def is_visible(self):
        return not self._closed and not self._hidden

    def show(self):
        self._hidden = False
        if self.window is not None:
            self.window.deiconify()

    def hide(self) -> None:
        if not self.runtime._tray and not (self.dock and self.dock.hotkey_registered):
            if self.dock:
                self.dock.open(focus=True)
                self.dock._set_notice("Tekrar açmak için tepsi simgesi veya çalışan bir kısayol gerekir.")
            return
        self._hidden = True
        if self.window is not None:
            self.window.withdraw()
        if self.dock:
            self.dock.dismiss_bubble()
            if self.dock.panel is not None:
                self.dock.panel.withdraw()

    def reset_position(self) -> None:
        pos = reset_position(self.size[0], self.size[1], windows_monitors(self.root))
        self.window.geometry(f"+{pos[0]}+{pos[1]}")
        self._save(mascot_pos=list(pos))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dock:
            self.dock.close()
        try:
            if self.root is not None:
                self.root.destroy()
        except Exception:  # noqa: BLE001
            _record_failure("modules/mascot_window.py:close")


def _run(runtime, ready) -> None:
    mascot = MascotWindow(runtime)
    mascot.ready = ready
    try:
        mascot.open()
    except Exception as exc:  # noqa: BLE001
        _record_failure("modules/mascot_window.py:_run")
        print(f"Masaüstü maskot penceresi açılamadı: {type(exc).__name__}")
    finally:
        was_active = getattr(runtime, "_mascot", None) is mascot
        if was_active:
            runtime._mascot = None
        mascot.close()
        ready.set()
        if was_active and not _STOP.is_set() and not runtime.engine.stop_event.is_set():
            runtime._show_main()


def start(runtime, *, default=False) -> bool:
    """Wait for the visible surface (or tray access) before replacing the console."""
    global _THREAD
    if runtime.config.load_settings().get("mascot_window", default) is not True:
        return False
    if not sys.platform.startswith("win"):
        if not default:
            print("Masaüstü maskot penceresi yalnız Windows'ta açılır.")
        return False
    if not available():
        print("Masaüstü maskot penceresi açılamadı: tkinter/Pillow yok.")
        return False
    if _THREAD is not None and _THREAD.is_alive():
        return getattr(runtime, "_mascot", None) is not None
    _STOP.clear()
    ready = threading.Event()
    _THREAD = threading.Thread(target=_run, args=(runtime, ready), name="jarvis-mascot", daemon=True)
    _THREAD.start()
    if not ready.wait(4):
        _STOP.set()
        return False
    return getattr(runtime, "_mascot", None) is not None


def stop() -> None:
    _STOP.set()
