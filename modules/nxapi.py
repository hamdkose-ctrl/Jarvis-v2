"""Yeni arayüzün (nx) motor tarafı: Dosyalar ekranı, dosya işlemleri, Windows açılışında başlatma, arayüz ayarları.

web.Bridge bu fonksiyonları ince sarmalayıcılarla dışarı açar. Dosya yolları yalnızca kullanıcının kendi
klasörlerinde (İndirilenler, Masaüstü, Belgeler, Resimler, Jarvis Dosyaları) olabilir.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import DATA_DIR, load_settings, save_settings

HOME = Path.home()
FILES_DIR = HOME / "Documents" / "Jarvis Dosyaları"          # arayüzden yüklenen dosyalar buraya

CATS = {
    "pdf": {".pdf"},
    "word": {".docx", ".doc", ".odt", ".rtf"},
    "excel": {".xlsx", ".xls", ".csv", ".ods"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic"},
    "other": {".txt", ".md", ".pptx", ".ppt", ".dwg", ".dxf", ".json", ".xml", ".log", ".zip"},
}
_ALL = set().union(*CATS.values())


_KNOWN_FOLDER_IDS = {      # Windows Known Folder kimlikleri (FOLDERID_*)
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
}


def known_folder(name: str) -> Path | None:
    """Windows'un bildirdiği gerçek klasör yolu (OneDrive yönlendirmesi, başka diske taşınmış, Türkçe ad). Windows dışında None."""
    guid = _KNOWN_FOLDER_IDS.get(name)
    if not guid or os.name != "nt":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes
        raw = uuid.UUID(guid)
        class _GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        g = _GUID(raw.time_low, raw.time_mid, raw.time_hi_version, (ctypes.c_ubyte * 8)(*raw.bytes[8:]))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
            return None
        try:
            path = Path(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
        return path if path.is_dir() else None
    except Exception:
        _record_failure('modules/nxapi.py:known_folder')
        return None


def home_folder(name: str) -> Path | None:
    """Masaüstü/Belgeler/İndirilenler/Resimler (İngilizce ad: Desktop, Documents, Downloads, Pictures) klasörünün gerçek yolu:
    önce Windows'un bildirdiği, yoksa ana klasör ve OneDrive altındaki ad. Hiçbiri yoksa None."""
    kf = known_folder(name)
    if kf is not None and kf.is_dir():
        return kf
    for base in (HOME, HOME / "OneDrive"):
        if (base / name).is_dir():
            return base / name
    return None


def _roots() -> list[Path]:
    out = [FILES_DIR]
    for name in _KNOWN_FOLDER_IDS:                 # Windows'un söylediği gerçek klasörler, aynı kaynaktan izinli
        p = known_folder(name)
        if p is not None and p.resolve() not in {r.resolve() for r in out if r.exists()}:
            out.append(p)
    for c in ("Downloads", "İndirilenler", "Desktop", "Masaüstü", "Documents", "Belgeler", "Pictures", "Resimler",
              "OneDrive/Desktop", "OneDrive/Masaüstü", "OneDrive/Documents", "OneDrive/Belgeler"):
        p = HOME / c
        if p.is_dir() and p.resolve() not in {r.resolve() for r in out if r.exists()}:
            out.append(p)
    return out


def _cat(ext: str) -> str:
    return next((k for k, v in CATS.items() if ext in v), "other")


def allowed(path: str | Path) -> Path | None:
    """Yol kullanıcının klasörlerinden birinde mi? Değilse None (arayüzden rastgele sistem dosyası açılmasın)."""
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return None
    for r in _roots():
        try:
            if r.exists() and (p == r.resolve() or r.resolve() in p.parents):
                return p
        except OSError:
            continue
    return None


_TR = {"Documents": "Belgeler", "Desktop": "Masaüstü", "Downloads": "İndirilenler", "Pictures": "Resimler"}


def _where(folder: Path) -> str:
    """Kısa, okunur konum: 'Jarvis Dosyaları › Proje', 'Masaüstü › jarvis V5'."""
    try:
        rel = folder.relative_to(FILES_DIR)
        return " › ".join(("Jarvis Dosyaları",) + rel.parts)
    except ValueError:
        pass
    try:
        parts = [p for p in folder.relative_to(HOME).parts if p != "OneDrive"]
    except ValueError:
        return str(folder)
    return " › ".join(_TR.get(p, p) for p in parts) or "Ana klasör"


_FILE_CACHE: dict = {"rows": None, "ts": 0.0}          # tam tarama sonucu (items, limit öncesi)
_FILE_CACHE_LOCK = threading.Lock()
_FILE_TTL = 45.0                                        # saniye; kısa ömürlü, arayüz tepkisi korunur
_file_generation = 0
_file_refreshing = threading.Event()                    # arka plan taraması sürüyor mu


def _scan_files() -> list[dict]:
    """Ağır kısım: tüm kökleri dolaşır, dosya satırlarını üretir. Sıralama/limit yok — önbelleğe ham gider."""
    seen, items = set(), []
    for root in _roots():
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$", "node_modules", "__pycache__"))
                           and d not in ("AppData", "venv", ".venv")] if depth < 2 else []
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if ext not in _ALL or fn.startswith(("~$", ".")):
                    continue
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                    key = str(p.resolve()).lower()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                items.append({"path": str(p), "name": fn, "ext": ext.lstrip("."), "cat": _cat(ext),
                              "size": st.st_size, "mtime": st.st_mtime,
                              "folder": str(p.parent).replace(str(HOME), "~"),
                              "mine": root == FILES_DIR, "where": _where(p.parent)})
                if len(items) >= 4000:
                    return items
    return items


