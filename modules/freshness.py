"""Güncellik kuralı: hangi istek taze dış veri (haber, kur, borsa, skor, isteğe bağlı hava) gerektirir.

Tek tanım; router (görev yürütücüsüne devir) ve work_modes (eylem mi sohbet mi) ikisi de buradan okur.
Hava, router'da kendi 'weather' niyetine gider; bu yüzden yalnız weather=True ile konu sayılır.
"""
import re


def _fold(text):
    return ' '.join(str(text or '').casefold().translate(str.maketrans('çğıöşü', 'cgiosu')).split())


def fresh_request(text, weather=False):
    low = _fold(text)
    topics = r'haber\w*|gelisme\w*|fiyat\w*|kur|dolar|euro|altin|borsa|piyasa|skor\w*|mac sonucu\w*'
    if weather:
        topics += r'|hava'
    topic = bool(re.search(r'\b(?:' + topics + r')\b', low))
    fresh = bool(re.search(r'\b(?:guncel|bugunku|mevcut|son|bugun|su an|simdi|latest|recent|yeni|ne kadar|kac)\b', low))
    implicit_news = bool(re.search(r'\b(?:haber\w*|gelisme\w*)\b', low)
                         and re.search(r'\b(?:neler|nelerdir|ne var|ozet\w*|anlat\w*|goster\w*|arastir\w*)\b', low))
    market_now = bool(re.search(r'\b(?:dolar|euro|altin|borsa|skor\w*)\b', low)
                      and re.search(r'\b(?:kac|ne kadar|durum\w*|sonuc\w*)\b', low))
    # Tanım kalıbı ("nedir", "ne demek", "tarihçe") yalnız açık tazelik işareti yoksa statik der;
    # "bugünkü dolar kuru nedir" gibi bir isteği bastırmaz.
    if re.search(r'\b(?:nedir|ne demek|tarihce)\b', low) and not (topic and fresh):
        return False
    return topic and (fresh or implicit_news or market_now)
