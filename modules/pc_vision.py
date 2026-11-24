"""Ekranda yazıyı bulma (Windows OCR) — PC ajanının gözü.

Neden: bazı uygulamalar (Hesap Makinesi) düğmelerini erişilebilirlik katmanında
göstermiyor; klavye karşılığı da yoksa ajan "bulamadım" deyip duruyordu. Windows'un
kendi OCR motoru (Türkçe paketi kurulu) ekrandaki yazının **konumunu** verir.

Kurallar:
- Yalnız **okur**: ekran görüntüsü alır, yazıyı arar. Tıklama `pc_hands` tarafında
  ve yalnız onaydan sonra yapılır.
- Eşleşme birden fazlaysa **tahmin etmez**: adayları döndürür, çağıran sorar.
- Motor yoksa/başarısızsa `None`: ajan "göremedim" der, uydurmaz.
"""
from __future__ import annotations

import time

from modules.diagnostics import record_failure as _record_failure

MIN_CONFIDENCE = 0.4


def _fold(text: str) -> str:
    table = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
    return " ".join(str(text or "").casefold().translate(table).split())


def available() -> bool:
    try:
        from winsdk.windows.media.ocr import OcrEngine
        return bool(OcrEngine.available_recognizer_languages)
    except Exception:
        _record_failure("modules/pc_vision.py:available")
        return False


def _engine():
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    langs = list(OcrEngine.available_recognizer_languages)
    preferred = next((l for l in langs if str(l.language_tag).startswith("tr")), langs[0])
    return OcrEngine.try_create_from_language(Language(preferred.language_tag))


async def _recognize(bitmap) -> list[dict]:
    engine = _engine()
    if engine is None:
        return []
    result = await engine.recognize_async(bitmap)
    words = []
    for line in result.lines:
        for word in line.words:
            box = word.bounding_rect
            words.append({"text": word.text,
                          "x": int(box.x + box.width / 2),
                          "y": int(box.y + box.height / 2),
                          "w": int(box.width), "h": int(box.height)})
    return words


def read_screen() -> list[dict]:
    """Ekrandaki tüm kelimeleri konumlarıyla döndürür (boş liste = okuyamadım)."""
    try:
        import asyncio
        from PIL import ImageGrab
        from winsdk.windows.storage.streams import DataWriter
        from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode

        image = ImageGrab.grab().convert("RGBA")
        width, height = image.size
        writer = DataWriter()
        writer.write_bytes(image.tobytes())
        # detach_buffer() akıştan ÖNCE çağrılmalı: detach_stream() sonrası
        # tampon None dönerdi (canlı hata).
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.RGBA8, width, height, BitmapAlphaMode.PREMULTIPLIED)
        return asyncio.run(_recognize(bitmap))
    except Exception:
        _record_failure("modules/pc_vision.py:read_screen")
        return []


def find_text(query: str, *, words: list[dict] | None = None) -> dict:
    """Ekranda yazıyı arar: tek eşleşme → konum, çok → adaylar, yok → None."""
    needle = _fold(query)
    if not needle:
        return {"status": "empty", "words": []}
    found = read_screen() if words is None else words
    hits = [w for w in found if needle in _fold(w["text"])]
    if not hits:
        return {"status": "missing", "words": []}
    if len(hits) > 1:
        return {"status": "ambiguous", "words": hits[:5]}
    return {"status": "ok", "point": {"x": hits[0]["x"], "y": hits[0]["y"]}, "word": hits[0]}


def describe(query: str) -> str:
    """Kullanıcıya tek cümle: buldum / birden fazla / göremedim."""
    result = find_text(query)
    if result["status"] == "ok":
        point = result["point"]
        return f"Ekranda “{query}” yazısını buldum ({point['x']},{point['y']}). Onaylarsan oraya basarım."
    if result["status"] == "ambiguous":
        names = "; ".join(f"“{w['text']}” ({w['x']},{w['y']})" for w in result["words"][:4])
        return f"Ekranda “{query}” için {len(result['words'])} eşleşme var: {names}. Hangisine basayım?"
    return f"Ekranda “{query}” yazısını göremedim."
