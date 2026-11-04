"""Deterministic, non-authoritative Understanding proposal for canonical Brain v1.

This foundation consumes only caller-supplied canonical context, candidates,
resolved references, and the current user text. It does not read sources, mutate
state, run workers, grant authority, or wire itself into production routing.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from modules import typo
from modules.app_identities import verified_alias as _verified_app_alias
from modules.brain_actions import action_request, ends_with_action, instructional_question
from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextAction,
    ContextReference,
    ConversationRelation,
    EchoPreview,
    PendingOwner,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)


_CONTEXT_CONTROL = (
    "boşver",
    "bosver",
    "başka konu",
    "baska konu",
    "konuyu değiştir",
    "konuyu degistir",
)
_TOPIC_CHANGE = ("başka konu", "baska konu", "konuyu değiştir", "konuyu degistir")
_BOSVER = ("boşver", "bosver")
_COMMAND_TOKENS = (
    "göster",
    "goster",
    "aç",
    "ac",
    "kapat",
    "oluştur",
    "olustur",
    "hazırla",
    "hazirla",
    "karşılaştır",
    "karsilastir",
    "ara",
    "bul",
    "indir",
    "yükle",
    "yukle",
    "sil",
    "gönder",
    "gonder",
    "hatırlat",
    "hatirlat",
    "uyar",
    "planla",
    "listele",
    "özetle",
    "ozetle",
)
_READ_LIKE_TOKENS = (
    "göster",
    "goster",
    "aç",
    "ac",
    "bul",
    "listele",
    "özetle",
    "ozetle",
    "karşılaştır",
    "karsilastir",
)
_NOTE_DOMAIN_TOKENS = (
    "not",
    "notu",
    "notunu",
    "notum",
    "notumu",
    "notlar",
    "notları",
    "notlari",
    "notlarım",
    "notlarim",
    "notlarımı",
    "notlarimi",
)
_WEATHER_DOMAIN_TOKENS = ("hava", "havayı", "havayi", "havanın", "havanin")
_FILE_DOMAIN_TOKENS = (
    "dosya",
    "dosyayı",
    "dosyayi",
    "dosyasını",
    "dosyasini",
    "dosyalar",
    "dosyaları",
    "dosyalari",
    "dosyalarım",
    "dosyalarim",
    "dosyalarımı",
    "dosyalarimi",
    "word",
)
_PLURAL_REFERENCE_MARKERS = (
    " iki ",
    "ikisini",
    "bunları",
    "bunlari",
    "dosyaları",
    "dosyalari",
    "hepsini",
    "karşılaştır",
    "karsilastir",
)
_CURRENT_MARKERS = (
    "şu an",
    "su an",
    "şu anda",
    "su anda",
    "şimdi",
    "simdi",
    "bugün",
    "bugun",
    "güncel",
    "guncel",
    "mevcut durum",
    "yarın",
    "yarin",
)
_RECENT_MARKERS = (
    "son gün",
    "son gun",
    "son hafta",
    "son bir hafta",
    "son ay",
    "son zaman",
    "yakın zamanda",
    "yakin zamanda",
    "en son haber",
    "son haber",
)
_HISTORICAL_MARKERS = (
    "geçmiş",
    "gecmis",
    "eskiden",
    "tarihinde",
    "yılında",
    "yilinda",
    "tarihçe",
    "tarihce",
    "dün",
    "dun",
    "dünkü",
    "dunku",
)
_STATIC_MARKERS = (
    " nedir",
    " ne demek",
    " ne anlama gelir",
    " nasıl çalışır",
    " nasil calisir",
    " kimdir",
    " açıkla",
    " acikla",
    " açıklar",
    " anlat",
    " anlatır",
    # Güvenlik/risk sorusu bir açıklama isteğidir; işlemin kendisini başlatmaz (§PR3C-2).
    " güvenli mi",
    " güvenli midir",
    " riskli mi",
    " riskli midir",
    " riskleri neler",
    " riskleri nedir",
)
_PENDING_PROTOCOL_TOKENS = frozenset({"evet", "hayır", "hayir", "yes", "no"})
_GENERIC_CHAT = ("merhaba", "selam", "nasılsın", "nasilsin", "teşekkür", "tesekkur")

# Advisory mode is a natural-language choice, so its lexicon belongs to understanding.
# The advisor modules keep only schema validation and rendering.
ADVISORY_DECISION = "decision"
ADVISORY_CRITIQUE = "critique"
ADVISORY_GUIDANCE = "guidance"
ADVISORY_ARGUMENT_KEY = "advisory"
ADVISORY_MODES = frozenset({ADVISORY_DECISION, ADVISORY_CRITIQUE, ADVISORY_GUIDANCE})
_ADVISORY_DECISION = re.compile(
    r"\b(?:hangisi\w*|hangisini|seçenek\w*|secenek\w*|tercih\s+et\w*|tercihim\w*|"
    r"karar\s+ver(?!di|dik|din)\w*|karar\w*\s+veremiyorum|karşılaştır\w*|karsilastir\w*|"
    r"artı\s*(?:ve\s*)?eksi\w*|arti\s*(?:ve\s*)?eksi\w*|avantaj\w*|dezavantaj\w*|pro.?con\w*)",
    re.I,
)
# "A mı B mi", "gideyim mi kalayım mı": two yes/no particles = a choice.
_ADVISORY_CHOICE = re.compile(r"\bm[ıiuü]\b.+\bm[ıiuü]\b", re.I)
_ADVISORY_CRITIQUE = re.compile(
    r"\b(?:eleştir\w*|elestir\w*|zayıf\s+(?:nokta|yan|yön)\w*|zayif\s+(?:nokta|yan|yon)\w*|"
    r"dürüstçe|durustce|dürüst\s+ol\w*|durust\s+ol\w*|açık\s+sözlü|acik\s+sozlu|"
    r"eksikler\w*|eksik\s+(?:yan|yön|yon|nokta)\w*|neresi\s+(?:kötü|kotu|eksik|zayıf|zayif)|"
    r"nerede\s+hata\s+yap\w*)",
    re.I,
)
_ADVISORY_GUIDANCE = re.compile(
    r"\b(?:adım\s+adım|adim\s+adim|rehber\w*|yol\s+göster\w*|yol\s+goster\w*|"
    r"nasıl\s+(?:yap|başla|basla|ilerle|hazırla|hazirla|kur|öğren|ogren)\w*|"
    r"nasil\s+(?:yap|basla|ilerle|hazirla|kur|ogren)\w*|"
    r"ne\s+yapmal[ıi]y[ıi]m|ne\s+yapmam\s+(?:lazım|lazim|gerek)\w*|"
    r"tavsiye\w*|önerin\s+ne|onerin\s+ne|ne\s+önerirsin|ne\s+onerirsin)",
    re.I,
)


def _advisory_request(text: str) -> str | None:
    if _ADVISORY_DECISION.search(text) or _ADVISORY_CHOICE.search(text):
        return ADVISORY_DECISION
    if _ADVISORY_CRITIQUE.search(text):
        return ADVISORY_CRITIQUE
    if _ADVISORY_GUIDANCE.search(text):
        return ADVISORY_GUIDANCE
    return None


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    # Turkish dotted/dotless I must be mapped before casefold ("İzmir" -> "izmir", not "i̇zmir").
    return " ".join(value.replace("İ", "i").replace("I", "ı").casefold().strip().split())


def _reference_tuple(name: str, value: object, owner: str) -> tuple[ContextReference, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} tuple olmalı.")
    rows = tuple(value)
    for row in rows:
        if not isinstance(row, ContextReference):
            raise ValueError(f"{name} yalnız ContextReference taşımalı.")
        if row.owner != owner:
            raise ValueError(f"{name} başka owner referansı taşıyamaz.")
    return rows


def _require_reference_candidates(
    candidates: tuple[ContextReference, ...],
    references: tuple[ContextReference, ...],
) -> None:
    for reference in references:
        if not any(reference is candidate for candidate in candidates):
            raise ValueError("references yalnız supplied candidate nesnelerinden gelmeli.")


def _contains_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def _bounded_token(text: str, token: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


def _contains_command_token(text: str, tokens: Iterable[str] = _COMMAND_TOKENS) -> bool:
    return any(_bounded_token(text, token) for token in tokens)


def _quoted_terms(text: str) -> tuple[str, ...]:
    return tuple(match.strip() for match in re.findall(r"[\"“]([^\"”]+)[\"”]", text) if match.strip())


def _is_literal_command_usage(text: str) -> bool:
    quoted = _quoted_terms(text)
    if not quoted or not any(term in _COMMAND_TOKENS for term in quoted):
        return False
    literal_markers = (
        "metinde",
        "kelimesi",
        "kelimesini",
        "sözcüğü",
        "sözcüğünü",
        "sozcugu",
        "sozcugunu",
        "komutu",
        "yazıyor",
        "yaziyor",
        " yaz",
    )
    return _contains_any(f" {text}", literal_markers)


def _is_meta_language(text: str) -> bool:
    if re.fullmatch(r"(?:ara|bul|araştır|arastir)\s+ne demek\??", text) is not None:
        return True
    if re.fullmatch(
        r"\S+\s+(?:kelimesi|sözcüğü|sozcugu|fiili|sayısı|sayisi)\s+"
        r"(?:ne demek|ne anlama gelir|nedir)\??",
        text,
    ) is not None:
        return True
    if re.fullmatch(
        r"\S+\s+(?:kelimesini|sözcüğünü|sozcugunu)\s+\S+\s+(?:çevir|cevir)\??",
        text,
    ) is not None:
        return True
    if re.fullmatch(r"\S+\s+model\s+(?:ne demek|nedir)\??", text) is not None:
        return True
    if " ifadesi " in f" {text} " and re.search(
        r"(?:ne demek|ne anlama gelir|nedir|kaç günü anlatır|kac gunu anlatir)\??$",
        text,
    ) is not None:
        return True
    if " olmayan " in f" {text} " and re.search(r"(?:ne demek|ne anlama gelir|nedir)\??$", text) is not None:
        return True
    if _is_literal_command_usage(text) and re.search(r"(?:ne demek|ne anlama gelir|nedir)\??$", text) is not None:
        return True
    return False


def _is_bosver_control(text: str) -> bool:
    if _is_meta_language(text):
        return False
    return any(re.match(rf"^{re.escape(signal)}(?:$|[\s,;.!])", text) is not None for signal in _BOSVER)


def _is_context_control(text: str) -> bool:
    return _is_bosver_control(text) or text in _TOPIC_CHANGE


def _is_topic_change(text: str) -> bool:
    return text in _TOPIC_CHANGE


def _replacement_parts(text: str) -> tuple[str, str] | None:
    if "?" in text:
        return None
    cleaned = text.strip().rstrip(".!").strip()
    had_negative_prefix = False
    prefix = re.match(r"^(?:hayır|hayir),?\s+", cleaned)
    if prefix is not None:
        had_negative_prefix = True
        cleaned = cleaned[prefix.end():].strip()
    parts = re.split(r"\s+(?:değil|degil)\s+", cleaned, maxsplit=1)
    if len(parts) != 2:
        return None
    rejected, replacement = (part.strip() for part in parts)
    if not rejected or not replacement:
        return None
    rejected_words = rejected.split()
    replacement_words = replacement.split()
    if had_negative_prefix:
        if 1 <= len(rejected_words) <= 3 and 1 <= len(replacement_words) <= 3:
            return rejected, replacement
        return None
    if len(rejected_words) == 1 and len(replacement_words) == 1:
        return rejected, replacement
    return None


def _is_correction(text: str) -> bool:
    if _is_bosver_control(text):
        return True
    return _replacement_parts(text) is not None


def _looks_like_capability(text: str) -> bool:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    return _contains_command_token(text)


def _has_read_like_command(text: str) -> bool:
    return _contains_command_token(text, _READ_LIKE_TOKENS)


def _plural_reference_intent(text: str) -> bool:
    padded = f" {text} "
    return _contains_any(padded, _PLURAL_REFERENCE_MARKERS)


def _temporal_need(text: str) -> TemporalNeed:
    if _is_meta_language(text):
        return TemporalNeed.STATIC
    if _contains_any(text, _CURRENT_MARKERS):
        return TemporalNeed.CURRENT
    if _contains_any(text, _RECENT_MARKERS):
        return TemporalNeed.RECENT
    if _contains_any(text, _HISTORICAL_MARKERS) or re.search(r"\b(?:1\d{3}|20\d{2}|2100)\b", text):
        return TemporalNeed.HISTORICAL
    padded = f" {text}"
    if _contains_any(padded, _STATIC_MARKERS):
        return TemporalNeed.STATIC
    return TemporalNeed.UNSURE


def _contains_domain_token(text: str, tokens: Iterable[str]) -> bool:
    return any(_bounded_token(text, token) for token in tokens)


# Ekli/bozuk yazımlı belge biçimi ("pdfyi", "worde") tek başına dosya alanı değildir; alan ancak
# kaynak ve hedef biçim aynı dönüştürme cümlesinde geçince doğar ("pdfyi worde çevir"). Tek biçim
# sözcüğü taşıyan "bunu pdf'e çevir" eski sahibinde kalır.
_FILE_DOCUMENT_FORMAT = re.compile(
    r"(?<!\w)(pdf|docx?|txt|md|csv|xlsx?|pptx?|word|excel)"
    r"(?:['’]?(?:y?[ıiuü]|y?[ea]|n[ıiuü]))?(?!\w)",
    re.I,
)


def _has_file_domain(text: str) -> bool:
    if _contains_domain_token(text, _FILE_DOMAIN_TOKENS):
        return True
    if re.search(r"\.(?:pdf|doc|docx|txt|md|csv|xls|xlsx|ppt|pptx)(?!\w)", text) is not None:
        return True
    if _FILE_FORMAT_RE.search(text) is None:
        return False
    return len({match.group(1).lower() for match in _FILE_DOCUMENT_FORMAT.finditer(text)}) >= 2


_WEATHER_LOCATION = re.compile(r"([a-zçğıöşü]{3,}?)(?:['’]?(?:da|de|ta|te|daki|deki|nın|nin))?\s+hava")


# Fillers the legacy city parser never saw ("şu anda hava nasıl"); WEATHER_STOP itself is frozen by its own test.
_WEATHER_EXTRA_STOP = frozenset({"anda"})


def _weather_location(text: str) -> str | None:
    """City word before 'hava' ('ankara'da hava nasıl'); None when absent or a filler word."""
    from modules.tr_speech_sets import WEATHER_STOP
    match = _WEATHER_LOCATION.search(text)
    if match is None or match.group(1) in WEATHER_STOP or match.group(1) in _WEATHER_EXTRA_STOP:
        return None
    return match.group(1)


_WEATHER_RAIN_ASK = re.compile(r"(?<!\w)yağmur\s+(?:yağacak|var)\s+m[ıi](?!\w)")
_WEATHER_OFF_TOPIC = re.compile(r"(?<!\w)(?:havaalan|havaliman|hava\s+(?:yolu|kuvvet)|havai)(?!\w)")


def _is_weather_request(text: str) -> bool:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if _WEATHER_OFF_TOPIC.search(text) is not None:
        return False
    # Eski ham hava dalının yağmur sorusu yüzü: başka bir alan hedefi taşımayan kapalı kalıp.
    if _WEATHER_RAIN_ASK.search(text) is not None:
        return True
    if not _contains_domain_token(text, _WEATHER_DOMAIN_TOKENS):
        return False
    return re.search(r"(?<!\w)hava(?!\w).*\b(?:nasıl|nasil|nasıldı|nasildi)\b", text) is not None


RESEARCH_MAX_QUERY = 1000
_RESEARCH_WEB_CUE = re.compile(r"(?<!\w)(?:internet\w*|web\w*|google\w*|haber\w*|araştır\w*|arastir\w*)")
_RESEARCH_PRIVATE_TARGET = re.compile(
    r"(?<!\w)(?:bunu|şunu|sunu|onu|mail\w*|e-?posta\w*|dosya\w*|belge\w*|not\w*|takvim\w*|"
    r"sayfa\w*|site\w*|izleme|listem\w*|hesab\w*|gelen)(?!\w)"
)


_RESEARCH_MARKET_NOW = re.compile(r"(?<!\w)(?:dolar|euro|altın|altin|borsa|skor\w*)(?!\w)")
_RESEARCH_NEWS_TOPIC = re.compile(r"(?<!\w)(?:haber\w*|gelişme\w*|gelisme\w*)(?!\w)")
# Taze dış veri isteğinin tek canonical tanımını taşırlar (eski modules/freshness kuralı).
_RESEARCH_FRESH_TOPIC = re.compile(
    r"(?<!\w)(?:haber\w*|gelişme\w*|gelisme\w*|fiyat\w*|kuru?(?!\w)|dolar|euro|altın|altin|borsa|piyasa|skor\w*|"
    r"maç sonucu\w*|mac sonucu\w*)(?!\w)"
)
_RESEARCH_FRESH_MARK = re.compile(
    r"(?<!\w)(?:güncel|guncel|bugünkü|bugunku|mevcut|son|bugün|bugun|şu an|su an|şu anda|su anda|şimdi|simdi|"
    r"latest|recent|yeni|ne kadar|kaç|kac)(?!\w)"
)
_RESEARCH_FRESH_ASK = re.compile(
    r"(?<!\w)(?:neler|nelerdir|ne var|özet\w*|ozet\w*|anlat\w*|göster\w*|goster\w*|araştır\w*|arastir\w*|"
    r"durum\w*|sonuç\w*|sonuc\w*|kaç|kac)(?!\w)"
)
_RESEARCH_DEFINITION = re.compile(r"(?<!\w)(?:nedir|ne demek|tarihçe|tarihce)(?!\w)")
# "kur" tek başına hem döviz konusudur hem de fiil ("alarm kur", "masaüstü kur"). Taze dış veri
# konusu sayılabilmesi için yanındaki para/işaret bağlamı ya da doğrudan bir değer sorusu gerekir.
_RESEARCH_MONEY_CONTEXT = re.compile(
    r"(?<!\w)(?:dolar|euro|altın|altin|döviz|doviz|faiz|enflasyon|borsa|piyasa|fiyat\w*|lira)(?!\w)"
)
_RESEARCH_VALUE_ASK = re.compile(r"(?<!\w)(?:ne kadar|kaç\w*\s+(?:lira|tl|dolar|euro|ediyor|eder))(?!\w)")
# "kur" tek başına hem döviz konusudur hem de fiil ("alarm kur", "masaüstü kur"). Döviz isteği sayılması
# için para bağlamı, doğrudan bir değer sorusu ya da bugüne/şimdiye ait bir tazelik işareti gerekir.
# 'güncel kur' dövizdir; "saat kaç oldu ... alarm kur" fiildir — bu yüzden _RESEARCH_FRESH_MARK'ın
# sayı sorusu 'kaç'ı da kapsaması burada delil sayılmaz. 'yarın' geleceğe ait bir hatırlatmadır, taze
# dış veri değil; o yüzden bu işarette yoktur.
_RESEARCH_NOW_MARK = re.compile(
    r"(?<!\w)(?:bugün|bugun|bugünkü|bugunku|bu gün|şu an|su an|şuanda|şu anda|şimdi|simdi|"
    r"güncel|guncel|mevcut|dünkü|dunku|son)(?!\w)"
)


def _needs_fresh_external_data(text: str) -> bool:
    """Haber/kur/borsa/skor/fiyat gibi taze dış veri isteyen cümle; hava burada konu değildir.

    Tanım kalıbı ("haber nedir") yalnız açık bir tazelik işareti yoksa statik kalır;
    "bugünkü dolar kuru nedir" gibi bir isteği bastırmaz."""
    topic = _RESEARCH_FRESH_TOPIC.search(text)
    if topic is None:
        return False
    if topic.group(0) in {"kur", "kuru"} and not (
            _RESEARCH_MONEY_CONTEXT.search(text) or _RESEARCH_VALUE_ASK.search(text)
            or _RESEARCH_NOW_MARK.search(text)):
        # "yarın için alarm kur" bir hatırlatma kurma fiilidir; taze döviz verisi istemi değildir.
        # "güncel kur" / "dolar şu an kaç" / "kur ne kadar" bu daldan geçmez: hepsi döviz isteğidir.
        return False
    fresh = _RESEARCH_FRESH_MARK.search(text) is not None
    if not fresh and instructional_question(text):
        # "Haberlerde kaynak güvenilirliği nasıl anlaşılır?" açıklama sorusudur; taze veri istemez.
        # Açık tazelik işareti olan bir "nasıl" sorusu ("bugünkü kura göre ...") bu daldan geçmez.
        return False
    if not fresh:
        news = _RESEARCH_NEWS_TOPIC.search(text) is not None and _RESEARCH_FRESH_ASK.search(text) is not None
        market = _RESEARCH_MARKET_NOW.search(text) is not None and _RESEARCH_FRESH_ASK.search(text) is not None
        if not (news or market):
            return False
        if _RESEARCH_DEFINITION.search(text) is not None:
            return False
    return True


def _is_explicit_research_request(text: str) -> bool:
    """True for an explicit public-web research ask or a fresh external-data request; private/deictic targets stay with their owner."""
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if _RESEARCH_PRIVATE_TARGET.search(text) is not None:
        return False
    if _needs_fresh_external_data(text):
        return True
    if _RESEARCH_WEB_CUE.search(text) is None:
        return False
    return _contains_command_token(text, ("ara", "bul", "araştır", "arastir"))


def _research_arguments(original: str, normalized: str) -> dict[str, object]:
    """Research proposal uses the user's exact request and never grants PUBLIC provenance."""
    query = original.strip()
    if not query or len(query) > RESEARCH_MAX_QUERY or "\x00" in query:
        return {}
    if not _is_explicit_research_request(normalized):
        return {}
    return {"research": {"query": query, "route": "PRIVATE"}}


_NOTES_PLURAL = ("notlar", "notları", "notlari", "notlarım", "notlarim", "notlarımı", "notlarimi")
_NOTES_SINGULAR = ("not", "notu", "notunu", "notum", "notumu")
_NOTES_READ_VERBS = ("göster", "goster", "oku", "say", "listele")
_NOTES_WRITE_RE = re.compile(
    r"^(?P<target>.+?)\s+not\w*\s+(?P<verb>sil|kaldır|kaldir|iptal\s+et|düzelt|duzelt|değiştir|degistir|güncelle|guncelle)\w*"
    r"(?:\s*[:,]\s*(?P<new>.*))?$"
)
_NOTES_WRITE_STOP = frozenset({
    "bu", "şu", "su", "o", "son", "tüm", "tum", "bütün", "butun", "hepsi", "hepsini",
    "numaralı", "numarali",
})
_NOTES_FILLERS = frozenset({"lütfen", "lutfen", "bana", "bir", "bu", "şu", "su", "o", "tüm", "tum", "bütün", "butun",
                            "hepsini", "son", "şunu", "bunu", "mi", "mı", "mu", "mü", "misin", "mısın", "musun", "müsün", "jarvis"})
# "notlarımda/notlarda/notumda" are the inflected forms the old raw-text search accepted.
_NOTE_SEARCH_DOMAIN_TOKENS = _NOTE_DOMAIN_TOKENS + (
    "notlarımda", "notlarimda", "notlarda", "notumda", "notumdaki",
    "notlarımdaki", "notlarimdaki", "notlarındaki", "notlarindaki",
)
_NOTE_SEARCH_CUES = ("ara", "arar", "bul", "bulur", "gecen", "geçen", "gecenleri", "geçenleri",
                     "yaziyor", "yazıyor")
_NOTE_SEARCH_STOP = _NOTES_FILLERS | frozenset({
    "ara", "arar", "bul", "bulur", "goster", "göster", "oku", "say", "listele",
    "gecen", "geçen", "gecenleri", "geçenleri", "yaziyor", "yazıyor", "hangi",
    "var", "mi", "mı", "mu", "mü", "neydi", "nelerdi", "neler", "nerede", "ne",
    "ile", "ilgili", "hakkinda", "hakkında", "icinde", "içinde", "icindeki", "içindeki",
    "olan", "benim", "bana", "aldigim", "aldığım", "yazdigim", "yazdığım",
    "kaydettigim", "kaydettiğim", "tuttugum", "tuttuğum",
    "bugun", "bugün", "bugunku", "bugünkü", "dun", "dün", "dunku", "dünkü",
    "bu", "hafta", "haftaki", "ay", "ayki",
})
_NOTE_SEARCH_END = re.compile(
    r"\bnot\w*\s*(?:var mi|var mı|neydi|nelerdi|neler|ne|nerede|goster|göster|oku|bul|ara|var)?$"
    r"|\b(?:ara|arar|bul|bulur|goster|göster|oku)\w*$|\bvar mi$|\bvar mı$|\bneydi$"
)
_NOTE_SUMMARY_VERBS = ("özetle", "ozetle", "özet", "ozet")
# Bounded ordinal/last-note mutations stay with the notes owner's existing protocol; they are not a
# multi-target question even though "son not" references the whole inventory.
_NOTE_BOUNDED_MUTATION = re.compile(
    r"(?<!\w)(?:son|ilk|birinci|ikinci|üçüncü|ucuncu|dördüncü|dorduncu|beşinci|besinci|altıncı|altinci|"
    r"yedinci|sekizinci|dokuzuncu|onuncu|\d{1,3})\.?\s*(?:numaralı|numarali)?\s*not\w*\s+"
    r"(?:sil|kaldır|kaldir|iptal\s+et|düzelt|duzelt|değiştir|degistir|güncelle|guncelle)\w*"
)
_NOTE_SUMMARY_OTHER = frozenset({
    "mail", "maili", "mailler", "mailleri", "dosya", "dosyayi", "dosyayı", "sayfa", "sayfayi", "sayfayı",
    "web", "internet", "internette", "haber", "haberleri", "takvim", "takvimi",
    "hatirlat", "hatırlat", "gorsel", "görsel", "resim", "resmi",
})
_NOTE_WINDOWS = (
    (re.compile(r"\b(?:gecen|geçen) hafta"), "last_week"),
    (re.compile(r"\bbu hafta"), "this_week"),
    (re.compile(r"\b(?:gecen|geçen) ay"), "last_month"),
    (re.compile(r"\bbu ay"), "this_month"),
    (re.compile(r"\b(?:bugun|bugün)"), "today"),
    (re.compile(r"\b(?:dun|dün)"), "yesterday"),
)
NOTES_WRITE_CAPABILITY = "notes.write"
NOTE_TARGET_UNRESOLVED = "note target unresolved"
NOTE_TARGET_AMBIGUOUS = "note target ambiguous"
NOTE_UPDATE_TEXT_MISSING = "note update text missing"
NOTE_SEARCH_QUERY_MISSING = "note search query missing"


def _note_write_request(text: str) -> tuple[str, str] | None:
    """Return (operation, named target) only for a bounded named note mutation."""
    match = _NOTES_WRITE_RE.fullmatch(text.strip(" .!?"))
    if match is None:
        return None
    target = match.group("target").strip()
    words = re.findall(r"[\wçğıöşü]+", target)
    if not 1 <= len(words) <= 4:
        return None
    if any(word.isdecimal() or word in _NOTES_WRITE_STOP for word in words):
        return None
    verb = match.group("verb")
    operation = "delete" if verb.startswith(("sil", "kaldır", "kaldir", "iptal")) else "update"
    return operation, target


def _note_update_text(original: str) -> str | None:
    if ":" not in original:
        return None
    value = original.split(":", 1)[1].strip()
    if not value or len(value) > 16000 or "\x00" in value:
        return None
    return value


def _is_bare_notes_command(text: str) -> bool:
    """True only when the WHOLE sentence is a note noun + read verb (+ filler words)."""
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text.lower())
    known = set(_NOTES_PLURAL) | set(_NOTES_SINGULAR) | set(_NOTES_READ_VERBS) | _NOTES_FILLERS
    return bool(words) and all(word in known for word in words)


