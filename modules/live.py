"""Canlı konuşma: Gemini Live API ile sesli sohbet.

"Hey Jarvis" (internetsiz, bilgisayarda algılanır) → bir Live oturumu açılır → ses iki yönde akar, cevap
Gemini'nin kendi sesiyle gelir. Yazıya çevirme / cevap hazırlama / seslendirme ayrı adımlar değildir; bu yüzden
cevap, konuşman biter bitmez başlar. Bir iş gerekince (mail, takvim, dosya, uygulama…) model tek bir araç çağırır:
`komut`. O araç Jarvis'in mevcut komut sistemine (main.handle) gider; yani eski özelliklerin hepsi çalışır.

Gizlilik: oturum kapalıyken mikrofon sesi bilgisayardan çıkmaz. Oturum, son etkinlikten sonra
`live_idle_seconds` (varsayılan 90 sn) geçince kendiliğinden kapanır.
Echo: Jarvis konuşurken mikrofon sese gönderilmez (hoparlör sesini kendi sorusu sanmasın). Konuşmayı kesmek için
"Hey Jarvis" de, Ctrl+Boşluk'a bas ya da Durdur'a bas. Kulaklık kullanıyorsan ayarlardan `live_headphones`
açılırsa konuşurken de dinler ve araya girebilirsin.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import asyncio
import collections
import contextlib
import logging
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

from modules.live_tools import DEFAULT_VOICE, VOICE_INFO, VOICES, TOOL_DESCRIPTION, TOOLS, _schema, _build_request
from modules.live_audio import _Resampler, _HighPass, _soft_limit, _Player
from modules.speech_activity import SpeechActivity
from modules.audio_diagnostics import AudioDiagnostics
from modules.voice_timing import VoiceTiming
import numpy as np

from config import load_settings

log = logging.getLogger("jarvis")

SEND_RATE = 16000
RECV_RATE = 24000
FRAME = 1280                    # 80 ms (openWakeWord'ün beklediği parça)
PRE_FRAMES = 14                 # uyanma anından önceki ~1,1 sn ("Hey Jarvis"in kendisi); yalnızca live_send_wake açıksa gönderilir
DEFAULT_MODEL = "models/gemini-3.1-flash-live-preview"
PREBUFFER = 0.60               # her cümlenin başında biriktirilen ses (sn): kesik kesik çalmayı/kelime yutmayı önler
PREBUFFER_MAX = 0.80            # bu kadar beklenip yeterli ses gelmediyse eldekini çal
ECHO_TAIL = 0.15                # konuşma bittikten sonra hoparlörün son sesi için ek bekleme (sn)
BARGE_THRESHOLD = 0.8           # konuşurken "Hey Jarvis" için sıkı eşik (kendi sesinden kesilmesin)
BARGE_FRAMES = 2                # ... ve üst üste bu kadar karede aşılmalı
TOOL_RESULT_MAX = 3000
# Jarvis'in bir işi yaptığını söylediği sözler: bu konuşma turunda hiç araç çağrılmadıysa iş yapılmamıştır
_CLAIM = re.compile(r"\b(?:açıyorum|açtım|oynatıyorum|oynattım|çalıyorum|başlatıyorum|başlattım|ekledim|ekliyorum|"
                    r"kaydettim|kaydediyorum|gönderdim|gönderiyorum|ayarladım|ayarlıyorum|kapattım|kapatıyorum|"
                    r"hallettim|not aldım|not ettim|durdurdum|durduruyorum|sildim|siliyorum|yaptım|yapıyorum)\b")
NOSPEECH_CLOSE = 12             # uyandıktan sonra bu kadar sn hiç konuşma duyulmazsa oturum kapanır (yanlış uyanma)
SILENCE_DEFAULT = 1100          # bu kadar sessizlik (ms) olunca kullanıcının sözü bitti sayılır
AGC_TARGET = 1250               # uzak/kısık mikrofonda dijital hedef; Windows mikrofon seviyesine dokunulmaz
AGC_MAX = 9.0                   # dijital kazancı sınırlı tut; Windows mikrofon seviyesine dokunulmaz
LOW_MIC_SPEECH = 60             # kazanç sonuna dayanmışken konuşma seviyesi bunun altındaysa "mikrofon kısık" uyarısı
SAVE_SECONDS = 30               # tanı için son oturumda modele giden ses (son N sn) .jarvis\son_ses.wav dosyasına yazılır


def _cfg(key: str, default):
    v = load_settings().get(key)
    return default if v in (None, "") else v


def model_name() -> str:
    m = str(_cfg("live_model", DEFAULT_MODEL))
    return m if m.startswith("models/") else "models/" + m


def voice_name() -> str:
    v = str(_cfg("live_voice", DEFAULT_VOICE))
    return v if v in VOICES else DEFAULT_VOICE


def enabled() -> bool:
    """Canlı konuşma, mikrofon sesini sürekli Gemini Live'a akıtır; gizli ve yalnızca-yerel modda kapalıdır."""
    try:
        from modules import privacy, llm
        if not llm.gemini_aux_allowed(model_name()):
            return False
        if llm.provider() in ("openai", "anthropic"):
            return False
        if privacy.mode() in ("gizli", "yerel"):
            return False
    except Exception:   # noqa: BLE001
        _record_failure('modules/live.py:enabled')
        pass
    return bool(_cfg("live_mode", True))


