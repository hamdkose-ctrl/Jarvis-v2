from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    text = target.read_text(encoding='utf-8')
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected block count 1, got {count}')
    target.write_text(text.replace(old, new, 1), encoding='utf-8')


# task_results: task çıktılarında merkezi outcome contract metadata.
replace(
    'modules/task_results.py',
    "import math\n",
    "import math\nfrom modules import outcome_contracts\n",
)
replace(
    'modules/task_results.py',
    "    output = dict(output)\n    if output['state'] == 'done':\n        if kind == 'browser':\n            output['image_sha256'] = file_digest(output.get('image', ''))\n        check(kind, output)\n        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence'}\n    return output\n",
    "    output = dict(output)\n    if output['state'] == 'done':\n        if kind == 'browser':\n            output['image_sha256'] = file_digest(output.get('image', ''))\n        output = outcome_contracts.attach(kind, output)\n        check(kind, output)\n        outcome_contracts.validate_metadata(kind, output, legacy_ok=False)\n        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence',\n                                  'outcome': output['outcome_contract']['id']}\n    return output\n",
)
replace(
    'modules/task_results.py',
    "    checked = check(metadata.get('agent'), output)\n",
    "    checked = check(metadata.get('agent'), output)\n    if metadata.get('outcome') is not None:\n        outcome_contracts.validate_metadata(metadata.get('agent'), output, legacy_ok=False)\n        if metadata['outcome'] != output['outcome_contract']['id']:\n            raise ValueError('Doğrulama kaydı sonuç sözleşmesiyle eşleşmiyor.')\n",
)

# goal_tools: yerel sonuçlar da contract taşır; open-only tek kaynaktan karar verir.
replace(
    'modules/goal_tools.py',
    "from modules import app_actions, llm, privacy, requests_state, task_agents, task_results, task_tools\n",
    "from modules import app_actions, llm, privacy, requests_state, task_agents, task_results, task_tools, outcome_contracts\n",
)
replace(
    'modules/goal_tools.py',
    "def local_result(owner,kind,text,**extra):\n    if not isinstance(text,str) or not text.strip():raise ValueError('Araç boş sonuç döndürdü.')\n    return {'state':'done','text':_text(text),'owner':owner,'local_evidence':kind,**extra}\n",
    "def local_result(owner,kind,text,**extra):\n    if not isinstance(text,str) or not text.strip():raise ValueError('Araç boş sonuç döndürdü.')\n    output={'state':'done','text':_text(text),'owner':owner,'local_evidence':kind,**extra}\n    return outcome_contracts.attach(kind,output,local=True)\n",
)
replace(
    'modules/goal_tools.py',
    "    if output.get('state')!='done' or output.get('owner')!=owner or output.get('local_evidence') not in LOCAL:\n        raise ValueError('Yerel araç kanıtı veya sahibi geçersiz.')\n    if not isinstance(output.get('text'),str) or not output['text'].strip():raise ValueError('Araç sonucu boş.')\n",
    "    if output.get('state')!='done' or output.get('owner')!=owner or output.get('local_evidence') not in LOCAL:\n        raise ValueError('Yerel araç kanıtı veya sahibi geçersiz.')\n    if not isinstance(output.get('text'),str) or not output['text'].strip():raise ValueError('Araç sonucu boş.')\n    outcome_contracts.validate_common(output['local_evidence'],output,local=True)\n",
)
replace(
    'modules/goal_tools.py',
    "        from modules import router\n        if not router._open_only_request(identity.get('request','')):\n",
    "        if not outcome_contracts.open_only_request(identity.get('request','')):\n",
)

