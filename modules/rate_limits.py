"""Ölçülmüş sağlayıcı hız tavanları (uydurma sayı yok).

Kaynak: kullanıcının **kendi** Google AI Studio "Rate Limit" sayfası (26 Kasım 2026,
Free tier, proje `Default Gemini Project`). Sayfa ekran görüntüsünden okundu:

    Gemini 3.5 Flash Lite : RPM 17 / 15   · TPM 186.7K / 250K
    Gemini 2.5 Flash TTS  : RPM 5 / 3     · TPM 165 / 10K
    Gemini 3.6 Flash      : RPM 2 / 5     · TPM 3.85K / 250K

Sol sayı **o hesabın gördüğü tepe**, sağ sayı **tavan**. Tavanlar buraya yalnız bu
kaynaktan girer; doğrulanmamış bir model adı için fren **kapalı** kalır (uydurma limit
yok kuralı). Fren bu dosyayı okur; sayı yoksa bekleme yapılmaz.
"""
from __future__ import annotations

# model adı -> (dakikalık istek tavanı, dakikalık token tavanı)
LIMITS: dict[str, tuple[int, int]] = {
    "gemini-3.5-flash-lite": (15, 250_000),
    "gemini-2.5-flash-tts": (3, 10_000),
    "gemini-3.6-flash": (5, 250_000),
}

# Tavanın bu oranına ulaşınca bekleme başlar: son isteğin tavanı aşmasını beklemeyiz.
HEADROOM = 0.9


def limit_for(model: str) -> tuple[int, int] | None:
    """Modelin (RPM, TPM) tavanı; doğrulanmamış modelde None → fren kapalı."""
    key = str(model or "").strip().casefold()
    for name, pair in LIMITS.items():
        if name in key or key in name:
            return pair
    return None


def should_wait(rpm: int, tpm: int, model: str) -> bool:
    """Son 60 saniyedeki kullanım tavanın `HEADROOM` oranına ulaştı mı?"""
    pair = limit_for(model)
    if pair is None:
        return False
    limit_rpm, limit_tpm = pair
    return rpm >= limit_rpm * HEADROOM or tpm >= limit_tpm * HEADROOM
