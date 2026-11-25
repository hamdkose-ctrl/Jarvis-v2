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
WINDOW_AMBIGUOUS = ("“{query}” için {n} pencere var: {titles}. Hangisinde işlem yapayım?")
SECRET = "Şifre alanına ben yazmam; o alanı senin doldurman gerekiyor."
REPEAT = "Aynı öğeye az önce bastım; çift işlem olmasın diye ikinci kez basmıyorum."
NO_CHANGE = ("“{what}” için bastım ama ekran değişmedi. İkinci kez basmadım; "
             "pencereyi bir kontrol et, istersen tekrar denerim.")

_last_action: dict[tuple, float] = {}
# Onay bekleyen işlem: "sil düğmesine bas" → soru → "onaylıyorum" → çalışır.
# Tek slot ve kısa ömür: kullanıcı başka bir şeye geçtiyse eski işlem çalışmasın.
_pending: dict = {}
Ocr_ASK = ("Ekranda “{what}” yazısını buldum ({x},{y}). Düğme olarak göremiyorum; "
           "oraya tıklamamı onaylıyor musun?")
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
        # Canlı karne bulgusu: iki aynı pencere varken "pencere yok" demek yanlış —
        # kullanıcı hangisini kastettiğini söylemeli (tahmin yok).
        if found.get("reason") == "ambiguous":
            titles = "; ".join(str(c.get("title") or "")[:34] for c in (found.get("candidates") or [])[:4])
            return {"status": "ambiguous",
                    "text": WINDOW_AMBIGUOUS.format(query=window or "pencere",
                                                   n=len(found.get("candidates") or []), titles=titles)}
        return {"status": "no_window", "text": NO_TARGET if not window else "Pencere açık değil."}
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


def click(window: str, query: str, *, confirm: bool = False, abort=None,
          allow_keyboard_fallback: bool = True) -> dict:
    """Penceredeki öğeye basar (UIA invoke/click)."""
    found = find_control(window, query)
    if found["status"] == "not_found" and allow_keyboard_fallback:
        keyed = click_with_keyboard(window, query, abort=abort)
        if keyed["status"] != "not_found":
            return keyed
        # Son çare: ekranda yazıyı bul (Windows OCR) → konum → onay → tıkla.
        from modules import pc_vision
        seen = pc_vision.find_text(query)
        if seen["status"] == "ok":
            _pending.clear()
            _pending.update({"action": {"kind": "point", "x": seen["point"]["x"], "y": seen["point"]["y"]},
                             "at": time.time()})
            return {"status": "needs_confirmation",
                    "text": Ocr_ASK.format(what=query, x=seen["point"]["x"], y=seen["point"]["y"])}
        if seen["status"] == "ambiguous":
            return {"status": "ambiguous", "text": pc_vision.describe(query)}
        return found
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
        # Tarayıcıda adres çubuğu kısayolu (Ctrl+L) denenir; başka pencerede denenmez.
        target_window = pc_awareness.find_window(window).get("match") or {}
        if is_browser(target_window) and _fold(query) in ("adres", "adres cubugu", "adres çubuğu", "url"):
            addressed = type_address_bar(window, text, abort=abort)
            if addressed["status"] != "not_browser":
                return addressed
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
NOT_VISIBLE = ("“{window}” penceresine yapıştırdım ama yazı görünmüyor — alan seçili "
               "değil. Önce yazılacak alana tıklayıp söyle.")


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


def _text_visible(text: str) -> bool:
    """Yapıştırılan metin ekranda göründü mü? Ölçemiyorsak 'göründü' saymayız."""
    needle = _fold(text)[:24]
    if not needle:
        return False
    try:
        from modules import pc_vision
        words = pc_vision.read_screen()
    except Exception:
        _record_failure("modules/pc_hands.py:_text_visible")
        return False
    if not words:
        return False
    return needle in _fold(" ".join(word["text"] for word in words))


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
    # "Yapıştırdım" demek yetmez: metin ekranda göründü mü? (canlı bulgu: odaklanmış
    # alan yoksa Chrome'da yapıştırma hiçbir yere gitmiyor)
    if not _text_visible(text):
        return {"status": "no_change", "text": NOT_VISIBLE.format(window=target["title"][:40])}
    return {"status": "done", "text": PASTED.format(window=target["title"][:40])}


