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


def _harf_katla(text: str) -> str:
    """Türkçe harfleri ASCII'ye katlar; noktalama korunur (hesap için gerekli)."""
    if not isinstance(text, str):
        return ''
    katlanmis = text.replace('İ', 'i').replace('I', 'i').casefold()
    for kaynak, hedef in (('ı', 'i'), ('ş', 's'), ('ç', 'c'), ('ğ', 'g'),
                          ('ü', 'u'), ('ö', 'o'), ('â', 'a'), ('î', 'i'), ('û', 'u')):
        katlanmis = katlanmis.replace(kaynak, hedef)
    katlanmis = unicodedata.normalize('NFKD', katlanmis)
    return ''.join(ch for ch in katlanmis if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Türkçe küçük harf + noktalama temizliği; anlam değişmez."""
    if not isinstance(text, str):
        return ''
    # Kalıplar ASCII yazılsın, "kıs" ile "kis" ayrı ayrı eşleşmesin diye harfler
    # katlanır. Eşleşme tam olduğu için anlam kaybı yok.
    katlanmis = re.sub(r'[^\w\s]', ' ', _harf_katla(text))
    return re.sub(r'\s+', ' ', katlanmis).strip()


def _seviye(deger: str) -> int:
    return max(0, min(100, int(deger)))


_PATTERNS: tuple[tuple[re.Pattern, object], ...] = (
    # --- okuma (yan etkisi yok) ---
    (re.compile(r'(saat kac( oldu)?|su an saat kac|saat)'), ('fast_time', {})),
    (re.compile(r'(tarih ne|bugun gunlerden ne|hangi gun(dayiz)?|bugun ayin kaci|tarih)'),
     ('fast_date', {})),
    (re.compile(r'(sistem durumu(nu goster)?|durum ne)'), ('fast_system_status', {})),
    # Ekranı okumak yan etkisizdir: tıklama/yazma yok, yalnız Windows'tan okunur.
    (re.compile(r'(ekranda (ne|neler) var|ekranda ne acik|ne goruyorsun)'), ('screen_summary', {})),
    (re.compile(r'(hangi program(lar)? (acik|calisiyor)|acik (olan )?(program(lar)?|pencereler))'),
     ('screen_summary', {})),
    (re.compile(r'(ne ustunde calisiyorum|aktif (pencere|program) (ne|hangisi))'), ('screen_summary', {})),
    # --- konuşma ---
    (re.compile(r'(sus|sessiz ol|kes sesini|konusmayi (durdur|kes))'), ('fast_speech_stop', {})),
    # --- ses denetimi (tek sahip: audio_action / level_set) ---
    (re.compile(r'(sesi (kapat|sustur)|sessize al)'), ('audio_action', {'action': 'mute'})),
    (re.compile(r'(sesi (ac|geri ac)|sessizi kaldir)'), ('audio_action', {'action': 'unmute'})),
    (re.compile(r'(sesi (arttir|yukselt|biraz ac)|sesi ac)'), ('audio_action', {'action': 'volume_up'})),
    (re.compile(r'(sesi (kis|azalt|dusur))'), ('audio_action', {'action': 'lower'})),
    (re.compile(r'sesi (yuzde )?(\d{1,3}) (a |e )?(yap|ayarla)'),
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
    # --- salt-okuma: hava, gündem, not sayısı (model gerekmez) ---
    (re.compile(r'(hava (durumu )?nasil( bugun)?|bugun hava (durumu )?nasil|hava durumu)'),
     ('weather', {})),
    (re.compile(r'(bugun|bugunku) (ne var|neler var|planim ne|programim ne)'),
     ('agenda_read', {'view': 'day_plan', 'period': 'today'})),
    (re.compile(r'(yarin|yarinki) (ne var|neler var|planim ne|programim ne)'),
     ('agenda_read', {'view': 'day_plan', 'period': 'tomorrow'})),
    (re.compile(r'kac notum var'), ('notes_read', {'which': 'count'})),
    # --- ekran (salt okuma) ---
    (re.compile(r'(ekran goruntusu al|ekrani (yakala|goruntule))'), ('screen_capture', {})),
    # --- uygulama kapatma: yalnız onay sorusu açar (etki onaydan sonra) ---
    (re.compile(r'(.{2,30}?)( uygulamasini)? kapat'), ('app_close', lambda m: {'name': m.group(1).strip()})),
    # --- uygulama açma (yalnız kapalı liste) ---
    (re.compile(r'(.{2,30}?)( uygulamasini)? (ac|baslat)'),
     ('app_open', lambda m: {'name': m.group(1).strip()})),
)


_ISLEM_SOZCUKLERI = (('carpi', '*'), ('kere', '*'), ('bolu', '/'), ('bol', '/'),
                     ('arti', '+'), ('eksi', '-'), ('ussu', '**'), ('uzeri', '**'),
                     ('mod', '%'), ('kere', '*'))

_IZINLI = set('0123456789+-*/%()., ')


class _HesapHatasi(ValueError):
    pass


def _hesapla(ifade: str) -> float:
    """Yalnız sayı ve dört işlem: `eval` yok, AST beyaz listesi var."""
    import ast

    def yuru(dugum):
        if isinstance(dugum, ast.Expression):
            return yuru(dugum.body)
        if isinstance(dugum, ast.Constant) and isinstance(dugum.value, (int, float))                 and not isinstance(dugum.value, bool):
            return dugum.value
        if isinstance(dugum, ast.UnaryOp) and isinstance(dugum.op, (ast.UAdd, ast.USub)):
            deger = yuru(dugum.operand)
            return deger if isinstance(dugum.op, ast.UAdd) else -deger
        if isinstance(dugum, ast.BinOp):
            sol, sag = yuru(dugum.left), yuru(dugum.right)
            if isinstance(dugum.op, ast.Add):
                return sol + sag
            if isinstance(dugum.op, ast.Sub):
                return sol - sag
            if isinstance(dugum.op, ast.Mult):
                return sol * sag
            if isinstance(dugum.op, ast.Div):
                if sag == 0:
                    raise _HesapHatasi('sıfıra bölme')
                return sol / sag
            if isinstance(dugum.op, ast.Mod):
                if sag == 0:
                    raise _HesapHatasi('sıfıra bölme')
                return sol % sag
            if isinstance(dugum.op, ast.Pow):
                if abs(sag) > 64 or abs(sol) > 10 ** 6:
                    raise _HesapHatasi('üs çok büyük')
                return sol ** sag
            raise _HesapHatasi('desteklenmeyen işlem')
        raise _HesapHatasi('desteklenmeyen ifade')

    return float(yuru(ast.parse(ifade, mode='eval')))


def _bicimle(deger: float) -> str:
    if deger == int(deger) and abs(deger) < 1e15:
        return str(int(deger))
    return f'{deger:.4f}'.rstrip('0').rstrip('.').replace('.', ',')


def compute(command: str):
    """Salt hesap komutlarını model çağırmadan yanıtlar; değilse None.

    Kapalı biçim: en az bir sayı ve bir işlem içeren kısa ifade. Serbest metin
    ("bunu neden yaptın") buraya girmez; `_IZINLI` dışında karakter varsa None.
    """
    metin = _harf_katla(command).replace('^', '**')
    for kelime, sembol in _ISLEM_SOZCUKLERI:
        metin = metin.replace(kelime, f' {sembol} ')
    metin = re.sub(r'\s+', ' ', metin).strip()
    if not metin or len(metin) > MAX_CHARS or not set(metin) <= _IZINLI:
        return None
    if not any(ch.isdigit() for ch in metin):
        return None
    if not any(islem in metin for islem in '+-*/%'):
        return None
    if metin.count('(') != metin.count(')'):
        return None
    ifade = metin.replace(',', '.')
    try:
        sonuc = _hesapla(ifade)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
    if sonuc != sonuc or sonuc in (float('inf'), float('-inf')):
        return None
    return f'Sonuc {_bicimle(sonuc)}.'


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
        if intent in ('app_open', 'app_close') and str(args.get('name', '')).strip() not in KNOWN_APPS:
            continue        # tanınmayan uygulama: hızlı yol değil, Brain karar verir
        return intent, dict(args)
    return None


# --- Selamlama / nezaket: model GEREKTİRMEZ ---------------------------------
# Canlı kusur (23 Kasım 22:17): kullanıcı "merhaba" dedi, tüm sağlayıcılar
# düşmüştü (gemini 504, groq 429, cloudflare biçim hatası) ve Jarvis cevap
# veremedi. Oysa "merhaba" bir bilgi sorusu değil; model çağırmadan cevaplanır.
# Kural: yalnız TAM eşleşme. "merhaba, hava nasıl?" buraya girmez (Brain'e gider).
_SELAMLAMA = {
    'merhaba': ('Merhaba.', 'Merhaba, buradayım.', 'Selam, dinliyorum.'),
    'merhabalar': ('Merhaba.', 'Merhaba, buradayım.'),
    'selam': ('Selam.', 'Selam, buradayım.'),
    'selamlar': ('Selamlar.', 'Selam, dinliyorum.'),
    'hey jarvis': ('Buradayım.', 'Dinliyorum.'),
    'jarvis': ('Buradayım.', 'Efendim?'),
    'gunaydin': ('Günaydın.', 'Günaydın, iyi başlangıçlar.'),
    'iyi aksamlar': ('İyi akşamlar.', 'İyi akşamlar, dinliyorum.'),
    'iyi geceler': ('İyi geceler.', 'İyi geceler, yarın görüşürüz.'),
    'naber': ('İyiyim, sağ ol. Sen nasılsın?', 'Buradayım, işler yolunda. Sen nasılsın?'),
    'nasilsin': ('İyiyim, sağ ol. Sen nasılsın?', 'İyiyim, çalışıyorum. Sen nasılsın?'),
    'nasilsiniz': ('İyiyim, teşekkürler. Siz nasılsınız?',),
    'iyi misin': ('İyiyim, sağ ol.', 'İyiyim, teşekkürler.'),
    'tesekkurler': ('Rica ederim.', 'Ne demek, rica ederim.'),
    'tesekkur ederim': ('Rica ederim.', 'Ne demek, rica ederim.'),
    'sagol': ('Rica ederim.', 'Ne demek.'),
    'sag ol': ('Rica ederim.', 'Ne demek.'),
    'eline saglik': ('Sağ ol, kolay gelsin.',),
    'kolay gelsin': ('Sağ ol, sana da kolay gelsin.',),
    'iyi calismalar': ('Sağ ol, sana da iyi çalışmalar.',),
    'gorusuruz': ('Görüşürüz.', 'Görüşürüz, iyi günler.'),
    'hoscakal': ('Hoşça kal.', 'Hoşça kal, iyi günler.'),
    'hosca kal': ('Hoşça kal.', 'Hoşça kal, iyi günler.'),
}


def chitchat(command: str, *, hour: int | None = None) -> str | None:
    """Selamlama/nezaket sözüne model çağırmadan kısa cevap; değilse None.

    Kapalı sözlük ve tam eşleşme: tanınmayan ya da içinde başka istek olan
    cümle buradan geçmez. Aynı söz her seferinde aynı cevabı vermez (saat +
    uzunluk ile döner), ama cevap her zaman kısa ve tek cümle.
    """
    metin = normalize(command)
    if not metin or len(metin) > MAX_CHARS:
        return None
    secenekler = _SELAMLAMA.get(metin.strip(' .!?'))
    if not secenekler:
        return None
    if hour is None:
        import time as _time
        try:
            hour = _time.localtime().tm_hour
        except Exception:
            hour = 12
    return secenekler[(len(metin) + int(hour)) % len(secenekler)]
