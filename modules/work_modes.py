"""Deterministik çalışma modu: normal isteklerde yap, formal spec yalnız açıkça istenirse.

Bu sınıflandırıcı araç seçmez. Router'ın LLM cevabını denetlemesi için üst düzey kullanıcı
niyetini söyler; böylece eylem istekleri model tarafından yanlışlıkla sohbet olarak bırakılmaz.
"""
from __future__ import annotations
import re

from modules import freshness
from modules.brain_actions import _ACTION, ends_with_action, informational_question, instructional_question  # noqa: F401  (tek tanım Brain'de)


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
    return freshness.fresh_request(text, weather=True)


def action_request(text: str) -> bool:
    low = _fold(text)
    if ambiguous_reference(text) or instructional_question(text):
        return False
    if fresh_external(text):
        return True
    if informational_question(text):
        return False
    return bool(_ACTION.search(low))


def classify(text: str) -> str:
    """Return spec, do or chat. Spec is opt-in; actionable requests are do."""
    if explicit_spec(text):
        return 'spec'
    if action_request(text):
        return 'do'
    return 'chat'