def confirm_pending(*, abort=None) -> dict:
    """Onay bekleyen riskli işlemi çalıştırır (kullanıcı "onaylıyorum" dedi)."""
    if not _pending:
        return {"status": "none", "text": NO_PENDING}
    action, asked_at = _pending.get("action"), float(_pending.get("at") or 0)
    _pending.clear()
    if time.time() - asked_at > PENDING_SECS:
        return {"status": "expired", "text": EXPIRED}
    if isinstance(action, dict) and action.get("kind") == "point":
        return click_point(action["x"], action["y"], confirm=True, abort=abort)
    return _run(action, confirm=True, abort=abort)


# --- Klavye ile "tıklama" (UIA iç düğmeleri göstermiyorsa) -----------------
# Canlı bulgu: Hesap Makinesi'nde UIA rakam düğmelerini görmüyor. Bu uygulamalarda
# doğru yol tıklamak değil, klavyeyle aynı işi yapmak ("7" → + tuşu).
KEY_NAMES = {
    "arti": "+", "artı": "+", "eksi": "-", "cikarma": "-", "çıkarma": "-",
    "carpi": "*", "çarpı": "*", "bolu": "/", "bölü": "/", "bolme": "/",
    "esittir": "=", "eşittir": "=", "esit": "=", "virgul": ".", "virgül": ".",
    "nokta": ".", "temizle": "esc", "sil": "backspace", "esittir2": "=",
}
KEYED = "“{what}” öğesini göremedim; {window} penceresinde klavyeyle yaptım."


def key_for(query: str) -> str | None:
    """Öğe adını klavye tuşuna çevirir; çevrilemezse None (tahmin yok)."""
    text = _fold(query).strip(" .!'")
    if len(text) == 1 and (text.isdigit() or text in "+-*/=.%"):
        return text
    return KEY_NAMES.get(text)


def click_with_keyboard(window: str, query: str, *, abort=None) -> dict:
    """UIA düğmeyi bulamadığında aynı işi klavyeyle yapar (yalnız tek tuş)."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    key = key_for(query)
    if key is None:
        return {"status": "not_found", "text": NOT_FOUND.format(query=query, window=window[:40])}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else found.get("reason", "")}
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    try:
        import pyautogui
        pyautogui.press(key)
    except Exception:
        _record_failure("modules/pc_hands.py:click_with_keyboard")
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="tuş gönderilemedi")}
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    return {"status": "done", "text": KEYED.format(what=query, window=target["title"][:40])}


# --- Fare yedeği: açık koordinat ------------------------------------------
# UIA bir uygulamada hiçbir iç öğe vermiyorsa (ör. Hesap Makinesi) ve tuş karşılığı
# da yoksa tek dürüst yol kullanıcının **açıkça söylediği** noktaya tıklamaktır.
# Koordinat uydurulmaz; her zaman onay istenir; tıklama öncesi/sonrası ekran
# karşılaştırılır.
POINT_ASK = "{x},{y} noktasına tıklamamı istiyorsun. Ekranda ne olduğunu bilmiyorum; onaylıyor musun?"
POINT_DONE = "{x},{y} noktasına tıkladım."
POINT_FAILED = "{x},{y} noktasına tıklayamadım: {reason}"


def _two_points(before: dict) -> bool:
    """Ekran gerçekten değişti mi? (piksel karşılaştırması, en iyi çaba)"""
    try:
        from PIL import ImageGrab
        import numpy as np
        left, top, right, bottom = before["box"]
        after = np.asarray(ImageGrab.grab(bbox=(left, top, right, bottom)), dtype="int16")
        return float(np.abs(after - before["pixels"]).mean()) > 0.5
    except Exception:
        _record_failure("modules/pc_hands.py:_two_points")
        return True          # ölçemediysek "değişmedi" diye yanlış alarm vermeyelim


def click_point(x: int, y: int, *, confirm: bool = False, abort=None) -> dict:
    """Söylenen ekran noktasına tıklar (onay şart)."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    if not confirm:
        _pending.clear()
        _pending.update({"action": {"kind": "point", "x": int(x), "y": int(y)},
                         "at": time.time()})
        return {"status": "needs_confirmation", "text": POINT_ASK.format(x=x, y=y),
                "action": {"kind": "point", "x": int(x), "y": int(y)}}
    try:
        import pyautogui
        from PIL import ImageGrab
        import numpy as np
        before = None
        try:
            box = pyautogui.size()
            before = {"box": (0, 0, int(box[0]), int(box[1])),
                      "pixels": np.asarray(ImageGrab.grab(bbox=(0, 0, int(box[0]), int(box[1]))),
                                           dtype="int16")}
        except Exception:
            # Ekran görüntüsü alınamıyorsa (kilitli oturum, uzak masaüstü, CI) tıklama
            # yine yapılır; yalnız "değişti mi" doğrulaması atlanır ve dürüstçe söylenir.
            _record_failure("modules/pc_hands.py:click_point_before")
        pyautogui.click(int(x), int(y))
    except Exception as exc:
        _record_failure("modules/pc_hands.py:click_point")
        return {"status": "failed", "text": POINT_FAILED.format(x=x, y=y, reason=str(exc)[:60])}
    if before is not None and not _two_points(before):
        return {"status": "no_change", "text": NO_CHANGE.format(what=f"{x},{y}")}
    return {"status": "done", "text": POINT_DONE.format(x=x, y=y)}