# router: open-only aynı outcome policy'den; LLM eylemi chat'e düşürürse Do modu korur.
old_open = '''def _open_only_request(text):
    """open_app yalnız pencereyi açmanın kendisi nihai hedefse kullanılabilir."""
    low=' '.join(str(text or '').casefold().replace('ı','i').split()).strip(' .!?')
    # Bağlaç veya ikinci bir işlem fiili varsa pencereyi açmak yalnız ara adımdır.
    if re.search(r'\b(?:ve|sonra|ardindan|ardından|sonrasinda|sonrasında|acip|açıp|actiktan|açtıktan)\b',low):return False
    action_verbs=re.findall(r'\b(?:ac|aç|baslat|başlat|calistir|çalıştır|kapat|degistir|değiştir|ayarla|yaz|gir|sec|seç|tikla|tıkla|uygula|kaydet|sil|gonder|gönder)\w*',low)
    if len(action_verbs)!=1 or not re.match(r'^(?:ac|aç|baslat|başlat|calistir|çalıştır)',action_verbs[0]):return False
    return bool(re.fullmatch(r'(?:lutfen\s+|lütfen\s+)?(?:ac|aç|baslat|başlat|calistir|çalıştır)\s+.+|(?:lutfen\s+|lütfen\s+)?.+?\s+(?:uygulamasini\s+|uygulamasını\s+)?(?:ac|aç|baslat|başlat|calistir|çalıştır)(?:ar misin|ar mısın|ir misin|ır mısın)?',low))
'''
new_open = '''def _open_only_request(text):
    """Compatibility wrapper; user-outcome policy owns the actual rule."""
    from . import outcome_contracts
    return outcome_contracts.open_only_request(text)
'''
replace('modules/router.py', old_open, new_open)
replace(
    'modules/router.py',
    "    text = command.strip()\n    low = text.casefold().replace(\"ı\", \"i\")\n",
    "    text = command.strip()\n    low = text.casefold().replace(\"ı\", \"i\")\n    from . import work_modes\n    mode = work_modes.classify(text)\n",
)
replace(
    'modules/router.py',
    "    if intent not in _INTENTS or (intent == 'chat' and _action_request(text)):\n        if re.fullmatch(r'(?:bunu|onu|şunu|böyle|öyle)\\s+\\S+(?:\\s+et)?[ .!?]*',text.casefold()):\n            return {'intent':'clarify','args':{'question':'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n        if _action_request(text):return {'intent':'task','args':{'request':text}}\n        return {'intent': 'clarify', 'args': {'question': 'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n",
    "    if intent not in _INTENTS or (intent == 'chat' and (_action_request(text) or mode == 'do')):\n        if work_modes.ambiguous_reference(text) or re.fullmatch(r'(?:bunu|onu|şunu|böyle|öyle)\\s+\\S+(?:\\s+et)?[ .!?]*',text.casefold()):\n            return {'intent':'clarify','args':{'question':'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n        if _action_request(text) or mode == 'do':return {'intent':'task','args':{'request':text}}\n        return {'intent': 'clarify', 'args': {'question': 'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n",
)

# smart_router: eski public API korunur, sınıflandırma tek policy'den gelir.
replace(
    'modules/smart_router.py',
    '''def failure_kind(exc):
    """'key', 'quota' or 'other'; looks only at the status code and error wording, nothing is stored."""
    code = failure_status(exc)
    text = str(exc)
    if code in (401, 403) or 'yetkisiz' in text or 'API_KEY_INVALID' in text: return 'key'
    if code == 429 or re.search(r'\b429\b|RESOURCE_EXHAUSTED|quota', text, re.I): return 'quota'
    return 'other'


def failure_status(exc):
    code = getattr(exc, 'code', None)
    if not isinstance(code, int):
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
    return code if type(code) is int and 100 <= code <= 599 else None
''',
    '''def failure_kind(exc):
    from modules import failure_policy
    return failure_policy.legacy_kind(exc)


def failure_status(exc):
    from modules import failure_policy
    return failure_policy.status_code(exc)
''',
)
replace(
    'modules/smart_router.py',
    "def failure_text(exc):\n    return {'key':'anahtarı geçersiz','quota':'istek/token sınırına takıldı'}.get(failure_kind(exc), 'yanıt vermedi')\n",
    "def failure_text(exc):\n    from modules import failure_policy\n    return failure_policy.short_text(exc)\n",
)
replace(
    'modules/smart_router.py',
    '''def cooldown(provider, exc):
    """Seconds to skip a provider after a failure: long for a bad key, medium for quota, short for a local outage."""
    kind = failure_kind(exc)
    if kind == 'key': return 1800
    if kind == 'quota': return 300
    if provider == 'ollama': return 30
    return 60
''',
    '''def cooldown(provider, exc):
    from modules import failure_policy
    return failure_policy.cooldown_seconds(provider, exc)
''',
)

