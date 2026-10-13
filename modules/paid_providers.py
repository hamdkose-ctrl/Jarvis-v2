"""Optional, explicitly selected OpenAI/Claude adapters; no automatic paid fallback."""
from __future__ import annotations
import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import requests
from config import DATA_DIR
from modules import privacy, requests_state

PROVIDERS = {'openai':('OpenAI','https://api.openai.com/v1'),
             'anthropic':('Claude','https://api.anthropic.com/v1')}
_lock = threading.RLock()

class ProviderError(RuntimeError):
    pass

def _paths(owner,provider):
    if provider not in PROVIDERS or not re.fullmatch(r'[a-z0-9]+',owner or ''):
        raise ValueError('Kullanıcı veya sağlayıcı geçersiz.')
    root=DATA_DIR/'keys'
    return root/f'{owner}.{provider}.txt',root/f'{owner}.{provider}.json'

def _atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.provider-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

def key(owner,provider):
    path,_=_paths(owner,provider)
    try:return privacy.unprotect(path.read_text(encoding='utf-8')).strip() if path.exists() else ''
    except (OSError,ValueError):return ''

def settings(owner,provider):
    _,path=_paths(owner,provider)
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return {'model':str(data.get('model') or ''),'workspace':str(data.get('workspace') or ''),'candidate_model':str(data.get('candidate_model') or '')}
    except (OSError,ValueError,AttributeError):return {'model':'','workspace':'','candidate_model':''}

def status(owner,provider):
    return {'key':bool(key(owner,provider)),**settings(owner,provider)}

def configure(owner,provider,*,api_key=None,model=None,workspace=None,candidate_model=None):
    kpath,path=_paths(owner,provider)
    with _lock:
        data=settings(owner,provider)
        for name,value in (('model',model),('workspace',workspace),('candidate_model',candidate_model)):
            if value is None:continue
            if not isinstance(value,str) or len(value)>200 or re.search(r'[\r\n]',value):raise ValueError('Model veya çalışma alanı geçersiz.')
            data[name]=value.strip()
        if api_key is not None:
            if not isinstance(api_key,str) or len(api_key)>1000 or re.search(r'[\r\n]',api_key):raise ValueError('Anahtar biçimi geçersiz.')
            if api_key.strip():
                protected=privacy.protect(api_key.strip())
                if sys.platform=='win32' and not protected.startswith('dpapi:'):
                    raise ValueError('Windows anahtar koruması çalışmadı; anahtar kaydedilmedi.')
                _atomic(kpath,protected)
            else:kpath.unlink(missing_ok=True)
        _atomic(path,json.dumps(data,ensure_ascii=False))
    return status(owner,provider)

def _headers(owner,provider):
    secret=key(owner,provider)
    if not secret:raise ProviderError(PROVIDERS[provider][0]+' anahtarın yok; Bağlantılar bölümünden ekle.')
    if provider=='openai':return {'Authorization':'Bearer '+secret,'Content-Type':'application/json'}
    headers={'x-api-key':secret,'anthropic-version':'2023-06-01','Content-Type':'application/json'}
    workspace=settings(owner,provider)['workspace']
    if workspace:headers['anthropic-workspace-id']=workspace
    return headers