# Yazıya dökmenin sık yanlış yazdığı ifadeler -> asıl söylenen ("yanlış=doğru"). Ses sekmesinden değiştirilebilir (stt_fixes).
DEFAULT_FIXES = ("die milch=Steam, city mall=Steam, ella viste=Hey Jarvis, él duerme=Hey Jarvis, cch=sesi aç, "
                 "tack så mycket=takvimi aç")


def parse_fixes(text: str | None = None) -> list[tuple[str, str]]:
    raw = DEFAULT_FIXES if text is None else text
    pairs = []
    for item in re.split(r"[,;\n]", raw):
        if "=" in item:
            a, b = item.split("=", 1)
            a, b = " ".join(a.split()), " ".join(b.split())
            if a and b:
                pairs.append((a, b))
    return pairs


_FIXES_VERSION = 2
_FIXES_ADDED = {2: ["tack så mycket=takvimi aç"]}     # sonradan eklenen varsayılanlar (kayıtlı listeye bir kez eklenir)


def _migrate_fixes() -> None:
    """Ses sekmesi her kayıtta "Yanlış duyulanlar" listesini de kaydeder; o zaman sonradan eklenen varsayılanlar hiç
    görünmezdi. Kayıtlı liste varsa yeni varsayılanları bir kez sonuna ekler (kullanıcı sonra silerse geri gelmez)."""
    from config import save_settings
    s = load_settings()
    ver = int(s.get("stt_fixes_v") or 1)
    if ver >= _FIXES_VERSION:
        return
    saved = s.get("stt_fixes")
    if saved is not None:
        have = {a.lower() for a, _ in parse_fixes(saved)}
        extra = [pair for v in range(ver + 1, _FIXES_VERSION + 1) for pair in _FIXES_ADDED.get(v, [])
                 if pair.split("=")[0].strip().lower() not in have]
        if extra:
            saved = ", ".join([x for x in [str(saved).strip(" ,")] if x] + extra)
        save_settings(stt_fixes=saved, stt_fixes_v=_FIXES_VERSION)
    else:
        save_settings(stt_fixes_v=_FIXES_VERSION)


def apply_fixes(text: str, fixes: list[tuple[str, str]] | None = None) -> str:
    """Ekranda ve log'da görünen yazıdaki bilinen yanlış duyulmaları düzeltir (büyük/küçük harf fark etmez)."""
    for wrong, right in (parse_fixes(load_settings().get("stt_fixes")) if fixes is None else fixes):
        text = re.sub(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)",
                      lambda m, r=right: r[:1].upper() + r[1:] if m.group(0)[:1].isupper() else r, text, flags=re.IGNORECASE)
    return text


def _tr_time() -> str:
    days = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar")
    n = datetime.now()
    return f"{n:%d.%m.%Y} {days[n.weekday()]}, saat {n:%H:%M}"




_speak_check = None


def set_speak_check(fn) -> None:
    """main.py susturma düğmesini bağlar: fn() False dönerse canlı modun sesi çalınmaz."""
    global _speak_check
    _speak_check = fn


def speak_allowed() -> bool:
    try:
        return _speak_check is None or bool(_speak_check())
    except Exception:                                 # noqa: BLE001
        _record_failure('modules/live.py:speak_allowed')
        return True


def _play_music(args: dict) -> str:
    """muzik_cal: YouTube'da arayıp ilk sonucu açar (Spotify yalnızca açıkça istenir ve kuruluysa)."""
    from modules import media
    q = " ".join(str(args.get("sorgu") or "").split()) or "türkçe pop şarkılar"
    plat = str(args.get("platform") or "").lower()
    if "spotify" in plat:
        if media.spotify_installed():
            return media.spotify(q)
        return "Spotify bu bilgisayarda kurulu değil; YouTube'dan açtım. " + media.youtube(q)
    return media.youtube(q)


def _task_place(args: dict) -> str | None:
    """gorev_ekle: 'iş' / 'ev' ise devir listesinin anahtarı ("is"/"ev"), yer belirtilmediyse None (normal görev)."""
    y = " ".join(str(args.get("yer") or "").split()).replace("İ", "i").replace("I", "ı").lower()
    if y in {"iş", "is", "ış", "ıs", "işte", "iş yeri", "işyerinde"}:
        return "is"
    if y in {"ev", "evde", "ev işi"}:
        return "ev"
    return None


def _add_handoff(args: dict) -> str:
    """Ev-iş devir listesine ekler (Google Görevler). Hata olursa açık sebebi döndürür."""
    from modules import handoff
    text = " ".join(str(args.get("metin") or "").split())
    where = _task_place(args)
    if not text or where is None:
        return "Geçersiz istek: yapılacak işi söylemedi. Kullanıcıya tekrar sor."
    when = str(args.get("zaman") or "").lower()
    due = handoff.due(when) if when.strip() else None
    try:
        handoff.add(text, where, due)
    except Exception as e:                            # noqa: BLE001
        _record_failure('modules/live.py:_add_handoff')
        return "Yapamadım: " + str(handoff.explain_error(e))
    gun = "" if due is None else f" ({due.strftime('%d.%m')})"
    return f"{'İş' if where == 'is' else 'Ev'} listesine ekledim{gun}: {text}"