# diagnose ve Gmail aynı hata sınıflandırıcısını kullanır.
old_explain = '''def explain(e: BaseException) -> str:
    """Komut sırasında çıkan hatayı kullanıcıya söylenecek anlaşılır bir cümleye çevirir."""
    name = type(e).__name__
    msg = str(e)
    low = msg.lower()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if name in ("LocalModelError", "CloudError"):
        return msg
    if code == 429 or "resource_exhausted" in low or "quota" in low or "429" in low:
        return ("Yapay zekanın kullanım hakkı şimdilik doldu. Birkaç dakika sonra tekrar dene; günlük sınır dolduysa "
                "gece yarısı sıfırlanır. İstersen Yetenekler sayfasından başka bir model seçebilirsin.")
    if code in (401, 403) or "api key" in low or "api_key" in low or "permission_denied" in low or "unauthenticated" in low:
        return "Gemini anahtarı çalışmıyor. Entegrasyonlar sayfasından anahtarı kontrol et ya da yenisini ekle."
    if code in (500, 502, 503, 504) or "unavailable" in low or "overloaded" in low:
        return "Yapay zeka servisi şu an yoğun. Birkaç saniye sonra tekrar dener misin?"
    if "timeout" in low or "timed out" in low or name in ("Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout"):
        return "Yanıt çok gecikti. İnternet yavaş olabilir; birazdan tekrar dene."
    if (name in ("ConnectionError", "ConnectError", "gaierror", "ConnectionResetError", "ConnectionRefusedError")
            or "getaddrinfo" in low or "name resolution" in low or "network" in low or "connection" in low):
        return "İnternete ulaşamıyorum. Bağlantını kontrol eder misin?"
    return ("Bu komutu yaparken bir sorun çıktı. “Sistemi kontrol et” dersen neyin bozuk olduğuna bakayım.")
'''
new_explain = '''def explain(e: BaseException) -> str:
    """Komut sırasında çıkan hatayı ortak failure policy ile açıklar."""
    from modules import failure_policy
    return failure_policy.explain(e)
'''
replace('modules/diagnose.py', old_explain, new_explain)

account = Path('modules/account_tools.py')
account_text = account.read_text(encoding='utf-8')
start = account_text.index('def _network_unavailable(exc):')
end = account_text.index('\n\ndef ', start + 5)
old_network = account_text[start:end]
new_network = "def _network_unavailable(exc):\n    from modules import failure_policy\n    return failure_policy.network_unavailable(exc)"
if old_network != new_network:
    account.write_text(account_text[:start] + new_network + account_text[end:], encoding='utf-8')

# Durable planner hata sınıfını kaydeder; mevcut recovery davranışını değiştirmez.
replace(
    'modules/goal_executor.py',
    "from modules import goal_tools, llm, privacy, requests_state, task_tools\n",
    "from modules import failure_policy, goal_tools, llm, privacy, requests_state, task_tools\n",
)
replace(
    'modules/goal_executor.py',
    "            job.setdefault('feedback',[]).append(privacy.redact(str(exc),force=True)[:1600]);_save(job)\n            if isinstance(exc,RuntimeError):\n",
    "            job.setdefault('feedback',[]).append(privacy.redact(str(exc),force=True)[:1600])\n            job.setdefault('failures',[]).append(failure_policy.snapshot(exc,context='planner'));job['failures']=job['failures'][-20:];_save(job)\n            if isinstance(exc,RuntimeError):\n",
)

