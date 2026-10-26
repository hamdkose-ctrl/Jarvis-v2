"""Real Playwright browser, isolated owner profile, bounded declarative actions."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
import uuid
from config import DATA_DIR
from modules import privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

STORE = DATA_DIR / 'browser_agent'
_LOCK = threading.RLock()
_ALLOWED = {'goto','read','click','fill','select','press','screenshot'}


def _root(owner):
    if not re.fullmatch(r'[\w-]{1,100}', owner or ''): raise ValueError('Kullanıcı geçersiz.')
    root = STORE / owner; root.mkdir(parents=True,exist_ok=True); return root


def _url(url):
    parsed = urlsplit(str(url))
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Yalnız http/https adresi kullanılır; adres içinde şifre kullanılamaz.')
    return url


def _domain(page):
    return (urlsplit(str(page.url)).hostname or '').casefold()


def _digest(page):
    return hashlib.sha256((page.url+'\n'+page.title()+'\n'+page.locator('body').inner_text()[:16000]).encode()).hexdigest()


def snapshot(page):
    # The model receives visible page data, never scripts, cookies or password values.
    return {'url':page.url,'title':page.title(),'text':page.locator('body').inner_text()[:12000],
        'controls':page.locator('a,button,input,textarea,select').evaluate_all('''els => els.slice(0,100).map(e => ({tag:e.tagName.toLowerCase(),id:e.id,name:e.name||'',type:e.type||'',text:(e.innerText||e.getAttribute('aria-label')||e.placeholder||'').slice(0,150),href:e.tagName==='A'?e.href:''}))''')}


def _target(page, selector):
    if not isinstance(selector,str) or not selector or len(selector)>400: raise ValueError('Seçici geçersiz.')
    item = page.locator(selector)
    if item.count()!=1: raise ValueError('Hedef tek bir öğeye karşılık gelmeli.')
    if not item.is_visible(): raise ValueError('Hedef görünür değil.')
    return item


def _signature(item):
    return item.evaluate("e => JSON.stringify({tag:e.tagName,type:e.type||'',id:e.id,name:e.name||'',text:(e.innerText||e.getAttribute('aria-label')||e.placeholder||'').slice(0,150),href:e.href||'',formAction:e.formAction||e.form?.action||'',formMethod:e.formMethod||e.form?.method||''})")


def _permission_name(action, item=None):
    """Sınıflandırıcıya yalnız işlem etiketi/DOM kimliği gider; fill değeri asla gitmez."""
    parts=[]
    if item is not None:
        try:
            data=json.loads(_signature(item))
        except (TypeError,ValueError,AttributeError):
            data={}
        label=next((data.get(k) for k in ('text','name','id') if isinstance(data.get(k),str) and data.get(k).strip()),'')
        if label: parts.append(label)
        field_type=data.get('type')
        if isinstance(field_type,str) and field_type.casefold()=='password': parts.append('password')
        if not parts:
            for key in ('tag','type','id','name'):
                value=data.get(key)
                if isinstance(value,str) and value.strip(): parts.append(value)
    if not parts:
        for key in ('op','selector','key'):
            value=action.get(key)
            if isinstance(value,str) and value.strip(): parts.append(value)
    return ' '.join(parts)[:1500]


def _permission_decision(owner, page, action, item=None, *, audit=True):
    """Tarayıcı adımını ortak kapıdan geçirir; tanınmayan ad mevcut politikayı değiştirmez."""
    try:
        from modules import permission_audit, permission_classify, permission_gate, permission_policy
        target=_domain(page)
        kind,known=permission_classify.classify_detail('browser',_permission_name(action,item),target)
        if known:
            # Browser grants cannot weaken today's mandatory interactive approval; only DENY may tighten it.
            result=permission_gate.decide({'class':kind,'target':target,'via':'browser'}, {}, time.time())
            decision,reason=result['decision'],result['reason']
        else:
            decision,reason='allow','Tanınmayan ad; mevcut tarayıcı onay politikası geçerli.'
        decision,reason=permission_policy.apply(owner,'browser',kind,decision,reason)
        if decision not in ('allow','ask','deny') or not isinstance(reason,str):
            raise ValueError('Geçersiz izin kararı.')
        if audit:
            permission_audit.record(owner,decision,kind,target,'browser',reason)
    except Exception:
        _record_failure('modules/browser_agent.py:permission_gate')
        raise ValueError('İzin denetimi tamamlanamadı; tarayıcı işlemi yapılmadı.') from None
    if decision=='deny':
        raise ValueError(' '.join(reason.split())[:200] or 'Bu tarayıcı işlemi izin politikası nedeniyle yapılmadı.')
    return {'decision':decision,'class':kind,'reason':reason,'target':target}


def _permission_preview(owner,page,actions,first_item,*,audit=True):
    asks=[]
    for index,action in enumerate(actions):
        result=_permission_decision(owner,page,action,first_item if index==0 else None,audit=audit)
        if result['decision']=='ask' and result['reason'] not in asks:
            asks.append(result['reason'])
    return asks


def _sensitive(action, item):
    # A link may have event handlers or a GET endpoint with side effects.
    # Every interactive step is included in the concrete approval preview.
    return action['op'] in ('click','fill','select','press')


def validate(actions, *, read_only=False):
    if not isinstance(actions,list) or not 1<=len(actions)<=20: raise ValueError('1–20 tarayıcı adımı gerekli.')
    if not isinstance(read_only,bool): raise ValueError('Salt-okunur modu geçersiz.')
    result=[]
    for a in actions:
        if not isinstance(a,dict) or a.get('op') not in _ALLOWED: raise ValueError('Tarayıcı aracı geçersiz.')
        a=dict(a)
        if read_only:
            from modules import browser_readonly
            browser_readonly.assert_readonly_action(a)
            if a['op'] not in ('goto','read'):
                raise ValueError('Salt-okunur tarayıcı modunda yalnız goto ve read adımları kullanılabilir.')
        if a['op']=='goto': _url(a.get('url',''))
        if a['op'] in ('click','select','press') and not (a.get('expect_text') or a.get('expect_url')):
            raise ValueError('Düğme/tuş/seçim işlemi için beklenen metin veya URL doğrulaması gerekli.')
        if a['op']=='press' and a.get('key') not in ('Enter','Tab','Escape','ArrowDown','ArrowUp'): raise ValueError('Tuş desteklenmiyor.')
        if len(str(a.get('value',''))) > 10000: raise ValueError('Alan metni çok uzun.')
        result.append(a)
    return result


def _save_pending(root, page, actions, item, permission_asks=None):
    token=uuid.uuid4().hex[:12]
    pending={'id':token,'created':time.time(),'url':page.url,'digest':_digest(page),
             'signature':_signature(item),'actions':actions}
    path=root/'pending.json'; path.write_text(json.dumps(pending,ensure_ascii=False),encoding='utf-8')
    note=''
    if permission_asks:
        note=' İzin kapısı onay notu: '+'; '.join(permission_asks)+'.'
    return {'state':'approval','id':token,'action':actions[0], 'url':page.url,
            'message':f"İşlem planı hazır: {json.dumps(actions,ensure_ascii=False)}.{note} Bu planı uygulamak için ‘tarayıcı onayla {token}’, vazgeçmek için ‘tarayıcı iptal’ yaz."}


def _execute(page, root, actions, approved=None, *, owner=None, read_only=False):
    log=[]
    plan_approved=False
    explicit_owner=owner is not None
    owner=owner or root.name
    for i,a in enumerate(validate(actions,read_only=read_only)):
        requests_state.check()
        op=a['op']; item=None
        if op in ('click','fill','select','press'):
            item=_target(page,a.get('selector'))
            sensitive=_sensitive(a,item)
            if item.get_attribute('type')=='password': raise ValueError('Şifreyi açılan tarayıcıda kendin gir; sohbet/model şifre alanını doldurmaz.')
            if sensitive and not plan_approved and approved is None:
                permission_asks=_permission_preview(owner,page,actions[i:],item,audit=explicit_owner)
                return {**_save_pending(root,page,actions[i:],item,permission_asks),'steps':log,'page':snapshot(page)}
            _permission_decision(owner,page,a,item,audit=explicit_owner)
            if sensitive and not plan_approved:
                if approved['digest']!=_digest(page) or approved['signature']!=_signature(item):
                    raise ValueError('Sayfa veya hedef değişmiş; yeni işlem önizlemesi gerekli.')
                plan_approved=True  # The displayed remainder is the exact approved plan.
        else:
            _permission_decision(owner,page,a,audit=explicit_owner)
        before_url=page.url
        before_text=page.locator('body').inner_text() if op in ('click','press') else ''
        if op=='goto': page.goto(_url(a['url']),wait_until='domcontentloaded',timeout=25000)
        elif op=='read': pass
        elif op=='click': item.click(timeout=10000)
        elif op=='fill':
            item.fill(str(a.get('value','')),timeout=10000)
            if item.input_value()!=str(a.get('value','')): raise ValueError('Alan değeri doğrulanamadı.')
        elif op=='select': item.select_option(str(a.get('value','')),timeout=10000)
        elif op=='press': item.press(a['key'],timeout=10000)
        elif op=='screenshot': pass
        page.wait_for_timeout(150)
        if a.get('expect_url') and a['expect_url'] != page.url: raise ValueError('Beklenen adres doğrulanamadı.')
        if a.get('expect_text') and a['expect_text'] not in page.locator('body').inner_text(): raise ValueError('Beklenen metin doğrulanamadı.')
        if op in ('click','press') and page.url==before_url and not (a.get('expect_text') and a['expect_text'] not in before_text):
            raise ValueError('İşlem uygulandı fakat beklenen yeni sonuç doğrulanamadı; otomatik tekrar uygulanmadı.')
        log.append({'op':op,'url':page.url,'verified':bool(a.get('expect_text') or a.get('expect_url') or op in ('read','goto','fill','screenshot'))})
    result={'state':'done','steps':log,'page':snapshot(page)}
    if not read_only:
        path=root/('screen-'+uuid.uuid4().hex[:12]+'.png'); page.screenshot(path=str(path),full_page=False)
        result['image']=str(path)
    return result


def run(owner, actions=None, approval=None, *, headless=False, read_only=False):
    with _LOCK:
        return _run(owner,actions,approval,headless=headless,read_only=read_only)


def _run(owner, actions=None, approval=None, *, headless=False, read_only=False):
    if blocked:=privacy.blocked('web'): return {'state':'blocked','message':blocked}
    root=_root(owner)
    pending=None
    if not approval and (root/'pending.json').exists():
        raise ValueError('Önce bekleyen tarayıcı planını onayla veya tarayıcı iptal yaz.')
    if approval:
        path=root/'pending.json'
        try: pending=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError): raise ValueError('Bekleyen tarayıcı işlemi yok.')
        if pending['id']!=approval or time.time()-pending['created']>600: raise ValueError('Onay eşleşmiyor veya süresi dolmuş.')
        actions=pending['actions']
    actions=validate(actions,read_only=read_only)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'state':'unavailable','message':'Tarayıcı ajanını hazırlamak için Jarvis kökündeki kurulum.bat dosyasını çalıştır.'}
    requests_state.check()
    with _LOCK, sync_playwright() as pw:
        try:
            context=pw.chromium.launch_persistent_context(str(root/'profile'),headless=headless,accept_downloads=False)
        except Exception:
            _record_failure('modules/browser_agent.py:run')
            return {'state':'unavailable','message':'Chromium açılamadı. kurulum.bat ile kurulumu onar; ayrıntı tanılama kaydında.'}
        try:
            page=context.pages[0] if context.pages else context.new_page()
            if pending:
                page.goto(pending['url'],wait_until='domcontentloaded',timeout=25000)
                # Consume before any effect: a retry must never send/submit twice.
                (root/'pending.json').unlink()
            result=_execute(page,root,actions,pending,owner=owner,read_only=read_only)
            privacy.audit('tarayıcı ajanı',result['state'])
            return result
        finally: context.close()


def cancel(owner):
    with _LOCK:
        (_root(owner)/'pending.json').unlink(missing_ok=True)
    return 'Bekleyen tarayıcı işlemi iptal edildi.'


def render(result):
    state=result['state']
    text=result.get('message','')
    if result.get('page'):
        page=result['page']; text+='\n\n'+page['title']+'\n'+page['url']+'\n\n'+page['text'][:9000]
    if result.get('image'):
        data=base64.b64encode(Path(result['image']).read_bytes()).decode()
        text+='\n\n![Tarayıcı sonucu](data:image/png;base64,'+data+')'
    return f'Tarayıcı: {state}\n'+text


def handle(owner, command):
    c=command.casefold().strip()
    if c=='tarayıcı iptal': return cancel(owner)
    if c.startswith('tarayıcı onayla '):
        try: return render(run(owner,approval=command.strip().split()[-1]))
        except (ValueError,RuntimeError) as exc: return str(exc)
    return None
