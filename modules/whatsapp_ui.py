"""WhatsApp masaüstü arayüzü: isimle sohbet arama.

Neden ayrı modül: `messaging.send_whatsapp` yalnız **kayıtlı numara** ile çalışır
(`whatsapp://send?phone=...`). Kullanıcının WhatsApp'ta kayıtlı ama telefon rehberinde
olmayan kişiler ("Bitanem" gibi) için numara yok → mesaj gitmiyordu (canlı bulgu
26 Kasım 14:13). Bu modül arayüzden arar.

Güvenlik sınırı (kaldırılan eski GUI yolundan farkı):
- Arama **yalnız arar ve sonuçları gösterir**; kişi seçmez.
- Yazma/gönderme `confirm=True` olmadan **yapılmaz**; onayı kullanıcı verir.
- Enter tek başına hiçbir zaman basılmaz.
"""
from __future__ import annotations

import time
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

TITLE = "WhatsApp"
WINDOW_CLASS = "WinUIDesktopWin32WindowClass"
_PAUSE = 0.35


def window() -> dict | None:
    """WhatsApp penceresini bulur (kapalıysa tepside saklı olabilir; görünürlük şart değil)."""
    try:
        import win32gui
    except Exception:
        _record_failure("modules/whatsapp_ui.py:window")
        return None
    found: list[dict] = []

    def visit(handle, _):
        title = win32gui.GetWindowText(handle) or ""
        try:
            klass = win32gui.GetClassName(handle)
        except Exception:
            _record_failure("modules/whatsapp_ui.py:window:class")
            klass = ""
        if TITLE in title or (klass == WINDOW_CLASS and title.strip() in ("", TITLE)):
            found.append({"handle": handle, "title": title})
        return True

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


def _foreground() -> int:
    import win32gui
    return int(win32gui.GetForegroundWindow() or 0)


def _raise_window(handle: int) -> bool:
    """Pencereyi öne almayı dener; **gerçekten** öne geldiyse True.

    Canlı kusur (26 Kasım 17:5x): arka plandaki süreç `SetForegroundWindow` çağırınca
    Windows sessizce engelliyor ve ajan "WhatsApp penceresi öne alınamadı" diyordu.
    Tek deneme yerine sırayla üç yol denenir ve sonuç `GetForegroundWindow` ile doğrulanır.
    """
    import win32con
    import win32gui
    try:
        win32gui.ShowWindow(handle, win32con.SW_RESTORE)
    except Exception:
        _record_failure("modules/whatsapp_ui.py:_raise_window:show")
    for attempt in range(2):
        try:
            win32gui.SetForegroundWindow(handle)
        except Exception:
            _record_failure("modules/whatsapp_ui.py:_raise_window:setfg")
        if _foreground() == handle:
            return True
        try:
            import win32api
            import win32process
            current = win32api.GetCurrentThreadId()
            front = _foreground()
            front_thread = win32process.GetWindowThreadProcessId(front)[0]
            if front_thread and front_thread != current:
                win32process.AttachThreadInput(current, front_thread, True)
                try:
                    win32gui.BringWindowToTop(handle)
                    win32gui.SetForegroundWindow(handle)
                finally:
                    win32process.AttachThreadInput(current, front_thread, False)
        except Exception:
            _record_failure("modules/whatsapp_ui.py:_raise_window:attach")
        if _foreground() == handle:
            return True
        try:
            win32gui.SwitchToThisWindow(handle, True)
        except Exception:
            _record_failure("modules/whatsapp_ui.py:_raise_window:switch")
        if _foreground() == handle:
            return True
        time.sleep(0.25 * (attempt + 1))
    return _foreground() == handle


def show() -> dict:
    """Pencereyi öne alır (tepside kapalıysa geri yükler)."""
    info = window()
    if not info:
        return {"status": "no_window", "text": "WhatsApp penceresini bulamadım; açık mı?"}
    if not _raise_window(info["handle"]):
        return {"status": "failed", "text": "WhatsApp penceresi öne alınamadı; hiçbir şey yazmadım."}
    time.sleep(_PAUSE)
    return {"status": "done", "text": "WhatsApp öne alındı."}


_CASE_SUFFIXES = ("lerden", "lardan", "den", "dan", "ten", "tan", "nin", "nın", "nun", "nün",
                  "ye", "ya", "ne", "na", "ni", "nı", "nu", "nü", "e", "a", "i", "ı", "u", "ü")
_FILLERS = {"bir", "bu", "şu", "su", "o", "ve", "ile"}
_HONORIFICS = {"hanim", "hanım", "bey", "abi", "abla", "teyze", "amca", "hocam"}


def _strip_suffix(word: str) -> str:
    """Tek kelimeden hâl ekini atar (kısa adı bozmadan)."""
    for suffix in _CASE_SUFFIXES:
        keep = 4 if len(suffix) == 1 else 3
        if len(word) - len(suffix) >= keep and word.endswith(suffix):
            return word[: len(word) - len(suffix)]
    return word