def _notes_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Read-only notes proposal: all notes or ONE resolved note reference by stable id."""
    if not _contains_command_token(text, _NOTES_READ_VERBS) or not _is_bare_notes_command(text):
        return {}
    if _contains_domain_token(text, _NOTES_PLURAL):
        return {"notes": {"which": "all"}}
    notes = [ref for ref in references if ref.kind == "note"]
    if len(notes) == 1 and _contains_domain_token(text, _NOTES_SINGULAR):
        return {"notes": {"which": "one", "id": notes[0].id}}
    return {}


def notes_read_view(text: str) -> tuple[str, dict[str, object]] | None:
    """Tek tam-cümle salt-okuma önerisi: (capability, Core'a gidecek argümanlar) veya None.

    Referans çözmez (bağlam ikinci kez yürütülmez): yalnız çoklu not listesi önerilebilir.
    Öneri burada doğar, yetkiyi `brain_core_map.core_plan` doğrular; bu yüzden düzeltilmiş
    bir yazım tek başına hiçbir yazma akışının sahibi olamaz."""
    arguments = _notes_arguments(text, ())
    return None if not arguments else ("notes.read", dict(arguments))


def _note_window_label(text: str) -> str | None:
    for pattern, label in _NOTE_WINDOWS:
        if pattern.search(text) is not None:
            return label
    return None


def _note_search_query(text: str) -> str:
    """The user's own search words only; note/date/cue/filler words never become the query."""
    stripped = re.sub(r"\bnot\w*", " ", text)
    words = re.findall(r"[\wçğıöşü]+", stripped)
    return " ".join(word for word in words if word not in _NOTE_SEARCH_STOP)


def _is_single_note_search(text: str) -> bool:
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text.lower())
    known = (set(_NOTE_SEARCH_DOMAIN_TOKENS) | set(_NOTES_PLURAL) | set(_NOTES_SINGULAR)
             | set(_NOTE_SEARCH_CUES) | set(_NOTE_SEARCH_STOP)
             | {"göster", "goster", "oku", "say", "listele", "notlarım", "notlarim"})
    return bool(words) and all(word in known for word in words)


