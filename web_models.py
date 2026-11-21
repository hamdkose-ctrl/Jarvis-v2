"""UI bridge operations with explicit owning-runtime dependencies."""
from __future__ import annotations

class WebModels:

    def user_keys(self) -> list:
        """Kendi Gemini anahtarı olan kullanıcılar (anahtarın kendisi gönderilmez)."""
        runtime = self._runtime
        from modules.personalization import list_users, slugify
        return [u for u in list_users() if runtime.llm.user_key(slugify(u))]

    def user_key_set(self, name: str, key: str='') -> dict:
        """Kullanıcıya kendi Gemini anahtarını verir (önce dener); boş anahtar yalnız o kullanıcıdan silinir."""
        runtime = self._runtime
        from modules.personalization import slugify
        slug, key = (slugify(name or ''), (key or '').strip())
        if not slug:
            return {'ok': False, 'msg': 'Kullanıcı bulunamadı.'}
        if not key:
            runtime.llm.set_user_key(slug, None)
            return {'ok': True, 'msg': f'{name} için Gemini anahtarı silindi. Başka kullanıcının anahtarı kullanılmayacak.'}
        try:
            from google import genai as _g
            test_client = _g.Client(api_key=key, http_options=runtime.llm._gemini_http_options())
            test_client.models.generate_content(model=runtime.llm.model_names(slug)[0], contents="Yalnızca 'tamam' yaz.",config={"max_output_tokens":32})
        except Exception as e:
            runtime._record_failure('web_models.py:user_key_set')
            low = str(e).lower()
            if 'api key' in low or 'api_key' in low or 'permission' in low or ('401' in low) or ('403' in low) or ('400' in low):
                return {'ok': False, 'msg': 'Bu anahtar çalışmıyor. aistudio.google.com/apikey adresinden kopyaladığını kontrol et.'}
            if '429' not in low and 'quota' not in low and ('exhausted' not in low):
                return {'ok': False, 'msg': f'Anahtar denenemedi: {str(e)[:120]}'}
        runtime.llm.set_user_key(slug, key)
        return {'ok': True, 'msg': f'Kaydedildi. {name} konuşurken artık kendi anahtarı kullanılacak.'}

    def api_key_save(self, key: str, model: str='', fallback: str='') -> dict:
        """Bağlantılar ekranındaki Gemini anahtarını aktif kullanıcıya kaydeder.

    Çoklu kullanıcı düzeninde global anahtarı değiştirmek sohbet ile UI'nın
    farklı anahtar görmesine yol açıyordu. Bu giriş artık doğrudan aktif profile aittir.
    """
        runtime = self._runtime
        p = runtime._p()
        key = (key or '').strip()
        if key:
            runtime.llm.set_user_key(p.slug, key)
            runtime.llm.set_user_context(p.slug)
        fbs = [m.strip() for m in (fallback or '').split(',') if m.strip()]
        if model.strip() or fbs:
            runtime.llm.model_settings(p.slug, model, fbs)
        return {'Gemini': {'ok': True, 'saved': True}}

    def llm_validate(self, force: bool=False) -> dict:
        runtime = self._runtime
        return runtime.llm.model_check(bool(force))

    def role_qualification_status(self) -> dict:
        from modules import role_qualification
        return role_qualification.status()

    def role_qualification_prepare(self) -> dict:
        from modules import role_qualification
        return role_qualification.prepare()

    def llm_status(self) -> dict:
        runtime = self._runtime
        st = runtime.llm.status()
        backend = st.get('local_backend') or 'ollama'
        preference = str(st.get('ollama_model') or '').strip()
        installed = [str(x).strip() for x in st.get('ollama_models', []) if str(x).strip()]
        effective = preference
        stale = False
        warning = ''
        try:
            effective = runtime.llm._ollama_effective_model(runtime.llm.provider_configuration())
        except runtime.llm.LocalModelError:
            effective = ''
        if backend == 'ollama':
            from modules.llm import _installed_ollama_name
            stale = bool(preference and effective and not _installed_ollama_name(preference, installed))
            if stale:
                warning = 'Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.'
        st.update({
            'local_model_preference': preference,
            'local_effective_model': effective,
            'local_model_stale': stale,
            'local_model_warning': warning,
            'local_models_checked': True,
            'local_installed_models': installed,
            'local_model_choice_provider': 'ollama',
            'local_model_select_enabled': bool(installed),
        })
        return st

    def router_local_capabilities(self, expected_owner: str='') -> dict:
        owner=self._router_owner(expected_owner)
        from modules import llm,model_capabilities
        with llm.owner_context(owner):
            config=llm.provider_configuration()
            model=llm._ollama_effective_model(config,refresh_missing=False)
            return model_capabilities.refresh_local(model,config)

    def router_request_trace(self, request_id: str, expected_owner: str='') -> dict:
        from modules import smart_router
        return {'trace':smart_router.trace(self._router_owner(expected_owner),request_id)}

    def llm_set(self, provider: str, model: str='', url: str='') -> dict:
        runtime = self._runtime
        runtime.llm.set_user_context(runtime._p().slug)
        runtime.llm.set_provider(provider, model or None, url or None)
        runtime.privacy.audit('model sağlayıcı', f'{provider} {model}'.strip())
        return runtime.llm.status()

    def local_backend_set(self, backend: str, url: str='', model: str='') -> dict:
        """Yerel model sunucusu: Ollama, LM Studio veya llama.cpp (OpenAI uyumlu uç nokta). Sağlayıcı değişmez."""
        runtime = self._runtime
        runtime.llm.set_local_backend(backend, url, model)
        st = runtime.llm.status()
        label = st['local_label']
        msg = (f'{label} çalışıyor, {len(st["ollama_models"])} model görüldü.' if st['ollama_up'] else
               f'{label} kaydedildi ama şu an yanıt vermiyor ({st["ollama_url"]}).')
        runtime.privacy.audit('yerel model sunucusu', f'{backend} {st["ollama_url"]}')
        return {'ok': bool(st['ollama_up']), 'msg': msg, 'status': st}

    def smart_router_status(self) -> dict:
        runtime = self._runtime
        from modules import smart_router
        return smart_router.status(runtime._p().slug)

    def router_ready_status(self) -> dict:
        from modules import smart_router
        return smart_router.ready_status(self._runtime._p().slug)

    def smart_router_save(self, gemini_scopes: list, expected_owner: str) -> dict:
        from modules import smart_router
        state = smart_router.configure(self._router_owner(expected_owner), gemini_scopes=gemini_scopes)
        return {'ok': True, 'msg': 'Gemini veri izinleri kaydedildi.', 'status': state}

    def router_ready_check(self, provider: str, expected_owner: str) -> dict:
        from modules import smart_router
        return smart_router.check_ready_connection(self._router_owner(expected_owner), provider)

    def router_cloudflare_save(self, account_id: str='', token: str='', remove: bool=False, expected_owner: str='') -> dict:
        from modules import image_gen
        import re
        owner=self._router_owner(expected_owner)
        if type(remove) is not bool:raise ValueError('Silme seçimi geçersiz.')
        if remove:
            image_gen.set_user_cloudflare(owner,None,None)
            return {'ok':True,'msg':'Yalnız bu kullanıcının Cloudflare bağlantısı kaldırıldı.'}
        account=(account_id or '').strip() or image_gen.user_cloudflare_account(owner)
        secret=(token or '').strip() or image_gen.user_cloudflare_token(owner)
        if not re.fullmatch(r'[a-fA-F0-9]{32}',account):raise ValueError('Cloudflare hesap kimliği 32 onaltılık karakter olmalı.')
        if not secret or len(secret)>4096 or any(ord(c)<33 for c in secret):raise ValueError('Cloudflare token geçersiz.')
        image_gen.set_user_cloudflare(owner,account,secret)
        return {'ok':True,'msg':'Cloudflare bağlantısı kaydedildi.'}

    def router_ready_key_save(self, provider: str, key: str, expected_owner: str) -> dict:
        from modules import llm
        owner = self._router_owner(expected_owner)
        key = key.strip() if isinstance(key, str) else ''
        if not key or len(key) > 4096:
            raise ValueError('API anahtarını gir.')
        if provider == 'gemini':
            llm.set_user_key(owner, key)
        elif provider == 'groq':
            llm.set_user_groq_key(owner, key)
        else:
            raise ValueError('Hazır bağlantı geçersiz.')
        return {'ok': True, 'msg': 'API anahtarı kaydedildi.'}

    def groq_key_save(self, key: str='', model: str='', activate: bool=False) -> dict:
        """Groq anahtarını kaydeder, küçük bir çağrıyla dener. activate=True ise sağlayıcı Groq olur."""
        runtime = self._runtime
        p = runtime._p()
        key = (key or '').strip()
        if key:
            runtime.llm.set_user_groq_key(p.slug, key)
            runtime.llm.set_user_context(p.slug)
        if model.strip():
            runtime.llm.choose_model(p.slug, 'groq', model)
        if not runtime.llm.user_groq_key(p.slug):
            return {'ok': False, 'msg': f'{p.name} için Groq anahtarı girilmedi.'}
        t0 = runtime.time.time()
        try:
            runtime.llm.test_groq()
        except runtime.llm.CloudError as e:
            return {'ok': False, 'msg': str(e)}
        runtime.privacy.audit('groq anahtarı', 'kaydedildi ve denendi')
        if activate:
            runtime.llm.set_provider('groq')
        return {'ok': True, 'msg': f'Groq yanıt verdi ({round(runtime.time.time() - t0, 1)} sn).', 'status': runtime.llm.status()}

    def model_choice_save(self, provider: str, model: str='') -> dict:
        """Aktif kullanıcının Groq veya yerel modelini kaydeder; seçili sağlayıcıyı değiştirmez."""
        runtime = self._runtime
        p = runtime._p()
        model = (model or '').strip()
        if provider == 'ollama':
            st = runtime.llm.status()
            installed = [str(x).strip() for x in st.get('ollama_models', []) if str(x).strip()]
            if not model or model not in installed:
                return {'ok': False, 'msg': 'Yalnız seçili yerel backend üzerinde kurulu modellerden biri seçilebilir.'}
        try:
            runtime.llm.choose_model(p.slug, provider, model)
        except ValueError as e:
            return {'ok': False, 'msg': str(e)}
        runtime.privacy.audit('model seçimi', f'{provider} {model}'.strip())
        label = 'Groq' if provider == 'groq' else 'Yerel model'
        return {'ok': True, 'msg': f'{label} için {model} kaydedildi ({p.name}).', 'status': runtime.llm.status()}

    def _router_owner(self,expected_owner):
        owner=self._runtime._p().slug
        if expected_owner!=owner:raise PermissionError('Kullanıcı değişti; bağlantı işlemi uygulanmadı.')
        return owner

    def router_connection_save(self, record: dict, key: str='', expected_owner: str='') -> dict:
        from modules import router_connections
        row=router_connections.save(self._router_owner(expected_owner),record,secret=key or None)
        return {'ok':True,'msg':'Özel bağlantı kaydedildi; model denemesi yapılmadı.','connection':row}

    def router_connection_delete(self, identity: str, expected_owner: str='') -> dict:
        from modules import router_connections
        router_connections.remove(self._router_owner(expected_owner),identity)
        return {'ok':True,'msg':'Bu kullanıcının özel bağlantısı kaldırıldı.'}

    def router_connection_models(self, identity: str, expected_owner: str='') -> dict:
        from modules import router_connections,provider_protocols,llm,requests_state
        owner=self._router_owner(expected_owner)
        requests_state.request_identity(owner)
        row,secret=router_connections.resolve(owner,identity,require_enabled=False)
        with llm.owner_context(owner):
            return {'ok':True,'models':provider_protocols.models(row,secret)}

    def router_connection_test(self, identity: str, accept_charge: bool=False, expected_owner: str='') -> dict:
        from modules import router_connections,provider_protocols,router_quota,smart_router,usage_meter,llm,requests_state
        if accept_charge is not True:raise ValueError('Tek gerçek API denemesi için açık tercih gerekli.')
        owner=self._router_owner(expected_owner)
        row,secret=router_connections.resolve(owner,identity,require_enabled=False)
        # A test never enables a connection or attests role/vision/free-tier quality.
        router_quota.reserve(owner,router_quota.custom_provider(row),row['model'],directory=smart_router._STORE,
            quota_scope=router_quota.custom_scope(owner,row),application_limit=row['daily_requests'],cost_limit=row.get('daily_cost_microusd'))
        requests_state.request_identity(owner)
        with llm.owner_context(owner),usage_meter.capture_attempt(owner,'connection-test:'+identity,'test:'+identity):
            answer=provider_protocols.generate(owner,row,secret,[{'role':'user','content':'Reply only OK.'}],'',min(32,row['max_output_tokens']))
        if answer.finish_reason not in (None,'stop','end_turn','stop_sequence'):
            raise ValueError('API deneme yanıtı tamamlanmadı.')
        return {'ok':True,'msg':'Tek API çağrısı yanıt verdi; rol yeterliliği veya ücretsiz hesap kabulü değildir.',
                'model':row['model'],'usage':answer.usage}

    def router_connection_vision_test(self, identity: str, accept_charge: bool=False, expected_owner: str='') -> dict:
        from modules import router_connections,provider_protocols,router_quota,smart_router,llm,requests_state
        import secrets,tempfile
        from pathlib import Path
        from PIL import Image,ImageDraw,ImageFont
        if accept_charge is not True:raise ValueError('Tek gerçek görüntü denemesi için açık tercih gerekli.')
        owner=self._router_owner(expected_owner)
        requests_state.request_identity(owner)
        row,secret=router_connections.resolve(owner,identity,require_enabled=False)
        router_quota.reserve(owner,router_quota.custom_provider(row),row['model'],directory=smart_router._STORE,
            quota_scope=router_quota.custom_scope(owner,row),application_limit=row['daily_requests'],cost_limit=row.get('daily_cost_microusd'))
        # The answer exists ONLY in image pixels. A successful text connection,
        # a model name or a user checkbox cannot produce this observation.
        expected=''.join(secrets.choice('0123456789') for _ in range(8))
        with tempfile.TemporaryDirectory(prefix='jarvis-vision-check-') as folder,llm.owner_context(owner):
            path=Path(folder)/'challenge.png'
            image=Image.new('RGB',(400,100),'white')
            ImageDraw.Draw(image).text((15,20),expected,font=ImageFont.load_default(size=48),fill='black')
            image.save(path)
            answer=provider_protocols.generate(owner,row,secret,[{'role':'user','content':'Read the eight digits in the image. Reply with digits only.'}],'',min(32,row['max_output_tokens']),image_path=str(path))
        if answer.finish_reason not in (None,'stop','end_turn','stop_sequence') or answer.text.strip()!=expected:
            raise ValueError('Görüntü desteği doğrulanamadı; model görüntüdeki kodu doğru okuyamadı.')
        router_connections.record_vision_observation(owner,row)
        return {'ok':True,'msg':'Bu bağlantı/exact model tek sentetik görüntüyü doğru okudu. Genel görüntü doğruluğu veya Brain rol kabulü değildir.','usage':answer.usage}

    def llm_measure(self) -> dict:
        runtime = self._runtime
        from modules import ui_jobs
        p = runtime._p()
        owner, names = (p.slug, runtime.llm.model_names(p.slug))

        def measure():
            runtime.llm.set_user_context(owner)
            client = runtime.llm.gemini_client()
            if client is None:
                return {'Gemini': {'ok': False, 'error': 'Bu kullanıcı için anahtar yok.'}}
            out = {}
            for name in names:
                t0 = runtime.time.monotonic()
                try:
                    client.models.generate_content(model=name, contents="Sadece 'tamam' yaz.",config={"max_output_tokens":32})
                    out[name] = {'ok': True, 'sec': round(runtime.time.monotonic() - t0, 1)}
                except Exception:
                    runtime._record_failure('web_models.py:llm_measure')
                    out[name] = {'ok': False, 'error': 'Model ölçülemedi; tanı günlüğünü kontrol et.'}
            return out
        return ui_jobs.start(owner, 'model_measure', measure)

    def ui_job_status(self, rid: str) -> dict:
        runtime = self._runtime
        from modules import ui_jobs
        return ui_jobs.status(runtime._p().slug, rid)
