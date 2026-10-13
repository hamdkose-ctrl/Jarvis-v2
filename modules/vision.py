"""Jarvis'in 'görmesi': ekran paylaşımı ve kamera.

Görüntü yalnızca sen bir şey sorduğunda tek kare olarak yapay zekaya gönderilir; sürekli yayın yapılmaz.
Önizleme yalnızca bilgisayarında gösterilir.
"""
import base64
import io
import os
import tempfile
import threading
import time

try:
    from config import CAMERA_INDEX
except ImportError:
    CAMERA_INDEX = 0

MAX_SIDE = 1280        # yapay zekaya giden karenin en uzun kenarı (küçültmek hızlandırır)
_mode: str | None = None      # None, "screen" ya da "camera"
_camera = None


def mode() -> str | None:
    return _mode


def _screen_image():
    import pyautogui
    return pyautogui.screenshot().convert("RGB")


class _Camera:
    """Kamerayı arka planda okuyup en son kareyi tutar (her soruda yeniden açmak yavaş olurdu)."""

    def __init__(self, index: int):
        import cv2
        self.cap = None
        # Windows'ta her kamera her arka uçla açılmaz: sırayla DSHOW, MSMF ve varsayılanı dene;
        # seçili sıra çalışmazsa diğer kamera numaralarına da bak.
        backends = [getattr(cv2, n) for n in ("CAP_DSHOW", "CAP_MSMF") if hasattr(cv2, n)] if os.name == "nt" else []
        backends.append(getattr(cv2, "CAP_ANY", 0))
        indexes = [index] + [i for i in range(4) if i != index]
        for idx in indexes:
            for backend in backends:
                cap = cv2.VideoCapture(idx, backend)
                ok = False
                if cap.isOpened():
                    for _ in range(20):          # ısınma: ilk kareler boş/siyah gelebilir
                        ok, frm = cap.read()
                        if ok and frm is not None and frm.size:
                            break
                        ok = False
                        time.sleep(0.05)
                if ok:
                    self.cap = cap
                    break
                cap.release()
            if self.cap is not None:
                break
        if self.cap is None:
            raise RuntimeError("Kamera açılamadı. Başka bir uygulama (Teams, Zoom, Kamera) kullanıyor olabilir ya da "
                               "Windows Ayarlar > Gizlilik > Kamera'da masaüstü uygulamalarına izin verilmemiş.")
        self.frame = None
        self._run = True
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        for _ in range(60):          # ilk kare gelene kadar en fazla ~3 sn bekle
            if self.frame is not None:
                break
            time.sleep(0.05)
        if self.frame is None:
            self.stop()
            raise RuntimeError("Kameradan görüntü alınamadı.")

    def _loop(self) -> None:
        while self._run:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self.frame = frame
            else:
                with self._lock:
                    self.frame = None
                time.sleep(0.05)
                continue

    def image(self):
        import cv2
        from PIL import Image
        with self._lock:
            frame = None if self.frame is None else self.frame.copy()
        return None if frame is None else Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def stop(self) -> None:
        self._run = False
        self._thread.join(timeout=1.0)
        self.cap.release()


def start(which: str) -> None:
    """'screen' ya da 'camera' paylaşımını başlatır; olmazsa RuntimeError fırlatır."""
    global _mode, _camera
    from modules import privacy
    if msg := privacy.blocked(which):
        raise PermissionError(msg)
    stop()
    if which == "camera":
        try:
            _camera = _Camera(CAMERA_INDEX)
        except ImportError as exc:
            raise RuntimeError("Kamera için paket eksik: python -m pip install opencv-python") from exc
    elif which == "screen":
        _screen_image()              # çalışıyor mu diye bir kare dene
    else:
        raise ValueError(which)
    _mode = which


def stop() -> None:
    global _mode, _camera
    _mode = None
    if _camera is not None:
        _camera.stop()
        _camera = None


def current_image():
    """Paylaşılan kaynağın şu anki karesi (PIL Image); paylaşım yoksa None."""
    from modules import privacy
    if privacy.blocked(_mode or "screen"):
        return None
    if _mode == "camera" and _camera is not None:
        return _camera.image()
    if _mode == "screen":
        return _screen_image()
    return None


def snapshot_path() -> str | None:
    """Karenin küçültülmüş PNG kopyasını geçici dosyaya yazar; çağıran işi bitince silmeli."""
    img = current_image()
    if img is None:
        return None
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    fd, path = tempfile.mkstemp(prefix="jarvis_share_", suffix=".png")
    os.close(fd)
    img.save(path, "PNG")
    return path


def _b64(img, size) -> str:
    img = img.copy()
    img.thumbnail(size)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def preview_b64(size=(240, 135)) -> str | None:
    """Arayüz önizlemesi için küçük PNG (base64); tkinter PhotoImage(data=...) ile gösterilir."""
    img = current_image()
    return None if img is None else _b64(img, size)


def preview_multi(*sizes) -> list[str | None]:
    """Aynı kareyi birden çok boyutta üretir (tek yakalama)."""
    img = current_image()
    return [None if img is None else _b64(img, s) for s in sizes]