def _notes_search_request(text: str) -> bool:
    """True only for a bounded note lookup request; mutations/definitions and other domains stay out."""
    if not _has_note_domain(text) or _notes_summary_request(text) is not None:
        return False
    if any(_bounded_token(text, word) for word in (
            "sil", "kaldir", "kaldır", "duzelt", "düzelt", "degistir", "değiştir", "guncelle", "güncelle",
            "temizle", "ekle", "al", "yaz", "et",
    )):
        return False
    if any(_bounded_token(text, word) for word in ("nasil", "nasıl", "neden", "nedir", "niye", "demek")):
        return False
    cue = _contains_command_token(text, _NOTE_SEARCH_CUES)
    # A second action joined by "ve"/"," belongs to the step runner, not to a single notes lookup.
    if not cue and ("," in text or " ve " in f" {text} "):
        return False
    if _note_window_label(text) is not None:
        return True
    if _note_search_query(text):
        return cue or _NOTE_SEARCH_END.search(text) is not None
    # Bare list/read forms ("notlarım") stay with the existing read owner; only an explicit
    # search cue turns an empty query into the fail-closed clarification.
    return cue and _is_single_note_search(text)


def _notes_search_arguments(text: str) -> dict[str, object]:
    if not _notes_search_request(text):
        return {}
    window = _note_window_label(text)
    query = _note_search_query(text)
    if query:
        if len(query.split()) > 3:
            return {}
        row: dict[str, object] = {"which": "search", "query": query}
        if window is not None:
            row["window"] = window
        return {"notes": row}
    if window is not None:
        return {"notes": {"which": "search", "window": window}}
    return {}


def _has_note_domain(text: str) -> bool:
    return _contains_domain_token(text, _NOTE_SEARCH_DOMAIN_TOKENS)


def _notes_summary_request(text: str) -> str | None:
    """Return 'all' or 'one' for a single notes-summary request, else None."""
    if not _has_note_domain(text) or not _contains_command_token(text, _NOTE_SUMMARY_VERBS):
        return None
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text)
    if any(word in _NOTE_SUMMARY_OTHER for word in words):
        return None
    if " ve " in f" {text} " or "," in text or any(marker in text for marker in (" sonra ", " ardından ", " akabinde ")):
        return None
    if _contains_domain_token(text, _NOTES_PLURAL):
        return "all"
    if _contains_domain_token(text, _NOTES_SINGULAR):
        return "one"
    return None


def _notes_summary_arguments(text: str, references: tuple[ContextReference, ...], kind: str) -> dict[str, object]:
    if kind == "all":
        return {"notes": {"which": "summary"}}
    if kind != "one":
        return {}
    notes = [ref for ref in references if ref.kind == "note"]
    if len(notes) != 1:
        return {}
    return {"notes": {"which": "summary", "id": notes[0].id}}


def _notes_request_kind(text: str) -> str | None:
    """The single notes operation Understanding proposes: search, summary, all or one."""
    if _notes_summary_request(text) is not None:
        return "summary"
    if _notes_search_request(text):
        return "search"
    if _contains_domain_token(text, _NOTES_PLURAL) and _contains_command_token(text, _NOTES_READ_VERBS):
        return "all"
    if _contains_domain_token(text, _NOTES_SINGULAR) and _contains_command_token(text, _NOTES_READ_VERBS):
        return "one"
    return None


def _notes_write_arguments(original: str, normalized: str,
                           references: tuple[ContextReference, ...]) -> dict[str, object]:
    request = _note_write_request(normalized)
    notes = [ref for ref in references if ref.kind == "note"]
    if request is None or len(notes) != 1:
        return {}
    operation, _target = request
    row: dict[str, object] = {"operation": operation, "id": notes[0].id}
    if operation == "update":
        value = _note_update_text(original)
        if value is None:
            return {}
        row["text"] = value
    return {"notes": row}


def _is_notes_read_request(text: str) -> bool:
    return _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _contains_command_token(text, _NOTES_READ_VERBS)


# Eski router'ın deterministik ekran/pencere kuralları: aynı cümleler artık burada tanınır,
# Core kararı brain_core_map doğrular. Türkçeli ve ASCII yazımın ikisi de kapılır.
SCREEN_CAPABILITY = "screen.analyze"
WINDOW_LIST_CAPABILITY = "desktop.windows.list"
WINDOW_OP_CAPABILITY = "desktop.window.op"
# Bounded clarify follow-up: the target of the question ("Neyi açmamı istiyorsun?") completes
# the existing app-open owner. Core re-validates the name and keeps the launch guards.
APP_OPEN_CAPABILITY = "app.open"
# Same bounded shape for close: the answer only resolves the target; the existing close
# confirmation/permission/effect owner still runs after approval.
APP_CLOSE_CAPABILITY = "app.close"
_SCREEN_ANALYZE_CUE = re.compile(
    r"(?<!\w)(?:ekran(?:ı|i|imi|ımı)?|ekrandaki).{0,35}(?:analiz|incele|bak|ne var|ne görüyorsun|ne goruyorsun)"
    r"|"
    r"(?<!\w)(?:analiz|incele)(?!\w).{0,25}\bekran",
    re.I,
)
_SCREEN_GENERIC_REQUEST = re.compile(
    r"^(?:(?:hey\s+)?jarvis[ ,]*)?(?:ekran(?:ı|i|imi|ımı)?\s*)?(?:analiz\s*et|incele|bak)[ .!?]*$", re.I)
# Core plan'ı olmayan ama legacy sahibi kesin olan okuma komutları; açık bir slot bunları
# kendi cevabı sanmamalı ("hava durumuna bak" bir mesaj gövdesi değildir).
_WEATHER_STATUS_CUE = re.compile(
    r"(?<!\w)hava\s+durumu(?:na|nu|n[üu])?(?:\s+(?:bak|göster|goster|söyle|soyle))?(?!\w)", re.I)
_SCREENSHOT_CUE = re.compile(
    r"(?<!\w)(?:ekran\s+görüntüsü\w*|screenshot|resmini\s+çek)(?!\w)", re.I)
_WINDOW_LIST_REQUEST = re.compile(
    r"^(?:(?:hey\s+)?jarvis[ ,]*)?(?:açık|acik)(?: olan)? pencereler(?:i|im|imi)?"
    r"\s+(?:listele|göster|goster|say)[ .!?]*$", re.I)
_WINDOW_OP_REQUEST = re.compile(
    r"^(.+?)\s+penceresini\s+(öne getir|one getir|küçült|kucult|büyüt|buyut|eski boyutuna getir)[ .!?]*$", re.I)
_WINDOW_OP_ACTIONS = {"öne getir": "focus", "one getir": "focus", "küçült": "minimize", "kucult": "minimize",
                      "büyüt": "maximize", "buyut": "maximize", "eski boyutuna getir": "restore"}
WINDOW_TARGET_MAX = 120


def _screen_arguments(original: str, normalized: str) -> dict[str, object]:
    if _SCREEN_ANALYZE_CUE.search(normalized) is None:
        return {}
    if _SCREEN_GENERIC_REQUEST.fullmatch(normalized):
        return {"question": ""}
    question = re.sub(r"^(?:(?:hey\s+)?jarvis[ ,]*)+", "", original.strip(), flags=re.I).strip(" .!?")
    return {"question": question[:1000]}


def _desktop_window_arguments(normalized: str) -> dict[str, object]:
    """Tek satırlık pencere istekleri: liste ya da bilinen bir hedefe yönelik tek pencere eylemi."""
    if _WINDOW_LIST_REQUEST.fullmatch(normalized):
        return {"window": {"action": "list"}}
    match = _WINDOW_OP_REQUEST.fullmatch(normalized)
    if match is None:
        return {}
    target, phrase = match.group(1).strip(" '\"“”"), match.group(2)
    action = _WINDOW_OP_ACTIONS.get(phrase)
    if action is None or not target or len(target) > WINDOW_TARGET_MAX or "\x00" in target:
        return {}
    return {"window": {"action": action, "target": target}}


def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    if _note_write_request(text) is not None:
        return "notes.write"
    if _notes_request_kind(text) is not None:
        return "notes.read"
    if _is_weather_request(text):
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    # Ekranı okuma ve pencere kontrolü: sözcük düzeyinde kesinse model'e sorulmadan canonical öneri olur.
    if _SCREEN_ANALYZE_CUE.search(text) is not None:
        return SCREEN_CAPABILITY
    if _WINDOW_LIST_REQUEST.fullmatch(text) or _WINDOW_OP_REQUEST.fullmatch(text):
        return WINDOW_LIST_CAPABILITY if _WINDOW_LIST_REQUEST.fullmatch(text) else WINDOW_OP_CAPABILITY
    if _organize_targets(text):
        return ORGANIZE_CAPABILITY
    if _file_operation(text) is not None:
        return "files.read"
    # Klasör analizi tek dosya okumasından sonra gelir: "… dosyasını özetle" bir dosya isteğidir,
    # kök adı geçse de klasör taraması başlatmaz (ölçülen taban sırası).
    if folder_analysis_request(text) is not None:
        return FOLDER_ANALYSIS_CAPABILITY
    # Eski ham dalın "hava durumuna bak / söyle" yüzü: dosya-not-ekran hedefi yoksa hava okumasıdır.
    if _weather_status_request(text):
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    if any(_bounded_token(text, token) for token in ("hatırlat", "hatirlat", "uyar")):
        return "reminder.propose"
    # New canonical path: explicit public-web research, including the Turkish verb "araştır".
    if _is_explicit_research_request(text):
        return "research.search"
    # Preserve the pre-B4d advisory hint for generic ara/bul phrases. Without validated
    # research arguments Core will not claim these; their existing legacy owner remains.
    if _looks_like_capability(text) and _contains_command_token(text, ("ara", "bul")):
        return "research.search"
    return None


TRANSLATE_CAPABILITY = "text.translate"
TRANSLATE_SOURCE_MISSING = "translate source missing"


def _translate_proposal(text: str, candidates: tuple[ContextReference, ...]):
    """(Request, arguments) for a text-translation command; the source comes from Candidate Builder turns.

    The single grammar and source rule live in modules.translation_request (shared with the legacy chain)."""
    from modules import translation_request
    request = translation_request.parse(text)
    if request is None or translation_request.non_text_target(text):
        return None, {}
    turns = sorted(
        ({"id": ref.id, "role": ref.provenance.get("role"), "text": ref.provenance.get("text"),
          "ts": ref.provenance.get("ts")} for ref in candidates if ref.kind == "conversation_turn"),
        key=lambda row: str(row["ts"] or ""),
    )
    source, origin, turn_id = translation_request.pick_source(request, text, turns)
    if not source:
        return request, {}
    row = {"target": request.target, "text": source, "origin": origin}
    if turn_id is not None:
        row["turn_id"] = str(turn_id)
    return request, {"translate": row}


def _reminder_arguments(text: str) -> dict[str, object]:
    """title/when/repeat from the single reminder parser (modules.when underneath); creation sentences only."""
    from modules import reminder_parse
    if not reminder_parse.is_creation_request(text):
        return {}
    parsed = reminder_parse.parse(text)
    return {"reminder": {"title": parsed["title"], "when": parsed["when"], "repeat": parsed["repeat"]}}


FILE_SUMMARIZE = "summarize"
FILE_ANALYZE = "analyze"
FILE_OPEN = "open"
FILE_LOCATE = "locate"
FILE_LIST = "list"
FILE_COMPARE = "compare"
FILE_TRANSLATE = "translate"
FILE_CONVERT = "convert"
FILE_TARGET_UNRESOLVED = "file target unresolved"
FILE_TRANSLATION_TARGET_MISSING = "file translation target missing"
FILE_CONVERSION_FORMAT_MISSING = "file conversion format missing"
FILE_MUTATE_CAPABILITY = "files.mutate"
FILE_MUTATION_TARGET_UNRESOLVED = "file mutation target unresolved"
_FILE_MUTATION_UNDO = re.compile(r"^(?:son )?dosya i[sş]lemini geri al$")
_FILE_MUTATION_MOVE = re.compile(
    r"^(?P<target>.+?)\s+dosyas[ıi]n[ıi]\s+(?P<folder>masaüstüne|masaustune|indirilenlere|belgelere|resimlere)\s+ta[sş][ıi]\w*$",
    re.I,
)
_FILE_MUTATION_RENAME = re.compile(
    r"^(?P<target>.+?)\s+dosyas[ıi]n[ıi]n\s+ad[ıi]n[ıi]\s+(?P<name>.+?)\s+(?:yap|olarak de[ğg]i[sş]tir\w*|yeniden adland[ıi]r\w*)$",
    re.I,
)
_FILE_MUTATION_CREATE = re.compile(
    r"^(?P<folder>masaüstüne|masaustune|indirilenlere|belgelere)\s+(?P<name>.+?)\s+ad[ıi]nda\s+(?:bir )?(?:metin|not|txt) dosyas[ıi]\s+(?:olu[sş]tur\w*|yap\w*)"
    r"(?:\s+(?:ve )?i[çc]ine (?P<content>.+?) yaz\w*)?$",
    re.I,
)


def _file_mutation_proposal(text: str, references: tuple[ContextReference, ...]):
    """Typed file mutation proposal; target paths come only from resolved owner-bound references."""
    cleaned = text.strip(" .!?")
    if _FILE_MUTATION_UNDO.fullmatch(cleaned):
        return {"mutation": {"operation": "undo"}}, None
    move = _FILE_MUTATION_MOVE.fullmatch(cleaned)
    rename = _FILE_MUTATION_RENAME.fullmatch(cleaned)
    create = _FILE_MUTATION_CREATE.fullmatch(cleaned)
    if create is not None:
        folder = {
            "masaüstüne": "masaüstü", "masaustune": "masaustu",
            "indirilenlere": "indirilenler", "belgelere": "belgeler",
        }.get(typo.fold(create.group("folder")), typo.fold(create.group("folder")))
        return {"mutation": {"operation": "create", "folder": folder,
                             "name": create.group("name").strip(),
                             "content": (create.group("content") or "").strip()}}, None
    if move is None and rename is None:
        return None, None
    target = (move.group("target") if move is not None else rename.group("target")).strip()
    rows = [ref for ref in references if ref.kind == "file"]
    if len(rows) != 1:
        return {"mutation": {"operation": "move" if move is not None else "rename"}}, FILE_MUTATION_TARGET_UNRESOLVED
    path = rows[0].provenance.get("path")
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        return {"mutation": {"operation": "move" if move is not None else "rename"}}, FILE_MUTATION_TARGET_UNRESOLVED
    candidate_name = rows[0].provenance.get("name")
    candidate_name = candidate_name if isinstance(candidate_name, str) and candidate_name.strip() else re.split(r"[\\/]", path)[-1]
    candidate_stem = candidate_name.rsplit(".", 1)[0]
    wanted = typo.fold(target.strip(" '\\\""))
    if wanted not in {typo.fold(candidate_name), typo.fold(candidate_stem)}:
        return {"mutation": {"operation": "move" if move is not None else "rename"}}, FILE_MUTATION_TARGET_UNRESOLVED
    if move is not None:
        folder = {
            "masaüstüne": "masaüstü", "masaustune": "masaustu",
            "indirilenlere": "indirilenler", "belgelere": "belgeler", "resimlere": "resimler",
        }.get(typo.fold(move.group("folder")), typo.fold(move.group("folder")))
        return {"mutation": {"operation": "move", "path": path, "folder": folder}}, None
    return {"mutation": {"operation": "rename", "path": path, "name": rename.group("name").strip()}}, None

