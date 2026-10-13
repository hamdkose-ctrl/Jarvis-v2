"""Phone page actions; dependencies are provided by the owning bridge."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

class WebPhone:

    def phone_toggle(self, on: bool) -> dict:
        runtime = self._runtime
        err = ''
        if on:
            try:
                runtime.phone.start()
            except OSError as e:
                err = str(e)
        else:
            runtime.phone.stop()
        runtime.privacy.audit('telefon erişimi', 'açıldı' if on and (not err) else 'kapatıldı' if not on else 'açılamadı', ok=not err)
        info = self.phone_info()
        if err:
            info['error'] = err
        return info

    def phone_info(self, user: str='', refresh: bool=False) -> dict:
        """user: kimin telefonu için adres/QR gösterilecek. Her kullanıcının adresinde kendi anahtarı vardır;
        o anahtarla yalnız o kişi adına konuşulur ve yalnız onun konuşmaları görülür."""
        runtime = self._runtime
        from modules.personalization import get_active, list_users
        names = list_users()
        pc = get_active()
        if pc and pc not in names:
            names = [pc] + names
        user = user if user in names else pc or (names[0] if names else '')
        if refresh:
            runtime.phone.clear_pairings(user)
        st = runtime.config.load_settings()
        ts = runtime.cached('tailscale', 6, runtime.phonemod.tailscale_status)
        info = {'running': runtime.phone.running, 'urls': [], 'port': runtime.phone.port, 'scope': runtime.PhoneServer.scope(), 'secure_default': True, 'auto': bool(st.get('phone_auto', False)), 'tailscale': ts, 'firewall': f'netsh advfirewall firewall add rule name="Jarvis Telefon" dir=in action=allow protocol=TCP localport={runtime.phone.port} remoteip=100.64.0.0/10,LocalSubnet', 'token_len': len(runtime.phone.token), 'token_legacy': len(runtime.phone.token) < 24}
        hu = runtime.cached('ts_https', 6, lambda: runtime.phonemod.https_url(port=runtime.phone.port, strict=runtime.PhoneServer.scope() == 'secure')) if ts.get('state') == 'running' else ''
        runtime.phone.https = hu
        info['https'] = {'active': bool(hu), 'url': hu}
        info['users'], info['user'] = (names, user)
        info['connected'] = runtime.phone.connected(user)
        info['qr_ttl'] = 90
        if runtime.phone.running:
            for label, url in runtime.phone.urls(user):
                info['urls'].append({'label': label, 'url': url, 'qr': runtime.qr_matrix(url)})
        return info

    def phone_set(self, data: dict) -> dict:
        """scope: 'both' | 'tailscale', auto: Jarvis açılınca telefon erişimini kendiliğinden aç."""
        runtime = self._runtime
        ch: dict = {}
        if data.get('scope') in ('secure', 'both', 'tailscale'):
            ch['phone_scope'] = data['scope']
            ch['phone_allow_http'] = data['scope'] == 'both'
        if 'auto' in data:
            ch['phone_auto'] = bool(data['auto'])
        if ch:
            runtime.config.save_settings(**ch)
            runtime.privacy.audit('telefon ayarı', ', '.join((f'{k}={v}' for k, v in ch.items())))
        if 'phone_scope' in ch and runtime.phone.running:
            runtime.phone.stop()
            try:
                runtime.phone.start()
            except OSError as e:
                info = self.phone_info()
                info['error'] = str(e)
                return info
        return self.phone_info()

    def phone_app_qr(self, name: str='') -> dict:
        """A key-free QR grants one Android HTTPS provisioning request for 90s."""
        runtime = self._runtime
        from modules.personalization import Profile, slugify
        name = (name or '').strip() or runtime._p().name
        slug = slugify(name)
        if not slug:
            return {'ok': False, 'msg': 'Kullanıcı bulunamadı.'}
        own = runtime.llm.user_key(slug)
        key = own
        if not key:
            return {'ok': False, 'msg': "Bu kullanıcının Gemini anahtarı yok. Önce Kullanıcılar'dan bu profile ait anahtarı ekle."}
        try:
            goals = [str(g) for g in Profile(name).data.get('goals') or []][-3:]
        except Exception:
            _record_failure('web_phone.py:phone_app_qr')
            goals = []
        models = runtime.llm.model_names(slug)
        endpoint = runtime.phonemod.https_url(port=runtime.phone.port, strict=True)
        from urllib.parse import urlparse
        parsed = urlparse(endpoint or '')
        if (parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.ts.net')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment or parsed.port not in (None,443)):
            return {'ok': False, 'msg': 'Güvenli Android kurulumu için Telefon bölümündeki Tailscale HTTPS bağlantısını aç. Anahtarlı QR artık üretilmiyor.'}
        if not runtime.phone.running:
            try:
                runtime.phone.start()
            except OSError:
                return {'ok': False, 'msg': 'Telefon sunucusu başlatılamadı.'}
        runtime.phone.https = endpoint
        code = runtime.phone.android_setup.issue(slug, {'j':'jarvis-android', 'v':1, 'n':name, 'm':models[:3], 'a':runtime._aname(), 'g':goals})
        payload = runtime.json.dumps({'j':'jarvis-android', 'v':2, 'u':endpoint.rstrip('/')+'/api/android-setup', 'c':code}, separators=(',', ':'))
        qr = runtime.qr_matrix(payload)
        if qr is None:
            return {'ok': False, 'msg': "QR üretilemedi: 'segno' paketi kurulu değil (pip install segno)."}
        runtime.privacy.audit('telefon uygulaması', f"{name} için kurulum QR'ı gösterildi")
        return {'ok': True, 'qr': qr, 'name': name, 'own': bool(own), 'ttl':90, 'version':2}

    def phone_token_reset(self) -> dict:
        runtime = self._runtime
        runtime.phone.token = runtime.phonemod.reset_token()
        runtime.phone.clear_pairings()
        runtime.privacy.audit('telefon anahtarı', 'yenilendi')
        return self.phone_info()

    def tailscale_https(self, on: bool) -> dict:
        """Tailscale Serve ile telefon sunucusuna https adresi aç/kapat (tarayıcı mikrofonu için)."""
        runtime = self._runtime
        host = runtime.phonemod.tailscale_ip() if runtime.PhoneServer.scope() == 'tailscale' else '127.0.0.1'
        ok, msg = runtime.phonemod.https_set(bool(on), runtime.phone.port, host or '127.0.0.1')
        if on and (not runtime.phone.running):
            msg = (msg + ' ' if msg else '') + '(Not: sol karttaki “Telefon erişimini aç”ı da aç.)'
        import re as _re
        lk = _re.search('https://login\\.tailscale\\.com/\\S+', msg or '')
        if lk and (not ok):
            try:
                import webbrowser
                webbrowser.open(lk.group(0))
            except Exception:
                _record_failure('web_phone.py:tailscale_https')
                pass
        runtime.privacy.audit('telefon https', 'açıldı' if on and ok else 'kapatıldı' if ok else 'başarısız')
        runtime._CACHE.pop('ts_https', None)
        info = self.phone_info()
        if not ok:
            info['error'] = msg or 'Tailscale komutu çalışmadı.'
        return info

    def tailscale_action(self, action: str) -> dict:
        """'download' (indirme sayfasını aç) | 'open' (Tailscale uygulamasını başlat)."""
        runtime = self._runtime
        import webbrowser
        if action == 'download':
            webbrowser.open('https://tailscale.com/download')
        elif action == 'open':
            exe = runtime.phonemod.tailscale_exe()
            ipn = runtime.os.path.join(runtime.os.path.dirname(exe), 'tailscale-ipn.exe') if exe else ''
            try:
                if ipn and runtime.os.path.exists(ipn):
                    runtime.subprocess.Popen([ipn])
                elif exe:
                    runtime.subprocess.Popen([exe, 'up'], creationflags=getattr(runtime.subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError:
                pass
        runtime._CACHE.pop('tailscale', None)
        return self.phone_info()