# --- Kurtarma: bir kez daha dene, sonra dürüstçe vazgeç --------------------
# Canlı ders: tek denemeyle vazgeçmek de, sonsuz denemek de yanlış. Kural:
# penceresi yoksa pencereyi öne almayı dene; ekran değişmediyse kısa bekleyip bir kez
# daha dene. En fazla 2 deneme; ikinci de olmazsa "yapamadım" ve neden.
RETRIED = "İlk deneme olmadı ({reason}); bir kez daha denedim."
GAVE_UP = "İki denemede de olmadı: {reason} Başka bir yol söylersen denerim."
MAX_ATTEMPTS = 2


def _retryable(status: str) -> bool:
    return status in ("no_window", "no_change", "failed")


def attempt(fn, *args, window: str = "", abort=None, **kwargs) -> dict:
    """Bir işlemi en çok iki kez dener; ikinci denemede pencereyi öne alır."""
    first = fn(*args, abort=abort, **kwargs) if abort is not None else fn(*args, **kwargs)
    if not _retryable(first.get("status", "")):
        return first
    if first.get("status") == "no_window":          # pencere kaçmış: öne al ve tekrar dene
        found = pc_awareness.find_window(window)
        if found.get("match"):
            _focus(found["match"])
    else:                                           # ekran değişmedi/başarısız: kısa bekle
        time.sleep(0.6)
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    second = fn(*args, abort=abort, **kwargs) if abort is not None else fn(*args, **kwargs)
    if second.get("status") == "done":
        return {**second, "text": RETRIED.format(reason=first.get("text", "")) + " " + second.get("text", "")}
    return {"status": second.get("status", "failed"), "text": GAVE_UP.format(reason=second.get("text", ""))}


# --- Tarayıcı adres çubuğu -------------------------------------------------
# Canlı sınır: Chrome'da metin alanı odaklı değilken pano yapıştırması boşa gidiyor.
# Bilinen kısayol var: Ctrl+L adres çubuğunu seçer. Bu yalnız tarayıcılarda denenir.
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera")
ADDRESS_DONE = "Adres çubuğunu seçip “{text}” yazdım."


def is_browser(window: dict) -> bool:
    title = _fold(str(window.get("title") or "")) + " " + _fold(str(window.get("app") or ""))
    return any(name in title for name in BROWSERS)


def type_address_bar(window: str, text: str, *, abort=None) -> dict:
    """Tarayıcıda Ctrl+L ile adres çubuğunu seçip yazar (yalnız tarayıcı)."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else found.get("reason", "")}
    if not is_browser(target):
        return {"status": "not_browser", "text": "Bu pencere tarayıcı değil; adres çubuğu kısayolunu kullanmadım."}
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.2)
    except Exception:
        _record_failure("modules/pc_hands.py:type_address_bar")
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="adres çubuğu seçilemedi")}
    if not _paste(text):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="yapıştırma çalışmadı")}
    if not _text_visible(text):
        return {"status": "no_change", "text": NOT_VISIBLE.format(window=target["title"][:40])}
    return {"status": "done", "text": ADDRESS_DONE.format(text=text[:30])}


# --- Enter / arama ---------------------------------------------------------
ENTERED = "{window} penceresinde Enter'a bastım."


def press_enter(window: str, *, abort=None) -> dict:
    """Odaktaki pencereye Enter gönderir (yazdıktan sonra aramayı başlatmak için)."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else found.get("reason", "")}
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    try:
        import pyautogui
        pyautogui.press("enter")
    except Exception:
        _record_failure("modules/pc_hands.py:press_enter")
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="Enter gönderilemedi")}
    time.sleep(0.8)
    return {"status": "done", "text": ENTERED.format(window=target["title"][:40])}