# Operations Core fully owns with no sensible legacy raw-text fallback: Brain must ask rather than
# let Core guess. FILE_OPEN/FILE_LOCATE stay legacy-resolved by name search when Brain has no single
# resolved reference (pre-existing behavior); Brain only proposes them when a reference did resolve.
_FILE_TARGET_REQUIRED = frozenset({FILE_SUMMARIZE, FILE_ANALYZE, FILE_TRANSLATE, FILE_CONVERT})
_FILE_ASK_EXEMPT = frozenset({FILE_OPEN, FILE_LOCATE})
_FILE_FORMAT_RE = re.compile(
    r"(?<!\w)(pdf|excel|xlsx|word|docx)(?:['’]?(?:e|a|ye|ya))?(?:\s+format(?:ına|ina))?\s+"
    r"(?:dönüştür|donustur|çevir|cevir)\w*(?!\w)"
)


_TRANSLATE_VERB_RE = re.compile(r"(?<!\w)(?:çevir|cevir)\w*(?!\w)")


def _file_language(text: str) -> str | None:
    """Hedef dil: tek tanım translation_targets'ta yaşıyor (ASCII yazım ve -den/-dan kaynak biçimi dahil)."""
    if _TRANSLATE_VERB_RE.search(text) is None:
        return None
    from modules import translation_targets
    return translation_targets.target_from_command(text) or None


def _file_format(text: str) -> str | None:
    match = _FILE_FORMAT_RE.search(text)
    if match is None:
        return None
    return {"excel": "xlsx", "word": "docx"}.get(match.group(1), match.group(1))


# "sonucu/raporu excel olarak hazırla": aynı isteğin dosya çıktısı. Dönüştürme fiiliyle
# (_FILE_FORMAT_RE) karışmaz; tek tanım burada, Core yalnız izinli biçimi kabul eder.
_FILE_SAVE_FORMAT_PATTERNS = (
    ("xlsx", r"(?:sonuc|sonuç|rapor|çıktı|cikti).{0,35}(?:excel|xlsx)|(?:excel|xlsx).{0,25}(?:olarak|format|rapor|çıktı|cikti|hazırla|olustur|oluştur)"),
    ("docx", r"(?:sonuc|sonuç|rapor|çıktı|cikti).{0,35}(?:word|docx)|(?:word|docx).{0,25}(?:olarak|format|rapor|çıktı|cikti|hazırla|olustur|oluştur)"),
    ("pdf", r"(?:sonuc|sonuç|rapor|çıktı|cikti).{0,35}(?:pdf)|(?:pdf).{0,25}(?:olarak|formatında|rapor|çıktı|cikti|hazırla|olustur|oluştur)"),
)


def _file_save_format(text: str) -> str | None:
    for fmt, pattern in _FILE_SAVE_FORMAT_PATTERNS:
        if re.search(pattern, text):
            return fmt
    return None


def _file_operation(text: str) -> str | None:
    """One bounded natural-language file operation; multi-action requests stay with the step/legacy path."""
    if not _has_file_domain(text) or _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    operations: list[str] = []
    if _contains_command_token(text, ("karşılaştır", "karsilastir")):
        operations.append(FILE_COMPARE)
    converts = re.search(r"(?<!\w)(?:dönüştür|donustur)\w*(?!\w)", text) is not None
    translates = re.search(r"(?<!\w)(?:çevir|cevir)\w*(?!\w)", text) is not None
    # "word'e çevir" hedef biçim adı taşıyorsa dil çevirisi değil dosya dönüştürmesidir.
    if converts or (translates and _file_format(text) is not None):
        operations.append(FILE_CONVERT)
    elif translates:
        operations.append(FILE_TRANSLATE)
    if re.search(r"(?<!\w)(?:analiz\s+et\w*|incele\w*)(?!\w)", text):
        operations.append(FILE_ANALYZE)
    if _contains_command_token(text, ("özetle", "ozetle")):
        operations.append(FILE_SUMMARIZE)
    if _contains_command_token(text, ("aç", "ac")):
        operations.append(FILE_OPEN)
    if _contains_command_token(text, ("bul",)):
        operations.append(FILE_LOCATE)
    if _contains_command_token(text, ("listele",)):
        operations.append(FILE_LIST)
    if _contains_command_token(text, ("göster", "goster")):
        plural = _contains_domain_token(text, ("dosyalar", "dosyaları", "dosyalari", "dosyalarım", "dosyalarim", "dosyalarımı", "dosyalarimi"))
        operations.append(FILE_LIST if plural else FILE_LOCATE)
    # Same operation may be expressed twice; different operations mean a compound request.
    unique = tuple(dict.fromkeys(operations))
    if len(unique) != 1:
        return None
    if unique[0] != FILE_COMPARE and re.search(
        r"(?<!\w)ve\s+(?:kaydet\w*|g\u00f6nder\w*|gonder\w*|payla\u015f\w*|paylas\w*|yazd\u0131r\w*|yazdir\w*|\u00e7\u0131kt\u0131\s+al\w*|cikti\s+al\w*)(?!\w)",
        text,
    ):
        return None
    return unique[0]


def _file_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Operation + target proposal. Paths come ONLY from resolved file references, never raw text."""
    operation = _file_operation(text)
    if operation is None:
        return {}
    if operation == FILE_LIST:
        return {"operation": FILE_LIST}
    files = [ref for ref in references if ref.kind == "file"]
    if operation == FILE_COMPARE:
        paths = []
        for ref in files:
            value = ref.provenance.get("path")
            if isinstance(value, str) and value.strip() and value not in paths:
                paths.append(value)
        return {"operation": FILE_COMPARE, "paths": tuple(paths)} if 2 <= len(paths) <= 10 else {}
    if len(files) != 1:
        return {}
    path = files[0].provenance.get("path")
    if not isinstance(path, str) or not path.strip():
        return {}
    row: dict[str, object] = {"operation": operation, "path": path}
    if operation == FILE_TRANSLATE:
        target = _file_language(text)
        if target is None:
            return {}
        row["target"] = target
    elif operation == FILE_CONVERT:
        fmt = _file_format(text)
        if fmt is None:
            return {}
        row["format"] = fmt
    elif operation in (FILE_SUMMARIZE, FILE_ANALYZE):
        fmt = _file_save_format(text)
        if fmt is not None:
            row["format"] = fmt
    return row


# --- kanonical klasör düzenleme (PR3C-3) ---------------------------------------------------------
# Öneri tek bir kapalı sözleşme üretir: `operation` + `folder` ANAHTARI. Yol asla ham metinden
# türemez; Core anahtarı doğrular, domain (`files.ORGANIZE_FOLDERS`) anahtarı gerçek klasöre çevirir.
ORGANIZE_CAPABILITY = "files.organize"
ORGANIZE_OPERATION = "organize"
ORGANIZE_TARGET_AMBIGUOUS = "organize target ambiguous"
_ORGANIZE_PREVIEW_LABELS = {"desktop": "Masaüstü", "downloads": "İndirilenler", "documents": "Belgeler"}

# Emekli edilen ham dalın fiil kümesiyle birebir aynı, kapalı bir fiil listesi: `"düzenleyeceğim
# nereden başlamak mantıklı"` bir öğüt sorusudur, emir değildir. Uzunluk-koruyan katlamada yalnız
# Türkçe karakteri düşmüş *aynı* biçim okunur; ek almak yeni yetki üretmek olur.
_ORGANIZE_VERB = re.compile(r"(?<!\w)(?:duzenle|topla|temizle|derle|sirala)(?!\w)")
# "düzenlemeyi geri al" bir önizleme isteği değil, geri alma sahibinin cümlesidir.
_ORGANIZE_UNDO = re.compile(r"(?:geri\s+al\w*|iptal\w*|vazgec\w*|eski\s+yerine)")
# Emekli edilen ham dalın dışlamaları: not ve takvim düzenlemesi kendi alanlarının sözünü taşır.
_ORGANIZE_OTHER_DOMAIN = re.compile(r"(?<!\w)(?:not\w*|takvim\w*)(?!\w)")
# Anahtar kümesi `files.ORGANIZE_FOLDERS` ile birebir aynıdır; ikisi de kapalı listedir.
_ORGANIZE_FOLDERS = (
    ("desktop", re.compile(r"(?<!\w)(?:masaust\w*|desktop\w*)(?!\w)")),
    ("downloads", re.compile(r"(?<!\w)(?:indirilen\w*|indirdi\w*|download\w*)(?!\w)")),
    ("documents", re.compile(r"(?<!\w)(?:belge\w*|document\w*)(?!\w)")),
)


def _organize_targets(text: str) -> tuple[str, ...]:
    """Düzenleme fiili ve anahtar(ler)ı; katlanmış görünüm okunur, karakter eksikliği tanınır.

    Birden fazla anahtar bir sıralı isteği tek klasöre bağlamak tahmindir; o yüzden liste döner ve
    çağıran pipeline iki ya da fazlasını belirsizlik sayar. Boş klasör istek anahtarsız gelir."""
    if not text or _is_meta_language(text) or _is_literal_command_usage(text):
        return ()
    folded = typo.fold(text)
    if _ORGANIZE_VERB.search(folded) is None:
        return ()
    if _ORGANIZE_UNDO.search(folded) or _ORGANIZE_OTHER_DOMAIN.search(folded):
        return ()
    return tuple(key for key, pattern in _ORGANIZE_FOLDERS if pattern.search(folded))


def _organize_arguments(targets: tuple[str, ...]) -> dict[str, object]:
    """Tek doğrulanmış anahtar taşınabiliyorsa {operation, folder}; belirsizse öneri payload'ı yok."""
    if len(targets) != 1:
        return {}
    return {"operation": ORGANIZE_OPERATION, "folder": targets[0]}


# --- kanonical klasör analizi (PR3C-4) -----------------------------------------------------------
# Karar bir kez burada doğar ve kapalı üç sözlükle sınırlıdır: hangi izinli kök (`folder`), "klasör"
# sözünden hemen önceki sözcük kendi başına bir bilinen kök mü (`named`), ve o sözcük (`name`).
# Yol asla burada doğmaz — anahtarları gerçek klasör kimliğine yalnız domain çevirir. Kalıplar
# emekli edilen ham dalın (folder_analysis.resolve) katlanmış biçimiyle birebir aynıdır: metin
# `typo.fold` ile ASCII'ye indirildiği için [öo]/[çc] gibi çift yazımlar tek biçimde toplanır ve
# Türkçe karakterli/karaktersiz aynı cümle aynı kararı verir.
FOLDER_ANALYSIS_CAPABILITY = "files.folder_analyze"
FOLDER_ANALYSIS_OPERATION = "analyze"
_FOLDER_ANALYSIS_LABELS = {"downloads": "İndirilenler", "desktop": "Masaüstü", "documents": "Belgeler",
                           "pictures": "Resimler", "jarvis": "Jarvis Dosyaları"}

# Sıra = tanima önceliği: `jarvis dosyaları` kümesi emekli edilen `_SPECIAL` ile aynı yerde, ilk okunur.
_FOLDER_ANALYSIS_WORDS = (
    ("jarvis", re.compile(r"jarvis\s+dosyalar\w*|yuklediklerim\w*")),
    ("downloads", re.compile(r"indirilen\w*|download\w*|indirdikler\w*")),
    ("desktop", re.compile(r"masaust\w*|desktop\w*")),
    ("documents", re.compile(r"belgeler\w*|belgelerim\w*|documents\w*")),
    ("pictures", re.compile(r"resimler\w*|fotograflar\w*|pictures\w*")),
)
# Analiz fiilinin iki yüzü: tek başına "incele/analiz et/ne var" ve yalnız "klasör" sözüyle birlikte
# anlam kazanan "özetle/tara/gözden geçir".
_FOLDER_ANALYSIS_ASK = re.compile(r"(?<!\w)(?:incele\w*|analiz\w*|ne(?:ler)?\s+var|ne\s+hakkinda|"
                                  r"icinde(?:ki)?\s+ne\w*|icerig\w*|neyle\s+ilgili|ne\s+iceriyor)")
_FOLDER_ANALYSIS_ASK_WITH_FOLDER = re.compile(r"(?<!\w)(?:ozetle\w*|tara\b|tarar\s+misin|gozden\s+gecir\w*)")
# Başka alanların fiilleri: taşıma/düzenleme/izleme/açma kendi sahiplerinde; "toplantı" ve "silinen"
# kök-ek sınırı sayesinde fiil sayılmaz (emekli edilen `_NOT_THIS` ile aynı dışlamalar).
_FOLDER_ANALYSIS_VETO = re.compile(r"(?<!\w)(?:duzenle|topla|temizle|sirala|izle|ac|sil|tasi|kopyala|yedekle)"
                                   r"(?:\b|r\b|sana\b|y?abilir|y?ar\s+misin|r\s+misin)"
                                   r"|dosyasin|dosyayi|dosyas\b|geciyor")
# "bu klasörü incele" bir hedef sorusudur, üst klasör adlı bir alt klasör isteği değil.
_FOLDER_ANALYSIS_GENERIC = frozenset({"bu", "su", "o", "bir", "tum", "butun", "ilgili", "ki",
                                      "suradaki", "buradaki", "icindeki"})
_FOLDER_ANALYSIS_KLASOR = re.compile(r"(?<!\w)klasor\w*")
_FOLDER_ANALYSIS_NAMED = re.compile(r"((?:\S+\s+){0,3}?)(\S+)\s+klasor\w*")


def folder_analysis_request(text: str) -> dict[str, object] | None:
    """Klasör analizi önerisi: kapalı kök anahtarı(+ları) ve adı geçen alt klasör sözcüğü.

    Bulunamayan alt klasör üst klasöre genişletilmez: `name` taşındığında domain ya gerçek bir alt
    klasör bulur ya da kullanıcıya tam adı sorar; hangisinin olduğunu yalnız diskteki kimlik söyler,
    o yüzden karar domain'de kalır. Ne fiil ne de anahtar bulunursa öneri yoktur — ham cümleyi ikinci
    kez yorumlayan bir yedeği de yoktur."""
    if not text or _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    folded = typo.fold(text)
    if _FOLDER_ANALYSIS_VETO.search(folded) is not None:
        return None
    named_folder = _FOLDER_ANALYSIS_KLASOR.search(folded) is not None
    if not (_FOLDER_ANALYSIS_ASK.search(folded)
            or (named_folder and _FOLDER_ANALYSIS_ASK_WITH_FOLDER.search(folded))):
        return None
    match = _FOLDER_ANALYSIS_NAMED.search(folded)
    # Sözcük katlanmış görünümün aynı konumundan dilimlenir: `typo.fold` uzunluk korur, böylece
    # kullanıcı kendi yazdığı Türkçe adla cevaplanır ("çalışma" → 'çalışma', değil 'calisma').
    name = text[match.start(2):match.end(2)].strip("'’\"") if match else ""
    folder = next((key for key, pattern in _FOLDER_ANALYSIS_WORDS if pattern.search(folded)), "")
    named = next((key for key, pattern in _FOLDER_ANALYSIS_WORDS if pattern.fullmatch(name)), "")
    if not folder and not named:
        return None
    if typo.fold(name) in _FOLDER_ANALYSIS_GENERIC or _FOLDER_ANALYSIS_ASK.fullmatch(typo.fold(name)):
        name = ""
    return {"operation": FOLDER_ANALYSIS_OPERATION, "folder": folder, "named": named, "name": name}


