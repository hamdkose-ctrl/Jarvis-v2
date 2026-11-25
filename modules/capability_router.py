"""TEK beyin: cümleyi yeteneğe bağlayan tek karar noktası.

Kullanıcı kararı: "beyin kelimeye dayalı olmasın, çoklu beyin istemiyorum."
Bu yüzden karar **tek yerde** (burası) ve **anlam üzerinden** verilir:

- Yetki: yalnız bu modül "ne yapılacak" der. `fast_commands` / `capability_brain`
  burada **beyin değil**, yalnız model yoksa devreye giren **çevrimdışı yedek**.
- Anlam: model, cümlenin ne istediğini seçer (katalog = veri, beyin değil).
- Bağlam: `context` ile önceki adım/pencer/onay aktarılır; "bunu" gibi ifadeler
  tahmin edilmez, bağlamdan çözülür veya tek soru sorulur.
- Güvenlik: model yapmaz, yalnız seçer; doğrulama burada (katalog üyeliği, alan
  varlığı, yol kontrolü). Emin değilse `ask`/`none` döner ve **iş yapılmaz**.
"""
from __future__ import annotations

from modules import capability_catalog

CONTEXT_KEYS = ("window", "last_action", "pending", "text")


def route(text: str, context: dict | None = None) -> dict:
    """Tek karar noktası. Döner: {status: run|ask|none, capability, slots, source, text}."""
    raw = str(text or "").strip()
    if not raw:
        return _none(raw)
    context = {key: context[key] for key in CONTEXT_KEYS if context and context.get(key)}
    meaning = _meaning(raw, context)
    if meaning["status"] == "run":
        return meaning
    if meaning["status"] == "ask":
        return meaning
    # Model anlamadı: çevrimdışı yedek yalnız **bilinen güvenli** işlerde devreye girer.
    offline = _offline(raw)
    if offline:
        return offline
    return _none(raw, meaning.get("candidates"))


def _meaning(raw: str, context: dict) -> dict:
    from modules import capability_llm
    result = capability_llm.resolve(raw, context=context or None)
    status = result.get("status")
    if status == "ok":
        return {"status": "run", "capability": result["capability"], "slots": result.get("slots") or {},
                "source": "brain", "text": raw, "confidence": result.get("confidence")}
    if status == "need":
        return {"status": "ask", "capability": result.get("capability"), "slots": result.get("slots") or {},
                "missing": result.get("missing") or [], "source": "brain", "text": raw}
    return {"status": "none", "candidates": result.get("candidates") or [], "text": raw}


def _offline(raw: str) -> dict | None:
    """Model yokken yalnız kesin bilinen kalıplar; bu bir beyin değil, yedek."""
    from modules import capability_brain, fast_commands
    fast = fast_commands.resolve(raw)
    if fast:
        return {"status": "run", "capability": fast[0], "slots": dict(fast[1]),
                "source": "offline", "text": raw}
    result = capability_brain.resolve(raw)
    if result.get("status") == "ok" and result.get("via") == "catalog":
        return {"status": "run", "capability": result["capability"], "slots": result.get("slots") or {},
                "source": "offline", "text": raw}
    if result.get("status") == "need":
        return {"status": "ask", "capability": result.get("capability"), "slots": result.get("slots") or {},
                "missing": result.get("missing") or [], "source": "offline", "text": raw}
    return None


def _none(raw: str, candidates=None) -> dict:
    return {"status": "none", "capability": None, "slots": {}, "source": "brain",
            "text": raw, "candidates": candidates or []}


def describe() -> str:
    """Kullanıcıya 'ne yapabilirim' demek için katalogdan tek satır liste."""
    return "; ".join(item["examples"][0] for item in capability_catalog.CATALOG)