def describe_file(path) -> dict | None:
    """Dosya listesindeki satırın aynısını tek dosya için üretir (içerik araması isabetleri için)."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    ext = p.suffix.lower()
    return {"path": str(p), "name": p.name, "ext": ext.lstrip("."), "cat": _cat(ext), "size": st.st_size,
            "mtime": st.st_mtime, "folder": str(p.parent).replace(str(HOME), "~"),
            "mine": FILES_DIR in p.parents, "where": _where(p.parent)}


def list_files(limit: int = 400, force: bool = False) -> dict:
    """Kullanıcının klasörlerindeki belgeler/görseller, en yeniden eskiye (alt klasörlere 2 seviye iner).

    Sonuç TTL önbelleğinden gelir; süresi dolmuşsa İLK yanıtı önbellekteki (eski ama hızlı) liste
    verir ve aynı anda arka planda yeni tarama başlatır — arayüz asla disk beklemesin.
    force=True doğrudan senkron tarama yapar (arayüzde "yenile" düğmesi gibi).
    """
    global _file_generation
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    with _FILE_CACHE_LOCK:
        rows, cached_at = _FILE_CACHE["rows"], _FILE_CACHE["ts"]
        fresh = rows is not None and not force and (now - cached_at) < _FILE_TTL
        if rows is None or force or ((now - cached_at) >= _FILE_TTL and not _file_refreshing.is_set()):
            _file_generation += 1
            generation = _file_generation
            _file_refreshing.set()
            if fresh or rows is None or force:
                # İlk istek (önbellek boş) ya da zorla: senkron tarama.
                try:
                    rows = _scan_files()
                    _FILE_CACHE["rows"], _FILE_CACHE["ts"] = rows, time.monotonic()
                finally:
                    _file_refreshing.clear()
            else:
                # Bayat önbellek: eski listeyi hemen ver, arkada tazele.
                import threading
                threading.Thread(target=_background_refresh, args=(generation,), daemon=True, name="dosya-onbellek").start()
    if rows is None:   # arka plan taraması ilk kez çalışıyorsa ve boş döndüyse
        rows = []
    return _shape_files(rows, limit)


def _background_refresh(generation=None) -> None:
    """Scan outside the UI lock; an obsolete scan cannot replace a forced refresh."""
    if generation is None:
        with _FILE_CACHE_LOCK:
            generation = _file_generation
    try:
        rows = _scan_files()
        with _FILE_CACHE_LOCK:
            if generation == _file_generation:
                _FILE_CACHE["rows"], _FILE_CACHE["ts"] = rows, time.monotonic()
    finally:
        with _FILE_CACHE_LOCK:
            if generation == _file_generation:
                _file_refreshing.clear()


def reset_file_cache() -> None:
    """Önbelleği boşaltır. Testler FILES_DIR'i patch'lediği için testler arasında eski kopyanın
    sızmamasını sağlar; arayüzün "yenile" düğmesine de ayrı bir zorlama yolu verir."""
    global _file_generation
    with _FILE_CACHE_LOCK:
        _file_generation += 1
        _file_refreshing.clear()
        _FILE_CACHE["rows"] = None
        _FILE_CACHE["ts"] = 0.0


_SHAPE_CACHE = {}


def _shape_files(rows: list[dict], limit: int) -> dict:
    """Ham satırları sıralayıp limit'ler ve kategori sayaçlarını üretir."""
    # Cache only the order. The O(N) signature notices an in-place adapter edit;
    # the expensive O(N log N) sort is reused across limits and UI refreshes.
    signature=tuple(x["mtime"] for x in rows)
    with _FILE_CACHE_LOCK:
        if _SHAPE_CACHE.get("signature") != signature:
            _SHAPE_CACHE.update(signature=signature, order=sorted(range(len(rows)), key=lambda i:rows[i]["mtime"], reverse=True))
        items = [dict(rows[i]) for i in _SHAPE_CACHE["order"][:limit]]
    counts = {k: sum(1 for x in items if x["cat"] == k) for k in CATS}
    counts["all"] = len(items)
    return {"files": items, "counts": counts, "dir": str(FILES_DIR)}