# Echo / semantic preview labels. Each one is derived from an already resolved
# capability + bounded argument; none of them re-reads the user sentence.
_FILE_PREVIEW_LABELS = {
    FILE_SUMMARIZE: "Dosyayı özetleme",
    FILE_ANALYZE: "Dosyayı inceleme",
    FILE_OPEN: "Dosyayı açma",
    FILE_LOCATE: "Dosyayı bulma",
    FILE_LIST: "Dosyaları listeleme",
    FILE_COMPARE: "Dosyaları karşılaştırma",
    FILE_TRANSLATE: "Dosyayı çevirme",
    FILE_CONVERT: "Dosyayı dönüştürme",
}
_PREVIEW_FORMAT_LABELS = {"xlsx": "Excel", "docx": "Word", "pdf": "PDF", "csv": "CSV"}
_PREVIEW_CAPABILITY_LABELS = {
    "notes.read": "Notları okuma",
    NOTES_WRITE_CAPABILITY: "Notu güncelleme",
    TRANSLATE_CAPABILITY: "Sohbetteki metni çevirme",
    "reminder.propose": "Hatırlatma önerisi",
}


def _base_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.replace("\\", "/").rpartition("/")[2].strip()


def _preview_subject(arguments: Mapping[str, Any], references: tuple[ContextReference, ...]) -> str:
    paths = arguments.get("paths")
    if isinstance(paths, (tuple, list)):
        names = tuple(dict.fromkeys(_base_name(item) for item in paths))
        return ", ".join(name for name in names if name)
    name = _base_name(arguments.get("path"))
    if name:
        return name
    for ref in references:
        if ref.kind in {"file", "note"}:
            return _base_name(ref.provenance.get("path")) or ref.id.rpartition(":")[2]
    return ""


def _preview_text(capability_hint: str | None, arguments: Mapping[str, Any],
                  references: tuple[ContextReference, ...]) -> EchoPreview | None:
    if capability_hint == "files.read":
        operation = arguments.get("operation")
        label = _FILE_PREVIEW_LABELS.get(operation if isinstance(operation, str) else "")
        if label is None:
            return None
        if operation == FILE_TRANSLATE:
            label = f"Dosyayı {arguments.get('target', '')} diline çevirme"
        elif operation == FILE_CONVERT:
            fmt = str(arguments.get("format") or "")
            label = f"Dosyayı {_PREVIEW_FORMAT_LABELS.get(fmt, fmt)} biçimine çevirme"
        subject = _preview_subject(arguments, references)
        return EchoPreview(text=f"{label}: {subject}" if subject else label)
    if capability_hint == ORGANIZE_CAPABILITY:
        label = _ORGANIZE_PREVIEW_LABELS.get(str(arguments.get("folder") or ""))
        return EchoPreview(text=f"{label} klasörünü düzenleme") if label else None
    if capability_hint == FOLDER_ANALYSIS_CAPABILITY:
        # Görünüm yalnız doğrulanmış kapalı anahtardan okunur: kullanıcı cümlesi ikinci kez yorumlanmaz.
        key = str(arguments.get("folder") or arguments.get("named") or "")
        label = _FOLDER_ANALYSIS_LABELS.get(key)
        return EchoPreview(text=f"{label} klasörünü inceleme") if label else None
    if capability_hint == PHOTO_CAPABILITY:
        operation = arguments.get("operation")
        if operation == _PHOTO_TRANSLATE:
            return EchoPreview(text=f"Fotoğraf metnini {arguments.get('target', '')} diline çevirme")
        if operation == _PHOTO_NOTE:
            return EchoPreview(text="Fotoğrafı nota ekleme")
        if operation == _PHOTO_ANALYZE:
            return EchoPreview(text="Fotoğrafı analiz etme")
        return None
    if capability_hint == "research.search":
        research = arguments.get("research")
        query = research.get("query") if isinstance(research, Mapping) else None
        if not isinstance(query, str) or not query.strip():
            return None
        return EchoPreview(text=f"Web'de arama: {query.strip()[:80]}")
    if capability_hint in {"weather.read", "weather.read.current"}:
        label = "Güncel hava durumu" if capability_hint.endswith("current") else "Hava durumu"
        location = arguments.get("location")
        return EchoPreview(text=f"{label}: {location}" if isinstance(location, str) and location else label)
    if capability_hint == LEVEL_CAPABILITY:
        prop = arguments.get("property")
        name = {"volume": "Ses", "brightness": "Parlaklık"}.get(prop if isinstance(prop, str) else "", "Seviye")
        level = arguments.get("level")
        return EchoPreview(text=f"{name} ayarı: %{level}" if isinstance(level, int) and not isinstance(level, bool)
                           else f"{name} ayarı")
    if capability_hint in _PREVIEW_CAPABILITY_LABELS:
        return EchoPreview(text=_PREVIEW_CAPABILITY_LABELS[capability_hint])
    return None


_LEVEL_WORDS = {
    "ses": "volume", "sesi": "volume", "sesin": "volume", "sesini": "volume",
    "ses seviyesi": "volume", "ses seviyesini": "volume",
    "parlaklık": "brightness", "parlaklığı": "brightness", "parlaklığını": "brightness",
    "parlaklik": "brightness", "parlakligi": "brightness", "parlakligini": "brightness",
    "ekran parlaklığı": "brightness", "ekran parlaklığını": "brightness",
    "ekran parlaklıgı": "brightness", "ekran parlakligi": "brightness",
    "ekran ışığı": "brightness", "ekran ışığını": "brightness",
    "ekran isigi": "brightness", "ekran isigin": "brightness",
}
_LEVEL_VERBS = r"(?:yap|olsun|ayarla|yapar mısın|yapsana)"
_LEVEL_EXPLICIT = re.compile(
    r"(" + "|".join(sorted((re.escape(word) for word in _LEVEL_WORDS), key=len, reverse=True)) + r")"
    r"\s+(?:yüzde\s*)?(\d{1,3})(?:\s*yüzde)?(?:\s+" + _LEVEL_VERBS + r")?"
)
_LEVEL_BARE = re.compile(r"(?:yüzde\s*(\d{1,3})(?:\s+" + _LEVEL_VERBS + r")?|(\d{1,3})\s+" + _LEVEL_VERBS + r")")
LEVEL_CAPABILITY = "pc.level.set"
ACTION_REQUEST_CODE = "ENDS_WITH_ACTION"
# Understanding "bu cümle bir icra isteğidir" hükmünü yalnız burada verir; kapı bu kaydı okur,
# kendi başına ham metinden niyet türetmez.
EXECUTION_REQUEST_CODE = "EXECUTION_REQUEST"
# Understanding "bu cümle açıklama/sohbet ister" hükmünü de yalnız burada verir: bir yüzey bu
# kaydı okuyabilir, ama aynı hükmü ham metinden ikinci kez sınıflandırarak üretemez.
EXPLANATION_REQUEST_CODE = "EXPLANATION_REQUEST"
LEVEL_UNSPECIFIED = "level target unspecified"


def _level_request(normalized: str, active_context: ActiveContext) -> tuple[str | None, int] | None:
    """Return (property|None, level) for a level-setting utterance, else None.

    The property is explicit in the text, or comes from the fresh ``last_property``
    reference the ActiveContext carries (owner-bound, TTL-checked by its provider).
    A bare number without either stays property=None so Core can ask.
    """
    text = normalized.strip(" .!?")
    explicit = _LEVEL_EXPLICIT.fullmatch(text)
    if explicit is not None:
        return _LEVEL_WORDS[explicit.group(1)], min(int(explicit.group(2)), 100)
    bare = _LEVEL_BARE.fullmatch(text)
    if bare is None:
        return None
    level = min(int(bare.group(1) or bare.group(2)), 100)
    for ref in active_context.recent_references:
        if ref.source == "session_state" and ref.id == "last_property":
            value = ref.provenance.get("value")
            if value in {"volume", "brightness"}:
                return value, level
    return None, level


# PR3A: `engine_commands.handle` içindeki düz-metin dalları (uygulama aç/kapat, ses, medya, ekran
# görüntüsü, kapatma, uyandırma) burada tek tanıyıcıdır. Yalnız cümlenin TAMAMI bir kalıba uyduğunda
# öneri üretilir; Core kararı brain_core_map doğrular, etki sahibi yürütücüde kalır.
APP_TARGET_MISSING = "APP_TARGET_MISSING"
AUDIO_CAPABILITY = "pc.audio.action"
MEDIA_CAPABILITY = "pc.media.action"
SCREEN_CAPTURE_CAPABILITY = "screen.capture"
SHUTDOWN_REQUEST_CAPABILITY = "pc.shutdown.request"
SHUTDOWN_CANCEL_CAPABILITY = "pc.shutdown.cancel"
WAKE_ENABLE_CAPABILITY = "voice.wake.enable"

_APP_OPEN_TAIL = r"(?:aç|açar mısın|açsana|başlat|çalıştır)"
_APP_CLOSE_TAIL = r"(?:kapat|kapatır mısın|kapatsana|kapa)"
# Eski dallarla aynı sınırlar: hedef en fazla 40 karakter, açık sözcük yasağı, konuşma eki korunur.
_APP_OPEN_TARGET = re.compile(rf"^(?:lütfen\s+)?(.+?)\s+{_APP_OPEN_TAIL}$", re.I)
_APP_CLOSE_TARGET = re.compile(rf"^(?:lütfen\s+)?(.+?)\s+{_APP_CLOSE_TAIL}$", re.I)
_APP_OPEN_BLOCK = re.compile(
    r"^(?:ses|sesi|ışık|ışı|kapı|kamera|mikrofon|wifi|bluetooth|internet|onu|bunu|şunu|o|bu|şu|az önceki)\b")
_APP_CLOSE_BLOCK = re.compile(
    r"^(?:ses|sesi|müzi|bilgisayar|pc|mikrofon|kamera|ekran|paylaşım|ışı|wifi|internet|bluetooth|"
    r"jarvis|telefon|uyku|alarm|hatırlat|bildirim|parlaklı|"
    r"(?:onu|bunu|şunu|sunu|o|bu|şu)\b|onları|bunları|şunları)")
_APP_OPEN_MODIFIER = re.compile(r"\b(?:uygulamasını|programını|uygulamayı|programı|oyununu|oyunu)\b")
# "sayfa" hedefli istek bir web/sayfa isteğidir; uygulama hedefi olarak burada seçilmez.
_PAGE_TARGET = re.compile(r"\bsayfa")
# PR3C-1 yazım toleransı: Türkçe karakteri düşmüş görünüm ("chromu acar misin") yalnız ham
# gramerin kaçırdığı *açma* cümlesinde okunur. Katlama uzunluk korur; hedef ham metinden aynı
# span'la alınır, düzeltilmiş metin yürütülebilir komut olmaz. Kapatma yolunda ikinci yorum yok.
_APP_OPEN_TAIL_FOLD = typo.fold(_APP_OPEN_TAIL)
_APP_OPEN_TARGET_FOLD = re.compile(rf"^(?:lütfen\s+)?(.+?)\s+{_APP_OPEN_TAIL_FOLD}$")
_APP_OPEN_BLOCK_FOLD = re.compile(typo.fold(_APP_OPEN_BLOCK.pattern))
_PAGE_TARGET_FOLD = re.compile(typo.fold(_PAGE_TARGET.pattern))
_APP_OPEN_MODIFIER_FOLD = re.compile(r"\b(?:uygulamasini|programini|uygulamayi|programi|oyununu|oyunu)\b")
# Adımlar zinciri tek bir uygulama etkisi değildir: "Ayarları aç ve Bluetooth'u kapat" bütün
# cümlesiyle hedef yürütücüsüne devredilir (`outcome_contracts.open_only_request` aynı hükmü
# verir). Emekli edilen ham dal bağlaçlı cümleyi de tek uygulamaya bağlıyordu; canonical
# sahip zinciri ayırt eder ve hedef uydurmaz.
# Converb kanadı ancak bir eylem fiilinin gövdesine bitişik ek olarak sayılır: "WinZip" ve "7zip"
# kurulu bir uygulama adıdır (APPS sabiti dışında Start Menu'den de çözülür) ve son iki-üç harfi
# Türkçe fiilimsi eki varsayılamaz. Aile `outcome_contracts.open_only_request` fiilleriyle
# ortak tutulur; oraya fiil eklenince buraya da eklenir.
_APP_CONNECTIVE = re.compile(
    r"\b(?:ve|veya|sonra|ardından|ardindan|sonrasında|sonrasinda)\b|[,:;]", re.I)
_APP_ACTION_STEMS = (
    r"ac|aç|baslat|başlat|calistir|çalıştır|kapat|degistir|değiştir|ayarla|yaz|gir|sec|seç|"
    r"tikla|tıkla|uygula|kaydet|sil|gonder|gönder|duraklat|durdur|getir|cikar|çıkar|oynat|"
    r"cevir|çevir|kilitle|guncelle|güncelle|tasi|taşı|al|ver|yap|bas|oku|ara|tara"
)
_APP_CONVERB = re.compile(rf"(?:{_APP_ACTION_STEMS})[ıiyuüyc]?(?:ıp|ip|up|üp|arak|erek)\b", re.I)
_APP_ACTION_TOKEN = re.compile(rf"(?:{_APP_ACTION_STEMS})\w*", re.I)


def _app_chain(text: str) -> bool:
    """Bağlaç/noktalama zinciri ya da kanıtlanmış fiilimsi zinciri (eylem fiili + converb ve
    ardından ikinci bir eylem token'ı). Kelime sonu harfleri tek başına zincir kanıtı değildir."""
    if _APP_CONNECTIVE.search(text):
        return True
    converb = _APP_CONVERB.search(text)
    return converb is not None and _APP_ACTION_TOKEN.search(text, converb.end()) is not None

_AUDIO_NOUN = re.compile(r"(?<!\w)(?:ses|sesi|sesin|sesini|sessiz|sessize|sessizi|sessizden)(?!\w)")
_AUDIO_POLITE_TAIL = re.compile(
    r"(?:\s+(?:mısın|misin|musun|musun|bilir|sin|sın|sun|lütfen|lutfen|benim|için|in|rica|ederim))*\s*$")
