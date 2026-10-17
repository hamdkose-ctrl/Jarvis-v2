from pathlib import Path


def read(path):
    return Path(path).read_text(encoding='utf-8')


def write(path, text):
    Path(path).write_text(text, encoding='utf-8')


def replace_once(path, old, new):
    text = read(path)
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f'{path}: exact replacement not unique ({text.count(old)})')
    write(path, text.replace(old, new, 1))


def replace_region(path, start_marker, end_marker, new_block):
    text = read(path)
    if new_block in text:
        return
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f'{path}: start marker not found: {start_marker!r}')
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise SystemExit(f'{path}: end marker not found: {end_marker!r}')
    write(path, text[:start] + new_block + text[end:])


# 1) Outcome contracts
replace_once('modules/task_results.py', 'import math\n', 'import math\nfrom modules import outcome_contracts\n')
replace_once(
    'modules/task_results.py',
    "    output = dict(output)\n    if output['state'] == 'done':\n        if kind == 'browser':\n            output['image_sha256'] = file_digest(output.get('image', ''))\n        check(kind, output)\n        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence'}\n    return output\n",
    "    output = dict(output)\n    if output['state'] == 'done':\n        if kind == 'browser':\n            output['image_sha256'] = file_digest(output.get('image', ''))\n        output = outcome_contracts.attach(kind, output)\n        check(kind, output)\n        outcome_contracts.validate_metadata(kind, output, legacy_ok=False)\n        output['verification'] = {'version': VERSION, 'agent': kind, 'scope': 'execution_evidence',\n                                  'outcome': output['outcome_contract']['id']}\n    return output\n",
)
replace_once(
    'modules/task_results.py',
    "    checked = check(metadata.get('agent'), output)\n",
    "    checked = check(metadata.get('agent'), output)\n    if metadata.get('outcome') is not None:\n        outcome_contracts.validate_metadata(metadata.get('agent'), output, legacy_ok=False)\n        if metadata['outcome'] != output['outcome_contract']['id']:\n            raise ValueError('Doğrulama kaydı sonuç sözleşmesiyle eşleşmiyor.')\n",
)
replace_once(
    'modules/goal_tools.py',
    'from modules import app_actions, llm, privacy, requests_state, task_agents, task_results, task_tools\n',
    'from modules import app_actions, llm, privacy, requests_state, task_agents, task_results, task_tools, outcome_contracts\n',
)
replace_region(
    'modules/goal_tools.py',
    'def local_result(owner,kind,text,**extra):',
    '\n\ndef verify(output,owner):',
    "def local_result(owner,kind,text,**extra):\n    if not isinstance(text,str) or not text.strip():raise ValueError('Araç boş sonuç döndürdü.')\n    output={'state':'done','text':_text(text),'owner':owner,'local_evidence':kind,**extra}\n    return outcome_contracts.attach(kind,output,local=True)\n",
)
replace_once(
    'modules/goal_tools.py',
    "    if not isinstance(output.get('text'),str) or not output['text'].strip():raise ValueError('Araç sonucu boş.')\n",
    "    if not isinstance(output.get('text'),str) or not output['text'].strip():raise ValueError('Araç sonucu boş.')\n    outcome_contracts.validate_common(output['local_evidence'],output,local=True)\n",
)
replace_once(
    'modules/goal_tools.py',
    "        from modules import router\n        if not router._open_only_request(identity.get('request','')):\n",
    "        if not outcome_contracts.open_only_request(identity.get('request','')):\n",
)
replace_region(
    'modules/router.py',
    'def _open_only_request(text):',
    '\n\ndef classify(command: str, ask: Callable[[str, str], str], *, context=\'\') -> dict:',
    "def _open_only_request(text):\n    \"\"\"Compatibility wrapper; user-outcome policy owns the actual rule.\"\"\"\n    from . import outcome_contracts\n    return outcome_contracts.open_only_request(text)\n",
)

# 2) Failure policy
replace_region(
    'modules/smart_router.py',
    'def failure_kind(exc):',
    '\n\ndef failure_detail(attempt):',
    "def failure_kind(exc):\n    from modules import failure_policy\n    return failure_policy.legacy_kind(exc)\n\n\ndef failure_status(exc):\n    from modules import failure_policy\n    return failure_policy.status_code(exc)\n",
)
replace_region(
    'modules/smart_router.py',
    'def failure_text(exc):',
    '\n\ndef _free_emergency(owner, attempted):',
    "def failure_text(exc):\n    from modules import failure_policy\n    return failure_policy.short_text(exc)\n\n\ndef cooldown(provider, exc):\n    from modules import failure_policy\n    return failure_policy.cooldown_seconds(provider, exc)\n",
)
replace_region(
    'modules/diagnose.py',
    'def explain(e: BaseException) -> str:',
    '\n',
    "def explain(e: BaseException) -> str:\n    \"\"\"Komut sırasında çıkan hatayı ortak failure policy ile açıklar.\"\"\"\n    from modules import failure_policy\n    return failure_policy.explain(e)\n",
)
# diagnose.explain is the last function; the simple region helper above only replaced its signature line if newline is used.
# Normalize the tail explicitly to avoid retaining the old body.
diag = read('modules/diagnose.py')
start = diag.find('def explain(e: BaseException) -> str:')
if start >= 0:
    prefix = diag[:start]
    desired = "def explain(e: BaseException) -> str:\n    \"\"\"Komut sırasında çıkan hatayı ortak failure policy ile açıklar.\"\"\"\n    from modules import failure_policy\n    return failure_policy.explain(e)\n"
    if diag[start:] != desired:
        write('modules/diagnose.py', prefix + desired)

