"""Microphone frames, gain and wake/echo guards for the existing Live instance.

Receives service adapters; creates no new Live session or user identity.
"""
from __future__ import annotations
import time
import numpy as np
from modules.diagnostics import record_failure as _record_failure

def run(self, services) -> None:
    import sounddevice as sd
    from modules import voice, wakeword
    errs = 0
    while not self.stop_event.is_set():
        if not self.mic_on() or not services.enabled():
            self.stop_event.wait(0.1)
            continue
        try:
            dev_id = voice._input_device()
            try:
                dev = sd.query_devices(dev_id, 'input')
                name, native = (dev['name'], int(dev['default_samplerate'] or services.SEND_RATE))
            except Exception:
                _record_failure('modules/live.py:_mic_loop')
                name, native = ('?', services.SEND_RATE)
            if not services._cfg('live_native_rate', True):
                native = services.SEND_RATE
            rs = services._Resampler(native)
            hp = services._HighPass() if services._cfg('live_lowcut', True) else None
            block = max(256, int(round(services.FRAME * native / services.SEND_RATE)))
            pending = np.zeros(0, dtype=np.int16)
            with sd.InputStream(samplerate=native, channels=1, dtype='int16', blocksize=block, device=dev_id) as stream:
                errs = 0
                services.log.info("Mikrofon açıldı: %s (%d Hz kendi hızında okunuyor, %d Hz'e çevriliyor)", name, native, services.SEND_RATE)
                while not self.stop_event.is_set():
                    data, _ = stream.read(block)
                    diagnostics = self._diagnostics
                    if diagnostics is not None and self._state in ('connecting', 'awake'):
                        diagnostics.input(time.monotonic(), np.asarray(data).astype('<i2').tobytes(), native)
                    x = rs(np.asarray(data).reshape(-1))
                    if hp is not None:
                        x = hp(x)
                    if not self.mic_on() or not services.enabled():
                        break
                    pending = np.concatenate([pending, x])
                    while len(pending) >= services.FRAME:
                        fr, pending = (pending[:services.FRAME], pending[services.FRAME:])
                        try:
                            if not self.player.busy():
                                self._speech_activity.observe(fr, time.monotonic())
                            self._on_frame(self._agc(fr), wakeword)
                        except Exception:
                            _record_failure('modules/live.py:_mic_loop')
        except Exception as exc:
            _record_failure('modules/live.py:_mic_loop')
            if self.stop_event.is_set():
                return
            errs += 1
            if errs == 1:
                _record_failure('modules/live.py:_mic_loop')
            if errs == 5:
                self.emit('system', 'Mikrofona ulaşılamıyor. Mikrofon takılı mı? Windows ses ayarlarını kontrol et.')
            self.stop_event.wait(min(2 * errs, 15))

def gain(self, x, services):
    """Kısık mikrofonu otomatik güçlendirir. Konuşma seviyesi son ~20 sn'den tahmin edilir; hedefin altındaysa
    kazanç yavaşça artar (en fazla AGC_MAX), yeterliyse 1'e iner. `live_mic_gain` sayı olarak verilirse sabit kazanç."""
    fixed = services._cfg('live_mic_gain', 0)
    try:
        fixed = float(fixed)
    except (TypeError, ValueError):
        fixed = 0.0
    lvl = float(np.abs(x.astype(np.int32)).mean()) if len(x) else 0.0
    self._levels.append(lvl)
    if fixed > 0:
        self._gain = min(fixed, 20.0)
    else:
        self._gain_tick += 1
        if self._gain_tick % 12 == 0 and len(self._levels) >= 60:
            lv = np.sort(np.fromiter(self._levels, dtype=np.float32))
            floor, speech = (float(lv[int(len(lv) * 0.2)]), float(lv[int(len(lv) * 0.95)]))
            if speech > max(floor * 2.5, 30.0):
                target = min(services.AGC_MAX, max(1.0, services.AGC_TARGET / speech))
                self._gain = 0.85 * self._gain + 0.15 * target
                if self._state == 'awake' and speech < services.LOW_MIC_SPEECH and (self._gain > services.AGC_MAX * 0.85):
                    self._low_hits += 1
                    if self._low_hits == 20 and (not self._low_warned):
                        self._low_warned = True
                        services.log.warning('Mikrofon çok kısık: konuşma seviyesi %.0f, kazanç x%.1f', speech, self._gain)
                        self.emit('system', 'Mikrofonun sesi çok kısık geliyor, seni yanlış duyabilirim. Mikrofonu ağzına yaklaştır ya da başka bir mikrofon dene (Ayarlar > Ses).')
                else:
                    self._low_hits = 0
    if self._gain <= 1.02:
        return x
    return np.clip(services._soft_limit(x.astype(np.float32) * self._gain), -32768, 32767).astype(np.int16)