_AUDIO_MUTERS = ("kapat", "kes", "sustur", "sıfırla")
_AUDIO_UPNERS = ("yükselt", "arttır", "artır")
_AUDIO_DOWNNERS = ("kıs", "azalt", "düşür")
_AUDIO_UNMUTERS = ("kaldır", "getir", "çıkar", "çık")
_AUDIO_OPENERS = ("sessizi", "sessizden", "geri")

_MEDIA_NEXT = re.compile(
    r"^(?:(?:bir\s+)?sonraki\s+(?:şarkı\w*|parça\w*|müzik\w*|müziği|video\w*)|"
    r"(?:şarkıyı|parçayı|müziği)\s+geç|sonrakine\s+geç)$")
_MEDIA_PREV = re.compile(
    r"^(?:(?:bir\s+)?önceki\s+(?:şarkı\w*|parça\w*|müzik\w*|müziği|video\w*)|"
    r"(?:şarkıyı|parçayı|müziği)\s+geri\s+al|öncekine\s+dön)$")
_MEDIA_TOGGLE = re.compile(
    r"^(?:(?:müziği|şarkıyı|videoyu|oynatmayı)\s+(?:kes|durdur|duraklat|oynat|başlat|çal)|"
    r"müzik\s+(?:dursun|durdur))$")

_SCREEN_CAPTURE_REQUEST = re.compile(
    r"^(?:(?:hey\s+)?jarvis[ ,]+)?(?:(?:ekran\s+(?:görüntüsü|görüntüsünü))\s*(?:al|çek|çıkar)?|"
    r"screenshot\s*(?:al|çek)?|resmini\s+çek)$", re.I)
_SHUTDOWN_REQUEST = re.compile(r"^(?:lütfen\s+)?(?:bilgisayarı|bilgisayar(?:ı)?|pc(?:'i)?|pc)\s+(?:kapat|kapatır mısın|kapatsana|kapa)$")
_SHUTDOWN_CANCEL = re.compile(r"^(?:kapatmayı|kapatma)\s+iptal(?:\s+et)?$")
_WAKE_ENABLE = re.compile(r"^(?:(?:hey\s+)?jarvis)\s+uyandırmasını\s+(?:aç|ac)$")


def _jarvis_page_request(normalized: str) -> bool:
    """Jarvis'in kendi sayfasını açma isteği bir uygulama hedefi değildir; sahibi selfctl kapısıdır."""
    from modules.selfctl import recognizes_page
    return recognizes_page(normalized)


def _app_folded_request(text: str) -> tuple[str, dict[str, object]] | None:
    """Ham açma gramerinin kaçırdığı Türkçe-karakteri-düşmüş cümle; hedef yalnız doğrulanmış
    sabit kimliğe çözülürse `app.open` doğar, çözülemezse hedef sorusu."""
    folded = typo.fold(text)
    if _app_chain(folded):
        return None
    match = _APP_OPEN_TARGET_FOLD.match(folded)
    if match is None:
        return None
    spoken = _APP_OPEN_MODIFIER_FOLD.sub("", match.group(1).strip()).strip()
    if not spoken or len(spoken) > _CLARIFY_TARGET_MAX:
        return None
    if _APP_OPEN_BLOCK_FOLD.match(spoken) is not None or _PAGE_TARGET_FOLD.search(spoken):
        return None
    alias = _verified_app_alias(spoken)
    if alias is None:
        return "target-missing", {"app_target_kind": APP_OPEN_CAPABILITY}
    return APP_OPEN_CAPABILITY, {"app": alias}


def _app_request(normalized: str) -> tuple[str, dict[str, object]] | None:
    """Aç/kapat cümlesinin bounded hedefi; hedef yoksa clarify önerisi (`APP_TARGET_MISSING`)."""
    text = normalized.strip()
    # Dosya/belge hedefinin tek sahibi dosya alanıdır: "dosyayı aç" uygulama açmaz.
    if not text or _jarvis_page_request(text) or _file_operation(text) is not None:
        return None
    # Emekli edilen ham dal cümleyi `strip(" .!?")` ile okuyordu: sesli yazımda "Kapat." ve
    # "Kapatır mısın?" noktalamayla gelir; çıplak fiil tanımı o noktalamadan bağımsızdır.
    bare = re.fullmatch(r"(?:lütfen\s+)?(kapat|kapa|kapatır mısın|kapatsana|aç|açar mısın|açsana)",
                        text.strip(" .!?"))
    if bare is not None:
        kind = APP_OPEN_CAPABILITY if bare.group(1).startswith("aç") else APP_CLOSE_CAPABILITY
        return "target-missing", {"app_target_kind": kind}
    if _app_chain(text):
        return None
    close = _APP_CLOSE_TARGET.match(text)
    if close is not None:
        target = close.group(1).strip()
        if target and len(target) <= _CLARIFY_TARGET_MAX and _APP_CLOSE_BLOCK.match(target) is None \
                and not _PAGE_TARGET.search(target):
            return APP_CLOSE_CAPABILITY, {"app": target}
        return None
    open_match = _APP_OPEN_TARGET.match(text)
    if open_match is None:
        return _app_folded_request(text)
    spoken = _APP_OPEN_MODIFIER.sub("", open_match.group(1).strip()).strip()
    if not spoken or len(spoken) > _CLARIFY_TARGET_MAX or _APP_OPEN_BLOCK.match(spoken) is not None:
        return None
    # "indirme sayfasını aç" bir web sayfası isteğidir: uygulama hedefi burada seçilmez,
    # sahipleri (araştırma/tarayıcı/selfctl sayfası) kendi yollarında kalır.
    if _PAGE_TARGET.search(spoken):
        return None
    return APP_OPEN_CAPABILITY, {"app": spoken}


def _audio_action(normalized: str) -> str | None:
    """Tek cümlelik ses eylemi: cümlenin tamamı bir ses fiiliyle biter, hedef bir ses varlığıdır.

    Sayı taşıyan cümle seviye isteğidir (`pc.level.set`) ve burada yorumlanmaz."""
    text = _AUDIO_POLITE_TAIL.sub("", normalized.strip(" .!?")).strip()
    words = text.split()
    if not words:
        return None
    if not _AUDIO_NOUN.search(text) and "bilgisayarı sustur" not in text:
        return None
    if "yüzde" in words or any(word.isdigit() for word in words):
        return None
    verb = words[-1]
    if "sessize" in words and verb.startswith("al"):
        return "mute"
    if any(verb.startswith(stem) for stem in _AUDIO_DOWNNERS):
        return "lower"
    if any(verb.startswith(stem) for stem in _AUDIO_UPNERS):
        return "volume_up"
    if "modu" in words or "modunu" in words:
        return "unmute" if verb.startswith("kapat") else None
    if any(verb.startswith(stem) for stem in _AUDIO_UNMUTERS) and ("sessiz" in text or "geri" in words):
        return "unmute"
    if verb.startswith("aç"):
        return "unmute" if any(word in words for word in _AUDIO_OPENERS) else "open"
    if "sessiz" in text:
        return None
    if any(verb.startswith(stem) for stem in _AUDIO_MUTERS):
        return "mute"
    return None


def _media_action(normalized: str) -> str | None:
    text = normalized.strip(" .!?")
    if _MEDIA_NEXT.match(text):
        return "next"
    if _MEDIA_PREV.match(text):
        return "prev"
    if _MEDIA_TOGGLE.match(text):
        return "play_pause"
    return None


def _device_request(normalized: str) -> tuple[str, dict[str, object]] | None:
    """Tek canonical cihaz-istek tanıyıcısı: (hint, argüman) ya da None."""
    if not normalized or _is_meta_language(normalized) or _is_literal_command_usage(normalized):
        return None
    audio = _audio_action(normalized)
    if audio is not None:
        return AUDIO_CAPABILITY, {"audio": {"action": audio}}
    media = _media_action(normalized)
    if media is not None:
        return MEDIA_CAPABILITY, {"media": {"action": media}}
    if _SHUTDOWN_CANCEL.match(normalized):
        return SHUTDOWN_CANCEL_CAPABILITY, {}
    if _SHUTDOWN_REQUEST.match(normalized):
        return SHUTDOWN_REQUEST_CAPABILITY, {}
    if _WAKE_ENABLE.match(normalized):
        return WAKE_ENABLE_CAPABILITY, {}
    if _SCREEN_CAPTURE_REQUEST.match(normalized) and not _SCREEN_ANALYZE_CUE.search(normalized):
        return SCREEN_CAPTURE_CAPABILITY, {}
    return _app_request(normalized)


def _active_identity_set(active_context: ActiveContext) -> set[tuple[str, str]]:
    refs = (
        active_context.active_goal_references
        + active_context.active_task_references
        + active_context.active_artifacts
    )
    return {(row.kind, row.id) for row in refs}


def _continues_active(active_context: ActiveContext, references: tuple[ContextReference, ...]) -> bool:
    active = _active_identity_set(active_context)
    return any((row.kind, row.id) in active for row in references)


def _pending_field(reference: ContextReference) -> str:
    raw = reference.provenance.get("field")
    if isinstance(raw, str) and raw.strip():
        return _norm(raw)
    return _norm(reference.id)


def _is_pr6_protocol_answer(text: str) -> bool:
    if text in _PENDING_PROTOCOL_TOKENS:
        return True
    return bool(re.fullmatch(r"\d+", text))


def _looks_like_location_answer(text: str) -> bool:
    raw = text.strip()
    if not raw or any(mark in raw for mark in "?!,;:"):
        return False
    words = raw.split()
    if not 1 <= len(words) <= 2:
        return False
    for word in words:
        pieces = re.split(r"[-']", word)
        if not pieces:
            return False
        for piece in pieces:
            if not piece or not piece.isalpha() or not piece[0].isupper():
                return False
    return True


_PHOTO_FOLLOWUP = re.compile(
    r"analiz|incele|çevir|tercüme|translate|oku|yazı|\bnot|kaydet|sakla|çöz|soru|açıkla|anlat|nedir|"
    r"ne var|ne yazıyor|\bbu\b|bunu|bunda|şunu|resim|fotoğraf|foto|görsel|neresi|hesapla|özetle|kontrol|bak"
)

PHOTO_FOLLOWUP_CODE = "SEMANTIC_PHOTO_FOLLOWUP"
PHOTO_CAPABILITY = "photo.action"
PHOTO_TARGET_AMBIGUOUS = "photo target ambiguous"
PHOTO_TARGET_UNRESOLVED = "photo target unresolved"
_PHOTO_ANALYZE = "analyze"
_PHOTO_TRANSLATE = "translate"
_PHOTO_NOTE = "note"
_PHOTO_NOTE_REQUEST = re.compile(
    r"\bnot\b|not\s*(?:al|ekle|et|olarak)|nota\b|notlara|kaydet|sakla", re.IGNORECASE,
)
_PHOTO_NOTE_STRIP = re.compile(
    r"(?:(?:bu|şu)\s+)?(?:resmi|fotoğrafı|fotoyu|görseli)?\s*(?:not\s+olarak\s+)?"
    r"(?:not\s+(?:al|ekle|et)\w*|nota\s+(?:ekle|al)\w*|notlara\s+ekle\w*|kaydet\w*|sakla\w*|ekle\w*)",
    re.IGNORECASE,
)
_PHOTO_NOTE_HEAD = re.compile(
    r"^\s*(?:(?:bu|şu)\s+(?:resmi|fotoğrafı|fotoyu|görseli)|bunu|şunu)\b[: ]*", re.IGNORECASE,
)
_PHOTO_GENERIC_ANALYZE = re.compile(
    r"(?:bunu |şunu )?(?:analiz et|incele|ne var|bu ne|açıkla|anlat)\w*", re.IGNORECASE,
)


def _canonical_photo_path(active_context: ActiveContext, request_id: str) -> tuple[str | None, bool]:
    """One photo path this request may act on, or an explicit ambiguity.

    The current request's artifact wins; otherwise the pending photo is the continuation target.
    No raw text ever supplies a path."""
    rows = [
        ref for ref in active_context.active_artifacts
        if ref.kind == "photo" and ref.source == "engine_queue.photo"
        and isinstance(ref.provenance.get("path"), str) and ref.provenance.get("path")
    ]
    if not rows:
        return None, False
    current = {
        str(ref.provenance["path"]) for ref in rows
        if str(ref.provenance.get("origin_request_id") or "") == request_id
    }
    if current:
        return (next(iter(current)), False) if len(current) == 1 else (None, True)
    pending = next(
        (ref for ref in active_context.pending_references
         if (ref.id, ref.kind, ref.source) == ("pending_photo", "pending_state", "engine_commands")),
        None,
    )
    if pending is None:
        return None, False
    pending_path = pending.provenance.get("path")
    if not isinstance(pending_path, str) or not pending_path:
        return None, True
    matching = {str(ref.provenance["path"]) for ref in rows
                if str(ref.provenance["path"]) == pending_path}
    return (pending_path, False) if len(matching) == 1 else (None, True)


def _photo_proposal(text: str, normalized: str, active_context: ActiveContext,
                    request_id: str) -> tuple[dict[str, Any] | None, str | None]:
    path, ambiguous = _canonical_photo_path(active_context, request_id)
    if ambiguous:
        return None, PHOTO_TARGET_AMBIGUOUS
    if path is None:
        return None, None
    current = any(
        ref.kind == "photo" and ref.source == "engine_queue.photo"
        and str(ref.provenance.get("origin_request_id") or "") == request_id
        for ref in active_context.active_artifacts
    )
    if not current and not _photo_followup_continuation(normalized, active_context):
        return None, None
    # engine_loop's placeholder turn is the open "ne yapayım?" question, not a hidden analyze.
    if current and text.strip().casefold() in {"", "fotoğraf"}:
        return None, None
    if _PHOTO_NOTE_REQUEST.search(text) and not re.search("analiz|çevir|çöz", normalized):
        stripped = _PHOTO_NOTE_HEAD.sub("", _PHOTO_NOTE_STRIP.sub(" ", text), count=1)
        note_text = re.sub(r"\s+", " ", stripped).strip(" .,:;!-") or "Fotoğraf"
        return {"operation": _PHOTO_NOTE, "photo": path, "note_text": note_text}, None
    if re.search("çevir|tercüme|translate", normalized):
        from modules import translation_targets
        # Explicit but unsupported destination is a clarify, never a silent Türkçe fallback.
        if translation_targets.explicit_target_unresolved(text):
            return None, PHOTO_TARGET_UNRESOLVED
        target = translation_targets.target_from_command(text) or "Türkçe"
        return {"operation": _PHOTO_TRANSLATE, "photo": path, "target": target}, None
    question = text.strip()
    if _PHOTO_GENERIC_ANALYZE.fullmatch(question.strip(" .!?")):
        question = ""
    return {"operation": _PHOTO_ANALYZE, "photo": path, "question": question}, None


def _photo_followup_continuation(normalized: str, active_context: ActiveContext) -> bool:
    """Open-ended photo relation belongs to Understanding, never the exact state gate."""
    if not normalized or _is_context_control(normalized) or _is_correction(normalized):
        return False
    pending = any(
        ref.kind == "pending_state" and ref.source == "engine_commands" and ref.id == "pending_photo"
        for ref in active_context.pending_references
    )
    return pending and _PHOTO_FOLLOWUP.search(normalized) is not None


