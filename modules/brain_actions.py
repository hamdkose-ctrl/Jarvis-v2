"""Brain-owned action-verb rule: does an utterance END with an imperative/request action verb?

Single definition. Understanding exposes it as the ``ENDS_WITH_ACTION`` reason code so Core callers
(e.g. a goal waiting for an answer) never re-run a regex of their own. ``work_modes`` imports these
names for the Live-only legacy path until PR9 deletes it.
"""
from __future__ import annotations
import re


def _fold(text: str) -> str:
    return ' '.join(str(text or '').casefold().translate(str.maketrans('çğıöşü', 'cgiosu')).replace('ı', 'i').split()).strip(' .!?')


def instructional_question(text: str) -> bool:
    """Questions asking how to do something are explanations, not execution requests."""
    low = _fold(text)
    return bool(re.search(r'\b(?:nasil|ne sekilde|hangi komutla|yolu nedir|yontemi nedir)\b', low))


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


def ends_with_action(text: str) -> bool:
    """Soru bekleyen bir hedefe gelen cevap, sonu eylem fiiliyle biten yeni bir istek mi?"""
    low = _fold(text)
    if instructional_question(text) or informational_question(text):
        return False
    return any(m.end() == len(low) for m in _ACTION.finditer(low))
