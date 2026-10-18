"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebIntegrations:

    def handoff_status(self) -> dict:
        runtime = self._runtime
        from modules import handoff
        return {'place': handoff.place(), 'chosen': runtime.config.load_settings().get('this_pc'), 'ready': handoff.ready()}

    def handoff_place(self, p: str) -> dict:
        runtime = self._runtime
        from modules import handoff
        handoff.set_place(p)
        return self.handoff_status()

    def handoff_connect(self) -> dict:
        runtime = self._runtime
        from modules import handoff
        ok, msg = handoff.connect()
        return {'ok': ok, 'msg': msg}

    def google_upload(self, text: str) -> str:
        runtime = self._runtime
        from modules import google_setup
        try:
            data = runtime.json.loads(text)
        except ValueError:
            raise ValueError('Bu bir JSON dosyası değil.')
        problem = google_setup.client_problem(data)
        if problem and (not isinstance(data, dict) or 'installed' not in data):
            raise ValueError(problem)
        runtime.google_api.CRED.write_text(runtime.json.dumps(data), encoding='utf-8')
        if problem:
            return 'Kimlik dosyası kaydedildi ama eksik olabilir: ' + problem
        return 'Kimlik dosyası kaydedildi. Şimdi “Bağlan” düğmesine bas.'

    def google_setup_status(self) -> dict:
        runtime = self._runtime
        from modules import google_setup
        production = bool(runtime.config.load_settings().get('google_oauth_production', False))
        return dict(google_setup.status(runtime.google_api, production), steps=google_setup.steps())

    def google_setup_open(self, step: str) -> dict:
        """Sihirbaz adımının sabit Google Cloud sayfasını açar; yalnız bilinen adım kimlikleri kabul edilir."""
        from modules import google_setup
        import webbrowser
        webbrowser.open(google_setup.step_url(str(step)))
        return {'ok': True, 'msg': 'Google Cloud sayfası tarayıcıda açıldı.'}

    def google_connect(self) -> dict:
        runtime = self._runtime
        ok, msg = runtime.google_api.connect()
        return {'ok': ok, 'msg': msg}

    def google_reset(self) -> bool:
        runtime = self._runtime
        runtime.google_api.token_path().unlink(missing_ok=True)
        return True

    def google_oauth_status(self) -> dict:
        runtime = self._runtime
        st = runtime.config.load_settings()
        return {'production': bool(st.get('google_oauth_production', False)), 'console': 'https://console.cloud.google.com/auth/audience'}

    def google_oauth_console(self) -> dict:
        """Google Cloud yayın durumunu kullanıcı hesabında değiştirmek gerekir; ilgili resmi konsol sayfasını açar."""
        runtime = self._runtime
        import webbrowser
        webbrowser.open('https://console.cloud.google.com/auth/audience')
        return {'ok': True, 'msg': "Google Cloud açıldı. Audience / Yayınlanma durumu bölümünde uygulamayı In production yap; sonra JARVIS'te ‘Production yaptım’ düğmesine bas."}

    def google_oauth_production(self, on: bool=True) -> dict:
        runtime = self._runtime
        runtime.config.save_settings(google_oauth_production=bool(on))
        return {'ok': True, 'production': bool(on), 'msg': 'Google OAuth durumu Production olarak işaretlendi; Testing izin uyarısı kapatıldı.' if on else 'Google OAuth Testing olarak işaretlendi; izin eskiyince Jarvis hatırlatır (Google kesin bitiş zamanını bildirmez).'}

    def ntfy(self, action: str) -> dict:
        runtime = self._runtime
        p = runtime._p()
        topic = p.data['prefs'].get('ntfy_topic')
        if action == 'on':
            topic = topic or runtime.notify.new_topic()
            p.set_pref('ntfy_topic', topic)
            return {'on': True, 'topic': topic, 'msg': 'Telefona ntfy uygulamasını kur ve bu konuya abone ol.'}
        if action == 'show':
            return {'on': bool(topic), 'topic': topic or ''}
        if action == 'test':
            if not topic:
                return {'on': False, 'msg': 'Önce aç.'}
            ok = runtime.notify.send(topic, 'Jarvis', 'Deneme bildirimi')
            return {'on': True, 'msg': 'Deneme gönderildi ✓' if ok else 'Gönderilemedi (internet?)'}
        if action == 'off':
            p.data['prefs'].pop('ntfy_topic', None)
            p.save()
            return {'on': False}
        return {'on': bool(topic)}