# Arayüz düğmesi -> komut cümlesi (main._file_route bunları yapay zekâya sormadan doğrudan çalıştırır)
ACTIONS = {
    "analiz": "dosyasını kapsamlı analiz et",
    "ozet": "dosyasını özetle",
    "excel": "dosyasını Excel'e dönüştür",
    "word": "dosyasını Word'e dönüştür",
    "pdf": "dosyasını PDF'e dönüştür",
    "cevir": "dosyasını İngilizceye çevir",
    "cevir_tr": "dosyasını Türkçeye çevir",
    "gorsel": "görselini analiz et",
    "metin": "görselindeki metni çıkar",
    "telefon": "dosyasını telefona gönder",
}


def action_command(path: str, action: str) -> str:
    p = allowed(path)
    if p is None or not p.is_file():
        raise ValueError("Bu dosyaya erişemiyorum (yalnızca kendi klasörlerindeki dosyalar).")
    if action not in ACTIONS:
        raise ValueError("Bilinmeyen işlem.")
    return f'"{p}" {ACTIONS[action]}'


def _visible_windows() -> set:
    """Şu an ekranda görünen üst düzey pencereler (Windows)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out: set = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        if user32.IsWindowVisible(h) and user32.GetWindowTextLengthW(h) > 0:
            out.add(h)
        return True
    user32.EnumWindows(proc(cb), 0)
    return out


def _bring_new_window_front(before: set, wait: float = 10.0) -> None:
    """Açılan dosya/klasör penceresi Jarvis'in arkasında kalmasın: yeni pencere görününce öne getirir.

    Windows, arka plandaki bir programın başka pencereyi öne almasını engeller; kısa bir Alt tuşu
    vuruşu bu kilidi açar (Windows'un kendi önerdiği yöntem)."""
    import ctypes
    user32 = ctypes.windll.user32
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.25)
        try:
            new = [h for h in _visible_windows() if h not in before]
        except Exception:       # noqa: BLE001
            _record_failure('modules/nxapi.py:_bring_new_window_front')
            return
        if new:
            h = new[0]
            try:
                if user32.IsIconic(h):
                    user32.ShowWindow(h, 9)                # SW_RESTORE
                # Ön plandaki pencerenin girdi kuyruğuna geçici bağlanıp öne al. Alt tuşu KULLANMA:
                # Gezgin'de şerit kısayol harflerini (D, H, S, V, 1, 2…) gösteriyordu.
                kernel32 = ctypes.windll.kernel32
                fg = user32.GetForegroundWindow()
                t_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                t_me = kernel32.GetCurrentThreadId()
                attached = bool(t_fg and t_fg != t_me and user32.AttachThreadInput(t_me, t_fg, True))
                try:
                    user32.BringWindowToTop(h)
                    ok = user32.SetForegroundWindow(h)
                finally:
                    if attached:
                        user32.AttachThreadInput(t_me, t_fg, False)
                if not ok:      # son çare: hiçbir programın kullanmadığı F24 tuşu (görünür etkisi yok)
                    user32.keybd_event(0x87, 0, 0, 0)
                    user32.keybd_event(0x87, 0, 2, 0)
                    ok = bool(user32.SetForegroundWindow(h))
                if not ok:
                    # Dosya açıldı ama pencere öne gelmedi. Sessiz kalırsa kullanıcı işlemin
                    # gerçekleştiğini sanabilir; en azından günlüğe görünür bir iz bırak.
                    # (Arayüzde bildirim gösterme işi ayrı bir adım olarak duruyor.)
                    logging.getLogger('jarvis').warning(
                        'Açılan pencere öne getirilemedi; dosya açıldı ama arka planda kalmış olabilir.')
            except Exception:   # noqa: BLE001
                _record_failure('modules/nxapi.py:_bring_new_window_front')
                pass
            return


