"""Live session component; operates on the existing instance and service adapters.

No extra session state or user/request identity is created by extraction.
"""
from __future__ import annotations
import asyncio
import contextlib
import os
import threading
import time
from modules.diagnostics import record_failure as _record_failure

async def converse(self, services) -> None:
    from modules import llm, usage_meter
    self._convo = []
    self._closing = False
    self._sleep_after = False
    self._safe = bool(self._force_safe)
    self._diagnostics = services.AudioDiagnostics() if services._cfg('live_audio_diagnostics', False) else None
    retries = 0
    try:
        if not services.enabled():
            self.emit('system', 'Canlı konuşma kapalı: ses dışarı (buluta) gönderilmez. Yazarak söyleyebilirsin.')
            return
        cli = llm.gemini_client()   # Live politika gereği kapalı (enabled() False); kod PR9'da silinir
        if cli is None:
            self.emit('system', "Gemini anahtarı yok; Ayarlar'dan ekle.")
            return
        if time.monotonic() > self._resumable_until:
            self._resume = None
        while not self._closing and (not self.stop_event.is_set()):
            try:
                self._connect_t = time.monotonic()
                usage_meter.record('gemini-live', services.model_name(), 0, 0, 'baglanti_acildi')
                async with contextlib.AsyncExitStack() as stack:
                    session = await asyncio.wait_for(stack.enter_async_context(cli.aio.live.connect(model=services.model_name(), config=self._config())), 20)
                    self._session = session
                    self._state = 'awake'
                    self._activity = time.monotonic()
                    self._listening_since = self._activity
                    self._timing.note('connected')
                    if self._voice_confirmation is not None:
                        selected = self._voice_confirmation
                        self._voice_confirmation = None
                        self._voice_transition = False
                        self._generating = self._discard = False
                        self._pending_text.append(f'[Sistem bildirimi — ses değişimi tamamlandı; yeni bir ses değiştirme isteği DEĞİLDİR. Araç çağırma. Yalnız şu cümleyi Türkçe söyle]: Sesimi {selected} olarak güncelledim, bundan sonra bu sesle konuşacağım.')
                    services.log.info('Canlı oturum açıldı (pid %d, %s, %s, Türkçe ipucu %s%s)', os.getpid(), services.model_name(), services.voice_name(), 'açık' if self._stt_hint else 'yok', ', sade ayar' if self._safe else '')
                    self._session_opened()
                    await self._run_session(session)
                retries = 0
                if self._closing:
                    break
                if not (self._reconnect or self._resume):
                    break
                self._reconnect = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _record_failure('modules/live.py:_converse')
                msg = str(exc).lower()
                from modules.live_session_config import stt_rejected
                if time.monotonic() - self._connect_t < 8 and stt_rejected(self, msg):
                    _record_failure('modules/live.py:_converse')
                    services.log.warning('Ses yazıya dökme alanı reddedildi; bu çalıştırmada %s olmadan bağlanılıyor', ', '.join(sorted(self._stt_drop)))
                    continue
                retries += 1
                _record_failure('modules/live.py:_converse')
                if ('1011' in msg or 'internal error' in msg) and (not self._safe):
                    self._safe = True
                    self._force_safe = True
                    services.log.warning('Sunucu iç hatası (1011): bu çalıştırmada sade Live modu kullanılacak')
                self._resume = None
                self._outbox.clear()
                if retries > 2 or self._closing:
                    self.emit('system', self._explain(exc))
                    break
                await asyncio.sleep(1.0 * retries)
    finally:
        self._session = None
        self._state = 'asleep'
        self._generating = self._discard = False
        self._voice_transition = False
        self._voice_confirmation = None
        self._tools_running = 0
        self.player.clear()
        self._outbox.clear()
        self._pending_text.clear()
        self._flush_transcripts()
        self._suppress_output_turns = 0
        self.emit('state', 'idle')
        try:
            from modules import wakeword
            wakeword.reset()
        except Exception:
            _record_failure('modules/live.py:_converse')
            pass
        if self._snd_n:
            services.log.info('Oturumda gönderilen ses: ortalama seviye %.0f, kazanç x%.1f', self._snd_lvl / self._snd_n, self._gain)
        self._save_sent()
        diagnostics, self._diagnostics = (self._diagnostics, None)
        if diagnostics is not None:
            try:
                from config import DATA_DIR
                diagnostics.save(DATA_DIR, time.monotonic())
                services.log.info('Yerel ses tanısı kaydedildi: ham mikrofon ve başarılı ses gönderim çağrıları')
            except Exception:
                _record_failure('modules/live.py:audio_diagnostics')
        self._snd_n, self._snd_lvl = (0, 0.0)
        services.log.info('Canlı oturum kapandı')
        convo, self._convo = (self._convo, [])
        if self.on_session_end is not None and convo:
            threading.Thread(target=self._session_end, args=(convo,), daemon=True, name='canli-ogrenme').start()

def opened(self, services) -> None:
    if not self.on_session_start:
        return
    try:
        self.on_session_start()
    except Exception:
        _record_failure('modules/live.py:_session_opened')


def end(self, convo: list[tuple[str, str]], services) -> None:
    try:
        self.on_session_end(convo)
    except Exception:
        _record_failure('modules/live.py:_session_end')

async def run(self, session, services) -> None:
    tasks = [asyncio.create_task(self._send(session)), asyncio.create_task(self._receive(session)), asyncio.create_task(self._watch(session))]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception():
                raise t.exception()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
