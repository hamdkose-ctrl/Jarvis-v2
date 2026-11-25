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


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", fold(text)) if len(word) > 1 and word not in STOP}


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


def resolve(text: str) -> dict:
    """Cümleyi yeteneğe çevirir: {'status': ok|need|uncertain|none, ...}."""
    raw = str(text or "").strip()
    if not raw:
        return {"status": "none", "text": ""}
    file_words = {"klasor", "dosya", "indirilenler", "masaustu", "belge"}
    has_file_word = bool(tokens(raw) & file_words)
    fast = fast_commands.resolve(raw)
    if fast and not (has_file_word and fast[0].startswith("screen_")):
        return {"status": "ok", "intent": fast[0], "args": fast[1], "via": "pattern"}
    folded = fold(raw)
    words = tokens(raw)
    ranked = sorted(((item, _score(item, words, folded)) for item in capability_catalog.CATALOG),
                    key=lambda pair: pair[1], reverse=True)
    best, score = ranked[0]
    if has_file_word:
        file_items = [item for item, _ in ranked if item["intent"] in ("file_list", "file_read")]
        if file_items:
            best, score = file_items[0], max(score, MATCH_THRESHOLD)
    if score < MATCH_THRESHOLD:
        return {"status": "uncertain", "score": round(score, 2),
                "intent": None, "text": raw,
                "candidates": [item["intent"] for item, value in ranked[:3] if value > 0]}
    args = _slots(best, raw)
    missing = [slot for slot in best["needs"] if not args.get(slot)]
    if missing:
        return {"status": "need", "intent": best["intent"], "args": args,
                "missing": missing, "text": raw}
    return {"status": "ok", "intent": best["intent"], "args": args, "via": "catalog",
            "score": round(score, 2)}


FOLDERS = {"indirilenler": "Downloads", "downloads": "Downloads", "masaustu": "Desktop",
           "desktop": "Desktop", "belgeler": "Documents", "documents": "Documents"}


def guess_path(raw: str, *, want_file: bool) -> str:
    """Söylenen klasör/dosya adını gerçek yola çevirir; emin değilse boş döner."""
    from pathlib import Path as _Path
    words = tokens(raw)
    home = _Path.home()
    for word, folder in FOLDERS.items():
        if word in words and (home / folder).is_dir():
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
