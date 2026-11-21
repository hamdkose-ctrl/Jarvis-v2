"""Kullanıcıyı yoran kalıpları cevaptan çıkarır; içeriği değiştirmez.

Canlı olay (22 Kasım 02:35): sohbet yolu işlem çalıştıramadığı halde cevap
"onay verir misin, yoksa kararı sana mı bırakalım" diye bitiyordu. Kullanıcı
"versem yapacak" sanıyor; yapamıyor. Bu kalıplar atılır — cevabın geri kalanı
aynen korunur, uydurma cümle eklenmez.
"""
from __future__ import annotations

import re

# Yalnız izin/onay dilenmesi ve kararı kullanıcıya atma kalıpları.
_BAIT = (
    r"onay\s+ver(ir|men)",
    r"onayl(ıyor|ar)\s*mısın",
    r"izin\s+ver(ir|men|irsen)",
    r"çalıştırayım\s*mı",
    r"çalıştırmamı\s+ister",
    r"kararı\s+sana\s+(mı\s+)?bırak",
    r"kararı\s+kullanıcıya\s+bırak",
    r"devam\s+edeyim\s+mi\s*\?",
)
_PATTERN = re.compile("|".join(_BAIT), re.IGNORECASE)
# Cümle sonu: nokta/soru/ünlem; kısaltma yok sayılır.
_CUMLE = re.compile(r"[^.!?]+[.!?]?", re.S)


def strip_permission_bait(text: str) -> str:
    """İzin/onay dilenen cümleleri atar; kalan metni aynen döndürür."""
    if not isinstance(text, str) or not text.strip():
        return text
    kalan = [c for c in _CUMLE.findall(text) if not _PATTERN.search(c)]
    temiz = "".join(kalan).strip()
    temiz = re.sub(r"\s+", " ", temiz)
    if temiz:
        return temiz
    # Her şey atıldıysa boş cevap verme: kısa ve dürüst bir sınır cümlesi.
    return "Tamam."
