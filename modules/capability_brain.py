"""Yetenek beyni: serbest cümleyi katalogdaki bir yeteneğe eşler.

Sıra: (1) hızlı kalıplar — kesin ve anında; (2) **katalog eşleşmesi** — serbest
cümleyi örneklerle/anahtar sözcüklerle karşılaştırır; (3) hiçbiri tutmazsa
**yapmaz**, ne anladığını söyler.

İlkeler:
- Emin değilse iş yapmaz: eşik altındaki eşleşme `uncertain` döner, çağıran tek
  soru sorar. Tahminle pencere/dosya seçmek yok.
- Eksik bilgi uydurulmaz: gereken alan (pencere, metin, yol) yoksa `need` döner.
- Türkçe ekler: "chrome'da / chrome da / chrome'un" aynı pencere sayılır.
"""
from __future__ import annotations

import re

from modules import capability_catalog, fast_commands

MATCH_THRESHOLD = 2.0
FOLD = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
STOP = {"bir", "bu", "su", "şu", "ve", "ile", "da", "de", "ki", "mi", "ne", "icin", "için", "olan"}
WINDOW_WORDS = ("chrome", "not defteri", "notepad", "hesap makinesi", "edge", "explorer",
                "dosya gezgini", "outlook", "whatsapp", "word", "excel", "terminal")


def fold(text: str) -> str:
    return " ".join(str(text or "").casefold().translate(FOLD).split())


SUFFIXES = ("lari", "leri", "sini", "sana", "sene", "dan", "den", "tan", "ten", "dir", "dur",
            "lar", "ler", "ini", "ina", "ine", "nin", "nun", "daki", "deki", "a", "e", "i", "u")

SYNONYMS = {
    "yutup": "youtube", "youtube": "youtube", "video": "youtube", "izle": "youtube",
    "posta": "mail", "eposta": "mail", "gmail": "mail", "inbox": "mail", "mailler": "mail",
    "sarki": "muzik", "muzik": "muzik", "spotify": "muzik",
    "kaydet": "kaydet", "sakla": "kaydet", "store": "kaydet",
    "tikla": "tikla", "bas": "tikla", "dokun": "tikla",
    "yaz": "yaz", "yaziver": "yaz", "not": "yaz", "ekle": "yaz",
    "ara": "ara", "bul": "ara", "search": "ara",
    "ekran": "ekran", "sayfa": "ekran", "goruntu": "ekran",
    "klasor": "klasor", "dizin": "klasor", "folder": "klasor",
    "dosya": "dosya", "belge": "dosya", "file": "dosya",
    "oku": "oku", "goster": "oku", "bak": "oku",
}


def stem(word: str) -> str:
    """Kaba Türkçe gövdeleme: 'mailleri' → 'mail', 'youtube'ya' → 'youtube'."""
    text = fold(word)
    for suffix in sorted(SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix) and len(text) - len(suffix) >= 3:
            text = text[: -len(suffix)]
            break
    return SYNONYMS.get(text, text)


def tokens(text: str) -> set[str]:
    return {stem(word) for word in re.findall(r"[a-z0-9]+", fold(text)) if len(word) > 1 and word not in STOP}


SITES = {"youtube": "youtube.com", "yutup": "youtube.com", "mail": "gmail.com",
         "gmail": "gmail.com", "eposta": "gmail.com", "muzik": "music.youtube.com",
         "müzik": "music.youtube.com", "google": "google.com", "haber": "news.google.com",
         "harita": "maps.google.com", "twitter": "x.com", "whatsapp": "web.whatsapp.com"}

VERBS = {
    "pc_type": ("yaz", "yaziver", "gir"),
    "pc_search": ("git", "ara", "baslat", "enter", "yonlendir"),
    "pc_click_result": ("tikla", "bas", "gir", "ac"),
    "pc_click": ("tikla", "bas"),
    "pc_save": ("kaydet", "sakla"),
    "pc_confirm": ("onay", "onayliyorum", "evet"),
    "screen_summary": ("var", "acik", "calisiyorum"),
    "screen_controls": ("var", "dugmeler", "alanlar"),
    "file_list": ("listele", "var"),
    "file_read": ("oku",),
    "autonomy_schedule": ("kur", "sonra", "yarin"),
    "autonomy_status": ("durum",),
    "pc_open_site": ("ac", "acsana", "git", "gir"),
    "screen_read_text": ("yaziyor", "yazmis", "oku", "ne", "var"),
}


