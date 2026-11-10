"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebVoice:

    def local_stt_status(self) -> dict:
        from modules import local_stt
        return local_stt.status()

    def local_stt_prepare(self, model: str) -> dict:
        from modules import local_stt
        return local_stt.prepare(model)

    def voice_options(self) -> dict:
        runtime = self._runtime
        pr = runtime._p().data['prefs']
        rate = pr.get('rate', 5)
        from modules import voice_runtime
        lane = voice_runtime.active()
        if lane is None and voice_runtime.legacy_blocked():
            return {
                'local': True, 'rate_supported': False, 'voices': [],
                'voice': pr.get('voice', 'tr_erkek'),
                'rate': rate if isinstance(rate, int) else 5,
                'error': 'Voice Core yapılandırması geçersiz; ses seçimi kapalı.',
            }
        if lane is not None:
            installed = []
            for spec in lane.catalog.choices():
                try:
                    lane.check_voice(spec.voice_id)
                except (ValueError, OSError):
                    continue
                installed.append({'key': spec.voice_id, 'name': spec.label, 'info': 'Yerel Piper'})
            return {
                'local': True, 'rate_supported': True,
                'voices': installed, 'voice': pr.get('voice', 'tr_erkek'),
                'rate': rate if isinstance(rate, int) else 5,
            }
        if not runtime.config.load_settings().get('local_stt_enabled', False) and runtime._live().enabled():
            cur = runtime.config.load_settings().get('live_voice') or runtime._live().DEFAULT_VOICE
            return {'live': True, 'voices': [{'key': k, 'name': k, 'info': d} for k, d in runtime._live().VOICE_INFO.items()], 'voice': cur, 'rate': rate if isinstance(rate, int) else 5}
        return {'voices': [{'key': k, 'name': v[0]} for k, v in runtime.voice.VOICES.items()], 'voice': pr.get('voice', 'tr_erkek'), 'rate': rate if isinstance(rate, int) else 5}

    def voice_set(self, key: str) -> bool:
        runtime = self._runtime
        from modules import voice_runtime
        lane = voice_runtime.active()
        if lane is None and voice_runtime.legacy_blocked():
            return False
        from modules.engine_context import set_profile_voice
        if lane is not None:
            profile = runtime._p()
            accepted, _label = set_profile_voice(profile, key, lane=lane)
            if not accepted:
                return False
            runtime.engine.events.put(('say', 'Merhaba, seçtiğin yerel ses böyle.', profile.slug))
            return True
        lv = runtime._live()
        if not runtime.config.load_settings().get('local_stt_enabled', False) and lv.enabled() and key in lv.VOICE_INFO:
            if lv.get() is not None:
                lv.get().preview(key, 'Merhaba, sesim böyle.')
            else:
                runtime.config.save_settings(live_voice=key)
        elif key in runtime.voice.VOICES:
            accepted, _label = set_profile_voice(
                runtime._p(), key, voices=runtime.voice.VOICES,
            )
            if not accepted:
                return False
            runtime.engine.events.put(('say', 'Merhaba, sesim böyle.'))
        else:
            return False
        return True

    def rate_set(self, rate: int) -> bool:
        runtime = self._runtime
        from modules import voice_runtime
        from modules.engine_context import set_profile_rate
        lane = voice_runtime.active()
        level = max(-40, min(40, int(rate)))
        if not set_profile_rate(runtime._p(), level, lane=lane):
            return False
        runtime.engine.events.put(('say', 'Böyle konuşuyorum.'))
        return True

    def input_devices(self) -> list:
        """Her mikrofon bir kez: Windows aynı cihazı MME/DirectSound/WASAPI/WDM-KS diye
    4-5 kez listeler. Motor adı parça eşleştirmeyle MME'yi seçtiği için yalnız MME gösterilir."""
        runtime = self._runtime
        try:
            import sounddevice as sd
            apis = sd.query_hostapis()
            devs = list(enumerate(sd.query_devices()))

            def mme(d):
                return 'mme' in apis[d['hostapi']]['name'].lower()
            pool = [(i, d) for i, d in devs if d['max_input_channels'] > 0]
            if any((mme(d) for _, d in pool)):
                pool = [(i, d) for i, d in pool if mme(d)]
            out, seen = ([], set())
            skip = ('eşleyici', 'sound mapper', 'stereo mix', 'stereo karışımı', 'primary sound')
            for i, d in pool:
                name = d['name'].strip()
                key = name.casefold()
                if key in seen or any((k in key for k in skip)):
                    continue
                seen.add(key)
                out.append({'id': i, 'name': name})
            return out
        except Exception:
            runtime._record_failure('web.py:input_devices')
            return []

    def pc_mute_state(self) -> dict:
        """Bilgisayarın ana ses çıkışı sessizde mi? Okunamazsa muted=None."""
        from modules import system_control
        _com_thread()
        return {'muted': system_control.is_muted()}

    def pc_mute(self, on: bool) -> dict:
        """Bilgisayarın TÜM sesini kapatır/açar (Jarvis'in konuşması dahil). 'Jarvis'i sustur'dan ayrıdır."""
        from modules import system_control
        _com_thread()
        if not system_control.set_mute(bool(on)):
            raise ValueError('Bilgisayarın sesi değiştirilemedi. Varsayılan hoparlörü kontrol et.')
        return {'muted': system_control.is_muted()}


def _com_thread() -> None:
    """Web isteği iş parçacıklarında COM başlatılmamıştır; pycaw çağrısından önce bu iş parçacığında başlatır."""
    try:
        import comtypes
        comtypes.CoInitialize()
    except (ImportError, OSError):   # Windows dışı ya da COM bu iş parçacığında zaten başlatılmış
        pass
