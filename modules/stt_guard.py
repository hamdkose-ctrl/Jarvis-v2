"""Ses tanıma sonucunu komuta/sohbete geçmeden süzer (model çağrısı yok, yalnız metin kontrolü).

Türkçe konuşma bazen sessizlik ya da gürültüde "Sí", "C'est bien" gibi yabancı kısa sözlere,
Jarvis'in kendi sesi yeniden duyulunca da onun cümlelerine dönüşür. Böyle sonuçlar işlem
yapılmadan atılır; kullanıcıdan tekrar istenir. Ayarlar: `stt_guard` (varsayılan açık).
"""
from __future__ import annotations

import difflib
import re
import threading
import time
import unicodedata

# Sessizlik/gürültüde sık uydurulan kısa yabancı sözler (küçük harf, noktalamasız).
HALLUCINATIONS = frozenset({
    'sí', 'si', 'sì', 'oui', 'non', 'oh', 'uh', 'um', 'hmm', 'ah',
    "c'est bien", 'cest bien', 'merci', 'merci beaucoup', 'bien', 'très bien', 'voilà', "d'accord",
    'gracias', 'muchas gracias', 'vale', 'bueno', 'claro', 'hola', 'adiós', 'grazie', 'ciao', 'danke',
    'thank you', 'thanks', 'thank you for watching', 'thanks for watching', 'bye', 'you',
    'altyazı mk', 'altyazı m k', 'izlediğiniz için teşekkürler', 'abone olmayı unutmayın',
})
# Türkçede bulunmayan Latin harfleri (â, î, û Türkçede de kullanılır; bunlar sayılmaz).
_FOREIGN_LATIN = set('ñ¿¡áíóúéèàêëìòùœæßãõøå')
_TURKISH = set('çğışöüÇĞİŞÖÜ')
_ECHO_WINDOW = 20.0          # Jarvis'in son sözleri bu kadar saniye yankı adayıdır
_ECHO_RATIO = .8

_clock = time.monotonic   # yankı penceresi için kendi saat kaynağı (başka modüllerin zamanlamasına karışmaz)
_said: list[tuple[float, str]] = []
_lock = threading.Lock()


def enabled() -> bool:
    try:
        import config
        return bool(config.load_settings().get('stt_guard', True))
    except (ImportError, OSError, ValueError):
        return True


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFC', str(text or '')).replace('İ', 'i').replace('I', 'ı').lower()
    text = re.sub(r"[^\w\s']+", ' ', text)
    return re.sub(r'\s+', ' ', text).strip(" '")


def foreign(text: str) -> bool:
    """Türkçe konuşmadan çıkması beklenmeyen, gürültü/yanlış dil kokan sonuç mu?"""
    norm = _norm(text)
    if not norm:
        return True
    if norm in HALLUCINATIONS:
        return True
    letters = [c for c in str(text) if c.isalpha()]
    if not letters:
        return True
    # Latin dışı yazı (Korece, Japonca, Kiril, Arap...) çoğunluktaysa
    other = sum(1 for c in letters if not unicodedata.name(c, '').startswith('LATIN'))
    if other * 2 >= len(letters):
        return True
    # Kısa söz, Türkçe harfi yok ama İspanyolca/Fransızca harfi var ("Qué", "Très")
    words = norm.split()
    if len(words) <= 4 and not (_TURKISH & set(text)) and (_FOREIGN_LATIN & set(str(text).lower())):
        return True
    return False


def note_said(text: str, now: float | None = None) -> None:
    """Jarvis'in söylediği (TTS/Live çıktı) metni yankı karşılaştırması için kısa süre tutar."""
    norm = _norm(text)
    if not norm:
        return
    now = _clock() if now is None else now
    with _lock:
        _said.append((now, norm))
        while _said and (now - _said[0][0] > _ECHO_WINDOW or len(_said) > 8):
            _said.pop(0)


def echo(text: str, now: float | None = None) -> bool:
    """Duyulan söz Jarvis'in az önce söylediğinin tekrarı mı (hoparlörden mikrofona yankı)?"""
    norm = _norm(text)
    if len(norm) < 8:
        return False
    now = _clock() if now is None else now
    with _lock:
        recent = list(_said)
    for t, said in recent:
        if now - t > _ECHO_WINDOW:
            continue
        if len(norm.split()) >= 3 and norm in said:
            return True
        if difflib.SequenceMatcher(None, norm, said).ratio() >= _ECHO_RATIO:
            return True
    return False


def reject(text: str) -> str | None:
    """Sözün atılma nedeni ('foreign' / 'echo') ya da None (geçer). Ayar kapalıysa hep None."""
    if not enabled():
        return None
    if foreign(text):
        return 'foreign'
    if echo(text):
        return 'echo'
    return None
