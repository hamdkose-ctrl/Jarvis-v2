"""Deterministik çalışma modu: normal isteklerde yap, formal spec yalnız açıkça istenirse.

Bu sınıflandırıcı araç seçmez. Router'ın LLM cevabını denetlemesi için üst düzey kullanıcı
niyetini söyler; böylece eylem istekleri model tarafından yanlışlıkla sohbet olarak bırakılmaz.
"""
from __future__ import annotations
import re


def _fold(text: str) -> str:
    return ' '.join(str(text or '').casefold().translate(str.maketrans('çğıöşü', 'cgiosu')).replace('ı', 'i').split()).strip(' .!?')


def explicit_spec(text: str) -> bool:
    low = _fold(text)
    return bool(re.search(
        r'\b(?:spec|specification|spesifikasyon|gereksinim(?:ler)? dokumani|requirements? document|formal gereksinim|tasarim dokumani)\b',
        low,
    ))


def ambiguous_reference(text: str) -> bool:
    low = _fold(text)
    return bool(re.fullmatch(r'(?:bunu|onu|sunu|boyle|oyle)(?:\s+\w+){0,2}', low))


def fresh_external(text: str) -> bool:
    low = _fold(text)
    topic = bool(re.search(r'\b(?:haber\w*|gelisme\w*|fiyat\w*|kur|dolar|euro|altin|borsa|piyasa|skor\w*|hava)\b', low))
    fresh = bool(re.search(r'\b(?:guncel|son|bugun|su an|simdi|latest|recent|yeni|ne kadar|kac)\b', low))
    return topic and fresh


def action_request(text: str) -> bool:
    low = _fold(text)
    if ambiguous_reference(text):
        return False
    if fresh_external(text):
        return True
    return bool(re.search(
        r'\b(?:ac|baslat|calistir|duzelt|gelistir|iyilestir|uygula|sil|tasi|kaydet|kur|yukle|yap|'
        r'hazirla|olustur|arastir|incele|listele|kontrol et|kapat|degistir|ayarla|yaz|gonder|cevir|donustur)\w*\b',
        low,
    ))


def classify(text: str) -> str:
    """Return spec, do or chat. Spec is opt-in; actionable requests are do."""
    if explicit_spec(text):
        return 'spec'
    if action_request(text):
        return 'do'
    return 'chat'
