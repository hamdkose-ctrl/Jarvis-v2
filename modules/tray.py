"""Sistem tepsisi (sağ alt köşe) simgesi. pystray ve Pillow yoksa sessizce devre dışı kalır."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

from typing import Callable


def available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
        return True
    except ImportError:
        return False


def _image():
    from pathlib import Path
    from PIL import Image, ImageDraw
    logo = Path(__file__).resolve().parent.parent / "webui" / "icon.png"
    if logo.exists():
        try:
            return Image.open(logo).convert("RGBA").resize((64, 64), Image.LANCZOS)   # program logosu
        except OSError:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(6, 18, 36, 255), outline=(0, 229, 255, 255), width=4)
    hexp = [(32, 14), (48, 23), (48, 41), (32, 50), (16, 41), (16, 23)]
    d.polygon(hexp, outline=(0, 229, 255, 255), fill=(0, 140, 190, 255))
    return img


def start(on_show: Callable[[], None], on_mic: Callable[[], None], is_mic: Callable[[], bool],
          on_quit: Callable[[], None], on_sleep: Callable[[], None] | None = None,
          is_sleep: Callable[[], bool] | None = None, on_widget: Callable[[], None] | None = None,
          is_widget: Callable[[], bool] | None = None, name: Callable[[], str] | None = None):
    """Tepsi simgesini arka planda başlatır; başarılıysa simge nesnesini, değilse None döndürür."""
    if not available():
        return None
    try:
        import pystray
        nm = (lambda: (name() if name else "") or "Jarvis")
        menu = pystray.Menu(
            pystray.MenuItem(lambda _i: f"{nm()} · Göster", lambda *_: on_show(), default=True),
            pystray.MenuItem("Mikrofon açık", lambda *_: on_mic(), checked=lambda _i: bool(is_mic())),
            pystray.MenuItem("Hazırda bekle (uyku)", lambda *_: on_sleep and on_sleep(),
                             checked=lambda _i: bool(is_sleep and is_sleep()), visible=on_sleep is not None),
            pystray.MenuItem(lambda _i: f"Masaüstü küçük {nm()}", lambda *_: on_widget and on_widget(),
                             checked=lambda _i: bool(is_widget and is_widget()), visible=on_widget is not None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Tamamen kapat", lambda *_: on_quit()),
        )
        icon = pystray.Icon("jarvis", _image(), nm(), menu)
        icon.run_detached()
        return icon
    except Exception:       # noqa: BLE001 - tepsi olmazsa Jarvis yine çalışsın
        _record_failure('modules/tray.py:start')
        return None