# Öğrenilen davranış kuralları sorgu kapsamına göre yüklenir; query=None geriye uyumlu olarak hepsini verir.
old_rules = '''def rules_prompt(profile) -> str:
    # Eski sürümlerde yanlışlıkla "Pazartesi hatırlatacağım" gibi zamana bağlı vaatler kural olarak
    # kaydedilmiş olabilir. Bunları silmeden prompttan çıkar; gerçek hatırlatma motoru kullanılmalı.
    rs = [r for r in rules(profile) if not is_time_reminder_rule(r)]
    if not rs:
        return ""
    return ("Kullanıcının sana öğrettiği kurallar (her zaman uy, diğer talimatlarla çelişirse bunlar geçerli): "
            + " ".join(f"{i}) {r}" for i, r in enumerate(rs, 1)))
'''
new_rules = '''_RULE_SCOPE_PATTERNS = {
    'research': re.compile(r'\b(haber|araştır|arastir|kaynak|yayın|yayin|doğrula|dogrula|güncel|guncel|web)\w*', re.I),
    'pc': re.compile(r'\b(excel|ayar|bluetooth|uygulama|windows|pc|masaüst|masaust|hücre|hucre|parlak|ses)\w*', re.I),
    'communication': re.compile(r'\b(mail|e-posta|eposta|mesaj|gönder|gonder|alıcı|alici|whatsapp|telegram)\w*', re.I),
    'project': re.compile(r'\b(jarvis|kod|github|git|test|proje|repo|branch|commit)\w*', re.I),
}


def rule_scope(text: str) -> str:
    low = _low(_clean(text))
    for scope, pattern in _RULE_SCOPE_PATTERNS.items():
        if pattern.search(low):
            return scope
    return 'global'


def query_scopes(query: str) -> set[str]:
    low = _low(_clean(query))
    scopes = {'global'}
    for scope, pattern in _RULE_SCOPE_PATTERNS.items():
        if pattern.search(low):
            scopes.add(scope)
    return scopes


def rules_prompt(profile, query=None) -> str:
    # query=None eski çağrılar için bütün davranış kurallarını verir. Gerçek sorgu verildiğinde yalnız global
    # ve o işle ilgili kapsamlar yüklenir; zamana bağlı vaatler hiçbir zaman davranış kuralı olmaz.
    rs = [r for r in rules(profile) if not is_time_reminder_rule(r)]
    if query is not None:
        scopes = query_scopes(query)
        rs = [r for r in rs if rule_scope(r) in scopes]
    if not rs:
        return ""
    return ("Kullanıcının sana öğrettiği ilgili davranış kuralları (diğer talimatlarla çelişirse bunlar geçerli): "
            + " ".join(f"{i}) {r}" for i, r in enumerate(rs, 1)))
'''
replace('modules/learning.py', old_rules, new_rules)

# Kişiselleştirme sorguya göre kural yükler ve güncel veri için yanlış 'internet yok' iddiası üretmez.
replace(
    'modules/personalization.py',
    '            "İnternete erişimin yok: güncel fiyat, haber gibi konularda bilmediğini söyle, rakam uydurma.",\n',
    '            "Güncel fiyat, haber ve benzeri dış veriyi tahmin etme; bu istekler araçlı görev yoluna yönlendirilir.",\n',
)
replace(
    'modules/personalization.py',
    "            rp = learning.rules_prompt(self)\n",
    "            rp = learning.rules_prompt(self, query)\n",
)

# Açılış: GitHub ağı ana pencereyi bloklamaz; fazlar ölçülür.
replace(
    'gui.py',
    "import os\nimport sys\nimport tkinter as tk\n",
    "import os\nimport sys\nimport threading\nimport tkinter as tk\nfrom modules import startup_metrics\n",
)
old_update = '''# GitHub ana dalı: açılışta yalnız kontrol edilir; otomatik kurulum/üzerine yazma yoktur.
if __name__ == "__main__" and "--guncellemesiz" not in sys.argv:
    try:
        import updater
        _upd = updater.check(apply_now=False)
        if _upd:
            print("[Güncelleme]", _upd)  # yalnız bildirim; dosya değiştirilmez
    except Exception as _exc:             # noqa: BLE001 - güncelleme olmazsa eski sürümle devam
        _record_failure('gui.py:<module>')
        print(f"[Uyarı] Güncelleme denetlenemedi: {type(_exc).__name__}")
'''
new_update = '''# GitHub ana dalı açılışı bloklamaz; kontrol arka planda yalnız bildirim üretir.
def _check_updates_background() -> None:
    try:
        import updater
        update = updater.check(apply_now=False)
        if update:
            print("[Güncelleme]", update)
    except Exception as exc:              # noqa: BLE001 - güncelleme olmazsa eski sürümle devam
        _record_failure('gui.py:_check_updates_background')
        print(f"[Uyarı] Güncelleme denetlenemedi: {type(exc).__name__}")


def _start_update_check() -> None:
    if __name__ == "__main__" and "--guncellemesiz" not in sys.argv:
        threading.Thread(target=_check_updates_background, name='jarvis-update-check', daemon=True).start()
'''
replace('gui.py', old_update, new_update)
replace(
    'gui.py',
    "def main() -> None:\n    try:\n        import web\n",
    "def main() -> None:\n    startup_metrics.mark('web_import_start')\n    try:\n        import web\n        startup_metrics.mark('web_imported')\n",
)
replace(
    'gui.py',
    "    web.main()\n",
    "    _start_update_check()\n    startup_metrics.mark('web_main_start')\n    web.main()\n",
)
replace(
    'web.py',
    "    open_window(url)\n    import release_guard\n",
    "    open_window(url)\n    from modules import startup_metrics\n    startup_metrics.ready('window_open')\n    import release_guard\n",
)
