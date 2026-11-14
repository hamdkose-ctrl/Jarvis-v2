"""Official outbound adapters. Invoked only through the durable outbox."""
import base64
import hashlib
import json
import os
import tempfile
import threading
from email.message import EmailMessage
import re
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit
from config import DATA_DIR
from modules import privacy, requests_state, service_store, task_results
from modules.diagnostics import record_failure as _diagnostic_failure

_credential_lock = threading.RLock()
_UNSET = object()
_LOGIN_REQUIRED = 'Bağlantı bilgileri okunamadı; lütfen yeniden giriş yap.'


def _credential_path(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
        raise PermissionError(_LOGIN_REQUIRED)
    return path


def _write_private_json(path, data, *, max_bytes=131072, expected=_UNSET):
    """Verify an encrypted temporary copy BEFORE atomically replacing plaintext.

    No plaintext backup/temp is created. Failures before os.replace leave the
    original bytes intact. Expected bytes also guard a concurrent credential edit.
    """
    path = _credential_path(path)
    temporary = None
    with _credential_lock:
        if expected is _UNSET:
            expected = path.read_bytes() if path.exists() else None
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if not isinstance(data, dict) or len(encoded.encode('utf-8')) > max_bytes:
            raise ValueError('Bağlantı yapılandırması geçersiz.')
        protected = privacy.protect(encoded)
        if not isinstance(protected, str) or not protected.startswith(('dpapi:', 'b64:')):
            raise OSError('Bağlantı bilgileri korumalı kaydedilemedi.')
        if privacy.sys.platform == 'win32' and not protected.startswith('dpapi:'):
            raise OSError('Windows bağlantı koruması kullanılamadı.')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, name = tempfile.mkstemp(prefix='.credential-', dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(protected)
                handle.flush()
                os.fsync(handle.fileno())
            if privacy.unprotect(temporary.read_text(encoding='utf-8')) != encoded:
                raise OSError('Bağlantı koruması geri okuma kontrolünden geçmedi.')
            _credential_path(path)
            if (path.read_bytes() if path.exists() else None) != expected:
                raise OSError('Bağlantı dosyası işlem sırasında değişti; üzerine yazılmadı.')
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass  # Never mask a successful atomic commit.
        return protected.encode('utf-8')


def _read_private_json(path, *, max_bytes=131072, migrate=True, with_snapshot=False):
    """Plain JSON remains usable if safe migration cannot be completed."""
    with _credential_lock:
        protected = False
        try:
            path = _credential_path(path)
            with path.open('rb') as handle:
                raw = handle.read(max_bytes * 4 + 4097)
            if len(raw) > max_bytes * 4 + 4096:
                raise ValueError('size')
            stored = raw.decode('utf-8-sig').strip()
            protected = stored.startswith(('dpapi:', 'b64:'))
            text = privacy.unprotect(stored) if protected else stored
            if not isinstance(text, str) or len(text.encode('utf-8')) > max_bytes:
                raise ValueError('size')
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError('type')
        except Exception:
            _record_failure('modules/publish_services.py:credential_read')
            # Never log parser/DPAPI exception values or credential-bearing URLs.
            if not protected:
                raise ValueError('Bağlantı yapılandırması okunamadı veya geçersiz.') from None
            raise PermissionError(_LOGIN_REQUIRED) from None
        if migrate and (not protected or (stored.startswith('b64:') and privacy.sys.platform == 'win32')):
            try:
                raw = _write_private_json(path, data, max_bytes=max_bytes, expected=raw)
            except Exception:
                _record_failure('modules/publish_services.py:credential_migration')
                pass  # Original login remains usable; retry migration on next read.
        return (data, raw) if with_snapshot else data


def _record_failure(context):
    # Telegram carries its credential in the URL path. Ordinary URL redaction
    # masks query parameters only, so replace the exception before diagnostics.
    import sys
    kind=sys.exc_info()[0]
    try:
        raise RuntimeError('Servis taşıma hatası: '+(kind.__name__ if kind else 'unknown')) from None
    except RuntimeError:
        _diagnostic_failure(context)

OPERATIONS = {'gmail': 'send_mail', 'telegram': 'send_message', 'whatsapp': 'send_message',
              'youtube': 'upload_video', 'instagram': 'publish_image'}


class Preparing(RuntimeError):
    """A known container exists, but no publication was attempted yet."""
GOOGLE = {'gmail': ('gmail', 'v1', 'https://www.googleapis.com/auth/gmail.send'),
          'youtube': ('youtube', 'v3', 'https://www.googleapis.com/auth/youtube.upload'),
          'youtube_reply': ('youtube','v3','https://www.googleapis.com/auth/youtube.force-ssl')}

_APPROVED_CONNECTION = ContextVar('outbox_approved_connection',default=None)


def _connection_digest(service, data):
    # Access-token refresh/expiry is not an account change. A refresh credential
    # or native connector configuration change IS a new connection generation.
    if service in GOOGLE and data is not None:
        data={key:data.get(key) for key in ('client_id','client_secret','refresh_token')}
    return hashlib.sha256(json.dumps({'service':service,'connection':data},sort_keys=True,
                                     ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def connection_digest(owner, payload):
    """Opaque credential-generation binding, NOT a verified OAuth subject."""
    service_store.identity(owner)
    service=permission_key(payload)
    if service in GOOGLE:
        filename='google_'+service+'_write_token.json'
        path=DATA_DIR/'google_users'/owner/filename
        if not path.exists() and not path.is_symlink():path=DATA_DIR/filename
    else:
        service=payload['service'];path=DATA_DIR/'connector_users'/owner/(service+'.json')
    _credential_path(path)
    data=_read_private_json(path,migrate=False) if path.exists() or path.is_symlink() else None
    return _connection_digest(service,data)


@contextmanager
def approved_connection(owner, payload, digest):
    service=permission_key(payload)
    if service not in GOOGLE:service=payload['service']
    token=_APPROVED_CONNECTION.set((owner,service,digest))
    try:yield
    finally:_APPROVED_CONNECTION.reset(token)


def _check_approved_connection(owner, service, data):
    bound=_APPROVED_CONNECTION.get()
    if bound is not None:
        service_store.identity(owner)
        if (owner,service)!=(bound[0],bound[1]) or _connection_digest(service,data)!=bound[2]:
            raise PermissionError('Onaylanan hesap bağlantısı değişmiş; yeni dış işlem başlatılmadı.')


def permission_key(data):
    return data['service']+('_reply' if data.get('operation')=='reply_comment' else '')


def validate(data):
    if isinstance(data,dict) and 'text_from_task' in data:
        if 'text' in data or not isinstance(data['text_from_task'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,30}',data['text_from_task']):raise ValueError('Gönderim metni tek kaynak görevden gelmeli.')
        validate({k:v for k,v in data.items() if k!='text_from_task'}|{'text':'Kaynak görevden çözülecek'})
        return dict(data)
    if not isinstance(data, dict) or set(data) - {'service','destination','text','subject','file','file_sha256','privacy','image_url','source_task','video_url','media_type','operation','parent_id'}:
        raise ValueError('Gönderim girdisi geçersiz.')
    service, dest = data.get('service'), data.get('destination')
    if not isinstance(service, str) or service not in OPERATIONS or not isinstance(dest, str):
        raise ValueError('Servis ve kesin hedef gerekli.')
    patterns = {'gmail': r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',
                'telegram': r'-?[0-9]{1,20}', 'whatsapp': r'[1-9][0-9]{7,14}',
                'youtube': r'UC[A-Za-z0-9_-]{22}', 'instagram': r'[0-9]{1,30}'}
    if not re.fullmatch(patterns[service], dest):
        raise ValueError('Hedef tam e-posta/hesap kimliği olmalı; kişi adıyla gönderilmez.')
    operation=data.get('operation',OPERATIONS[service])
    if operation=='reply_comment':
        parent=data.get('parent_id')
        pattern=r'[A-Za-z0-9_.-]{1,200}' if service=='youtube' else r'[0-9]{1,30}' if service=='instagram' else ''
        if not pattern or not isinstance(parent,str) or not re.fullmatch(pattern,parent) or set(data)-{'service','destination','operation','parent_id','text'}:raise ValueError('Yorum cevabı girdisi geçersiz.')
        if not isinstance(data.get('text'),str) or not data['text'].strip() or len(data['text'])>2000 or '\x00' in data['text']:raise ValueError('Yorum cevap metni geçersiz.')
        return dict(data)
    if operation!=OPERATIONS[service]:raise ValueError('Bu servis yazma işlemi desteklenmiyor.')
    allowed = {'gmail': {'service','destination','text','subject'},
               'telegram': {'service','destination','text'}, 'whatsapp': {'service','destination','text'},
               'youtube': {'service','destination','file','file_sha256','subject','text','privacy','source_task'},
               'instagram': {'service','destination','text','image_url','video_url','media_type'}}[service]
    allowed.add('operation')
    if set(data) - allowed:
        raise ValueError('Bu serviste desteklenmeyen alan var.')
    for key, limit in (('text', 4096 if service=='telegram' else 2200 if service=='instagram' else 4000 if service=='whatsapp' else 20000), ('subject',100 if service=='youtube' else 200)):
        if key in allowed and (not isinstance(data.get(key),str) or not data[key].strip() or len(data[key])>limit or '\x00' in data[key]):
            raise ValueError('Gönderim metni/başlığı eksik veya çok uzun.')
    if 'subject' in data and any(c in data['subject'] for c in '\r\n'):
        raise ValueError('Başlık tek satır olmalı.')
    if service=='youtube':
        if data.get('privacy') not in ('private','unlisted','public'):
            raise ValueError('Video görünürlüğü açıkça belirtilmeli.')
        if 'source_task' in data:
            if 'file' in data or 'file_sha256' in data or not isinstance(data['source_task'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,30}',data['source_task']):
                raise ValueError('Video için tek doğrulanmış kaynak görev gerekli.')
        elif not isinstance(data.get('file'),str) or not isinstance(data.get('file_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',data['file_sha256']):
            raise ValueError('Video dosyası ve içerik özeti gerekli.')
    if service=='instagram':
        media_type=data.get('media_type','IMAGE')
        if media_type not in ('IMAGE','REELS') or ('image_url' in data)==('video_url' in data) or (media_type=='IMAGE')!=('image_url' in data):raise ValueError('Instagram için tek görsel veya açık REELS video kaynağı gerekli.')
        url=data.get('image_url') if media_type=='IMAGE' else data.get('video_url')
        if not isinstance(url,str) or len(url)>2048:
            raise ValueError('Görselin HTTPS adresi gerekli.')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Görsel adresi kimlik bilgisi içermeyen HTTPS olmalı.')
    return dict(data)


def configuration(owner, service):
    service_store.identity(owner)
    if not isinstance(service, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,40}', service):
        raise ValueError('Bağlantı servisi geçersiz.')
    path=DATA_DIR/'connector_users'/owner/(service+'.json')
    if any(p.is_symlink() for p in (path,path.parent,path.parent.parent)):
        raise ValueError('Bağlantı dosyası sembolik bağ olamaz.')
    if not path.is_file():
        raise PermissionError('Servise ait yerel bağlantı yapılandırması gerekli.')
    data=_read_private_json(path, max_bytes=16000)
    _check_approved_connection(owner,service,data)
    return data


def google_service(service, interactive=False):
    from modules import google_api
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    name, version, scope=GOOGLE[service]
    scopes=[scope]+(['https://www.googleapis.com/auth/youtube.readonly'] if service=='youtube' else [])
    creds=google_api._creds(DATA_DIR/('google_'+service+'_write_token.json'),scopes,interactive)
    bound=_APPROVED_CONNECTION.get()
    if bound is not None:
        _check_approved_connection(bound[0],service,json.loads(creds.to_json()))
    client=AuthorizedHttp(creds,http=httplib2.Http(timeout=google_api._SERVICE_HTTP_TIMEOUT_SECONDS))
    return build(name,version,http=client,cache_discovery=False)


def media_upload(path,mimetype):
    from googleapiclient.http import MediaFileUpload
    return MediaFileUpload(str(path),mimetype=mimetype,resumable=True,chunksize=8*1024*1024)


def _http(url, payload, headers=None):
    import requests
    # Never leak credential-bearing URLs or provider error bodies to diagnostics.
    try:
        response=requests.post(url,json=payload,headers=headers or {},timeout=30,allow_redirects=False)
        response.raise_for_status()
        result=response.json()
    except Exception:
        _record_failure('modules/publish_services.py:http')
        raise RuntimeError('Servis yanıtı alınamadı; dış işlem sonucu belirsiz.') from None
    if not isinstance(result,dict):raise ValueError('Servis JSON yanıtı geçersiz.')
    return result


def send(owner, data, progress, checkpoint=None):
    service_store.identity(owner);requests_state.check()
    data=validate(data)
    if blocked:=privacy.blocked('web'):raise PermissionError(blocked)
    service=data['service']
    if data.get('operation')=='reply_comment':return _reply(owner,data)
    if service=='gmail':
        message=EmailMessage();message['To']=data['destination'];message['Subject']=data['subject'];message.set_content(data['text'])
        raw=base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        svc=google_service('gmail');requests_state.check()
        result=svc.users().messages().send(userId='me',body={'raw':raw}).execute()
        remote=result.get('id') if isinstance(result,dict) else None
    elif service=='telegram':
        config=configuration(owner,service);token=config.get('bot_token')
        if not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token):raise PermissionError('Telegram bot token yapılandırması gerekli.')
        result=_http('https://api.telegram.org/bot'+token+'/sendMessage',{'chat_id':data['destination'],'text':data['text']})
        msg=result.get('result',{})
        if result.get('ok') is not True or not isinstance(msg,dict) or str(msg.get('chat',{}).get('id'))!=data['destination']:
            raise ValueError('Telegram gönderim kaydı hedefle eşleşmiyor.')
        if type(msg.get('message_id')) is not int or msg['message_id']<=0:raise ValueError('Telegram gerçek mesaj kimliği eksik.')
        remote=str(msg['message_id'])
    elif service in ('whatsapp','instagram'):
        config=configuration(owner,service)
        version,token=config.get('api_version'),config.get('access_token')
        if not isinstance(version,str) or not re.fullmatch(r'v[0-9]{1,2}\.0',version) or not isinstance(token,str) or not token:
            raise PermissionError('Meta API sürümü ve erişim izni gerekli.')
        headers={'Authorization':'Bearer '+token}
        base='https://graph.facebook.com/'+version+'/'
        if service=='whatsapp':
            phone=config.get('phone_number_id')
            if not isinstance(phone,str) or not phone.isdigit():raise PermissionError('WhatsApp Business telefon kimliği gerekli.')
            if config.get('allow_service_costs') is not True:raise PermissionError('WhatsApp servis ücretleri için açık yerel yetki gerekli.')
            result=_http(base+phone+'/messages',{'messaging_product':'whatsapp','to':data['destination'],'type':'text','text':{'body':data['text']}},headers)
            messages=result.get('messages',[])
            remote=messages[0].get('id') if isinstance(messages,list) and messages and isinstance(messages[0],dict) else None
        else:
            if config.get('ig_user_id')!=data['destination']:raise PermissionError('Instagram hesabı hedefle eşleşmiyor.')
            container=(checkpoint or {}).get('container_id')
            if container is None:
                body={'caption':data['text']}
                if data.get('media_type')=='REELS':body.update(media_type='REELS',video_url=data['video_url'])
                else:body['image_url']=data['image_url']
                result=_http(base+data['destination']+'/media',body,headers)
                container=result.get('id')
                if not isinstance(container,str) or not container.isdigit():raise ValueError('Instagram hazırlama kaydı eksik.')
                progress({'container_id':container}) # Persist before the publication call.
            if not isinstance(container,str) or not container.isdigit():raise ValueError('Kayıtlı Instagram hazırlama kimliği geçersiz.')
            requests_state.check()
            from modules import social_reads
            status=social_reads._get(base+container+'?fields=status_code',headers)
            if status.get('status_code')=='IN_PROGRESS':raise Preparing('Instagram hazırlama sürüyor; yayın henüz uygulanmadı.')
            if status.get('status_code')!='FINISHED':raise RuntimeError('Instagram hazırlama başarısız; yayın uygulanmadı.')
            result=_http(base+data['destination']+'/media_publish',{'creation_id':container},headers)
            remote=result.get('id')
    else:
        from modules import nxapi
        config=configuration(owner,service)
        if config.get('channel_id')!=data['destination']:raise PermissionError('YouTube kanal yapılandırması hedefle eşleşmiyor.')
        source=Path(data['file']);root=Path(nxapi.FILES_DIR).resolve()
        if source.is_symlink() or root not in source.resolve().parents or source.suffix.lower() not in ('.mp4','.webm','.mov'):
            raise ValueError('Video, Jarvis dosya alanında olmalı.')
        if task_results.file_digest(source)!=data['file_sha256']:raise ValueError('Video dosyası değişmiş.')
        media=media_upload(source,'video/mp4' if source.suffix.lower()=='.mp4' else 'video/webm' if source.suffix.lower()=='.webm' else 'video/quicktime')
        svc=google_service('youtube')
        channels=svc.channels().list(part='id',mine=True).execute()
        if data['destination'] not in [row.get('id') for row in channels.get('items',[])]:
            raise PermissionError('OAuth hesabının YouTube kanalı hedefle eşleşmiyor.')
        request=svc.videos().insert(part='snippet,status',body={
            'snippet':{'title':data['subject'],'description':data['text']},'status':{'privacyStatus':data['privacy']}},media_body=media)
        result=None
        for _ in range(1024):
            requests_state.check();_,result=request.next_chunk(num_retries=0)
            if result is not None:break
        remote=result.get('id') if isinstance(result,dict) else None
    if not isinstance(remote,str) or not remote or len(remote)>300:
        raise ValueError('Servis gerçek sonuç kimliği döndürmedi.')
    return {'service':service,'destination':data['destination'],'remote_id':remote,'scope':'provider_accepted'}


def _reply(owner,data):
    service=data['service'];config=configuration(owner,service)
    if service=='youtube':
        if config.get('channel_id')!=data['destination']:raise PermissionError('Yorum kanal yapılandırması hedefle eşleşmiyor.')
        svc=google_service('youtube_reply')
        channels=svc.channels().list(part='id',mine=True).execute()
        if data['destination'] not in [c['id'] for c in channels.get('items',[])]:raise PermissionError('Yorum OAuth kanalı eşleşmiyor.')
        comments=svc.comments().list(part='snippet',id=data['parent_id']).execute().get('items',[])
        if len(comments)!=1 or comments[0].get('id')!=data['parent_id']:raise ValueError('Cevaplanacak yorum bulunamadı.')
        video_id=comments[0].get('snippet',{}).get('videoId')
        videos=svc.videos().list(part='snippet',id=video_id).execute().get('items',[])
        if len(videos)!=1 or videos[0].get('snippet',{}).get('channelId')!=data['destination']:raise PermissionError('Yorum bu kanala ait videoda değil.')
        requests_state.check()
        result=svc.comments().insert(part='snippet',body={'snippet':{'parentId':data['parent_id'],'textOriginal':data['text']}}).execute()
        if result.get('snippet',{}).get('parentId')!=data['parent_id']:raise ValueError('Yorum cevap kaydı hedefle eşleşmiyor.')
    else:
        from modules import social_reads
        version,token,user=config.get('api_version'),config.get('access_token'),config.get('ig_user_id')
        if user!=data['destination'] or not isinstance(version,str) or not re.fullmatch(r'v[0-9]{1,2}\.0',version) or not isinstance(token,str) or not token:raise PermissionError('Instagram yorum bağlantısı gerekli.')
        base='https://graph.facebook.com/'+version+'/';headers={'Authorization':'Bearer '+token}
        comment=social_reads._get(base+data['parent_id']+'?fields=id,media',headers)
        media_id=comment.get('media',{}).get('id')
        if comment.get('id')!=data['parent_id'] or not isinstance(media_id,str) or not media_id.isdigit():raise ValueError('Yorum medya bağlantısı doğrulanamadı.')
        media=social_reads._get(base+media_id+'?fields=id,owner',headers)
        if str(media.get('owner',{}).get('id'))!=user:raise PermissionError('Yorum başka hesaba ait.')
        requests_state.check();result=_http(base+data['parent_id']+'/replies',{'message':data['text']},headers)
    remote=result.get('id')
    if not isinstance(remote,str) or not remote:raise ValueError('Gerçek cevap kimliği eksik.')
    return {'service':service,'destination':data['destination'],'remote_id':remote,'parent_id':data['parent_id'],'operation':'reply_comment','scope':'provider_accepted'}
