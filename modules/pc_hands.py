"""PC ajanı 3. dilim — el: tıkla, yaz (UIA önce, fare yedek).

Kurallar (kullanıcı onaylı):
- Önce UIA: penceredeki öğeye doğrudan erişir, fare oynatmaz, pencereyi öne getirmez.
- UIA öğeyi bulamazsa **yapmaz**: tahminle tıklamak yerine tek cümleyle "bulamadım" der.
- Yüksek riskli adımlar (silme, ödeme, gönderme, onay, kaldırma) **onay ister**; onay
  verilmeden işlem yapılmaz.
- Aynı yere iki kez basmaz: 2 sn içinde aynı öğeye ikinci tıklama reddedilir (çift gönderim).
- Esc/herhangi bir durdurma isteği `abort` olayıyla gelir; işlem başlamadan önce ve
  işlemden hemen sonra kontrol edilir.
- Hiçbir zaman şifre alanına yazmaz (`_secret` alanları hedef olamaz).
"""
from __future__ import annotations

import time

from modules import pc_awareness
from modules.diagnostics import record_failure as _record_failure

# Onay isteyen fiiller: geri alınamaz veya dışarıya etkisi olan adımlar.
RISKY_WORDS = (
    "sil", "kaldır", "kalıcı", "ödeme", "öde", "satın al", "onayla", "gönder",
    "paylaş", "yayınla", "iptal et", "sıfırla", "kapat ve kaydet",
)
CONFIRM_MESSAGE = "{what} geri alınamayabilir. Onaylıyor musun?"
NOT_FOUND = "“{query}” diye bir öğe {window} penceresinde yok; tahminle tıklamıyorum."
AMBIGUOUS = "{window} penceresinde {count} öğe “{query}” ile eşleşiyor: {names}. Hangisi?"
NO_TARGET = "Hangi pencerede işlem yapacağımı söylemedin."
SECRET = "Şifre alanına ben yazmam; o alanı senin doldurman gerekiyor."
REPEAT = "Aynı öğeye az önce bastım; çift işlem olmasın diye ikinci kez basmıyorum."
NO_CHANGE = ("“{what}” için bastım ama ekran değişmedi. İkinci kez basmadım; "
             "pencereyi bir kontrol et, istersen tekrar denerim.")

_last_action: dict[tuple, float] = {}
# Onay bekleyen işlem: "sil düğmesine bas" → soru → "onaylıyorum" → çalışır.
# Tek slot ve kısa ömür: kullanıcı başka bir şeye geçtiyse eski işlem çalışmasın.
_pending: dict = {}
PENDING_SECS = 120.0
NO_PENDING = "Onay bekleyen bir işlem yok."
EXPIRED = "Onay süresi geçti; işlemi yeniden söyle."
_repeat_window_secs = 2.0


_FOLD_TABLE = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")


def _fold(text: str) -> str:
    """Türkçe harf katlama: “Sil”/“SİL” aynı sayılsın."""
    folded = str(text or "").casefold().translate(_FOLD_TABLE)
    return " ".join(folded.replace("̇", "").split())   # "SİL" → "sil"


def is_risky(query: str, text: str = "") -> bool:
    """Adım geri alınamaz mı? (silme/ödeme/gönderme…)"""
    blob = _fold(f"{query} {text}")
    return any(_fold(word) in blob for word in RISKY_WORDS)


def find_control(window: str, query: str) -> dict:
    """Pencerede adı eşleşen öğeyi bulur; belirsizse tahmin etmez."""
    found = pc_awareness.find_window(window)
    if not found.get("match"):
        return {"status": "no_window", "text": NO_TARGET if not window else found.get("reason", "")}
    result = pc_awareness.controls(found["match"])
    rows = [row for row in result.get("controls", []) if not pc_awareness._secret(row)]
    needle = _fold(query)
    matches = [row for row in rows if needle and needle in _fold(row["name"])]
    if not matches:
        return {"status": "not_found", "text": NOT_FOUND.format(query=query, window=found["match"]["title"][:40])}
    if len(matches) > 1:
        names = "; ".join(row["name"][:30] for row in matches[:4])
        return {"status": "ambiguous", "text": AMBIGUOUS.format(window=found["match"]["title"][:40],
                                                              count=len(matches), names=names, query=query)}
    return {"status": "ok", "control": matches[0], "window": found["match"], "snapshot": result}


def _repeat_guard(key: tuple) -> bool:
    now = time.time()
    last = _last_action.get(key)
    if last is not None and now - last < _repeat_window_secs:
        return True
    _last_action[key] = now
    return False


