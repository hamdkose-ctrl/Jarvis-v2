"""Jarvis için döviz modülü (dolar ve euro kuru)."""
import requests

URL = "https://open.er-api.com/v6/latest/USD"


def _fmt(value: float) -> str:
    """34.5231 -> '34,52' (sesli okunurken doğru çıksın)."""
    return f"{value:.2f}".replace(".", ",")


def get_live_rate(asset_type: str) -> str:
    """Dolar ya da euro kurunu Türk Lirası cinsinden döndürür."""
    try:
        response = requests.get(URL, timeout=7)
        response.raise_for_status()
        rates = response.json().get("rates", {})

        try_rate = float(rates.get("TRY", 0))
        if try_rate == 0:
            return "Türk Lirası kur verisi şu an alınamadı."

        asset = asset_type.lower()
        if "dolar" in asset:
            return f"Güncel dolar kuru {_fmt(try_rate)} Türk Lirası."

        if "euro" in asset:
            eur_rate = float(rates.get("EUR", 0))
            if eur_rate == 0:
                return "Euro kuru şu an alınamadı."
            return f"Güncel euro kuru {_fmt(try_rate / eur_rate)} Türk Lirası."

        return "İstediğiniz para birimi çözümlenemedi."

    except requests.RequestException as e:
        print(f"[finance] ağ hatası: {e}")
        return "Döviz kurlarına şu an ulaşamadım."
    except (ValueError, TypeError) as e:
        print(f"[finance] veri hatası: {e}")
        return "Döviz verisi okunamadı."
