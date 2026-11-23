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
        if lane is None:
            # The single owner is absent only after a reported configuration fault.
            return {
                'local': True, 'rate_supported': False, 'voices': [],
                'voice': pr.get('voice', 'tr_erkek'),
                'rate': rate if isinstance(rate, int) else 5,
                'error': 'Voice Core yapılandırması geçersiz; ses seçimi kapalı.',
            }
        installed = []
        for spec in lane.catalog.choices():
            try:
                lane.check_voice(spec.voice_id)
            except (ValueError, OSError):
                continue
            info = 'Yerel Piper' if spec.backend == 'piper' else 'Edge (çevrimiçi)'
            installed.append({'key': spec.voice_id, 'name': spec.label, 'info': info})
        from modules import voice_runtime as _vr
        engine = _vr.voice_engine()
        selected = pr.get('voice') or 'tr_erkek'
        rate_supported = any(item['key'] == selected for item in installed)
        return {
            'local': True, 'rate_supported': rate_supported,
            'voices': installed, 'voice': selected,
            'rate': rate if isinstance(rate, int) else 5,
            'engine': engine,
            'engines': [{'key': 'edge', 'name': 'Edge', 'info': 'Çevrimiçi · doğal ses'},
                        {'key': 'windows', 'name': 'Windows', 'info': 'Yerel · internet gerekmez'}],
        }

    def voice_set(self, key: str) -> bool:
        runtime = self._runtime
        from modules import voice_runtime
        from modules.engine_context import set_profile_voice
        lane = voice_runtime.active()
        if lane is None:
            return False
        profile = runtime._p()
        accepted, _label = set_profile_voice(profile, key, lane=lane)
        if not accepted:
            return False
        runtime.engine.events.put(('say', 'Merhaba, seçtiğin ses böyle.', profile.slug))
        return True

    def rate_set(self, rate: int) -> bool:
        runtime = self._runtime
        from modules import voice_runtime
        from modules.engine_context import set_profile_rate
        lane = voice_runtime.active()
        if type(rate) is not int:
            return False
        level = max(-40, min(40, rate))
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
