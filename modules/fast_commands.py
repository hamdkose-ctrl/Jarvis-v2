"""Model gerektirmeyen komutlar: kapalı sözlük, tam eşleşme, tek yürütücü.

Neden: canlıda "saat kaç" gibi bir soru bile anlama modeline gidiyor, cevap
1-3 saniye gecikiyor ve kota harcıyordu. Buradaki her kalıp **tam eşleşme**
ister; eşleşmezse komut eskisi gibi Brain/Core yolundan gider. Bu modül karar
vermez, izin vermez: yalnız `engine_intents.dispatch` ile mevcut sahipleri
çağırır (etki sahibi değişmez).
"""
from __future__ import annotations

import re
import unicodedata

# Kapalı uygulama listesi: tanınmayan ad hızlı yola girmez, Brain'e kalır.
KNOWN_APPS = frozenset({
    'steam', 'spotify', 'chrome', 'google chrome', 'edge', 'firefox', 'discord',
    'telegram', 'whatsapp', 'notepad', 'not defteri', 'hesap makinesi', 'calculator',
    'paint', 'ayarlar', 'settings', 'explorer', 'dosya gezgini', 'terminal', 'cmd',
    'powershell', 'visual studio code', 'vs code', 'code', 'word', 'excel',
    'powerpoint', 'outlook', 'youtube', 'spotify',
})

MAX_CHARS = 64


def normalize(text: str) -> str:
    """Türkçe küçük harf + noktalama temizliği; anlam değişmez."""
    if not isinstance(text, str):
        return ''
    # Türkçe harfler ASCII'ye katlanır: kalıplar tek biçimde yazılsın, "kıs" ile
    # "kis" ayrı ayrı eşleşmesin. Eşleşme tam olduğu için anlam kaybı yok.
    katlanmis = text.replace('İ', 'i').replace('I', 'i').casefold()
    for kaynak, hedef in (('ı', 'i'), ('ş', 's'), ('ç', 'c'), ('ğ', 'g'),
                          ('ü', 'u'), ('ö', 'o'), ('â', 'a'), ('î', 'i'), ('û', 'u')):
        katlanmis = katlanmis.replace(kaynak, hedef)
    katlanmis = unicodedata.normalize('NFKD', katlanmis)
    katlanmis = ''.join(ch for ch in katlanmis if not unicodedata.combining(ch))
    katlanmis = re.sub(r'[^\w\s]', ' ', katlanmis)
    return re.sub(r'\s+', ' ', katlanmis).strip()


def _seviye(deger: str) -> int:
    return max(0, min(100, int(deger)))


_PATTERNS: tuple[tuple[re.Pattern, object], ...] = (
    # --- okuma (yan etkisi yok) ---
    (re.compile(r'(saat kac( oldu)?|su an saat kac|saat)'), ('fast_time', {})),
    (re.compile(r'(tarih ne|bugun gunlerden ne|hangi gun(dayiz)?|bugun ayin kaci|tarih)'),
     ('fast_date', {})),
    (re.compile(r'(sistem durumu(nu goster)?|durum ne)'), ('fast_system_status', {})),
    # --- konuşma ---
    (re.compile(r'(sus|sessiz ol|kes sesini|konusmayi (durdur|kes))'), ('fast_speech_stop', {})),
    # --- ses denetimi (tek sahip: audio_action / level_set) ---
    (re.compile(r'(sesi (kapat|sustur)|sessize al)'), ('audio_action', {'action': 'mute'})),
    (re.compile(r'(sesi (ac|geri ac)|sessizi kaldir)'), ('audio_action', {'action': 'unmute'})),
    (re.compile(r'(sesi (arttir|yukselt|biraz ac)|sesi ac)'), ('audio_action', {'action': 'volume_up'})),
    (re.compile(r'(sesi (kis|azalt|dusur))'), ('audio_action', {'action': 'lower'})),
    (re.compile(r'sesi (yuzde )?(\d{1,3}) (yap|ayarla)'),
     ('level_set', lambda m: {'property': 'volume', 'level': _seviye(m.group(2))})),
    (re.compile(r'ses (seviyesi )?(yuzde )?(\d{1,3})'),
     ('level_set', lambda m: {'property': 'volume', 'level': _seviye(m.group(3))})),
    (re.compile(r'parlakligi (yuzde )?(\d{1,3}) (yap|ayarla)'),
     ('level_set', lambda m: {'property': 'brightness', 'level': _seviye(m.group(2))})),
    (re.compile(r'parlaklik (yuzde )?(\d{1,3})'),
     ('level_set', lambda m: {'property': 'brightness', 'level': _seviye(m.group(2))})),
    # --- medya ---
    (re.compile(r'(sonraki|siradaki) (sarki|parca)'), ('media_action', {'action': 'next'})),
    (re.compile(r'(onceki) (sarki|parca)'), ('media_action', {'action': 'prev'})),
    (re.compile(r'(muzigi )?(duraklat|devam et|oynat|durdur)'),
     ('media_action', {'action': 'play_pause'})),
    # --- uygulama açma (yalnız kapalı liste) ---
    (re.compile(r'(.{2,30}?)( uygulamasini)? (ac|baslat)'),
     ('app_open', lambda m: {'name': m.group(1).strip()})),
)


def resolve(command: str) -> tuple[str, dict] | None:
    """Tam eşleşen hızlı komutu (intent, args) olarak döndürür; yoksa None."""
    metin = normalize(command)
    if not metin or len(metin) > MAX_CHARS:
        return None
    for pattern, hedef in _PATTERNS:
        eslesme = pattern.fullmatch(metin)
        if not eslesme:
            continue
        intent, args = hedef if isinstance(hedef, tuple) else (None, None)
        if callable(args):
            args = args(eslesme)
        if intent == 'app_open' and str(args.get('name', '')).strip() not in KNOWN_APPS:
            continue        # tanınmayan uygulama: hızlı yol değil, Brain karar verir
        return intent, dict(args)
    return None
