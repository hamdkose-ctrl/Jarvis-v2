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
        from modules.gemini_billing import _record_failure
        test_client = None
        try:
            from google import genai as _g
            test_client = _g.Client(api_key=key, http_options={'timeout': 45000})
            next(iter(test_client.models.list(config={'page_size': 1})), None)
        except Exception:
            _record_failure('web_models.py:user_key_set')
            return {'ok':False,'msg':'Anahtarın model listesine erişimi doğrulanamadı. Anahtarı ve proje erişimini kontrol et.'}
        finally:
            if test_client is not None:test_client.close()
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

    def gemini_profile_models(self, tier: str='free', key: str='') -> dict:
        from modules import model_health
        from google import genai
        runtime=self._runtime;owner=runtime._p().slug
        if owner != runtime.llm.current_user():raise PermissionError('Aktif kullanıcı değişmiş.')
        if tier not in ('free','paid'):raise ValueError('Geçersiz Gemini katmanı.')
        if runtime.llm.privacy.mode() in ('yerel','gizli'):raise PermissionError('Yerel/gizli modda bulut model listesi alınmaz.')
        if not isinstance(key,str) or len(key)>1000 or '\n' in key or '\r' in key:raise ValueError('Anahtar biçimi geçersiz.')
        key=key.strip() or runtime.llm.user_key(owner,tier=tier)
        result=model_health.check(owner,key,runtime.llm.model_names(owner,tier=tier),genai.Client,force=True)
        ok=result['state'] in ('ok','missing_models')
        return {'ok':ok,'models':result.get('available_models',[]),
                'msg':'Model listesi erişim bilgisidir; ücretsiz kota veya fiyat garantisi değildir.' if ok else result.get('message','Model listesi alınamadı.')}

    def gemini_profile_save(self, tier: str, key: str='', model: str='', fallback: str='') -> dict:
        from modules import user_models
        import re
        runtime=self._runtime;owner=runtime._p().slug
        if owner != runtime.llm.current_user():raise PermissionError('Aktif kullanıcı değişmiş.')
        if tier not in ('free','paid'):raise ValueError('Geçersiz Gemini katmanı.')
        if not isinstance(key,str) or len(key)>1000 or re.search(r'[\r\n]',key):raise ValueError('Anahtar biçimi geçersiz.')
        current=runtime.llm.model_names(owner,tier=tier)
        names=[model.strip() or (current[0] if current else '')]+[v.strip() for v in fallback.split(',') if v.strip()]
        if len(names)>8 or any(not re.fullmatch(r'[A-Za-z0-9._/-]{1,150}',v) for v in names):raise ValueError('Geçerli ana model ve en fazla 7 yedek model seç.')
        user_models.save(owner,names,tier=tier)
        if key.strip():runtime.llm.set_user_key(owner,key.strip(),tier=tier)
        return {'ok':True,'msg':'Gemini '+('ücretsiz' if tier=='free' else 'ücretli')+' anahtar/model ayarları kaydedildi. Model çağrısı yapılmadı; kullanım izni açılmadı.'}

    def gemini_billing_check(self, tier: str='free') -> dict:
        from modules import gemini_billing
        runtime=self._runtime;owner=runtime._p().slug
        if tier not in ('free','paid'):raise ValueError('Geçersiz Gemini katmanı.')
        key=runtime.llm.user_key(owner) if tier=='free' else runtime.llm.user_key(owner,tier='paid')
        result=gemini_billing.check(owner,key,tier=tier,interactive=True,force=True);state=result['state']
        messages={
            'billing_disabled':'Bu anahtarın projesinde ücretli faturalama kapalı. Ücretsiz model erişimi ve kota ayrıca değerlendirilir.',
            'billing_enabled':'Bu anahtarın projesinde ücretli faturalama açık. Ücretsiz bağlantı olarak doğrulanmadı; ücretli kullanım izni açılmadı.',
            'unverified':'Faturalama durumu doğrulanamadı. Google salt okunur bağlantısını ve proje erişimini kontrol et.'}
        if state=='unverified':
            messages[state]={
                'PROVIDER_ACCOUNT_AUTH_REQUIRED':'Google salt okunur hesabını bağla veya bağlantıyı yenile.',
                'PROVIDER_ACCOUNT_ACCESS_REQUIRED':'Google hesabının anahtar/proje faturalama bilgisine erişimi yok. Proje izinlerini ve API erişimini kontrol et.',
                'PROVIDER_ACCOUNT_RATE_LIMITED':'Google hesap kontrolü istek sınırına ulaştı; daha sonra tekrar dene.',
                'PROVIDER_BILLING_RECEIPT_SAVE_FAILED':'Google kontrol sonucu güvenle kaydedilemedi; Gemini kullanımı açılmadı.'
            }.get(result.get('reason_code'),messages[state])
        if tier=='paid' and state=='billing_enabled':messages[state]='Bu ücretli Gemini projesinde faturalama açık. Ücretli kullanım izni açılmadı.'
        return {'ok':state==('billing_disabled' if tier=='free' else 'billing_enabled'),'msg':messages[state],'billing':result}

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

    def llm_set(self, provider: str, model: str='', url: str='') -> dict:
        runtime = self._runtime
        runtime.llm.set_user_context(runtime._p().slug)
        runtime.llm.set_provider(provider, model or None, url or None)
        if provider in ('openai', 'anthropic') and runtime._live().get() is not None:
            runtime._live().get().close()
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

    def smart_router_save(self, key: str='', model: str | None='openrouter/free', cloud_free_confirmed: bool | None=False) -> dict:
        runtime = self._runtime
        from modules import smart_router
        state = smart_router.configure(runtime._p().slug, cloud_free_confirmed, model, key=key.strip() or None)
        if not runtime.llm.gemini_aux_allowed() and runtime._live().get() is not None:
            runtime._live().get().close()
        return {'ok': True, 'msg': 'Model bağlantısı ve seçim tercihleri kaydedildi.', 'status': state}

    def smart_router_key_delete(self) -> dict:
        runtime = self._runtime
        from modules import smart_router
        return smart_router.configure(runtime._p().slug, key='')

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

    def paid_provider_save(self, provider: str, key: str='', model: str='', workspace: str='') -> dict:
        runtime = self._runtime
        from modules import paid_providers
        if provider not in paid_providers.PROVIDERS:
            raise ValueError('Sağlayıcı geçersiz.')
        state = paid_providers.configure(runtime._p().slug, provider, api_key=key.strip() or None, candidate_model=model or None, workspace=workspace)
        return {'ok': True, 'msg': 'Kaydedildi. Sağlayıcı değişmedi; model seçip ayrıca etkinleştir.', 'status': state}

    def paid_provider_models(self, provider: str) -> dict:
        runtime = self._runtime
        from modules import paid_providers
        return {'ok': True, 'models': paid_providers.models(runtime._p().slug, provider)}

    def paid_provider_delete(self, provider: str) -> dict:
        runtime = self._runtime
        from modules import paid_providers
        paid_providers.configure(runtime._p().slug, provider, api_key='')
        return {'ok': True, 'msg': 'Yalnız bu kullanıcının anahtarı silindi.'}

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
                    client.models.generate_content(model=name, contents="Sadece 'tamam' yaz.")
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