def _hits(word: str, phrase: str) -> bool:
    """Türkçe ekleri kabaca tolere et: 'sonuca' ≈ 'sonucuna', 'tıkla' ≈ 'tıklıyorum'."""
    if word == phrase:
        return True
    shorter, longer = (word, phrase) if len(word) <= len(phrase) else (phrase, word)
    return len(shorter) >= 4 and longer.startswith(shorter)


def _score(capability: dict, words: set[str], text: str) -> float:
    phrases = {fold(phrase) for phrase in capability["phrases"]}
    score = 0.0
    for phrase in phrases:
        if " " in phrase:
            if phrase in text:
                score += 1.5
        elif any(_hits(word, phrase) for word in words):
            score += 1.0
    verbs = VERBS.get(capability["intent"], ())
    if any(any(_hits(word, verb) for word in words) for verb in verbs):
        score += 1.2          # eylem sözcüğü en güçlü işaret
    for example in capability["examples"]:
        overlap = len(tokens(example) & words)
        if overlap:
            score += 0.6 * overlap / max(1, len(tokens(example)))
    return score


def find_window_word(text: str) -> str:
    folded = fold(text)
    for name in WINDOW_WORDS:
        if fold(name) in folded:
            return name
    return ""


READ_CUES = ("ne yaziyor", "ne yazmis", "mail ne", "ilk mail", "sayfada ne", "ekranda ne yaz")


def _site_of(text: str) -> str:
    folded = fold(text)
    for word, site in SITES.items():
        if fold(word) in folded:
            return site
    return ""


def resolve(text: str) -> dict:
    """Cümleyi yeteneğe çevirir: {'status': ok|need|uncertain|none, ...}."""
    raw = str(text or "").strip()
    if not raw:
        return {"status": "none", "text": ""}
    file_words = {"klasor", "dosya", "indirilen", "indirilenler", "masaust", "masaustu", "belge"}
    has_file_word = bool(tokens(raw) & file_words)
    fast = fast_commands.resolve(raw)
    if fast and fast[0] == "app_open" and _site_of(raw):
        # Site adı söylenmişse uygulama açma kapısı yerine tarayıcıda gezinme yeterli.
        return {"status": "ok", "capability": "pc_open_site", "slots": {"text": _site_of(raw)},
                "via": "pattern"}
    if fast and not (has_file_word and fast[0].startswith("screen_")):
        return {"status": "ok", "capability": fast[0], "slots": fast[1], "via": "pattern"}
    folded = fold(raw)
    words = tokens(raw)
    if any(cue in folded for cue in READ_CUES):
        return {"status": "ok", "capability": "screen_read_text", "slots": {}, "via": "catalog"}
    ranked = sorted(((item, _score(item, words, folded)) for item in capability_catalog.CATALOG),
                    key=lambda pair: pair[1], reverse=True)
    best, score = ranked[0]
    if has_file_word:
        file_items = [item for item, _ in ranked if item["intent"] in ("file_list", "file_read")]
        if file_items:
            best, score = file_items[0], max(score, MATCH_THRESHOLD)
    if score < MATCH_THRESHOLD:
        return {"status": "uncertain", "score": round(score, 2),
                "capability": None, "text": raw,
                "candidates": [item["intent"] for item, value in ranked[:3] if value > 0]}
    # Yanlış iş yapmama: pencere gerektiren yeteneklerde pencere söylenmemişse
    # tahmin yok — "bana bir şiir yaz" bir PC komutu değildir.
    nav_words = ("git", "enter", "ara", "baslat")
    has_nav = any(any(_hits(word, verb) for word in words) for verb in nav_words)
    if (best["intent"] in ("pc_type", "pc_click", "pc_save", "pc_search")
            and not find_window_word(raw)
            and not (best["intent"] == "pc_search" and has_nav)):
        return {"status": "uncertain", "score": round(score, 2), "capability": None,
                "text": raw, "candidates": [best["intent"]]}
    if best["intent"] == "autonomy_schedule":
        from modules import autonomy_when
        parsed = autonomy_when.parse_when(raw)
        inner = fast_commands.resolve(parsed.get("rest") or "") if parsed.get("when") else None
        if not inner or not inner[0].startswith("pc_"):
            return {"status": "uncertain", "score": round(score, 2), "capability": None,
                    "text": raw, "candidates": [best["intent"]]}
    args = _slots(best, raw)
    missing = [slot for slot in best["needs"] if not args.get(slot)]
    if missing:
        return {"status": "need", "capability": best["intent"], "slots": args,
                "missing": missing, "text": raw}
    return {"status": "ok", "capability": best["intent"], "slots": args, "via": "catalog",
            "score": round(score, 2)}


