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

_last_action: dict[tuple, float] = {}
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
    return {"status": "done", "text": action["done_text"]}


def click(window: str, query: str, *, confirm: bool = False, abort=None) -> dict:
    """Penceredeki öğeye basar (UIA invoke/click)."""
    found = find_control(window, query)
    if found["status"] != "ok":
        return found
    control = found["control"]
    op = control.get("op") or "invoke"
    return _run({"query": query, "window": found["window"]["title"], "control_id": control["id"],
                 "snapshot": found["snapshot"], "op": op,
                 "done_text": f"“{control['name'][:40]}” öğesine bastım."},
                confirm=confirm, abort=abort)


def type_text(window: str, query: str, text: str, *, confirm: bool = False, abort=None) -> dict:
    """Metin alanına yazar (UIA set_value; olmazsa type)."""
    found = find_control(window, query)
    if found["status"] != "ok":
        return found
    control = found["control"]
    if pc_awareness._secret(control) or str(control.get("type", "")).casefold().endswith("password"):
        return {"status": "secret", "text": SECRET}
    op = "set_value" if "value" in (control.get("patterns") or []) else "type"
    return _run({"query": query, "window": found["window"]["title"], "control_id": control["id"],
                 "snapshot": found["snapshot"], "op": op, "text": text,
                 "done_text": f"“{control['name'][:30]}” alanına yazdım."},
                confirm=confirm, abort=abort)
