"""Yanlış duyulan sözler listesi ("duyulan=asıl") — yaşayan STT düzeltme sözleşmesi.

Liste kullanıcının Ayarlar › Ses › Yanlış duyulanlar alanındadır ve `learn_mishearing`
ona yeni çift ekler. Eski Gemini Live yığını bu yardımcıları kendi içinde
kullanıyordu; Live emekli olduğunda yaşayan tek caller'lar (modules/learning.py ve
arayüz ayarları) burada kalır. Bu modül hiçbir ses ya da tanım motoru çağırmaz.
"""
from __future__ import annotations

import re

# Yazıya dökmenin sık yanlış yazdığı ifadeler -> asıl söylenen ("yanlış=doğru"). Ses sekmesinden değiştirilebilir (stt_fixes).
DEFAULT_FIXES = ("die milch=Steam, city mall=Steam, ella viste=Hey Jarvis, él duerme=Hey Jarvis, cch=sesi aç, "
                 "tack så mycket=takvimi aç")


def parse_fixes(text: str | None = None) -> list[tuple[str, str]]:
    """Kayıtlı listeyi (metin) temiz 'duyulan=asıl' çiftlerine çevirir; boş/eksiz parçalar düşer."""
    raw = DEFAULT_FIXES if text is None else text
    pairs = []
    for item in re.split(r"[,;\n]", raw):
        if "=" in item:
            a, b = item.split("=", 1)
            a, b = " ".join(a.split()), " ".join(b.split())
            if a and b:
                pairs.append((a, b))
    return pairs


def format_fixes(pairs) -> str:
    """Çiftleri arayüzün ve kayıtlı ayarın beklediği tek satırlık forma çevirir."""
    return ", ".join(f"{wrong}={right}" for wrong, right in pairs)
