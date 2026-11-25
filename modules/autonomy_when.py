"""Zamanlı iş: "yarın 09:00'da şunu yap" cümlesinden zamanı çıkarır.

Kural: zaman **belirsizse tahmin etme**. "yarın" saat olmadan söylenirse sabah 09:00
kabul edilir ve bu **söylenir**; anlaşılmayan ifadede iş kuyruğa eklenmez.
"""
from __future__ import annotations

import re
import time

from modules.diagnostics import record_failure as _record_failure

DEFAULT_HOUR = 9
CLOCK = re.compile(r"\bsaat\s*(\d{1,2})[:.](\d{2})?\b|\b(\d{1,2})[:.](\d{2})\b")
RELATIVE = re.compile(r"\b(\d{1,3})\s*(dakika|dk|saat)\s*(sonra)\b")
DAYWORD = ("yarin", "bugun", "obur gun")


def _fold(text: str) -> str:
    table = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
    return " ".join(str(text or "").casefold().translate(table).split())


def parse_when(text: str, *, now: float | None = None) -> dict:
    """Cümleden zaman çıkarır: {'when': ts, 'rest': kalan metin, 'note': ...}."""
    moment = now if now is not None else time.time()
    lowered = _fold(text)
    note = ""
    relative = RELATIVE.search(lowered)
    if relative:
        amount = int(relative.group(1)) * (60 if relative.group(2) in ("dakika", "dk") else 3600)
        rest = (text[:relative.start()] + text[relative.end():]).strip(" ,;")
        return {"when": moment + amount, "rest": rest, "note": ""}
    clock = CLOCK.search(lowered)
    day_offset = 0
    if "obur gun" in lowered:
        day_offset = 2
    elif "yarin" in lowered:
        day_offset = 1
    if clock:
        hour = int(clock.group(1) or clock.group(3))
        minute = int(clock.group(2) or clock.group(4) or 0)
        rest = (text[:clock.start()] + text[clock.end():]).strip(" ,;")
    elif any(word in lowered for word in DAYWORD):
        hour, minute = DEFAULT_HOUR, 0
        rest = text
        for word in ("obur gun", "yarin", "bugun"):
            if word in lowered:
                rest = re.sub(word, "", rest, flags=re.IGNORECASE)
        rest = rest.strip(" ,;")
        note = f"saat söylenmediği için {DEFAULT_HOUR:02d}:00 kabul ettim"
    else:
        return {"when": None, "rest": str(text or ""), "note": "zaman bulamadım"}
    if hour > 23 or minute > 59:
        return {"when": None, "rest": str(text or ""), "note": "saat geçersiz"}
    base = time.localtime(moment)
    target = time.mktime((base.tm_year, base.tm_mon, base.tm_mday + day_offset,
                          hour, minute, 0, 0, 0, -1))
    # "yarın", "bugün", "da/de" gibi zaman kalıntılarını at. Türkçe harfler yüzünden
    # kelime kelime (katlanmış biçimle) karşılaştırıyoruz: "yarın" != "yarin".
    drop = {"yarin", "bugun", "obur", "gun", "da", "de", "ta", "te"}
    kept = [word for word in rest.replace("'", " ").split() if _fold(word) not in drop]
    rest = " ".join(kept).strip(" ,;")
    if target <= moment and day_offset == 0:
        target += 86400                      # saat geçmişse yarına kur
    return {"when": target, "rest": rest, "note": note}


def describe(when: float) -> str:
    return time.strftime("%d.%m %H:%M", time.localtime(when))