def _run(action: dict, *, confirm: bool, abort) -> dict:
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    query = action["query"]
    if is_risky(query, action.get("text", "")) and not confirm:
        _pending.clear()
        _pending.update({"action": action, "at": time.time()})
        return {"status": "needs_confirmation",
                "text": CONFIRM_MESSAGE.format(what=f"“{query}”"),
                "action": action}
    if _repeat_guard((action["window"], action["control_id"], action["op"])):
        return {"status": "repeat", "text": REPEAT}
    from modules.desktop_uia import DesktopUI, NotSent, WindowMissing
    ui = DesktopUI()
    try:
        ui.act(action["snapshot"], {"control": action["control_id"], "op": action["op"],
                                    "value": action.get("text", "")})
    except NotSent as exc:
        return {"status": "not_sent", "text": str(exc)}
    except WindowMissing as exc:
        return {"status": "no_window", "text": str(exc)}
    except Exception as exc:                      # yetki/UIA hatası: dürüst cevap
        _record_failure("modules/pc_hands.py:_run")
        return {"status": "failed", "text": f"İşlem yapılamadı: {exc}"}
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    # 4. dilim: doğrulama. Bastım demek yetmez; ekran gerçekten değişti mi?
    # Değişmediyse ikinci kez basmıyoruz (çift işlem riski), dürüstçe söylüyoruz.
    unchanged = _screen_unchanged(action)
    if unchanged:
        return {"status": "no_change", "text": NO_CHANGE.format(what=action["query"])}
    return {"status": "done", "text": action["done_text"]}


def _screen_unchanged(action: dict) -> bool:
    """Tıklamadan önceki ve sonraki pencere özeti aynı mı? (en iyi çaba)"""
    try:
        after = pc_awareness.controls(action["window_obj"])
    except Exception:
        _record_failure("modules/pc_hands.py:_screen_unchanged")
        return False
    before = action.get("snapshot") or {}
    def _digest(state: dict) -> str:
        rows = [(c.get("type"), c.get("name")) for c in (state.get("controls") or [])]
        return repr(rows)
    return bool(before) and _digest(after) == _digest(before)


def click(window: str, query: str, *, confirm: bool = False, abort=None) -> dict:
    """Penceredeki öğeye basar (UIA invoke/click)."""
    found = find_control(window, query)
    if found["status"] != "ok":
        return found
    control = found["control"]
    op = control.get("op") or "invoke"
    return _run({"query": query, "window": found["window"]["title"], "control_id": control["id"],
                 "snapshot": found["snapshot"], "window_obj": found["window"], "op": op,
                 "done_text": f"“{control['name'][:40]}” öğesine bastım."},
                confirm=confirm, abort=abort)


def type_text(window: str, query: str, text: str, *, confirm: bool = False, abort=None,
              allow_keyboard_fallback: bool = True) -> dict:
    """Metin alanına yazar (UIA set_value; olmazsa type)."""
    found = find_control(window, query)
    if found["status"] == "not_found" and allow_keyboard_fallback:
        return type_with_keyboard(window, text, abort=abort)
    if found["status"] != "ok":
        return found
    control = found["control"]
    if pc_awareness._secret(control) or str(control.get("type", "")).casefold().endswith("password"):
        return {"status": "secret", "text": SECRET}
    op = "set_value" if "value" in (control.get("patterns") or []) else "type"
    return _run({"query": query, "window": found["window"]["title"], "control_id": control["id"],
                 "snapshot": found["snapshot"], "window_obj": found["window"], "op": op, "text": text,
                 "done_text": f"“{control['name'][:30]}” alanına yazdım."},
                confirm=confirm, abort=abort)


# --- Klavye yedeği (UIA metin alanını göremiyorsa) -------------------------
# Canlı bulgu: Windows 11 Not Defteri'nde UIA yalnız pencereyi görüyor; metin
# alanı ayrı bir ağaçta kaldığı için `type_text` "bulamadım" diyordu. Kullanıcı
# politikası "UIA önce, olmazsa klavye/fare yedeği" olduğu için burada pencereyi
# öne alıp metni panoya koyarak yapıştırıyoruz (Türkçe karakterler bozulmasın).
PASTED = "Metin alanını göremedim; “{window}” penceresine yapıştırdım."
PASTE_FAILED = "“{window}” penceresine yazamadım: {reason}"


def _focus(window: dict) -> bool:
    """Pencereyi öne alır. Windows, ön planda olmayan süreçlere izin vermez:
    önce geri yükle, olmazsa kısa bir Alt dokunuşuyla izin penceresi aç."""
    try:
        import win32gui
        hwnd = int(window.get("hwnd") or 0)
        if not hwnd:
            return False
        win32gui.ShowWindow(hwnd, 9)          # SW_RESTORE
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            _record_failure("modules/pc_hands.py:_focus_alt")
            import pyautogui
            pyautogui.press("alt")            # ön plan kilidini açar
            win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        _record_failure("modules/pc_hands.py:_focus")
        return False


def _paste(text: str) -> bool:
    try:
        import pyautogui
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text)
        win32clipboard.CloseClipboard()
        pyautogui.hotkey("ctrl", "v")
        return True
    except Exception:
        _record_failure("modules/pc_hands.py:_paste")
        return False


def type_with_keyboard(window: str, text: str, *, abort=None) -> dict:
    """UIA bulunamadığında: pencereyi öne al, panodan yapıştır."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else found.get("reason", "")}
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    if not _paste(text):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pano/yapıştırma çalışmadı")}
    return {"status": "done", "text": PASTED.format(window=target["title"][:40])}


def confirm_pending(*, abort=None) -> dict:
    """Onay bekleyen riskli işlemi çalıştırır (kullanıcı "onaylıyorum" dedi)."""
    if not _pending:
        return {"status": "none", "text": NO_PENDING}
    action, asked_at = _pending.get("action"), float(_pending.get("at") or 0)
    _pending.clear()
    if time.time() - asked_at > PENDING_SECS:
        return {"status": "expired", "text": EXPIRED}
    return _run(action, confirm=True, abort=abort)