_CLARIFY_PROPOSALS = frozenset({APP_OPEN_CAPABILITY, APP_CLOSE_CAPABILITY})
_CLARIFY_TARGET_MAX = 40
_ANSWER_CONTROL = frozenset({
    "evet", "hayır", "hayir", "tamam", "olur", "onayla", "onaylıyorum", "onayliyorum",
    "iptal", "vazgeç", "vazgec", "boşver", "bosver",
})


def _clarify_proposal(reference: ContextReference, owner: str) -> Mapping[str, Any] | None:
    """The caller-supplied typed follow-up carried by an active clarify, if any.

    Context observes validity (owner + expiry) and carries the result as ``active``; this
    layer only reads supplied evidence, so it never reads a clock or imports an effect domain."""
    if reference.kind != "pending_state" or reference.source != "session_state" or reference.id != "pending_action":
        return None
    if reference.owner != owner or reference.provenance.get("active") is not True:
        return None
    value = reference.provenance.get("value")
    if not isinstance(value, Mapping) or value.get("stage") != "clarify":
        return None
    if str(value.get("owner") or "") != owner:
        return None
    proposal = value.get("proposal")
    if not isinstance(proposal, Mapping) or proposal.get("kind") not in _CLARIFY_PROPOSALS:
        return None
    return proposal


def _definition_question(normalized: str) -> bool:
    """An explication question ("hava durumu nedir") is chat, not a command with a legacy owner.

    Marker must end at a word boundary: "anlat" inside "anlatımı" / "açıkla" inside "açıklama"
    is a word prefix, not an explanation request."""
    text = f" {normalized}"
    for marker in _STATIC_MARKERS:
        start = text.find(marker)
        while start != -1:
            end = start + len(marker)
            if end == len(text) or not text[end].isalnum():
                return True
            start = text.find(marker, start + 1)
    return False


def explanation_request(text: str, normalized: str) -> bool:
    """Understanding'ın tek açıklama hükmü: cümle bilgi ister, yürütülecek bir iş değildir.

    Üç kanonical dal: tanım/açıklama sorusu (`_definition_question` — aynı hüküm zaten hava durumu
    ve ekran görüntüsü kapılarını da veto eder), soru biçimli rehberlik/eleştiri/karar isteği
    ("… ne yapmalıyım?") ve çıplak selamlama. Icra yetkisi taşıyan cümle (`action_request` /
    `ends_with_action`) açıklama değildir; soru biçimli *olmayan* rehberlik isteği
    ("adım adım wifi nasıl açılır") rehberlik kapısının sahibidir. Yüzeyler bu hükmü okur, ham
    metinden kendi başlarına yeniden sınıflandıramaz.
    """
    if action_request(text) or ends_with_action(text):
        return False
    if _definition_question(normalized):
        # Tanım kalıbı açık tazelik işareti taşıyan dış veri isteğini bastırmaz: "güncel dolar
        # kuru nedir?" canlı kur isteğidir, tanım sorusu değil (mevcut freshness sözleşmesi).
        if not (_RESEARCH_FRESH_TOPIC.search(normalized) and _RESEARCH_NOW_MARK.search(normalized)):
            # "haberleri anlat" gibi taze dış veri isteği açıklama fiiliyle bitse de tanım sorusu
            # değildir; gerçek bir tanım işareti ("nedir", "ne demek") taşımıyorsa tazelik kazanır.
            if not (_needs_fresh_external_data(normalized)
                    and _RESEARCH_DEFINITION.search(normalized) is None):
                return True
    if _advisory_request(normalized) is not None and str(text or "").rstrip().endswith("?"):
        return True
    return any(_bounded_token(normalized, chat) for chat in _GENERIC_CHAT)


# Sıra grameri ('önce A, sonra B' / 'A ardından B') tek sahibindedir. Veto işareti ve adım bölmesi
# aynı kalıptan doğar; motor yüzeyi cümleyi kendi başına bölmez, tipli planı buradan okur.
_SEQUENCE_MARKER = re.compile(r"(?:^\s*önce\s)|(?:\s(?:ardından|akabinde)\s)|(?:\bönce\b.+\bsonra\b)", re.I)
_SEQUENCE_SPLIT = re.compile(r"\s*(?:,\s*)?(?:ve\s+)?(?:daha\s+)?(?:sonra|ardından|akabinde)\s*,?\s+", re.I)
_SEQUENCE_LEAD = re.compile(r"^\s*önce\s+", re.I)


def is_sequenced(text: str) -> bool:
    """Cümle sıralı bir isteğe benziyor; tek adımlı 'önce …' de sıralı sayılır (plan vetosu)."""
    return _SEQUENCE_MARKER.search(text.replace("İ", "i").replace("I", "ı")) is not None


def sequence_steps(text: str) -> tuple[str, ...]:
    """Sıralı isteğin tipli adım planı: en az iki, en çok beş adım; kısa parçalar düşer.

    Adımlar kullanıcının kendi sözcükleriyle döner (büyük/küçük harf ve Türkçe ekler korunur).
    Yürütme typed adaptörde (`engine_sequence._run_steps`) kalır ve her adım kendi canonical
    kararını `brain_entry.run_step` üzerinden alır. Geçersiz tip ilk kalıp çağrısında TypeError
    verir; hiçbir adım üretilmez."""
    body = _SEQUENCE_LEAD.sub("", text)
    if not is_sequenced(text):
        return ()
    parts = [x.strip(" ,.") for x in _SEQUENCE_SPLIT.split(body)]
    parts = [x for x in parts if len(x) >= 3]
    return tuple(parts[:5]) if len(parts) >= 2 else ()


def _weather_status_request(normalized: str) -> bool:
    """Legacy-owned weather status command ("hava durumuna bak"); an independent request, not an answer."""
    if _definition_question(normalized):
        return False
    return _WEATHER_STATUS_CUE.search(normalized) is not None


def _screenshot_request(normalized: str) -> bool:
    """The screenshot command is owned by the legacy desktop handler; it never answers an open slot."""
    if _definition_question(normalized):
        return False
    return _SCREENSHOT_CUE.search(normalized) is not None


def _pending_answer_candidate(normalized: str) -> bool:
    """Structural eligibility shared by every pending slot; ``understand`` already decided the turn.

    Slot-specific semantics belong to each owner: a message body is deliberately free-form while a
    recipient, location or app answer is bounded. Rejecting chat vocabulary or a question mark here
    would silently revoke the open foreground message slot."""
    if not normalized or _is_pr6_protocol_answer(normalized):
        return False
    if _is_context_control(normalized) or _is_correction(normalized):
        return False
    return True


def _message_text_candidate(normalized: str) -> bool:
    """`pending_msg(stage=text)` is an explicit free-form contract: an ordinary sentence is content.

    Greetings and questions are normal message bodies, so this slot never inherits a lexical shape
    rule; only another owner's claim (State, Fast, canonical capability, bounded slot) outranks it."""
    return _pending_answer_candidate(normalized)


def _recipient_contact_evidence(text: str, reference: ContextReference) -> bool:
    """A registered contact name the caller supplied is the strongest recipient evidence."""
    names = reference.provenance.get("recipient_candidates")
    if not isinstance(names, (tuple, list)) or not names:
        return False
    known = {_norm(name) for name in names if isinstance(name, str) and name.strip()}
    return _norm(text) in known


def _human_name_shape(text: str) -> bool:
    """A legacy-compatible human name: bounded identity syntax, never a word-count ceiling.

    A one-word answer is the identity itself; a multi-word name keeps the proper-noun shape the
    other bounded slots use, so an ordinary lowercase sentence cannot become a recipient."""
    raw = text.strip()
    if not raw or len(raw) > _CLARIFY_TARGET_MAX or any(mark in raw for mark in "?!,;:"):
        return False
    words = raw.split()
    pieces = [[piece for piece in re.split(r"[-']", word) if piece] for word in words]
    if any(not parts or any(not part.isalpha() for part in parts) for parts in pieces):
        return False
    if len(words) > 1 and any(not part[0].isupper() for parts in pieces for part in parts):
        return False
    return True


def _bounded_recipient_candidate(text: str, normalized: str, reference: ContextReference) -> bool:
    """The recipient slot is a bounded identity; caller-supplied contact evidence comes first.

    Multi-word sentences and question forms are not identity evidence, so they must not be
    written into `pending_msg.to` even though the body slot legitimately accepts them."""
    if not _pending_answer_candidate(normalized):
        return False
    if any(_bounded_token(normalized, chat) for chat in _GENERIC_CHAT) or "?" in normalized:
        return False
    if any(mark in normalized for mark in ",;:"):
        return False
    return _recipient_contact_evidence(text, reference) or _human_name_shape(text)


def _app_target_evidence(target: str, reference: ContextReference) -> bool:
    """The target must match the canonical app alias evidence the caller supplied.

    Missing or empty evidence fails closed; a short unrelated word is never an app."""
    aliases = reference.provenance.get("targets")
    if not isinstance(aliases, (tuple, list)) or not aliases:
        return False
    known = {_norm(alias) for alias in aliases if isinstance(alias, str) and alias.strip()}
    candidate = _norm(target)
    return bool(candidate) and candidate in known


def _typed_clarify_answer(text: str, normalized: str, active_context: ActiveContext,
                          owner: str) -> tuple[str, dict[str, object]] | None:
    """A typed clarify accepts a bounded target; Understanding—not Core slot presence—decides it."""
    if not _pending_answer_candidate(normalized):
        return None
    target = text.strip(" .!?")
    if not target or _norm(target) in _ANSWER_CONTROL or "?" in target or "\x00" in target \
            or len(target) > _CLARIFY_TARGET_MAX:
        return None
    for pending in active_context.pending_references:
        proposal = _clarify_proposal(pending, owner)
        if proposal is not None and _app_target_evidence(target, pending):
            return str(proposal["kind"]), {"app": target}
    return None


MULTIPLE_PENDING_ANSWER_OWNERS = "MULTIPLE_PENDING_ANSWER_OWNERS"

# Specificity, never slot/consumer order, decides the one owner: a typed bounded clarify target
# first, then a specific domain answer, then a generic free-text draft. The recipient slot ties
# with a location answer unless caller-supplied contact evidence names it.
_PENDING_OWNER_RANK = {
    PendingOwner.APP_CLARIFY: 1,
    PendingOwner.WEATHER_LOCATION: 2,
    PendingOwner.MESSAGE_TO: 2,
    PendingOwner.MESSAGE_TEXT: 3,
}

# A registered contact is not a guess: legacy pending_msg consumption also preceded the weather
# question, so that identity evidence keeps the recipient ahead of an ambiguous city.
_KNOWN_RECIPIENT_RANK = 1


def _pending_answer_owners(text: str, normalized: str, active_context: ActiveContext,
                           clarify_answer: tuple[str, dict[str, object]] | None,
                           *, independent_capability: bool,
                           ) -> tuple[PendingOwner | None, bool]:
    """Pick the single pending owner this utterance can answer, or report true ambiguity.

    The caller supplies the already-made canonical capability decision: a new capability request
    is never an answer, so this selector never re-classifies the utterance. Eligibility is slot
    typed: a bounded recipient or location answer is shaped by its own evidence, while an open
    message body deliberately accepts free text and stays the lowest specificity fallback."""
    if independent_capability or not _pending_answer_candidate(normalized):
        return None, False
    owners: set[PendingOwner] = {PendingOwner.APP_CLARIFY} if clarify_answer is not None else set()
    known_recipient = False
    for pending in active_context.pending_references:
        if pending.kind != "pending_state":
            continue
        field = _pending_field(pending)
        if field == "pending_weather_location" and _looks_like_location_answer(text):
            owners.add(PendingOwner.WEATHER_LOCATION)
        elif field == "pending_msg":
            value = pending.provenance.get("value")
            if not isinstance(value, Mapping):
                continue
            stage = value.get("stage")
            if stage == "to" and _bounded_recipient_candidate(text, normalized, pending):
                owners.add(PendingOwner.MESSAGE_TO)
                known_recipient = known_recipient or _recipient_contact_evidence(text, pending)
            elif stage == "text" and _message_text_candidate(normalized):
                owners.add(PendingOwner.MESSAGE_TEXT)
    if not owners:
        return None, False
    ranks = {
        owner: (_KNOWN_RECIPIENT_RANK
                if owner is PendingOwner.MESSAGE_TO and known_recipient
                else _PENDING_OWNER_RANK[owner])
        for owner in owners
    }
    best_rank = min(ranks.values())
    best = {owner for owner, rank in ranks.items() if rank == best_rank}
    if len(best) > 1:
        return None, True
    return next(iter(best)), False


def _ambiguity_for_references(text: str, references: tuple[ContextReference, ...]) -> tuple[str, ...]:
    if len(references) <= 1 or _plural_reference_intent(text) or _is_correction(text):
        return ()
    if _NOTE_BOUNDED_MUTATION.search(text) is not None:
        return ()
    return ("multiple target references",)


def _correction_arguments(original_text: str, normalized: str) -> dict[str, object]:
    arguments: dict[str, object] = {"original_text": original_text}
    parts = _replacement_parts(normalized)
    if parts is not None:
        rejected, replacement = parts
        arguments["rejected_text"] = rejected
        arguments["replacement_text"] = replacement
    return arguments