def frame(self, x, wakeword, services) -> None:
    lvl = float(np.abs(x.astype(np.int32)).mean()) if len(x) else 0.0
    self._quiet_frames = self._quiet_frames + 1 if lvl == 0 else 0
    if self._quiet_frames == 400 and (not self._warned_quiet):
        self._warned_quiet = True
        self.emit('system', "Mikrofon hiç ses vermiyor. Windows'ta Ayarlar > Gizlilik > Mikrofon iznini kontrol et ya da Ayarlar'dan mikrofonu seç.")
    st = self._state
    if st == 'asleep':
        self._pre.append(x.tobytes())
        sc = wakeword.score(x)
        thr = wakeword.sensitivity_threshold()
        self._win_n += 1
        self._win_max = max(self._win_max, sc)
        self._win_lvl += lvl
        if self._win_n >= 750:
            services.log.info('Dinleme: mikrofon seviyesi %.0f (kazanç x%.1f), en yüksek Hey Jarvis skoru %.2f (eşik %.2f), dinleyici %s', self._win_lvl / self._win_n, self._gain, self._win_max, thr, wakeword.status()['state'])
            self._win_n, self._win_max, self._win_lvl = (0, 0.0, 0.0)
        soft_thr = max(0.08, thr * 0.68)
        self._wake_soft_hits = self._wake_soft_hits + 1 if sc >= soft_thr else 0
        if sc >= thr or self._wake_soft_hits >= 2:
            services.log.info('Uyandı: Hey Jarvis (skor %.2f, eşik %.2f%s)', sc, thr, ', iki-kare uzak ses doğrulaması' if sc < thr else '')
            self._wake_soft_hits = 0
            wakeword.reset()
            self.wake(by_word=True)
        elif sc >= soft_thr and time.monotonic() - self._score_logged > 5:
            self._score_logged = time.monotonic()
            services.log.info('Uyanma denemesi yetmedi: skor %.2f, eşik %.2f (hassasiyeti artırabilirsin)', sc, thr)
        elif not self._wake_warned:
            self._frames += 1
            if self._frames % 125 == 0:
                stt = wakeword.status()
                if stt['state'] == 'failed':
                    self._wake_warned = True
                    self.emit('system', '“Hey Jarvis” dinleyicisi çalışmıyor; ekrandaki mikrofon düğmesi ya da Ctrl+Boşluk ile konuşabilirsin. ' + stt['error'])
        return
    if st == 'connecting':
        if self._skip > 0:
            self._skip -= 1
            return
        self._outbox.append(x.tobytes())
        if time.monotonic() - self._since > 25:
            services.log.warning("Canlı bağlantı 25 sn'de kurulamadı, sıfırlanıyor")
            self._state = 'asleep'
            self.emit('system', 'Canlı konuşmaya bağlanılamadı. İnternetini kontrol edip tekrar “Hey Jarvis” de.')
            self.emit('state', 'idle')
        return
    speaking = self.player.busy()
    self._frames += 1
    if self._frames % 40 == 0:
        self._headphones = bool(services._cfg('live_headphones', False))
    now = time.monotonic()
    if speaking and (not self._headphones):
        self._was_muted = True
        if wakeword.score(x) >= services.BARGE_THRESHOLD:
            self._barge_hits += 1
            if self._barge_hits >= services.BARGE_FRAMES:
                self._barge_hits = 0
                wakeword.reset()
                services.log.info('Konuşma kesildi: Hey Jarvis')
                self.interrupt()
        else:
            self._barge_hits = 0
        return
    if self._was_muted:
        self._was_muted = False
        self._mute_until = max(self._mute_until, self.player.last_end + self.player.latency + services.ECHO_TAIL)
        if self._mute_until - now > 1.0:
            services.log.info('Mikrofon Jarvis konuştuktan sonra %.1f sn daha kapalı kalacak', self._mute_until - now)
        self._outbox.append(None)
    if now < self._mute_until:
        return
    self._snd_n += 1
    self._snd_lvl += lvl
    data = x.tobytes()
    self._sent.append(data)
    self._outbox.append(data)
