"""Live session component; operates on the existing instance and service adapters.

No extra session state or user/request identity is created by extraction.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

def transcription(self, types, services, minimal: bool = False) -> dict:
    """Gelen sesin yazıya dökülmesine Türkçe dil kodu ve özel sözlük verir (yanlış dilde yazmasın).
    Sunucu bir alanı reddederse yalnız o alan bu çalıştırmada bırakılır (`_stt_drop`); Türkçe kodu kalıcı
    kapatılmaz. minimal=True (1011 sonrası sade mod): yalnız dil kodu gider, sözlük gitmez."""
    self._stt_hint = False
    if not services._cfg('live_stt_language', True):
        return {}
    drop = getattr(self, '_stt_drop', set())
    fields = getattr(types.AudioTranscriptionConfig, 'model_fields', {})
    kw: dict = {}
    if 'language_codes' in fields and 'language_codes' not in drop:
        kw['language_codes'] = ['tr-TR']
    if 'custom_vocabulary' in fields and 'custom_vocabulary' not in drop and not minimal:
        mine = [w.strip() for w in str(services._cfg('stt_words', '')).split(',') if w.strip()]
        try:
            around = [str(w) for w in self.vocab()]
        except Exception:
            _record_failure('modules/live.py:_stt_kwargs')
            around = []
        first = ['Hey Jarvis', 'Jarvis']
        kw['custom_vocabulary'] = list(dict.fromkeys([*first, *mine[:15], *around[:20], *self._VOCAB]))[:50]
    self._stt_hint = bool(kw)
    return kw


_STT_REJECT = ('1007', 'invalid argument', 'unknown name', 'language_code', 'custom_vocabulary', 'vocabulary',
               'unsupported', 'not supported')


def stt_rejected(self, msg: str) -> bool:
    """Bağlantının hemen ardından gelen hata transkripsiyon alanının reddi gibiyse bir alanı bırakır.
    Önce özel sözlük, sonra dil kodu bırakılır; ayar dosyasına yazılmaz (Jarvis yeniden açılınca Türkçe kodu döner)."""
    if not self._stt_hint or not any(k in msg for k in _STT_REJECT):
        return False
    drop = getattr(self, '_stt_drop', None)
    if drop is None:
        drop = self._stt_drop = set()
    field = 'language_codes' if ('language' in msg and 'vocabulary' not in msg) or 'custom_vocabulary' in drop \
        else 'custom_vocabulary'
    if field in drop:
        return False
    drop.add(field)
    return True

def connection(self, services):
    from google.genai import types
    s = services.load_settings()
    decls = [types.FunctionDeclaration(name=n, description=d, parameters=sch) for n, (d, sch) in services.TOOLS.items()]
    silence = int(s.get('live_silence_ms') or services.SILENCE_DEFAULT)
    if silence == 700:
        silence = services.SILENCE_DEFAULT
    kw = {}
    low = getattr(getattr(types, 'EndSensitivity', None), 'END_SENSITIVITY_LOW', None)
    if low is not None and (not self._safe):
        kw['end_of_speech_sensitivity'] = low
    detect = types.AutomaticActivityDetection(silence_duration_ms=silence, prefix_padding_ms=300, **kw)
    if self._safe:
        stt = transcription(self, types, services, minimal=True)   # sade modda da Türkçe dil kodu korunur
    else:
        stt = self._stt_kwargs(types)
    extra = {}
    if services._cfg('live_compression', False) and (not self._safe):
        extra['context_window_compression'] = types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow())
    return types.LiveConnectConfig(response_modalities=['AUDIO'], system_instruction=self.prompt() + '\nAktif konuşma sesi: ' + services.voice_name() + '. Ses seçimi kalıcı ayardır. Önceki ses değiştirme isteklerini yeniden uygulama. Yalnız kullanıcının YENİ ve açık ses değiştirme isteğinde ses_degistir çağır. Beğendim, teşekkürler veya isim verme ses değiştirme isteği değildir.', tools=[types.Tool(function_declarations=decls)], speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=services.voice_name()))), input_audio_transcription=types.AudioTranscriptionConfig(**stt), output_audio_transcription=types.AudioTranscriptionConfig(), realtime_input_config=types.RealtimeInputConfig(automatic_activity_detection=detect), session_resumption=types.SessionResumptionConfig(handle=None if self._safe else self._resume), **extra)