def _fixes_prompt() -> str:
    fx = parse_fixes(load_settings().get("stt_fixes"))
    if not fx:
        return ""
    return ("Ses tanıma bazen bunları yanlış duyar; böyle bir şey duyarsan asıl söyleneni anla ('duyulan -> asıl'): "
            + "; ".join(f"{a} -> {b}" for a, b in fx) + ".")


def build_prompt(assistant: str, user: str, context: str = "") -> str:
    return "\n".join([
        f"Sen {assistant} adlı, Türkçe konuşan bir sesli masaüstü asistanısın. Şu an {user} ile konuşuyorsun. "
        f"Şu an: {_tr_time()}.",
        "Konuşma tarzın: doğal, sıcak, kısa. Çoğu cevap 1-3 cümle olsun. Liste, markdown, emoji kullanma. "
        "Konuşma HIZIN: sakin ve acele etmeden; kelimeleri net söyle, cümleler arasında kısa nefes payı bırak, "
        "her cevabın ilk cümlesine özellikle yavaş ve yumuşak başla. "
        "Kullanıcı Türkçe konuşur: sesi HER ZAMAN Türkçe olarak anla ve Türkçe cevap ver. Korece, Japonca, İspanyolca "
        "gibi başka bir dil gibi duyduğun şey neredeyse her zaman gürültü ya da yanlış duymadır; o dilde cevap verme, "
        "işlem yapma, gerekirse (cümle tamamlanmışsa) 'Tam anlayamadım, tekrar eder misin?' de. Yalnızca kullanıcı açıkça başka bir dilde "
        "konuşmanı isterse o dile geç.",
        "Sana söylenmeyen konuşmalara (TV, başka biri, anlamsız gürültü) karışma; emin değilsen sessiz kal.",
        "İş gerektiren her istekte araçları kullan: sık işler için özel araçlar (ses_ayarla, parlaklik_ayarla, "
        "sessiz, uygulama_ac, uygulama_kapat, medya, muzik_cal, not_ekle, hatirlatma_ekle, gorev_ekle, kural_ogren, yanlis_duyma, "
        "ses_degistir), diğer her şey "
        "için `komut`. Müzik/şarkı/belirli video oynatma isteği muzik_cal ile yapılır; AMA yalnızca 'YouTube aç' "
        "denmesi içerik oynatma isteği değildir, uygulama_ac ile sadece YouTube'u aç. "
        "Kullanıcı sayıyı yalnızca '20 yap' gibi söylerse bir önceki konuya (ses mi parlaklık mı) bak; emin değilsen sor. Aracı çağırmadan hemen önce tek çok kısa cümle söyle "
        "('Bakıyorum.', 'Hemen.') ki kullanıcı sessizlikte beklemesin. Araç sonucunu doğal ve kısa aktar; "
        "sonuç uzunsa ana noktayı söyle, ayrıntı ekranda yazıyor de. Araç sonucu olmadan bir işi yaptığını "
        "söyleme, sonucu uydurma. Araç hata ya da 'yapamadım' derse bunu açıkça söyle.",
        "Kullanıcı yalnızca adını söylediyse ('Hey Jarvis', 'Jarvis' ya da benzeri: 'servis', 'Yarvis', 'E-Jarvis') "
        "bu seni çağırmasıdır: HEMEN kısa ve duyulur bir karşılık ver ('Efendim?', 'Dinliyorum.'), sessiz kalma. "
        "Bunu 'anlamsız söz' sayma.",
        "Kullanıcının sözü bir cümlenin ortasında kesilmiş gibiyse (sonu 've', 'şey', 'bir de', 'için' gibi bağlaçla "
        "bitti) o düşünüyordur: sözünü kesme, 'anlamadım' deme, devamını bekle. Devamı birkaç saniye gelmezse "
        "'Devam et, dinliyorum.' de.",
        "Duyduğun şey anlamsız ya da bağlamdan kopuksa (yabancı dilde saçma sözler, tek tük kelimeler, "
        "TV/arka plan sesi) HİÇBİR işlem yapma ve cevap verme; emin olamadığın bir isteği araca göndermeden önce "
        "kısaca 'Şunu mu dedin: …?' diye teyit et. Not, görev, hatırlatma, mesaj ve dosya işlerini MUTLAKA bir araçla "
        "yap (not_ekle, gorev_ekle, hatirlatma_ekle ya da `komut`). Gün/saat içeren 'o gün hatırlat', 'Pazartesi hatırlat' "
        "gibi istekler KURAL DEĞİLDİR; kural_ogren çağırma, hatirlatma_ekle çağır. Hatırlatma aracı başarılı olmadan "
        "'o gün hatırlatacağım' diye söz verme. Bu konuşmada o iş için araç çağırıp başarılı sonuç "
        "almadıysan 'ekledim', 'açtım', 'kaydettim', 'hallettim' DEME; önce aracı çağır. Kullanıcı 'eklememişsin' derse "
        "tartışma, aracı şimdi çağır.",
        "Bir işi araç sonucu gelmeden 'kapatıyorum', 'açıyorum', 'yapıyorum' ya da 'yaptım' diye anlatma; araçtan "
        "önce yalnız 'Bakıyorum.' ya da 'Hemen.' de, işin olduğunu araç sonucuna göre söyle. Hangi işin istendiği "
        "belli değilse ('kapat', 'şunu aç' gibi nesnesiz sözler ya da yarım duyulan cümleler) tahmin edip araç "
        "çağırma; 'Neyi kapatmamı istiyorsun?' gibi kısa bir soruyla açıklama iste.",
        "Ekran ya da kamera paylaşımını kapatma isteği ('paylaşımı kapat', 'paylaşımı durdur', 'ekran paylaşımını "
        "bitir', 'kamerayı kapat') için `komut` aracına 'paylaşımı kapat' gönder; bunu uygulama kapatma sanma.",
        "Telefona dosya gönderme, mesaj, silme gibi işlerde NE yapılacağı belli değilse aracı ÇAĞIRMADAN önce sor "
        "('Hangi dosyayı göndereyim?'). `komut` aracına belirsiz istek yazma: dosyanın adını ya da tarifini ekle "
        "('LGS programı PDF'ini telefona gönder'). Kullanıcı açıkça 'son indirdiğim dosya' demedikçe rastgele dosya gönderme.",
        "'Jarvis'i kapat', 'kendini kapat', 'uygulamayı kapat' yalnızca JARVIS UYGULAMASINI kapatır: jarvis_kapat "
        "aracını kullan. Bunu ASLA 'bilgisayarı kapat' diye yeniden yorumlama. 'Bilgisayarı kapat', 'PC'yi kapat', "
        "'Windows'u kapat' ise ayrı bir sistem işlemidir; `komut` aracına aynen gönder ve mutlaka kullanıcı onayı iste.",
        "Kullanıcı 'PC ayarları', 'Windows ayarları', 'bilgisayar ayarları' (ya da 'PC not defteri', 'PC dosyaları') derse bunlar "
        "WINDOWS'un kendi uygulamalarıdır, Jarvis'in sayfaları değildir: `komut` aracına sözünü 'PC', 'Windows' ya da 'bilgisayar' "
        "sözcüğünü SİLMEDEN aynen gönder (ör. 'PC ayarlarını aç'). Jarvis'in kendi ayarları için kullanıcı 'Jarvis ayarları' der.",
        "Kapatma, silme, mesaj gönderme gibi onay isteyen işlerde araç sonucu onay isterse kullanıcıya sor. "
        "'Evet' / 'onaylıyorum' gibi bir onayı araca YALNIZCA kullanıcı kendisi söylediyse ilet; kendi başına asla "
        "onaylama.",
        "Kullanıcının bilgisayarına ve verilerine `komut` aracı üzerinden erişebilirsin (sistem durumu, açık "
        "uygulamalar, dosyalar, mail, takvim, ekran). 'Göremiyorum', 'erişimim yok' ya da 'özet çıkarayım mı?' "
        "diye sorma; önce aracı çağır, gerçekten yapılamazsa araç söyleyecektir.",
        "Güncel bilgi (fiyat, haber, skor) için bilmediğin rakamı uydurma; `komut` aracıyla araştırt.",
        _fixes_prompt(),
        context,
    ]).strip()


