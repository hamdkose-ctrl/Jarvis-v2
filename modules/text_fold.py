"""Türkçe metin katlama: tek tanım.

`str.casefold()` ve `str.lower()` Türkçe `İ` harfini `i` + birleşik nokta
(U+0307) yapar: "İPTAL".casefold() -> "i̇ptal". Bu yüzden büyük harfle söylenen
komutlar kapalı sözlüklerle eşleşmiyordu (canlı hata 22 Kasım 2026: "HEDEF
İPTAL" iptal etmedi, yeni iş açtı). Bütün komut eşleşmeleri bu yardımcıyı
kullanır; içerik aramaları kendi metnini olduğu gibi işler.
"""
from __future__ import annotations

_FOLD = str.maketrans("İI", "iı")
_TRAILING = " .!?;:,"


def fold(value: object) -> str:
    """Türkçe büyük harfleri doğru küçültür, boşlukları sadeleştirir."""
    if value is None:
        return ""
    return " ".join(str(value).translate(_FOLD).lower().split())


def fold_command(value: object) -> str:
    """Kapalı sözlükle karşılaştırılacak komut metni: fold + uç noktalama temizliği."""
    return fold(value).strip(_TRAILING)