def search_variants(name: str) -> list[str]:
    """Arama adayları: **tam ad korunur**, ek atması yalnız sonradan denenir.

    Kullanıcı kuralı (26 Kasım): "'bitaneme' derken 'bitanem'e demek istiyorum."
    Ama "Fatma" gibi adlar da bozulmamalı. Bu yüzden sıra: tam ad → sondaki ek atılmış
    hâli → son kelime → son kelimenin ek atılmış hâli. Hangisi sonuç verirse o kullanılır;
    böylece ek atması **aday doğrulamasıyla** yapılır, körlemesine değil.
    """
    from modules.pc_hands import _fold
    # Kesme işareti ek sınırıdır: "Zeynep'e" → "zeynep" (ayrı kelime yapmaz).
    raw = str(name or "").split("'")[0] if "'" in str(name or "") else str(name or "")
    text = _fold(raw)
    words = [w for w in text.split() if w and w not in _FILLERS]
    words = [w for w in words if w not in _HONORIFICS]
    if not words:
        return []
    full = " ".join(words)
    last = words[-1]
    candidates = [full, " ".join(words[:-1] + [_strip_suffix(last)]) if len(words) > 1 else _strip_suffix(full),
                  last, _strip_suffix(last)]
    out: list[str] = []
    for item in candidates:
        item = item.strip()
        if len(item) >= 2 and item not in out:
            out.append(item)
    return out


def search_query(name: str) -> str:
    """İlk (en güvenilir) arama adayı: tam ad. Ek atması `search_variants` ile yapılır."""
    variants = search_variants(name)
    return variants[0] if variants else ""


def _no_results_on_screen() -> bool:
    """WhatsApp "sonuç yok" durumunu ekrandan okur (aday doğrulaması)."""
    try:
        from modules import pc_vision
        words = pc_vision.read_screen()
    except Exception:
        _record_failure("modules/whatsapp_ui.py:_no_results_on_screen")
        return False
    text = " ".join(str(row.get("text") or "") for row in words).casefold()
    from modules.pc_hands import _fold
    folded = _fold(text)
    return "bulunamadi" in folded or "no chats found" in folded or "sonuc yok" in folded


def open_search(name: str) -> dict:
    """Arama kutusuna adı yazar (Ctrl+F + yapıştır). Kişi seçmez, mesaj göndermez.

    Adaylar sırayla denenir: tam ad → ek atılmış → son kelime. "Sonuç yok" görülürse
    bir sonraki adaya geçilir; böylece "Fatma" bozulmaz, "bitaneme" ise "bitanem"e düşer.
    """
    variants = search_variants(name)
    if not variants:
        return {"status": "empty", "text": "Kimi arayacağımı anlayamadım; adı söyler misin?"}
    opened = show()
    if opened["status"] != "done":
        return opened
    used = ""
    for query in variants:
        try:
            import pyautogui
            from modules.pc_hands import write_clipboard
            pyautogui.hotkey("ctrl", "f")
            time.sleep(_PAUSE)
            pyautogui.hotkey("ctrl", "a")
            write_clipboard(query)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1.1)
        except Exception:
            _record_failure("modules/whatsapp_ui.py:open_search")
            return {"status": "failed", "text": "WhatsApp'ta arama yapamadım."}
        used = query
        if not _no_results_on_screen():
            break
    return {"status": "done", "text": f"WhatsApp'ta “{used}” arattım.",
            "next": "Ekrandaki sonuçlardan hangisi doğru kişi? Onaylamadan mesaj yazmam."}


PENDING_FILE = Path.home() / ".jarvis" / "bellek" / "whatsapp-bekleyen.json"


def _pending_path():
    return PENDING_FILE


def remember_pending(name: str, text: str) -> None:
    """Onay bekleyen mesajı saklar (kişi + metin)."""
    import json
    path = _pending_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "text": text}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        _record_failure("modules/whatsapp_ui.py:remember_pending")


def pending() -> dict | None:
    import json
    try:
        data = json.loads(_pending_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        _record_failure("modules/whatsapp_ui.py:pending")
        return None
    return data if isinstance(data, dict) and data.get("text") else None


def clear_pending() -> None:
    try:
        _pending_path().unlink(missing_ok=True)
    except Exception:
        _record_failure("modules/whatsapp_ui.py:clear_pending")


def send_pending(*, confirm: bool = False) -> dict:
    """Onay verilirse bekleyen mesajı yazar ve gönderir."""
    data = pending()
    if not data:
        return {"status": "empty", "text": "Bekleyen bir WhatsApp mesajı yok."}
    if not confirm:
        return {"status": "needs_confirm",
                "text": f"“{data['name']}” için “{data['text']}” mesajını göndereyim mi?"}
    result = send_text(str(data["text"]), confirm=True)
    if result["status"] == "done":
        clear_pending()
    return result


def send_text(text: str, *, confirm: bool = False) -> dict:
    """Onaylıysa mesajı yazar ve gönderir; onay yoksa hiçbir şey yapmaz."""
    body = str(text or "").strip()
    if not body:
        return {"status": "empty", "text": "Mesaj boş."}
    if not confirm:
        return {"status": "needs_confirm",
                "text": f"“{body}” mesajını göndereyim mi? Onay vermeden göndermem."}
    try:
        import pyautogui
        from modules.pc_hands import write_clipboard
        write_clipboard(body)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        pyautogui.press("enter")
    except Exception:
        _record_failure("modules/whatsapp_ui.py:send_text")
        return {"status": "failed", "text": "Mesajı yazamadım/gönderemedim."}
    return {"status": "done", "text": "Gönderme komutunu uyguladım; teslimi doğrulayamıyorum."}
