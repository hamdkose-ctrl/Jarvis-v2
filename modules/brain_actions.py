"""Brain-owned action-verb rule: does an utterance END with an imperative/request action verb?

Single definition. Understanding exposes it as the ``ENDS_WITH_ACTION`` reason code and uses
``action_request`` for the Capability/Chat decision, so Core callers (e.g. a goal waiting for an
answer) never re-run a regex of their own. The legacy router chain was retired in PR10c.
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
    """Definition/date/why/yes-no questions ask for an answer, not for execution.

    'kur', 'aç' ve 'yaz' kökleri aynı zamanda isimdir ("kur artınca", "açıklama", "yazı"), bu
    yüzden neden sorusu yalnız soru işaretli cümlede eylem sayılmaz: "Kur artınca ithal ürün niye
    pahalanıyor?" açıklama, "Bunun neden bozulduğunu incele" ise icra isteğidir."""
    low = _fold(text)
    why_question = '?' in str(text or '') and bool(re.search(r'\b(?:niye|neden|nicin|ne yuzden)\b', low))
    return why_question or bool(
        re.search(r'\b(?:nedir|nelerdir|ne demek\w*|ne zaman|kimdir|nerededir|nereye|nerede|nereden|ne anlama gel\w*|anlami ne)\b', low)
        or re.search(r'\s(?:mi|mu)$', low))


def ends_with_action(text: str) -> bool:
    """Soru bekleyen bir hedefe gelen cevap, sonu eylem fiiliyle biten yeni bir istek mi?"""
    low = _fold(text)
    if instructional_question(text) or informational_question(text):
        return False
    return any(m.end() == len(low) for m in _ACTION.finditer(low))


def ambiguous_reference(text: str) -> bool:
    """Yalnız deiktik sözcükten oluşan cümle ("bunu", "onu şunu hallet") hedef taşımaz."""
    return bool(re.fullmatch(r'(?:bunu|onu|sunu|boyle|oyle)(?:\s+\w+){0,2}', _fold(text)))


def action_request(text: str) -> bool:
    """Eylem fiili taşıyan icra isteği: açıklama soruları ve çıplak deiktikler değildir.

    Kaldırılan legacy çalışma-modu sınıflandırıcısının `action_request` hükmünün yerine geçer;
    turun yetenek mi sohbet mi olduğuna yalnız Understanding karar verir, bu yüzden ikinci bir
    sınıflandırıcı ham metinden niyet türetmek için bu kuralı yeniden yazamaz."""
    if ambiguous_reference(text) or instructional_question(text) or informational_question(text):
        return False
    return bool(_ACTION.search(_fold(text)))
