"""Dosya kaydetme akışı (Ctrl+S → kaydet penceresi → ad → Kaydet).

Kurallar:
- Kaydetme **kalıcı değişiklik**: onay ister. Gece testleri yalnız sandbox klasöründe.
- Dosya adı alanı UIA'da yoksa klavye ile yazılır (pano), sonra Kaydet düğmesi denenir.
- Sonuç **diskten** doğrulanır: dosya gerçekten oluştu mu, içeriği ne? "Kaydettim" demek yetmez.
"""
from __future__ import annotations

import time
from pathlib import Path

from modules import pc_hands
from modules.diagnostics import record_failure as _record_failure

SANDBOX = Path.home() / ".jarvis" / "sandbox"
ASK = "“{name}” adıyla kaydetmemi istiyorsun. Dosya diske yazılacak; onaylıyor musun?"
DONE = "Kaydettim: {name} ({size} bayt)."
FAILED = "Kaydedemedim: {reason}"
OUTSIDE = "Yalnız deneme klasörüne kaydediyorum; başka yere yazmam."


def sandbox_path(name: str) -> Path:
    """Adı güvenli hale getirir ve sandbox içine sabitler (dışarı çıkamaz)."""
    raw = Path(str(name or "").strip()).name          # yol değil, yalnız dosya adı
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_. ").strip()
    safe = safe.replace(" ", "_").lstrip("._")[:60] or "kayit"
    SANDBOX.mkdir(parents=True, exist_ok=True)
    path = (SANDBOX / safe).resolve()
    if SANDBOX.resolve() not in path.parents:
        raise ValueError(OUTSIDE)
    return path


def save_as(window: str, name: str, *, confirm: bool = False, abort=None) -> dict:
    """Pencereye Ctrl+S gönderir, adı yazar, kaydeder ve diskten doğrular."""
    try:
        path = sandbox_path(name)
    except ValueError:
        return {"status": "refused", "text": OUTSIDE}
    if not confirm:
        pc_hands._pending.clear()
        pc_hands._pending.update({"action": {"kind": "save", "window": window, "path": str(path)},
                                  "at": time.time()})
        return {"status": "needs_confirmation", "text": ASK.format(name=path.name)}
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    found = pc_hands.pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": pc_hands.NO_TARGET}
    if not pc_hands._focus(target):
        return {"status": "failed", "text": FAILED.format(reason="pencere öne alınamadı")}
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.8)                      # kaydet penceresi açılsın
    except Exception:
        _record_failure("modules/pc_files.py:ctrl_s")
        return {"status": "failed", "text": FAILED.format(reason="Ctrl+S gönderilemedi")}
    if not pc_hands._paste(str(path)):
        return {"status": "failed", "text": FAILED.format(reason="dosya adı yazılamadı")}
    time.sleep(0.3)
    try:
        import pyautogui
        pyautogui.press("enter")
        time.sleep(1.0)
    except Exception:
        _record_failure("modules/pc_files.py:enter")
        return {"status": "failed", "text": FAILED.format(reason="kaydet onaylanamadı")}
    return verify_saved(path)


def verify_saved(path: Path) -> dict:
    """Diski oku: dosya gerçekten oluştu mu?"""
    if not path.exists():
        return {"status": "no_change", "text": FAILED.format(reason="dosya diskte oluşmadı")}
    size = path.stat().st_size
    return {"status": "done", "text": DONE.format(name=path.name, size=size), "path": str(path)}


def cleanup(path: str) -> bool:
    """Gece testlerinin açtığı dosyayı siler (yalnız sandbox içi)."""
    try:
        target = Path(path).resolve()
        if SANDBOX.resolve() not in target.parents:
            return False
        target.unlink(missing_ok=True)
        return True
    except Exception:
        _record_failure("modules/pc_files.py:cleanup")
        return False


def confirm_save(*, abort=None) -> dict:
    """Onay bekleyen kaydetme işlemini yürütür ("kaydet" onayı)."""
    pending = pc_hands._pending.get("action") or {}
    if pending.get("kind") != "save":
        return {"status": "none", "text": "Onay bekleyen kaydetme yok."}
    pc_hands._pending.clear()
    path = Path(pending["path"])
    return save_as(pending["window"], path.name, confirm=True, abort=abort)
