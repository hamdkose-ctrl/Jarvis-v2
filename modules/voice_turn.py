"""Sıra alma: "kullanıcı sözünü bitirdi mi?" kararı (A1).

Neden var: ses kaydı şu an tek kurala bakıyor — **1 saniye sessizlik = cümle bitti**.
Cümle ortasında nefes alınca kesiyor, cümle bittiğinde boşuna bekliyor. Ölçülmüş
desen (Stonic'in 25 açık Python modülünden çıkarılan davranış, kodu alınmadı):

* Ses algılama (VAD) "sustu" der, ama hemen kesmez.
* "Cümle tamam mı" kararı iki kaynaktan gelir: yerel küçük model (varsa) + yazının sonu.
* Tamamsa **1,2 sn** sessizlik yeter; değilse en çok **3,0 sn** beklenir.
* Model "tamam" derken yazı noktalamayla bitiyorsa beklemek uzatılmaz.
* Söz kesildikten sonra kullanıcı **5 sn** içinde devam ederse aynı cümleye eklenir.

Bu modül karar verir, ses açmaz/kapatmaz: `turn_wait()` kaç saniye sessizlik
bekleneceğini söyler. Böylece ölçüm yapılabilir ve eski davranış tek anahtarla
korunur (`VOICE_TURN_SMART=False` → eski sabit 1 sn).
"""
from __future__ import annotations

import re

# Ölçülmüş sabitler (Stonic settings.toml [turn]; kopyalanan kod değil, sayı).
VAD_START_SECS = 0.2          # ses başladı sayılmak için gereken konuşma
VAD_STOP_SECS = 0.2           # "sustu" demek için gereken sessizlik
VAD_CONFIDENCE = 0.7
FINISHED_WAIT_SECS = 1.2      # cümle tamamsa beklenecek sessizlik
MAX_WAIT_SECS = 3.0           # tamam değilse en çok bu kadar bekle
RESUME_GRACE_SECS = 5.0       # kesilen sözü aynı cümleye geri katma penceresi

# Noktalama: cümleyi kapatan işaretler. Üç nokta ("...") cümleyi KAPATMAZ:
# kullanıcı çoğu zaman devam edecek demektir.
_TERMINAL = re.compile(r'[.!?…]["\')\]]?\s*$')
_ELLIPSIS = re.compile(r'…|\.\.\.\s*$')

# Yazı ortada kalmış gibi duruyorsa: bağlaç/edat ile biten cümle tamam değildir.
_DANGLING_WORDS = {
    've', 'veya', 'ama', 'fakat', 'ancak', 'çünkü', 'cunku', 'ki', 'yani', 'ile',
    'için', 'icin', 'gibi', 'kadar', 'sonra', 'önce', 'once', 'eğer', 'eger',
    'hem', 'ya', 'de', 'da', 'bir', 'bu', 'şu', 'su', 'o', 'ki,', 'hani', 'hani,',
}
_TRAILING_COMMA = re.compile(r',\s*$')
# "gidip", "bakıp", "yapıp" gibi ulaçlar cümleyi bitirmez ("gidip ... yapacağım").
# İsimler yanlış yakalanmasın diye küçük istisna listesi var.
_CONVERB = re.compile(r'(?:ıp|ip|up|üp)$')
_CONVERB_EXCEPTIONS = {'sahip', 'talip', 'garip', 'edip'}

# Kısa ama tam cümleler: tek kelime cevaplar kesilmesin.
_SHORT_COMPLETE = {
    'evet', 'hayır', 'hayir', 'tamam', 'olur', 'peki', 'tabii', 'elbette',
    'yok', 'var', 'dur', 'bekle', 'teşekkürler', 'tesekkurler', 'sağol', 'sagol',
}


def _last_word(text: str) -> str:
    words = re.findall(r"[^\s]+", text.strip())
    return words[-1].lower().strip('.,;:!?"\'()') if words else ''


def terminal(text: str) -> bool:
    """Yazı cümle sonu noktalamasıyla bitiyor mu? ("..." hariç)"""
    body = str(text or '').rstrip()
    if not body:
        return False
    if _ELLIPSIS.search(body):
        return False
    return bool(_TERMINAL.search(body))


def dangling(text: str) -> bool:
    """Yazı ortada kalmış mı? (bağlaç/edat/sonundaki virgül)"""
    body = str(text or '').strip()
    if not body:
        return False
    if _TRAILING_COMMA.search(body):
        return True
    word = _last_word(body)
    if word in _DANGLING_WORDS:
        return True
    return len(word) >= 4 and bool(_CONVERB.search(word)) and word not in _CONVERB_EXCEPTIONS


def complete(text: str) -> bool:
    """Noktalama tek başına yeterli mi: tamam mı, yarım mı?

    Kural: sonunda cümle sonu işareti VAR ve ortada kalmış gibi durmuyor.
    Noktalama hiç yoksa (canlı yazıya çevirmede sık) yarım sayılır — model
    kararı varsa o ezer.
    """
    body = str(text or '').strip()
    if not body:
        return False
    if dangling(body):
        return False
    if terminal(body):
        return True
    if _last_word(body) in _SHORT_COMPLETE:
        return True
    return False


def turn_wait(text: str, model_complete: bool | None = None) -> float:
    """Kaç saniye sessizlikten sonra sözü keselim?

    model_complete: yerel "cümle tamam" modeli varsa kararı (None = model yok).
    Kural (ölçülmüş): model "tamam" derse 1,2 sn. Model "yarım" dese bile yazı
    noktalamayla bitiyorsa 1,2 sn — model İngilizce eğitildiği için kısa Türkçe
    cümleyi sık sık yarım sanıyor. İkisi de "yarım" derse 3,0 sn.
    """
    if model_complete is True:
        return FINISHED_WAIT_SECS
    if complete(text):
        return FINISHED_WAIT_SECS
    return MAX_WAIT_SECS


class TurnDecision:
    """Tek bir söz için sıra kararını tutar.

    Kullanım (kayıt döngüsü içinde):
        d = TurnDecision()
        d.update(transcript_so_far)          # yazıya çevirme akarken
        if d.should_cut(silence_secs=0.6):   # VAD sessizlik sayacı
            kes()
    """

    def __init__(self, *, model: callable | None = None):  # type: ignore[valid-type]
        self._model = model
        self.text = ''
        self._wait = MAX_WAIT_SECS
        self._model_says: bool | None = None
        self._last_speech_at: float | None = None
        self.resumed_after_cut = 0

    def update(self, text: str, *, now: float | None = None) -> float:
        """Yazının son hâlini ver, beklenecek sessizliği döndür."""
        self.text = str(text or '')
        self._model_says = None
        if self._model is not None and self.text:
            try:
                verdict = self._model(self.text)
                self._model_says = verdict if isinstance(verdict, bool) else None
            except Exception:       # model hatası sıra kararını kilitlemesin
                self._model_says = None
        self._wait = turn_wait(self.text, self._model_says)
        if now is not None:
            self._last_speech_at = now
        return self._wait

    @property
    def wait_seconds(self) -> float:
        return self._wait

    def should_cut(self, silence_secs: float) -> bool:
        """VAD bu kadar süredir sessizlik gördüyse söz bitti mi?"""
        if silence_secs < VAD_STOP_SECS:
            return False
        return silence_secs >= self._wait

    def hear_speech(self, now: float) -> None:
        """Ses yeniden geldi: kesilmiş söz devam ediyor mu?"""
        if self._last_speech_at is not None and now - self._last_speech_at <= RESUME_GRACE_SECS:
            self.resumed_after_cut += 1
        self._last_speech_at = now