def _request(owner,provider,method,path,body=None):
    requests_state.check()
    if privacy.mode() in ('gizli','yerel'):raise ProviderError('Gizli/yerel modda ücretli bulut sağlayıcısına istek gönderilmez.')
    headers=_headers(owner,provider)
    # A timeout may follow a billed response: do not silently retry a generation request.
    try:
        response=requests.request(method,PROVIDERS[provider][1]+path,headers=headers,json=body,timeout=(5,60),allow_redirects=False)
    except requests.RequestException:
        raise ProviderError(PROVIDERS[provider][0]+' bağlantısı kurulamadı; otomatik tekrar veya sağlayıcı değişimi yapılmadı.') from None
    requests_state.check()
    if response.status_code>=300:
        code=response.status_code
        reasons={400:'Model veya istek desteklenmiyor',401:'Anahtar geçersiz',403:'Bu modele erişim izni yok',
                 404:'Model bulunamadı',429:'Kota, bakiye veya hız sınırı'}
        raise ProviderError(f'{PROVIDERS[provider][0]}: {reasons.get(code,"Sağlayıcı hatası")} (HTTP {code}).')
    try:
        data=response.json()
        if not isinstance(data,dict):raise ValueError('Invalid response')
        return data
    except ValueError:raise ProviderError('Sağlayıcının yanıtı okunamadı.') from None

def models(owner,provider):
    rows=[];after=''
    for _ in range(20):
        suffix='?limit=100'+('&after_id='+after if after else '') if provider=='anthropic' else ''
        data=_request(owner,provider,'GET','/models'+suffix)
        page=data.get('data')
        if not isinstance(page,list):raise ProviderError('Model listesi okunamadı.')
        rows.extend({'id':x['id'],'name':x.get('display_name') or x['id']} for x in page if isinstance(x,dict) and isinstance(x.get('id'),str))
        if provider!='anthropic' or not data.get('has_more'):break
        cursor=data.get('last_id')
        if not isinstance(cursor,str) or not re.fullmatch(r'[\w.-]+',cursor) or cursor==after:raise ProviderError('Model listesinin devamı okunamadı.')
        after=cursor
    return rows

def generate(owner,provider,messages,system,max_tokens,image_path=None):
    model=settings(owner,provider)['model']
    if not model:raise ProviderError('Önce '+PROVIDERS[provider][0]+' modelini Bağlantılar bölümünden seç.')
    messages=[{'role':m['role'],'content':privacy.redact(str(m['content']))} for m in messages]
    system=privacy.redact(system)
    image=None
    if image_path:
        mime=mimetypes.guess_type(str(image_path))[0] or 'image/png'
        if mime not in ('image/png','image/jpeg','image/webp','image/gif'):raise ProviderError('Görüntü biçimi desteklenmiyor.')
        image=(mime,base64.b64encode(Path(image_path).read_bytes()).decode('ascii'))
    if provider=='openai':
        items=[]
        for index,m in enumerate(messages):
            content=[{'type':'input_text','text':m['content']}]
            if image and index==len(messages)-1:content.append({'type':'input_image','image_url':f'data:{image[0]};base64,{image[1]}'})
            # Historical assistant text is replayed as a plain easy-input message.
            items.append({'role':m['role'],'content':content if image and index==len(messages)-1 else m['content']})
        body={'model':model,'input':items,'max_output_tokens':max_tokens,'store':False}
        if system:body['instructions']=system
        data=_request(owner,provider,'POST','/responses',body)
        if data.get('status')!='completed' or data.get('error'):
            raise ProviderError('OpenAI yanıtı tamamlanmadı; başarılı sayılmadı.')
        text=''.join(part.get('text','') for item in data.get('output',[]) if item.get('type')=='message'
                     for part in item.get('content',[]) if part.get('type')=='output_text')
    else:
        if image:
            messages[-1]['content']=[{'type':'image','source':{'type':'base64','media_type':image[0],'data':image[1]}},
                                      {'type':'text','text':messages[-1]['content']}]
        body={'model':model,'messages':messages,'max_tokens':max_tokens}
        if system:body['system']=system
        data=_request(owner,provider,'POST','/messages',body)
        if data.get('stop_reason') not in ('end_turn','stop_sequence'):
            raise ProviderError('Claude yanıtı tamamlanmadı; başarılı sayılmadı.')
        text=''.join(x.get('text','') for x in data.get('content',[]) if x.get('type')=='text')
    if not text.strip():raise ProviderError('Sağlayıcı metin yanıtı vermedi.')
    return text
