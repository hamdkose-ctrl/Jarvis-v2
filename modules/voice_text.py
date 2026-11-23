"""Ses için metin temizliği (S3).

Sorun (ölçüldü, 23 Kasım): akademik cevapta ses, yazının **işaretlerini** okuyordu.
Cevabın 1631 karakteri seslendirmeye 389 karakter olarak gidiyor ama 56,7 saniye
sürüyordu (normal hız 11-14 karakter/sn → ~30 sn olmalıydı). Sebep: `**1.**`,
`https://doi.org/10.70269/...` ve `— 2026-06` gibi parçaların tek tek okunması.

Kurallar (hiçbir bilgi uydurulmaz, metin ekranda aynı kalır):
* Markdown işaretleri (`**`, `*`, `_`, `#`, `` ` ``, tablo çizgileri) seslenmez.
* Adres ve DOI okunmaz ("kaynak doi org ..." demek yerine atlanır).
* `2026-06` → "Haziran 2026", `12.03.2026` → "12 Mart 2026".
* `%12` → "yüzde on iki"; `1.250` → "bin 250" değil, "bin iki yüz elli" değil —
  sayı okunuşu Türkçe'ye çevrilir, basamak basamak değil.
* Parantez içi atıf `(2021)` / `[3]` seslenmez.
* Kod bloğu, emoji ve art arda gelen boşluklar temizlenir.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- sabitler
_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
           "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")

_ONES = ("", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_TENS = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan")
_SCALES = ((1_000_000_000, "milyar"), (1_000_000, "milyon"), (1_000, "bin"))

_URL = re.compile(r'(?:https?://|www\.)\S+', re.I)
_DOI = re.compile(r'\b(?:doi:\s*)?10\.\d{4,9}/[^\s,;)]+', re.I)
_EMAIL = re.compile(r'\S+@\S+\.\S+')
_CODE_FENCE = re.compile(r'```.*?```', re.S)
_INLINE_CODE = re.compile(r'`([^`]*)`')
_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')          # [metin](adres) → metin
_MD_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')           # resim tamamen düşer
_BRACKET_CITE = re.compile(r'\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]')
_PAREN_YEAR = re.compile(r'\(\s*(?:19|20)\d{2}[a-z]?\s*\)')
_MD_MARKS = re.compile(r'[*_#>~|]+')
_TABLE_LINE = re.compile(r'^\s*[|\-: ]{4,}\s*$', re.M)
_EMOJI = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]')
_DASHES = re.compile(r'\s*[—–]\s*')
_BULLET = re.compile(r'^\s*[-•*+]\s+', re.M)
_NUMBERED = re.compile(r'^\s*\d+[.)]\s+', re.M)
_ISO_DATE = re.compile(r'\b((?:19|20)\d{2})-(\d{2})(?:-(\d{2}))?\b')
_TR_DATE = re.compile(r'\b(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})\b')
_PERCENT = re.compile(r'%\s?(\d[\d.,]*)')
_PERCENT_AFTER = re.compile(r'(\d[\d.,]*)\s?%')
_THOUSANDS = re.compile(r'\b\d{1,3}(?:\.\d{3})+\b')
_DECIMAL = re.compile(r'\b(\d+),(\d+)\b')
_EMPTY_PARENS = re.compile(r'\(\s*\)|\[\s*\]')
_LABEL_ONLY = re.compile(r'^\s*(?:kaynak|doi|bağlantı|baglanti|link|adres|url)\s*:?\s*$', re.I | re.M)
_ORPHAN_JOIN = re.compile(r'[:;,]?\s+(?:ve|veya)\s*(?=[.,;:!?]|$)', re.I)
_SPACES = re.compile(r'[ \t]{2,}')
_BLANK_LINES = re.compile(r'\n{2,}')


def number_to_words(value: int) -> str:
    """Türkçe sayı okunuşu: 1250 → "bin iki yüz elli"."""
    if value == 0:
        return "sıfır"
    if value < 0:
        return "eksi " + number_to_words(-value)
    parts: list[str] = []
    remaining = value
    for size, name in _SCALES:
        if remaining >= size:
            count = remaining // size
            remaining = remaining % size
            if size == 1_000 and count == 1:
                parts.append(name)             # "bin", "bir bin" değil
            else:
                parts.append(number_to_words(count) + " " + name)
    if remaining:
        hundreds, rest = divmod(remaining, 100)
        if hundreds:
            parts.append(("yüz" if hundreds == 1 else _ONES[hundreds] + " yüz"))
        tens, ones = divmod(rest, 10)
        if tens:
            parts.append(_TENS[tens])
        if ones:
            parts.append(_ONES[ones])
    return " ".join(part for part in parts if part)


def _digits_to_words(text: str) -> str:
    """Yalnız basamak gruplu sayılar (1.250) ve ondalık (12,5) çevrilir.

    Düz sayılar (`14`, `5`) OLDUĞU GİBİ bırakılır: ses motoru onları zaten doğru
    okuyor ve "14:00" gibi saatler bozulmuyor. Yalnız yanlış okunan biçimler
    (binlik nokta, yüzde, tarih) çevrilir.
    """
    def thousands(match):
        return number_to_words(int(match.group(0).replace('.', '')))
    return _THOUSANDS.sub(thousands, text)


def _dates_to_words(text: str) -> str:
    """`2026-06` → "Haziran iki bin yirmi altı", `12.03.2026` → "on iki Mart ..."."""
    def iso(match):
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            return match.group(0)
        day = match.group(3)
        label = _MONTHS[month - 1] + " " + number_to_words(year)
        if day and 1 <= int(day) <= 31:
            return number_to_words(int(day)) + " " + label
        return label

    def tr(match):
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        return f"{number_to_words(day)} {_MONTHS[month - 1]} {number_to_words(year)}"
    return _TR_DATE.sub(tr, _ISO_DATE.sub(iso, text))


def _percent_to_words(text: str) -> str:
    """`%12`, `%12,5`, `12%` → "yüzde on iki", "yüzde on iki virgül beş"."""
    def one(raw: str) -> str:
        raw = raw.replace('.', '')
        whole, _, frac = raw.partition(',')
        out = "yüzde " + number_to_words(int(whole)) if whole.isdigit() else "yüzde"
        if frac and frac.isdigit():
            out += " virgül " + " ".join(_ONES[int(d)] or "sıfır" for d in frac)
        return out
    text = _PERCENT.sub(lambda m: one(m.group(1)), text)
    return _PERCENT_AFTER.sub(lambda m: one(m.group(1)), text)


def speakable(text: str) -> str:
    """Yazıyı sesin okuyacağı hâle getirir; ekrandaki metne dokunmaz.

    Hiçbir cümle uydurulmaz ve cümle sırası değişmez: yalnız okunmayacak
    parçalar (adres, markdown, atıf) düşer, sayı/tarih Türkçe okunuşa çevrilir.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    body = _CODE_FENCE.sub(" ", text)
    body = _MD_IMAGE.sub(" ", body)
    body = _MD_LINK.sub(lambda m: m.group(1), body)
    body = _URL.sub(" ", body)
    body = _DOI.sub(" ", body)
    body = _EMAIL.sub(" ", body)
    body = _INLINE_CODE.sub(" ", body)      # kod seslenmez
    body = _BRACKET_CITE.sub(" ", body)
    body = _PAREN_YEAR.sub(" ", body)
    body = _TABLE_LINE.sub(" ", body)
    body = _MD_MARKS.sub("", body)
    body = _BULLET.sub("", body)
    body = _NUMBERED.sub("", body)
    body = _EMOJI.sub(" ", body)
    body = _DASHES.sub(", ", body)
    body = _percent_to_words(body)
    body = _dates_to_words(body)
    body = _digits_to_words(body)
    body = _EMPTY_PARENS.sub(" ", body)
    body = _SPACES.sub(" ", body)
    body = _BLANK_LINES.sub("\n", body)
    body = _LABEL_ONLY.sub("", body)
    body = _ORPHAN_JOIN.sub("", body)
    body = re.sub(r'\s+([,.;:!?])', r'\1', body)
    body = re.sub(r'([,;:])\1+', r'\1', body)
    body = re.sub(r'^[\s,.;:]+', '', body)
    return body.strip()
