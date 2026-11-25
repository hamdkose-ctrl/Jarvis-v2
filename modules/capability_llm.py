"""Model destekli anlam eşleşmesi: katalog yetmediğinde cümleyi yeteneğe bağlar.

Neden: katalog eşleşmesi sözcük tabanlı; "şu işi hallediversene" gibi dolaylı
cümlelerde `uncertain` kalıyor. Model, **sınırlı ve doğrulanabilir** bir iş için
çağrılır: yalnız "hangi yetenek + hangi alanlar" sorusunu yanıtlar.

Güvenlik kuralları:
- Modele **yapma yetkisi verilmez**; yalnız JSON seçim yapar. Geçersiz yetenek/alan
  adı gelirse karar **atılır** (`uncertain`).
- Katalogda olmayan yetenek seçilemez (`capability_catalog` tek kaynak).
- Eksik alan varsa **soru** döner; alan uydurulmaz (ör. dosya yolu doğrulanır).
- Model yoksa/yanıt bozuksa sessizce `uncertain` — akış normal sohbete düşer.
"""
from __future__ import annotations

import json
import time

from modules import capability_brain, capability_catalog
from modules.diagnostics import record_failure as _record_failure

CACHE_SECONDS = 300.0
_cache: dict[str, tuple[float, dict]] = {}


def _schema_prompt(text: str) -> str:
    lines = ["Kullanıcının cümlesini aşağıdaki yeteneklerden BİRİNE bağla.",
             "Yetenekler:"]
    for item in capability_catalog.CATALOG:
        lines.append(f"- {item['intent']}: {item['does']} | gerekli: {', '.join(item['needs']) or 'yok'}"
                     f" | örnek: {item['examples'][0]}")
    lines.append("")
    lines.append(f'Cümle: "{text}"')
    lines.append("")
    lines.append('Yalnız şu JSON ile cevap ver: {"capability": "<ad>", "slots": {...}, "confidence": 0-1}')
    lines.append('Emin değilsen: {"capability": null, "confidence": 0}')
    lines.append("Alanlar: window (pencere adı), text (yazılacak metin), query (ekrandaki yazı), "
                 "path (dosya/klasör yolu), name (dosya adı), phrase (zamanlı iş cümlesi).")
    return "\n".join(lines)


def _ask_model(text: str) -> str | None:
    try:
        from modules import llm
        return llm.complete(_schema_prompt(text), purpose="capability") if hasattr(llm, "complete") else None
    except Exception:
        _record_failure("modules/capability_llm.py:_ask_model")
        return None


def _validate(payload: dict, text: str) -> dict:
    capability = payload.get("capability")
    entry = capability_catalog.by_intent(str(capability or ""))
    if entry is None:
        return {"status": "uncertain", "capability": None, "text": text, "via": "model"}
    slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
    slots = {key: value for key, value in slots.items() if isinstance(value, str) and value.strip()}
    if "window" not in slots:
        guess = capability_brain.find_window_word(text)
        if guess:
            slots["window"] = guess
    if "path" in slots:
        from pathlib import Path
        if not Path(slots["path"]).expanduser().exists():
            slots.pop("path")          # var olmayan yol kabul edilmez
    missing = [slot for slot in entry["needs"] if not slots.get(slot)]
    if missing:
        return {"status": "need", "capability": entry["intent"], "slots": slots,
                "missing": missing, "text": text, "via": "model"}
    return {"status": "ok", "capability": entry["intent"], "slots": slots, "text": text, "via": "model"}


def resolve(text: str) -> dict:
    """Katalog yetmediğinde modelden destek alır; her durumda doğrulanmış sonuç döner."""
    raw = str(text or "").strip()
    if not raw:
        return {"status": "none", "capability": None, "text": raw}
    cached = _cache.get(raw)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    answer = _ask_model(raw)
    if not answer:
        return {"status": "uncertain", "capability": None, "text": raw, "via": "model"}
    payload = _parse(answer)
    if payload is None:
        return {"status": "uncertain", "capability": None, "text": raw, "via": "model"}
    result = _validate(payload, raw)
    _cache[raw] = (time.time(), result)
    return result


def _parse(answer: str) -> dict | None:
    try:
        start = answer.index("{")
        end = answer.rindex("}") + 1
        data = json.loads(answer[start:end])
    except Exception:
        _record_failure("modules/capability_llm.py:_parse")
        return None
    if not isinstance(data, dict):
        return None
    try:
        if float(data.get("confidence") or 0) < 0.5:
            return None
    except (TypeError, ValueError):
        return None
    return data