account = read('modules/account_tools.py')
start = account.find('def _network_unavailable(exc):')
end = account.find('\n\ndef ', start + 5)
if start < 0 or end < 0:
    raise SystemExit('modules/account_tools.py: network helper boundaries not found')
network_block = "def _network_unavailable(exc):\n    from modules import failure_policy\n    return failure_policy.network_unavailable(exc)"
if account[start:end] != network_block:
    write('modules/account_tools.py', account[:start] + network_block + account[end:])

replace_once(
    'modules/goal_executor.py',
    'from modules import goal_tools, llm, privacy, requests_state, task_tools\n',
    'from modules import failure_policy, goal_tools, llm, privacy, requests_state, task_tools\n',
)
replace_once(
    'modules/goal_executor.py',
    "            job.setdefault('feedback',[]).append(privacy.redact(str(exc),force=True)[:1600]);_save(job)\n            if isinstance(exc,RuntimeError):\n",
    "            job.setdefault('feedback',[]).append(privacy.redact(str(exc),force=True)[:1600])\n            job.setdefault('failures',[]).append(failure_policy.snapshot(exc,context='planner'));job['failures']=job['failures'][-20:];_save(job)\n            if isinstance(exc,RuntimeError):\n",
)

# 3) Do-first routing
replace_once(
    'modules/router.py',
    '    text = command.strip()\n    low = text.casefold().replace("ı", "i")\n',
    '    text = command.strip()\n    low = text.casefold().replace("ı", "i")\n    from . import work_modes\n    mode = work_modes.classify(text)\n',
)
replace_once(
    'modules/router.py',
    "    if intent not in _INTENTS or (intent == 'chat' and _action_request(text)):\n        if re.fullmatch(r'(?:bunu|onu|şunu|böyle|öyle)\\s+\\S+(?:\\s+et)?[ .!?]*',text.casefold()):\n            return {'intent':'clarify','args':{'question':'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n        if _action_request(text):return {'intent':'task','args':{'request':text}}\n        return {'intent': 'clarify', 'args': {'question': 'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n",
    "    if intent not in _INTENTS or (intent == 'chat' and (_action_request(text) or mode == 'do')):\n        if work_modes.ambiguous_reference(text) or re.fullmatch(r'(?:bunu|onu|şunu|böyle|öyle)\\s+\\S+(?:\\s+et)?[ .!?]*',text.casefold()):\n            return {'intent':'clarify','args':{'question':'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n        if _action_request(text) or mode == 'do':return {'intent':'task','args':{'request':text}}\n        return {'intent': 'clarify', 'args': {'question': 'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}\n",
)
replace_once(
    'modules/personalization.py',
    '            "İnternete erişimin yok: güncel fiyat, haber gibi konularda bilmediğini söyle, rakam uydurma.",\n',
    '            "Güncel fiyat, haber ve benzeri dış veriyi tahmin etme; bu istekler araçlı görev yoluna yönlendirilir.",\n',
)

# 4) Scoped memory
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
    rs = [r for r in rules(profile) if not is_time_reminder_rule(r)]
    if query is not None:
        scopes = query_scopes(query)
        rs = [r for r in rs if rule_scope(r) in scopes]
    if not rs:
        return ""
    return ("Kullanıcının sana öğrettiği ilgili davranış kuralları (diğer talimatlarla çelişirse bunlar geçerli): "
            + " ".join(f"{i}) {r}" for i, r in enumerate(rs, 1)))
'''
replace_region(
    'modules/learning.py',
    'def rules_prompt(profile) -> str:',
    '\n\n# ------------------------------------------------------------------ 2) onaylı hafıza',
    new_rules,
)
replace_once(
    'modules/personalization.py',
    '            rp = learning.rules_prompt(self)\n',
    '            rp = learning.rules_prompt(self, query)\n',
)

# 5) Non-blocking measured startup
replace_once(
    'gui.py',
    'import os\nimport sys\nimport tkinter as tk\n',
    'import os\nimport sys\nimport threading\nimport tkinter as tk\nfrom modules import startup_metrics\n',
)
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
replace_region(
    'gui.py',
    '# GitHub ana dalı: açılışta yalnız kontrol edilir; otomatik kurulum/üzerine yazma yoktur.',
    '\n\n# Komut Merkezi (web arayüzü) tek arayüzdür.',
    new_update,
)
replace_once(
    'gui.py',
    'def main() -> None:\n    try:\n        import web\n',
    "def main() -> None:\n    startup_metrics.mark('web_import_start')\n    try:\n        import web\n        startup_metrics.mark('web_imported')\n",
)
replace_once(
    'gui.py',
    '    web.main()\n',
    "    _start_update_check()\n    startup_metrics.mark('web_main_start')\n    web.main()\n",
)
replace_once(
    'web.py',
    '    open_window(url)\n    import release_guard\n',
    "    open_window(url)\n    from modules import startup_metrics\n    startup_metrics.ready('window_open')\n    import release_guard\n",
)
