"""Deterministik çalışma modu: normal isteklerde yap, formal spec yalnız açıkça istenirse.

Bu sınıflandırıcı araç seçmez. Router'ın LLM cevabını denetlemesi için üst düzey kullanıcı
niyetini söyler; böylece eylem istekleri model tarafından yanlışlıkla sohbet olarak bırakılmaz.
"""
from __future__ import annotations
import re

from modules import freshness


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


def instructional_question(text: str) -> bool:
    """Questions asking how to do something are explanations, not execution requests."""
    low = _fold(text)
    return bool(re.search(r'\b(?:nasil|ne sekilde|hangi komutla|yolu nedir|yontemi nedir)\b', low))


def fresh_external(text: str) -> bool:
    return freshness.fresh_request(text, weather=True)


# Fiil kökü tek başına yetmez: "yap" kökü "yapay", "kur" kökü "kurban/kural", "aç" kökü "acaba/açıklar"
# sözcüklerinin de başıdır. İstek sayılmak için kökün ardından yalnız istek/emir/bağlaç ekleri gelebilir.
_ROOTS = (r'(?:ac|baslat|calistir|duzelt|duzenle|gelistir|iyilestir|uygula|sil|tasi|kur|yukle|yap|hazirla|olustur|'
          r'arastir|incele|listele|kapat|degistir|ayarla|yaz|gonder|cevir|donustur)')
_REQUEST_SUFFIX = (r'(?:|sana|sene|y?[iu]n|y?[iu]niz|y?[iu]p|y?[ae]bilir m[iu]\w*|y?[aeiu]?r m[iu]\w*|'
                   r'y?[ae]lim|m[ae]k? ist\w*|m[ae]n[iu] ist\w*|m[ae]l[iu]s[iu]n)')
_ACTION = re.compile(r'\b(?:' + _ROOTS + _REQUEST_SUFFIX + r'|(?:kontrol |kayd|devam )(?:et|etsene|eder m[iu]\w*|edip|edin\w*|'
                     r'edebilir m[iu]\w*|etmek ist\w*|etmeni ist\w*))(?=\s|$|[,;:.!?])')


def informational_question(text: str) -> bool:
    """Definition/date/yes-no questions ask for an answer, not for execution."""
    low = _fold(text)
    return bool(re.search(r'\b(?:nedir|nelerdir|ne demek\w*|ne zaman|kimdir|nerededir|nereye|nerede|nereden|ne anlama gel\w*|anlami ne)\b', low)
                or re.search(r'\s(?:mi|mu)$', low))


def action_request(text: str) -> bool:
    low = _fold(text)
    if ambiguous_reference(text) or instructional_question(text):
        return False
    if fresh_external(text):
        return True
    if informational_question(text):
        return False
    return bool(_ACTION.search(low))


def ends_with_action(text: str) -> bool:
    """Soru bekleyen bir hedefe gelen cevap, sonu eylem fiiliyle biten yeni bir istek mi?"""
    low = _fold(text)
    if instructional_question(text) or informational_question(text):
        return False
    return any(m.end() == len(low) for m in _ACTION.finditer(low))


def classify(text: str) -> str:
    """Return spec, do or chat. Spec is opt-in; actionable requests are do."""
    if explicit_spec(text):
        return 'spec'
    if action_request(text):
        return 'do'
    return 'chat'
