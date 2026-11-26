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


def search_query(name: str) -> str:
    """Söylenen isimden arama sorgusu üretir: hâl ekini atar, en ayırt edici kelimeyi seçer.

    Kullanıcı: "'bitaneme' derken 'bitanem'e demek istiyorum" (26 Kasım). Yani sondaki
    yönelme hâli eki ismin parçası değil: bitaneme → bitanem. Çok kelimeli dolgu
    ("bir taneme") varsa en uzun kelime aranır → tanem.
    """
    from modules.pc_hands import _fold
    words = [w for w in _fold(str(name or "")).replace("'", " ").split() if w]
    words = [w for w in words if w not in _FILLERS]
    cleaned: list[str] = []
    for word in words:
        for suffix in _CASE_SUFFIXES:
            # Tek harflik eki kısa adlardan atmayız: "anne" → "ann" olmasın.
            keep = 4 if len(suffix) == 1 else 3
            if len(word) - len(suffix) >= keep and word.endswith(suffix):
                word = word[: len(word) - len(suffix)]
                break
        # Unvan ("Hanıma" → "hanım") ismin yerine geçmez; ek atıldıktan SONRA süzülür.
        if len(word) >= 2 and word not in _HONORIFICS:
            cleaned.append(word)
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def open_search(name: str) -> dict:
    """Arama kutusuna ismi yazar (Ctrl+F + yapıştır). Kişi seçmez, mesaj göndermez."""
    query = search_query(name)
    if not query or len(query) < 3:
        return {"status": "empty", "text": "Kimi arayacağımı anlayamadım; adı söyler misin?"}
    opened = show()
    if opened["status"] != "done":
        return opened
    try:
        import pyautogui
        from modules.pc_hands import write_clipboard
        pyautogui.hotkey("ctrl", "f")
        time.sleep(_PAUSE)
        pyautogui.hotkey("ctrl", "a")
        write_clipboard(query)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.2)
    except Exception:
        _record_failure("modules/whatsapp_ui.py:open_search")
        return {"status": "failed", "text": "WhatsApp'ta arama yapamadım."}
    return {"status": "done", "text": f"WhatsApp'ta “{query}” arattım.",
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