def _open_front(launch) -> None:
    try:
        before = _visible_windows()
    except Exception:           # noqa: BLE001
        _record_failure('modules/nxapi.py:_open_front')
        before = None
    launch()
    if before is not None:
        import threading
        threading.Thread(target=_bring_new_window_front, args=(before,), daemon=True).start()


def open_path(path: str, reveal: bool = False) -> bool:
    p = allowed(path)
    if p is None or not p.exists():
        raise ValueError("Bu dosyaya erişemiyorum.")
    if sys.platform.startswith("win"):
        if reveal:
            _open_front(lambda: subprocess.Popen(["explorer", "/select,", str(p)]))
        elif p.is_dir():
            _open_front(lambda: subprocess.Popen(["explorer", str(p)]))
        else:
            _open_front(lambda: os.startfile(str(p)))   # type: ignore[attr-defined]  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(p.parent if reveal else p)])
    return True


def pick_folder() -> str:
    """Windows'un kendi klasör seçme penceresi (Edge'in "bu siteye yüklensin mi" sorusu çıkmaz)."""
    if not sys.platform.startswith("win"):
        return ""
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$f=New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
          "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
          "$d.Description='Jarvis''e yüklenecek klasörü seç';$d.ShowNewFolderButton=$false;"
          "if($d.ShowDialog($f) -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;$d.SelectedPath}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True,
                             timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def folder_files(path: str, limit: int = 300) -> list[Path]:
    root = Path(path)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$", "__pycache__", "node_modules"))]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if fn.startswith(("~$", ".")) or not (0 < p.stat().st_size < 200_000_000):
                    continue
            except OSError:
                continue
            out.append(p)
            if len(out) >= limit:
                return out
    return out


def import_folder(path: str) -> dict:
    """Seçilen klasörü (alt klasörleriyle) Jarvis Dosyaları altına kopyalar; aslına dokunmaz."""
    import shutil
    root = Path(path)
    files = folder_files(path)
    if not files:
        raise ValueError("Klasörde yüklenecek dosya bulunamadı.")
    base = FILES_DIR / root.name
    n = 1
    while base.exists():
        base = FILES_DIR / f"{root.name}_{n}"
        n += 1
    ok = 0
    for p in files:
        dest = base / p.relative_to(root)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            ok += 1
        except OSError:
            continue
    return {"ok": ok, "total": len(files), "dir": str(base)}


def save_upload(name: str, data: bytes) -> Path:
    from io import BytesIO
    return save_upload_stream(name, BytesIO(data))