FOLDERS = {"indirilenler": "Downloads", "downloads": "Downloads", "masaustu": "Desktop",
           "desktop": "Desktop", "belgeler": "Documents", "documents": "Documents"}


def guess_path(raw: str, *, want_file: bool) -> str:
    """Söylenen klasör/dosya adını gerçek yola çevirir; emin değilse boş döner."""
    from pathlib import Path as _Path
    words = tokens(raw)
    home = _Path.home()
    for word, folder in FOLDERS.items():
        matched = any(_hits(token, stem(word)) or _hits(stem(token), stem(word)) for token in words)
        if matched and (home / folder).is_dir():
            return str(home / folder) if not want_file else ""
    if not want_file:
        return ""
    # Dosya adı: ev klasöründe adı geçen tek dosya varsa onu kullan (okuma, en çok 400 dosya).
    needle = [word for word in words if len(word) > 2 and word not in
              {"oku", "dosya", "dosyayi", "dosyasini", "icini", "icerigini", "oku"}]
    if not needle:
        return ""
    found = []
    for path in list(home.rglob("*"))[:400]:
        if path.is_file() and all(part in fold(path.name) for part in needle):
            found.append(path)
    return str(found[0]) if len(found) == 1 else ""


def _slots(capability: dict, raw: str) -> dict:
    intent = capability["intent"]
    window = find_window_word(raw)
    args: dict = {}
    if window:
        args["window"] = window
    if intent == "pc_type":
        spoken = re.sub(r"(?i)\b(chrome|not defteri|notepad|hesap makinesi|edge|explorer)\b", " ", raw)
        spoken = re.sub(r"(?i)\b(adres|adres çubuğuna|arama kutusuna|kutusuna|alanına|alana|yaz|yazıver|gir)\b", " ", spoken)
        words_only = [word for word in spoken.split() if len(word) > 1]
        candidate = " ".join(words_only).strip(" ,.;'\"")
        if candidate:
            args["text"] = candidate
        if intent == "pc_type" and window and "window" not in args:
            args["window"] = window
    elif intent == "pc_open_site":
        words = tokens(raw)
        for word, site in SITES.items():
            if fold(word) in words or fold(word) in fold(raw):
                args["text"] = site
                break
        if not args.get("text"):
            spoken = re.sub(r"(?i)(aç|açsana|açar mısın|sitesini|siteyi|git|gir)", " ", raw)
            candidate = " ".join(part for part in spoken.split() if len(part) > 1)
            if candidate:
                args["text"] = candidate
    elif intent == "pc_click_result":
        spoken = re.sub(r"(?i)\b(sonucuna|sonuca|sonuç|tıkla|bas|ekrandaki|yazısına|linke|başlığa|gir)\b", " ", raw)
        words_only = [word for word in spoken.split() if len(word) > 1]
        candidate = " ".join(words_only).strip(" ,.;'\"")
        if candidate:
            args["query"] = candidate
    elif intent in ("file_list", "file_read"):
        guess = guess_path(raw, want_file=intent == "file_read")
        if guess:
            args["path"] = guess
    elif intent in ("pc_click", "pc_save"):
        target = re.sub(r"(?i)\b(düğmesine|düğme|bas|tıkla|kaydet|adıyla|adı|ile)\b", " ", raw)
        target = re.sub(r"(?i)\b(chrome|not defteri|not defterini|notepad|hesap makinesi)\b", " ", target)
        candidate = " ".join(target.split()).strip(" ,.;'\"")
        if intent == "pc_click" and candidate:
            args["target"] = candidate
        if intent == "pc_save" and candidate:
            args["name"] = candidate
    return args
