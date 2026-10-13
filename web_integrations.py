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
        try:
            data = runtime.json.loads(text)
        except ValueError:
            raise ValueError('Bu bir JSON dosyası değil.')
        if not isinstance(data, dict) or not {'installed', 'web'} & set(data):
            raise ValueError('Bu bir Google OAuth istemci dosyası gibi görünmüyor (client_secret…json).')
        runtime.google_api.CRED.write_text(runtime.json.dumps(data), encoding='utf-8')
        return 'Kimlik dosyası kaydedildi. Şimdi “Bağlan / dene”ye bas.'

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
        return {'ok': True, 'production': bool(on), 'msg': 'Google OAuth durumu Production olarak işaretlendi; 7 günlük test uyarısı kapatıldı.' if on else 'Google OAuth Testing olarak işaretlendi; 6. günde yenileme uyarısı verilecek.'}

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