def save_upload_stream(name: str, source) -> Path:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(name).name or "dosya"
    n = 0
    while True:
        dest = FILES_DIR / (name if n == 0 else f"{Path(name).stem}_{n}{Path(name).suffix}")
        try:
            stream = dest.open('xb')  # Reserve the filename atomically across upload threads.
        except FileExistsError:
            n += 1
            continue
        try:
            with stream:
                import shutil
                shutil.copyfileobj(source, stream, length=1 << 20)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return dest


# ------------------------------------------------------------------ Windows açılışında başlat
def _startup_file() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.vbs"


def autostart_get() -> bool:
    f = _startup_file()
    return bool(f and f.exists())


def autostart_set(on: bool) -> bool:
    f = _startup_file()
    if f is None:
        raise ValueError("Bu özellik yalnızca Windows'ta çalışır.")
    if on:
        bat = Path(__file__).resolve().parents[1] / "baslat.bat"
        f.parent.mkdir(parents=True, exist_ok=True)
        # Gizli pencereyle başlat (komut penceresi görünmesin)
        f.write_text(f'CreateObject("WScript.Shell").Run """{bat}""", 0, False\r\n', encoding="utf-16")
    elif f.exists():
        f.unlink()
    return autostart_get()


# ------------------------------------------------------------------ arayüz ayarları
DEFAULTS = {"nx_theme": "dark", "nx_notify": True, "nx_bust": True, "ai_mode": "auto", "nx_advanced": False}


def ui_settings() -> dict:
    s = load_settings()
    out = {k: s.get(k, v) for k, v in DEFAULTS.items()}
    out["tray"] = bool(s.get("tray", True))
    out["autostart"] = autostart_get()
    out["provider"] = s.get("provider") or "gemini"
    out["live_mode"] = s.get("live_mode", True) is not False
    out["wake_sensitivity"] = int(s.get("wake_sensitivity") or 3)
    out["live_silence_ms"] = int(s.get("live_silence_ms") or 1100)
    out["live_beep"] = s.get("live_beep", True) is not False
    from modules import learning, personalization
    out["learn_from_chat"] = learning.enabled(personalization.Profile(personalization.get_active()))
    bgf = DATA_DIR / "arka_plan.img"
    out["bg"] = bgf.exists()
    out["bg_video"] = False
    if out["bg"]:
        try:
            with open(bgf, "rb") as fh:
                h = fh.read(12)
            out["bg_video"] = h[4:8] == b"ftyp" or h[:4] == b"\x1aE\xdf\xa3"
        except OSError:
            pass
    out["nx_globe"] = s.get("nx_globe", True) is not False
    out["widget_on"] = s.get("widget_on", True) is not False
    return out


def ui_set(key: str, value) -> dict:
    """Arayüzden değiştirilebilen güvenli ayarlar (anahtar, gizlilik, izin yok)."""
    if key == "autostart":
        autostart_set(bool(value))
    elif key == "nx_theme" and value in ("dark", "light", "system"):
        save_settings(nx_theme=value)
    elif key == "learn_from_chat":
        from modules import personalization
        personalization.Profile(personalization.get_active()).set_pref(key, bool(value))
    elif key in ("nx_globe", "nx_notify", "nx_bust", "nx_advanced", "tray", "live_beep", "live_mode"):
        save_settings(**{key: bool(value)})
    elif key == "wake_sensitivity":
        save_settings(wake_sensitivity=max(1, min(5, int(value))))
    elif key == "live_silence_ms":
        save_settings(live_silence_ms=max(300, min(2500, int(value))))
    elif key == "bg" and not value:                  # arka plan resmini kaldır (yerine çizilen gece salonu)
        (DATA_DIR / "arka_plan.img").unlink(missing_ok=True)
    elif key == "ai_mode" and value in ("auto", "openrouter", "gemini", "groq", "ollama"):
        from modules import llm
        llm.set_provider(value)   # anahtar yoksa ValueError
        save_settings(ai_mode=value)
    else:
        raise ValueError("Bu ayar arayüzden değiştirilemez.")
    return ui_settings()