# --- Pencere hazırlığı / kurtarma (gece 3) --------------------------------
NOT_RESPONDING = "yanit vermiyor"
FROZEN = "“{window}” yanıt vermiyor; bekliyorum ({tries}/{limit})."
REOPENED = "Pencere kapalıydı; yeniden açmayı denedim."
STILL_MISSING = "“{window}” penceresini bulamadım ve açamadım."


def ensure_window(window: str, *, timeout: float = 8.0, opener=None, abort=None) -> dict:
    """Pencere var mı ve yanıt veriyor mu? Kaçmışsa açmayı dener, donmuşsa bekler."""
    deadline = time.time() + max(0.0, timeout)
    tries = 0
    reopened = False
    while True:
        if abort is not None and abort.is_set():
            return {"status": "stopped", "text": "Durduruldu."}
        found = pc_awareness.find_window(window)
        target = found.get("match")
        if target is None:
            if not reopened and opener is not None:
                reopened = True
                try:
                    opener(window)
                except Exception:
                    _record_failure("modules/pc_hands.py:ensure_window_opener")
                time.sleep(1.5)
                continue
            return {"status": "no_window", "text": STILL_MISSING.format(window=window)}
        title = _fold(str(target.get("title") or ""))
        if NOT_RESPONDING not in title:
            return {"status": "ok", "window": target, "reopened": reopened}
        tries += 1
        if time.time() > deadline:
            return {"status": "frozen", "text": FROZEN.format(window=target["title"][:40], tries=tries, limit=int(timeout))}
        time.sleep(0.5)


# --- Kopyala / yapıştır zinciri (10 madde #3) -----------------------------
# Amaç: bir penceredeki metni alıp başka uygulamaya taşımak. Kural: **panoyu
# doğrula** — "kopyaladım" demek yetmez, panoda gerçekten yeni metin olmalı.
CLIP_EMPTY = "Panoda metin yok; kopyalanacak bir şey seçili olmalı."
COPIED = "Kopyaladım: “{text}”."
PASTED_OK = "Yapıştırdım: “{text}”."
PASTED_MISSING = "Yapıştırdım ama yazı ekranda görünmüyor ({window}); alan seçili olmayabilir."


def read_clipboard() -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData() or "")
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        _record_failure("modules/pc_hands.py:read_clipboard")
        return ""


def write_clipboard(text: str) -> bool:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        _record_failure("modules/pc_hands.py:write_clipboard")
        return False


def copy_selection(window: str, *, abort=None) -> dict:
    """Odaktaki seçimi kopyalar; panoda yeni metin yoksa dürüstçe söyler."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else "Pencere açık değil."}
    before = read_clipboard()
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.3)
    except Exception:
        _record_failure("modules/pc_hands.py:copy_selection")
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="kopyalama gönderilemedi")}
    after = read_clipboard()
    if not after.strip() or after == before:
        return {"status": "no_change", "text": CLIP_EMPTY}
    return {"status": "done", "text": COPIED.format(text=after.strip()[:80]), "clipboard": after}


def paste_text(window: str, text: str | None = None, *, abort=None) -> dict:
    """Panodaki metni (ya da verilen metni) pencereye yapıştırır ve doğrular."""
    if abort is not None and abort.is_set():
        return {"status": "stopped", "text": "Durduruldu."}
    payload = text if text is not None else read_clipboard()
    if not str(payload or "").strip():
        return {"status": "no_change", "text": CLIP_EMPTY}
    found = pc_awareness.find_window(window)
    target = found.get("match")
    if not target:
        return {"status": "no_window", "text": NO_TARGET if not window else "Pencere açık değil."}
    if not _focus(target):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="pencere öne alınamadı")}
    if not write_clipboard(str(payload)) or not _paste(str(payload)):
        return {"status": "failed", "text": PASTE_FAILED.format(window=target["title"][:40], reason="yapıştırma çalışmadı")}
    if not _text_visible(str(payload)):
        return {"status": "no_change", "text": PASTED_MISSING.format(window=target["title"][:40])}
    return {"status": "done", "text": PASTED_OK.format(text=str(payload)[:60])}