def understand(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    candidates: tuple[ContextReference, ...],
    references: tuple[ContextReference, ...],
) -> UnderstandingResult:
    """Return an immutable semantic proposal without taking Core authority."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(text, str):
        raise ValueError("text string olmalı.")
    if not isinstance(active_context, ActiveContext):
        raise ValueError("active_context ActiveContext olmalı.")
    if active_context.owner != owner:
        raise ValueError("ActiveContext owner eşleşmiyor.")
    if active_context.request_id != request_id:
        raise ValueError("ActiveContext request_id eşleşmiyor.")
    candidates = _reference_tuple("candidates", candidates, owner)
    references = _reference_tuple("references", references, owner)
    _require_reference_candidates(candidates, references)

    normalized = _norm(text)
    temporal_need = _temporal_need(normalized)
    correction = _is_correction(normalized)
    topic_change = _is_topic_change(normalized)
    context_control = _is_context_control(normalized)
    # A canonical photo artifact plus a photo operation is a photo request: generic note/file/
    # translation grammars must not reinterpret the same utterance.
    photo_proposal, photo_ambiguity = _photo_proposal(text, normalized, active_context, request_id)
    photo_targeted = photo_proposal is not None or photo_ambiguity is not None
    note_write = None if (photo_targeted or context_control or topic_change or correction) else _note_write_request(normalized)
    note_search = False if (photo_targeted or context_control or topic_change or correction) else _notes_search_request(normalized)
    note_summary = None if (photo_targeted or context_control or topic_change or correction) else _notes_summary_request(normalized)
    notes_read_request = ((not (photo_targeted or context_control or topic_change or correction))
                          and (_is_notes_read_request(normalized) or note_search or note_summary is not None))
    file_operation = None if (photo_targeted or context_control or topic_change or correction) else _file_operation(normalized)
    file_mutation, file_mutation_ambiguity = (
        (None, None) if (photo_targeted or context_control or topic_change or correction)
        else _file_mutation_proposal(normalized, references)
    )
    organize_targets = () if (photo_targeted or context_control or topic_change or correction) else _organize_targets(normalized)
    folder_analysis = (None if (photo_targeted or context_control or topic_change or correction)
                       else folder_analysis_request(normalized))
    ambiguities = _ambiguity_for_references(normalized, references)
    if file_mutation_ambiguity is not None and not ambiguities:
        ambiguities = (file_mutation_ambiguity,)
    if photo_ambiguity is not None:
        ambiguities = (*ambiguities, photo_ambiguity)
    if note_write is not None:
        note_refs = [ref for ref in references if ref.kind == "note"]
        if not note_refs:
            ambiguities = (NOTE_TARGET_UNRESOLVED,)
        elif len(note_refs) > 1:
            ambiguities = (NOTE_TARGET_AMBIGUOUS,)
        elif note_write[0] == "update" and _note_update_text(text) is None:
            ambiguities = (NOTE_UPDATE_TEXT_MISSING,)
    elif note_summary == "one":
        note_refs = [ref for ref in references if ref.kind == "note"]
        if not note_refs:
            ambiguities = (NOTE_TARGET_UNRESOLVED,)
        elif len(note_refs) > 1:
            ambiguities = (NOTE_TARGET_AMBIGUOUS,)
    if (not ambiguities and note_search and not _notes_arguments(normalized, references)
            and _note_window_label(normalized) is None and _is_single_note_search(normalized)):
        ambiguities = (NOTE_SEARCH_QUERY_MISSING,)
    weather_request = _is_weather_request(normalized)
    research_request = _is_explicit_research_request(normalized)
    # Eylem fiili taşıyan icra isteği sohbet olarak bırakılamaz: hedef yürütücüsüne devredilir.
    # Çıplak deiktik ("onu sil") de icra isteğidir; kapıda hedef sorusuyla netleşir.
    # Netleştirme cevabı / konu değişimi / düzeltme yeni bir icra isteği sayılmaz.
    execution_request = (not (context_control or topic_change or correction)
                         and not _is_meta_language(normalized) and not _is_literal_command_usage(normalized)
                         and (action_request(text) or ends_with_action(text)))
    # Ekran/pencere istekleri de birer yetenektir; sohbet olarak bırakılırsa Core planı hiç çalışmaz.
    screen_request = ({} if (context_control or topic_change or correction)
                      else _screen_arguments(text, normalized))
    window_request = ({} if (context_control or topic_change or correction)
                      else _desktop_window_arguments(normalized))
    level = None if (context_control or topic_change or correction) else _level_request(normalized, active_context)
    # PR3A: kaldırılan ham cihaz dallarının tek canonical önerisi (ses/medya/ekran/kapatma/uygulama).
    device = (None if (context_control or topic_change or correction or level is not None)
              else _device_request(normalized))
    translation, translate_args = (None, {})
    if level is None and not photo_targeted and not (context_control or topic_change or correction):
        translation, translate_args = _translate_proposal(text, candidates)
        if translation is not None:
            # The translation source rule owns "which text"; reference ambiguity does not apply to it.
            ambiguities = () if translate_args else (TRANSLATE_SOURCE_MISSING,)
    if level is not None and level[0] is None:
        ambiguities = (LEVEL_UNSPECIFIED,)
    elif device is not None and device[0] == "target-missing" and not ambiguities:
        ambiguities = (APP_TARGET_MISSING,)
    elif not ambiguities and not context_control and file_operation is not None:
        file_refs = [ref for ref in references if ref.kind == "file"]
        if file_operation in _FILE_TARGET_REQUIRED and len(file_refs) != 1:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation in _FILE_ASK_EXEMPT and len(file_refs) > 1:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation == FILE_COMPARE and not 2 <= len(file_refs) <= 10:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation == FILE_TRANSLATE and _file_language(normalized) is None:
            ambiguities = (FILE_TRANSLATION_TARGET_MISSING,)
        elif file_operation == FILE_CONVERT and _file_format(normalized) is None:
            ambiguities = (FILE_CONVERSION_FORMAT_MISSING,)
    elif not ambiguities and len(organize_targets) > 1:
        # Bir cümle birden fazla klasörü düzenlemek istiyorsa hangi sırayla ve hangisi önce decided
        # değildir; tek klasöre tahminle bağlamak yerine kullanıcıya sorulur.
        ambiguities = (ORGANIZE_TARGET_AMBIGUOUS,)

    photo_followup = _photo_followup_continuation(normalized, active_context)
    # Canonical capability decision, produced exactly once. An explicit capability request is never
    # the target of an open-ended clarify: it supersedes it. A typed pending continuation is the
    # opposite case: its target answers an open clarify, so it is not an independent request.
    explicit_capability_request = (
        level is not None or notes_read_request or note_write is not None or weather_request
        or research_request or screen_request or window_request or execution_request
        or translation is not None or file_operation is not None or file_mutation is not None or photo_proposal is not None
        or device is not None or bool(organize_targets) or folder_analysis is not None
        or _looks_like_capability(normalized)
        or (not (context_control or topic_change or correction)
            and (_weather_status_request(normalized) or _screenshot_request(normalized)))
    )
    typed_pending_capability = (
        None if explicit_capability_request
        else _typed_clarify_answer(text, normalized, active_context, owner)
    )
    independent_capability = explicit_capability_request and typed_pending_capability is None
    pending_owner, pending_ambiguous = _pending_answer_owners(
        text, normalized, active_context, typed_pending_capability,
        independent_capability=independent_capability,
    )
    if pending_ambiguous:
        ambiguities = (*ambiguities, MULTIPLE_PENDING_ANSWER_OWNERS)
    if topic_change:
        relation = ConversationRelation.TOPIC_CHANGE
    elif correction:
        relation = ConversationRelation.CORRECTION
    elif photo_followup:
        # Bekleyen telefona devam: relation'ı surface regex'i değil Understanding seçer.
        relation = ConversationRelation.CONTINUE_ACTIVE
    elif typed_pending_capability is not None or pending_owner is not None or pending_ambiguous:
        relation = ConversationRelation.ANSWER_TO_PENDING
    elif _continues_active(active_context, references):
        relation = ConversationRelation.CONTINUE_ACTIVE
    else:
        relation = ConversationRelation.NEW_REQUEST

    if context_control:
        request_kind = RequestKind.CONTEXT_CONTROL
    elif ambiguities:
        request_kind = RequestKind.CLARIFY
    elif typed_pending_capability is not None or explicit_capability_request:
        request_kind = RequestKind.CAPABILITY
    else:
        request_kind = RequestKind.CHAT

    if topic_change:
        context_actions = (ContextAction.DROP_TOPIC,)
    elif correction:
        if _is_bosver_control(normalized):
            context_actions = (ContextAction.DROP_TOPIC,)
        else:
            context_actions = (ContextAction.REPLACE_REFERENCE,)
    else:
        context_actions = (ContextAction.KEEP,)

    reason_codes: list[str] = []
    if relation is ConversationRelation.ANSWER_TO_PENDING:
        reason_codes.append("SEMANTIC_PENDING_ANSWER")
    elif relation is ConversationRelation.CONTINUE_ACTIVE:
        reason_codes.append("ACTIVE_REFERENCE_CONTINUATION")
        if photo_followup:
            reason_codes.append(PHOTO_FOLLOWUP_CODE)
    elif relation is ConversationRelation.CORRECTION:
        reason_codes.append("USER_CORRECTION")
    elif relation is ConversationRelation.TOPIC_CHANGE:
        reason_codes.append("USER_TOPIC_CHANGE")
    else:
        reason_codes.append("NEW_REQUEST_DEFAULT")
    if execution_request:
        reason_codes.append(EXECUTION_REQUEST_CODE)
    if LEVEL_UNSPECIFIED in ambiguities:
        reason_codes.append("LEVEL_TARGET_UNSPECIFIED")
    elif FILE_TARGET_UNRESOLVED in ambiguities:
        reason_codes.append("FILE_TARGET_UNRESOLVED")
    elif FILE_TRANSLATION_TARGET_MISSING in ambiguities:
        reason_codes.append("FILE_TRANSLATION_TARGET_MISSING")
    elif FILE_CONVERSION_FORMAT_MISSING in ambiguities:
        reason_codes.append("FILE_CONVERSION_FORMAT_MISSING")
    elif NOTE_TARGET_UNRESOLVED in ambiguities:
        reason_codes.append("NOTE_TARGET_UNRESOLVED")
    elif NOTE_UPDATE_TEXT_MISSING in ambiguities:
        reason_codes.append("NOTE_UPDATE_TEXT_MISSING")
    elif NOTE_SEARCH_QUERY_MISSING in ambiguities:
        reason_codes.append("NOTE_SEARCH_QUERY_MISSING")
    elif MULTIPLE_PENDING_ANSWER_OWNERS in ambiguities:
        reason_codes.append(MULTIPLE_PENDING_ANSWER_OWNERS)
    elif ORGANIZE_TARGET_AMBIGUOUS in ambiguities:
        reason_codes.append(ORGANIZE_TARGET_AMBIGUOUS)
    elif photo_ambiguity is not None:
        reason_codes.append(photo_ambiguity)
    elif ambiguities:
        reason_codes.append("MULTIPLE_TARGET_REFERENCES")
    if level is not None and level[0] is not None:
        reason_codes.append("LEVEL_REQUEST")
    if ends_with_action(text):
        reason_codes.append(ACTION_REQUEST_CODE)

    confidence = Confidence.MEDIUM
    if relation in {
        ConversationRelation.ANSWER_TO_PENDING,
        ConversationRelation.CONTINUE_ACTIVE,
        ConversationRelation.CORRECTION,
        ConversationRelation.TOPIC_CHANGE,
    }:
        confidence = Confidence.HIGH
    if ambiguities:
        confidence = Confidence.LOW

    arguments = (
        _correction_arguments(text, normalized)
        if correction
        else {"original_text": text}
    )
    capability_hint = FILE_MUTATE_CAPABILITY if file_mutation is not None else _capability_hint(normalized, temporal_need)
    if typed_pending_capability is not None:
        capability_hint, clarify_arguments = typed_pending_capability
        arguments = {**arguments, **clarify_arguments}
    if translation is not None:
        capability_hint = TRANSLATE_CAPABILITY
        arguments = {**arguments, **translate_args}
    if photo_proposal is not None:
        # Photo operation is decided only here; every surface consumer reads this typed proposal.
        capability_hint = PHOTO_CAPABILITY
        arguments = {**arguments, **photo_proposal}
    if capability_hint in {"weather.read", "weather.read.current"}:
        location = _weather_location(normalized)
        if location is not None:
            arguments = {**arguments, "location": location}
    if capability_hint == "reminder.propose":
        arguments = {**arguments, **_reminder_arguments(text)}
    if capability_hint == "files.read":
        arguments = {**arguments, **_file_arguments(normalized, references)}
    if capability_hint == FILE_MUTATE_CAPABILITY and file_mutation is not None:
        arguments = {**arguments, **file_mutation}
    if capability_hint == "research.search":
        arguments = {**arguments, **_research_arguments(text, normalized)}
    if capability_hint == "notes.read":
        arguments = {**arguments, **_notes_arguments(normalized, references)}
        if not arguments.get("notes") and note_search:
            arguments = {**arguments, **_notes_search_arguments(normalized)}
        if not arguments.get("notes") and note_summary is not None:
            arguments = {**arguments, **_notes_summary_arguments(normalized, references, note_summary)}
    if capability_hint == NOTES_WRITE_CAPABILITY:
        arguments = {**arguments, **_notes_write_arguments(text, normalized, references)}
    if capability_hint == SCREEN_CAPABILITY:
        arguments = {**arguments, **_screen_arguments(text, normalized)}
    if capability_hint in {WINDOW_LIST_CAPABILITY, WINDOW_OP_CAPABILITY}:
        arguments = {**arguments, **_desktop_window_arguments(normalized)}
    if device is not None:
        # Cihaz önerisi tek kalıptan gelir: hedefsız fiil yalnız sorusunu taşır, etki taşımaz.
        arguments = {**arguments, **device[1]}
        if device[0] != "target-missing":
            capability_hint = device[0]
    if level is not None:
        arguments = {**arguments, "level": level[1]}
        if level[0] is not None:
            arguments["property"] = level[0]
            capability_hint = LEVEL_CAPABILITY
        else:
            capability_hint = None
    # Son bağlanır: bir üstteki hiçbir öneri düzenleme anahtarını taşıyorsa payload'ı da yoktur.
    if capability_hint == ORGANIZE_CAPABILITY:
        arguments = {**arguments, **_organize_arguments(organize_targets)}
    # Klasör analizi anahtarları da yalnız tek öneriden gelir: ipucu bu yetenek değilse payload yoktur.
    if capability_hint == FOLDER_ANALYSIS_CAPABILITY and folder_analysis is not None:
        arguments = {**arguments, **folder_analysis}

    # Advisory chat shaping is a semantic choice, so it is resolved once here and the
    # advisor layer only formats. A Core-mapped request keeps its own owner.
    advisory = None if (context_control or topic_change or correction or capability_hint) else _advisory_request(normalized)
    if advisory is not None:
        arguments = {**arguments, ADVISORY_ARGUMENT_KEY: advisory}
    # Açıklama hükmü de burada doğar ve tek sahibinden okunur: hiçbir legacy yüzey aynı cümleyi
    # ikinci kez "bu bir soru" diye sınıflandırmaz.
    if explanation_request(text, normalized):
        reason_codes.append(EXPLANATION_REQUEST_CODE)
        # Tanım/risk sorusu bir anahtar sözcük yüzünden yetenek önerisi taşıyamaz: bağımsız yeni
        # turda ipucu ve typed payload düşer, karar CHAT olur. Bekleyen cevap, typed pending,
        # konu değişimi/düzeltme ve belirsizlik turları kendi sahiplerinde kalır.
        if (not (context_control or topic_change or correction) and typed_pending_capability is None
                and pending_owner is None and not pending_ambiguous and not ambiguities
                and photo_proposal is None):
            if capability_hint:
                capability_hint = None
                arguments = {"original_text": text}
            if request_kind is RequestKind.CAPABILITY:
                request_kind = RequestKind.CHAT
    preview = None
    if request_kind is RequestKind.CAPABILITY and not ambiguities:
        preview = _preview_text(capability_hint, arguments, references)

    return UnderstandingResult(
        owner=owner,
        request_id=request_id,
        request_kind=request_kind,
        capability_hint=capability_hint,
        arguments=arguments,
        references=references,
        conversation_relation=relation,
        pending_owner=pending_owner,
        temporal_need=temporal_need,
        context_actions=context_actions,
        confidence=confidence,
        ambiguities=ambiguities,
        assumptions=(),
        reason_codes=tuple(reason_codes),
        needs_input=bool(ambiguities),
        preview=preview,
    )