def _own_volume_up() -> bool:
    """Windows ses karıştırıcısını değiştirme.

    Eski sürüm Jarvis'in uygulama çıkışını her konuşmada %100'e çekiyordu. Kullanıcının ses/mikrofon
    ayarlarına saygı göstermek için artık hiçbir Windows seviye kaydırıcısına dokunmuyoruz.
    """
    return True


# ---------------------------------------------------------------------------------------------------- hoparlör
# ---------------------------------------------------------------------------------------------------- ana sınıf
class Live:
    """handler(istek) -> str: araç çağrısını Jarvis'in komut sistemine ileten işlev (ayrı thread'de çalışır).
    emit(tür, metin, ek): arayüze olay. prompt(): sistem talimatının bağlamı (asistan adı, kullanıcı, bilgiler).
    mic_on(): mikrofon açık mı. on_sleep(): model uyku moduna geçildiyse oturumdan sonra kapanmak için sorgulanır."""

    def __init__(self, handler, emit, prompt, mic_on=lambda: True, wants_sleep=lambda: False, stop_event=None,
                 vocab=lambda: [], on_session_end=None, prepare_tool=None):
        self.handler, self.emit, self.prompt, self.vocab = handler, emit, prompt, vocab
        self.prepare_tool = prepare_tool
        self.on_session_end = on_session_end          # konuşma bitince (rol, metin) listesiyle çağrılır: öğrenme
        self.mic_on, self.wants_sleep = mic_on, wants_sleep
        self.stop_event = stop_event or threading.Event()
        self.player = _Player()
        self._timing = VoiceTiming()
        self.player.on_play = lambda: self._timing.note('output_write')
        self.loop = asyncio.new_event_loop()
        self._lock = threading.Lock()
        self._state = "asleep"                       # asleep | connecting | awake
        self._outbox: collections.deque = collections.deque(maxlen=600)   # bytes ya da None (ses akışı kesildi)
        self._pre: collections.deque = collections.deque(maxlen=PRE_FRAMES)
        self._mute_until = 0.0
        self._was_muted = False
        self._activity = time.monotonic()
        self._tools_running = 0
        self._generating = False
        self._discard = False
        self._session = None
        self._resume = None
        self._resumable_until = 0.0
        self._pending_text: list[str] = []
        self._suppress_output_turns = 0       # yazılı cevap Live sesiyle okunurken ikinci sohbet balonunu engeller
        self._in_buf: list[str] = []
        self._out_buf: list[str] = []
        self._quiet_frames = 0
        self._warned_quiet = False
        self._closing = False
        self._sleep_after = False
        self._reload = False
        self._reload_at = 0.0
        self._voice_confirmation = None
        self._voice_transition = False
        self._since = time.monotonic()
        self._barge_hits = 0
        self._wake_soft_hits = 0
        self._wake_warned = False
        self._score_logged = 0.0
        self._win_n = 0
        self._win_max = 0.0
        self._win_lvl = 0.0
        self._snd_n = 0
        self._snd_lvl = 0.0
        self._gain = 1.0
        self._sent: collections.deque = collections.deque(maxlen=int(SAVE_SECONDS * SEND_RATE / FRAME))
        self._low_hits = 0
        self._low_warned = False
        self._stt_hint = False
        self._stt_drop: set[str] = set()   # sunucunun bu çalıştırmada reddettiği transkripsiyon alanları
        self._connect_t = 0.0
        self._levels: collections.deque = collections.deque(maxlen=250)   # son ~20 sn'nin kare seviyeleri
        self._gain_tick = 0
        self._reconnect = False
        self._headphones = False
        self._frames = 0
        self._skip = 0
        self._recent_user: collections.deque = collections.deque(maxlen=6)   # son sözlerin ham yazısı (yanlış duyma öğrenmek için)
        self._force_safe = False   # bu çalıştırmada 1011 görülürse sonraki oturumları doğrudan sade ayarla aç
        self._convo: list[tuple[str, str]] = []      # bu konuşmanın (rol, metin) kaydı: bitince öğrenmeye gider
        self._heard_any = True                        # oturum açıldıktan sonra kullanıcıdan söz geldi mi
        self._woke_at = 0.0
        self._listening_since = None
        self._speech_activity = SpeechActivity()
        self._diagnostics = None
        self._ex_tools = 0                            # bu konuşma turunda (kullanıcının son sözünden beri) çağrılan araç sayısı
        self._claim: tuple[float, str] | None = None  # araçsız "yaptım" denetimi: (denetim zamanı, söylenen)
        self._corrected = False
        self._safe = False                            # 1011 sonrası: yalnızca zorunlu ayarlarla bağlan
        threading.Thread(target=self.loop.run_forever, daemon=True, name="canli-dongu").start()

    # ------------------------------------------------------------------ dışarıya açık
    def start(self) -> None:
        from modules import wakeword
        try:
            _migrate_fixes()
        except Exception:                             # noqa: BLE001
            _record_failure('modules/live.py:start')
        ready_now = wakeword.ready()                 # "Hey Jarvis" modelini arka planda hazırla
        self.emit("state", "idle")                  # model yüklenirken "Dinliyorum" diyerek yanıltma
        if not ready_now:
            self.emit("status", "Jarvis hazırlanıyor… Hey Jarvis dinleyicisi yükleniyor.")

            def _announce_ready():
                # İlk kurulumda model indirme/yükleme birkaç saniye sürebilir. Arayüzü bloklama.
                for _ in range(300):
                    if self.stop_event.is_set():
                        return
                    st = wakeword.status()
                    if st["state"] == "ready":
                        self.emit("status", "Hazır — Hey Jarvis diyebilirsin.")
                        self.emit("state", "idle")
                        return
                    if st["state"] == "failed":
                        self.emit("system", "Hey Jarvis dinleyicisi hazırlanamadı: " + st.get("error", ""))
                        self.emit("state", "idle")
                        return
                    time.sleep(0.1)
            threading.Thread(target=_announce_ready, daemon=True, name="canli-hazirlik").start()
        threading.Thread(target=self._mic_loop, daemon=True, name="canli-mikrofon").start()
        if sys.platform == "win32":
            threading.Thread(target=self._hotkey_loop, daemon=True, name="canli-kisayol").start()

    def active(self) -> bool:
        return self._state != "asleep"

    def wake(self, by_word: bool = False) -> None:
        """Oturumu şimdi açar (Hey Jarvis, Ctrl+Boşluk ya da arayüzdeki Konuş düğmesi).
        Varsayılan yalnız tetikleyen son 80 ms korunur; sonraki komutun başı sabit süreyle atılmaz.
        Tam uyanma tamponu yalnız eski live_send_wake ayarı açıksa gönderilir."""
        with self._lock:
            if self._state != "asleep":
                return
            self._state = "connecting"
            self._since = time.monotonic()
        self._outbox.clear()
        self._timing.begin()
        self._heard_any, self._woke_at = False, time.monotonic()
        self._listening_since = None
        self._speech_activity.reset()
        if _cfg("live_send_wake", False):
            self._outbox.extend(self._pre)
        elif by_word and self._pre:
            self._outbox.append(self._pre[-1])        # keep boundary syllables, not the whole wake phrase
        self._skip = 0
        self._beep()
        self.emit("state", "listening")
        asyncio.run_coroutine_threadsafe(self._converse(), self.loop)

    def say(self, text: str, suppress_ui: bool = False, exact: bool = False, slow: bool = False) -> None:
        """Bir metni seçili Gemini Live sesiyle söyletir.

        suppress_ui=True: metin arayüzde zaten gösterildiyse Live'ın ses transkriptini ikinci kez sohbet balonu yapma.
        exact=True: yazılı cevabı mümkün olduğunca kelimelerini değiştirmeden oku.
        """
        text = (text or "").strip()
        if not text:
            return
        if suppress_ui:
            self._suppress_output_turns += 1
        if slow:
            msg = ("[Sistem seslendirmesi — aşağıdaki ders anlatımını Türkçe olarak AYNEN oku; tek kelime ekleme/çıkarma, "
                   "yorum yapma. Sabırlı bir öğretmen gibi YAVAŞ, sakin ve tane tane oku; her cümleden sonra kısa bir "
                   "nefes payı bırak, ilk cümleye özellikle yavaş başla]: " + text)
        elif exact:
            msg = ("[Sistem seslendirmesi — aşağıdaki metni Türkçe olarak AYNEN oku. Tek kelime ekleme/çıkarma, yorum yapma. "
                   "Acele etmeden, sakin bir hızla oku]: " + text)
        else:
            msg = "[Sistem bildirimi — bunu kullanıcıya doğal ve kısa biçimde söyle, yorum ekleme]: " + text
        with self._lock:
            if self._state == "asleep":
                self._state = "connecting"
                self._timing.begin()
                self._since = time.monotonic()
                self._heard_any = True                # Jarvis kendisi konuşmak için açtı: "söz duyulmadı" diye kapatma
                self._pending_text.append(msg)
                asyncio.run_coroutine_threadsafe(self._converse(), self.loop)
                return
            self._pending_text.append(msg)

    def preview(self, name: str, text: str) -> None:
        """Ses sekmesinde "Seç ve dinle": sesi kaydeder, açık oturumu kapatıp örnek cümleyi yeni sesle söyletir."""
        from config import save_settings
        save_settings(live_voice=name)

        def run():
            if self._state != "asleep":
                self._closing = True
                for _ in range(40):
                    if self._state == "asleep":
                        break
                    time.sleep(0.1)
            self.say(text)
        threading.Thread(target=run, daemon=True, name="canli-ses-onizleme").start()

    def interrupt(self) -> None:
        """Konuşan Jarvis'i hemen susturur."""
        if self._generating:
            self._discard = True                     # model üretmeye devam etse de gelen ses atılır
        self.player.clear()

    def close(self) -> None:
        self._closing = True

    # ------------------------------------------------------------------ mikrofon
    def _beep(self, high: bool = True) -> None:
        """Uyanma/kapanma sesi (live_beep, varsayılan AÇIK): kullanıcı Jarvis'in dinlemeye geçtiğini duysun.
        Windows Beep'i yerine kısa, yumuşak (girişi ve çıkışı yavaşlatılmış) bir ton çalar; tık/pıt sesi olmaz."""
        if not _cfg("live_beep", True):
            return
        try:
            n = int(RECV_RATE * 0.14)
            t = np.arange(n) / RECV_RATE
            env = np.sin(np.pi * np.arange(n) / n) ** 2                 # yumuşak giriş ve çıkış: tık sesi olmaz
            tone = np.sin(2 * np.pi * (880 if high else 600) * t) * env * 0.10
            self.player.feed_now((tone * 32767).astype(np.int16).tobytes())
        except Exception:                             # noqa: BLE001
            _record_failure('modules/live.py:_beep')
            pass

    def _mic_loop(self) -> None:
        from modules.live_microphone import run
        return run(self, sys.modules[__name__])

    def _agc(self, x):
        from modules.live_microphone import gain
        return gain(self, x, sys.modules[__name__])

    def _on_frame(self, x, wakeword) -> None:
        from modules.live_microphone import frame
        return frame(self, x, wakeword, sys.modules[__name__])

    def _hotkey_loop(self) -> None:
        """Ctrl+Boşluk (yalnız Windows): Jarvis susuyorsa dinlemeye alır, konuşuyorsa keser."""
        import ctypes
        down = False
        while not self.stop_event.is_set():
            try:
                u = ctypes.windll.user32
                pressed = bool(u.GetAsyncKeyState(0x11) & 0x8000) and bool(u.GetAsyncKeyState(0x20) & 0x8000)
            except Exception:                         # noqa: BLE001
                _record_failure('modules/live.py:_hotkey_loop')
                return
            if pressed and not down:
                if self._state == "asleep":
                    self.wake()
                else:
                    self.interrupt()
            down = pressed
            time.sleep(0.05)

    # ------------------------------------------------------------------ oturum
    _VOCAB = ("Hey Jarvis", "Jarvis", "Steam", "Chrome", "YouTube", "Spotify", "sesi aç", "sesi kıs", "parlaklığı aç",
              "parlaklığı kıs", "not ekle", "hatırlat", "uyku modu", "Gmail", "takvim")

    def _stt_kwargs(self, types) -> dict:
        from modules.live_session_config import transcription
        return transcription(self, types, sys.modules[__name__])

    def _config(self):
        from modules.live_session_config import connection
        return connection(self, sys.modules[__name__])

    async def _converse(self) -> None:
        from modules.live_session import converse
        return await converse(self, sys.modules[__name__])

    def _session_end(self, convo: list[tuple[str, str]]) -> None:
        from modules.live_session import end
        return end(self, convo, sys.modules[__name__])

    def _save_sent(self) -> None:
        """Tanı: bu oturumda modele giden sesin son SAVE_SECONDS saniyesini .jarvis\\son_ses.wav'a yazar (yalnızca bu
        bilgisayarda kalır, her oturumda üzerine yazılır). Dinleyince sesin net mi boğuk/cızırtılı mı olduğu anlaşılır.
        Varsayılan kapalıdır; yalnız live_save_audio=true ile açıkça etkinleştirilir."""
        frames, self._sent = list(self._sent), collections.deque(maxlen=self._sent.maxlen)
        if not frames or not _cfg("live_save_audio", False):
            return
        try:
            import wave
            from config import DATA_DIR
            path = DATA_DIR / "son_ses.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SEND_RATE)
                w.writeframes(b"".join(frames))
            log.info("Tanı kaydı: modele giden ses %s dosyasına yazıldı (%.1f sn)", path, len(frames) * FRAME / SEND_RATE)
        except Exception:                             # noqa: BLE001
            _record_failure('modules/live.py:_save_sent')

    def _explain(self, exc: Exception) -> str:
        from modules import failure_policy
        category = failure_policy.classify(exc)
        self._session_error_category = category
        self._session_rate_limited = category in (failure_policy.RATE_LIMIT, failure_policy.QUOTA_EXHAUSTED)
        low = str(exc).lower()
        if "1011" in low or "internal error" in low:
            return ("Google'ın canlı konuşma servisi bağlantıyı üst üste kesti (sunucu tarafı hata, senden kaynaklı değil). "
                    "Birazdan tekrar “Hey Jarvis” de; sürerse yazarak devam edebilirsin.")
        try:
            from modules import diagnose
            return "Canlı konuşma kurulamadı: " + diagnose.explain(exc)
        except Exception:                             # noqa: BLE001
            _record_failure('modules/live.py:_explain')
            return "Canlı konuşma kurulamadı; biraz sonra tekrar dene."

    async def _run_session(self, session) -> None:
        from modules.live_session import run
        return await run(self, session, sys.modules[__name__])

    async def _send(self, session) -> None:
        from google.genai import types
        while True:
            if self._pending_text:
                await session.send_realtime_input(text=self._pending_text.pop(0))
                self._activity = time.monotonic()
                continue
            if not self._outbox:
                await asyncio.sleep(0.02)
                continue
            item = self._outbox.popleft()
            if item is None:
                await session.send_realtime_input(audio_stream_end=True)
            else:
                await session.send_realtime_input(
                    audio=types.Blob(data=item, mime_type=f"audio/pcm;rate={SEND_RATE}"))
                self._timing.note('audio_sent')
                if self._diagnostics is not None:
                    self._diagnostics.output(time.monotonic(), item, SEND_RATE)

    async def _watch(self, session) -> None:
        """Etkinlik yoksa oturumu kapatır (gizlilik + kota)."""
        idle = max(15, int(_cfg("live_idle_seconds", 90)))
        while True:
            await asyncio.sleep(0.5)
            if self._closing or self.stop_event.is_set():
                return
            if self._claim and time.monotonic() >= self._claim[0]:
                said, self._claim = self._claim[1], None
                if not self._ex_tools and not self._corrected:
                    self._corrected = True            # aynı tur için bir kez: döngüye girmesin
                    log.warning("İşlem kaydı: %s", 'modules/live.py:_watch')
                    self._pending_text.append(
                        "[Sistem notu — bunu kullanıcıya okuma]: Az önce bir işi yaptığını/yapacağını söyledin ama HİÇBİR "
                        "araç çağırmadın; yani iş YAPILMADI. İstek açıksa şimdi gerekli aracı çağır (müzik için muzik_cal). İstek "
                        "belirsizse ya da yanlış duymuş olabilirsen araç çağırma; kullanıcıya yapmadığını söyle ve ne "
                        "istediğini kısaca sor. Yapamıyorsan kullanıcıya kısaca yapamadığını söyle.")
            if self._reload and time.monotonic() >= self._reload_at and not self.player.busy() and not self._tools_running:
                self._reload = False
                self._resume = None
                self._reconnect = True
                self._flush_transcripts()
                return
            busy = self.player.busy() or self._tools_running or self._generating or self._pending_text
            if busy:
                self._activity = time.monotonic()
            elif self._heard_any and self._speech_activity.last is not None and time.monotonic() - self._speech_activity.last < 2:
                self._activity = time.monotonic()
            elif not self._heard_any and self._listening_since is not None and self._speech_activity.expired(
                    time.monotonic(), self._listening_since,
                    max(1, int(_cfg("live_nospeech_seconds", NOSPEECH_CLOSE)))):
                # Uyandı ama hiç söz gelmedi: büyük ihtimalle TV/ortam sesiyle yanlış uyanma. Hassasiyeti düşürmek gerçek
                # "Hey Jarvis"leri de kaçırtıyordu (kısık mikrofonda skor 0,15-0,23); onun yerine boş oturumu hemen kapat.
                if self._speech_activity.last is not None:
                    quota = 'var' if getattr(self, '_session_rate_limited', False) else 'yok'
                    log.warning("Yerel ses etkinliği var fakat konuşma transkripti gelmedi; oturum kapatıldı; oturumda kota hatası %s", quota)
                    self.emit("system", "Ses etkinliği algıladım fakat konuşmanı yazıya çeviremedim. Tekrar söyler misin?")
                else:
                    log.info("Bağlantı açıldıktan sonra %d sn konuşma transkripti veya yerel konuşma etkinliği gelmedi; oturum kapatıldı",
                             int(time.monotonic() - self._listening_since))
                self._heard_any = True
                self._closing = True
                self._beep_close()
                return
            elif self._sleep_after or time.monotonic() - self._activity > idle:
                self._closing = True
                self._resumable_until = time.monotonic() + 60
                self._beep_close()
                return

    def _beep_close(self) -> None:
        self._beep(high=False)

    async def _receive(self, session) -> None:
        empty = 0
        while True:
            got = False
            async for r in session.receive():
                got = True
                upd = getattr(r, "session_resumption_update", None)
                if upd is not None and getattr(upd, "resumable", False) and getattr(upd, "new_handle", None):
                    self._resume = upd.new_handle
                    self._resumable_until = time.monotonic() + 600
                if getattr(r, "go_away", None) is not None:
                    log.info("Sunucu oturumu kapatacak (go_away): bağlantı yenileniyor")
                    self._reconnect = True            # süre doldu: temiz kapat, kaldığı yerden yeniden bağlan
                    return
                if r.data:
                    self._timing.note('reply_audio')
                    self._activity = time.monotonic()
                    if not self._discard and not self._voice_transition:
                        if not self._generating:
                            self.emit("state", "speaking")
                        self._generating = True
                        self._flush_user()
                        self.player.feed(r.data)
                sc = r.server_content
                if sc is not None:
                    if getattr(sc, "interrupted", False):
                        self.player.clear()
                        self._generating = self._discard = False
                        self._out_buf.clear()
                    it = getattr(sc, "input_transcription", None)
                    if it and it.text:
                        self._timing.note('input_transcript')
                        self._heard_any = True
                        if not self._in_buf and not self._generating:
                            self._ex_tools, self._corrected, self._claim = 0, False, None   # kullanıcının yeni sözü
                        self._in_buf.append(it.text)     # etkinlik sayılmaz: ortam gürültüsü oturumu sonsuza dek açık tutmasın
                        self._discard = False         # kullanıcı yeniden konuşuyor: yeni cevap atılmasın
                    ot = getattr(sc, "output_transcription", None)
                    if ot and ot.text and not self._voice_transition:
                        self._flush_user()
                        self._out_buf.append(ot.text)
                    if getattr(sc, "turn_complete", False):
                        self._generating = self._discard = False
                        said = self._flush_transcripts()
                        if said and not self._ex_tools and not self._corrected and _CLAIM.search(said.lower()):
                            self._claim = (time.monotonic() + 1.5, said)    # araç birazdan gelebilir: 1,5 sn sonra bak
                        if not self._tools_running:
                            self.emit("state", "listening")
                if r.tool_call:
                    for fc in r.tool_call.function_calls or []:
                        self._tools_running += 1
                        self._ex_tools += 1
                        self.emit("state", "thinking")
                        asyncio.create_task(self._run_tool(session, fc))
            empty = 0 if got else empty + 1
            if empty > 50:                            # bağlantı sessizce kapandıysa boşa dönme
                raise ConnectionError("Canlı bağlantı kapandı")
            await asyncio.sleep(0.02)

    async def _run_tool(self, session, fc) -> None:
        from modules.live_tool_runner import run
        await run(self, session, fc, sys.modules[__name__])

    async def _direct_tool(self, fn, *args):
        from modules.live_tool_runner import direct
        return await direct(self, fn, *args, services=sys.modules[__name__])

    def _change_voice(self, name: str) -> str:
        from modules.live_tool_runner import change_voice
        return change_voice(self, name, sys.modules[__name__])

    # ------------------------------------------------------------------ arayüze konuşma kaydı
    def _flush_user(self) -> None:
        from modules.live_transcripts import flush_user
        flush_user(self, sys.modules[__name__])

    def _flush_transcripts(self) -> str:
        from modules.live_transcripts import flush_transcripts
        return flush_transcripts(self, sys.modules[__name__])


# ---------------------------------------------------------------------------------------------------- modül düzeyi
_live: Live | None = None


def start(handler, emit, prompt, mic_on=lambda: True, wants_sleep=lambda: False, stop_event=None,
          vocab=lambda: [], on_session_end=None, prepare_tool=None) -> Live:
    global _live
    _live = Live(handler, emit, prompt, mic_on, wants_sleep, stop_event, vocab, on_session_end, prepare_tool)
    _live.start()
    return _live


def get() -> Live | None:
    return _live


def stop_playback() -> None:
    """Durdur düğmesi / voice.stop_speaking buradan canlı sesi de keser."""
    if _live is not None:
        _live.interrupt()