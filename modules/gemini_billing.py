"""Read-only key/project billing inspection; never a free-quota guarantee."""
import re
from config import DATA_DIR
from modules import llm, privacy, requests_state

SCOPES = ['https://www.googleapis.com/auth/cloud-platform.read-only',
          'https://www.googleapis.com/auth/cloud-billing.readonly']
TOKEN = DATA_DIR / 'gemini_billing_token.json'


def _record_failure(context):
    from modules import google_api
    google_api._record_failure(context, credential_error=True)


def _session(interactive):
    from google.auth.transport.requests import AuthorizedSession
    from modules import google_api
    return AuthorizedSession(google_api._creds(TOKEN, SCOPES, interactive=interactive))


class _ReadFailure(ValueError):
    def __init__(self, status):self.status=status


def verify(owner, api_key, *, interactive=False):
    """Derive the inspected project from this exact key. No generation or writes to Google."""
    if not owner or owner != llm.current_user():
        raise PermissionError('İşlem sahibi aktif kullanıcıyla eşleşmeli.')
    if privacy.mode() in ('yerel','gizli'):
        raise PermissionError('Yerel/gizli modda bulut hesap kontrolü kapalı.')
    if not isinstance(api_key,str) or not api_key.strip():
        return {'state':'unverified','reason_code':'PROVIDER_CONFIGURATION_REQUIRED'}
    requests_state.check()
    session = None
    try:
        session = _session(interactive)
        def read(url, **kwargs):
            requests_state.check()
            response=session.get(url,timeout=(5,15),allow_redirects=False,**kwargs)
            if response.status_code != 200:raise _ReadFailure(response.status_code)
            data=response.json()
            if not isinstance(data,dict):raise ValueError('invalid response')
            return data
        key=read('https://apikeys.googleapis.com/v2/keys:lookupKey',params={'keyString':api_key.strip()})
        match=re.fullmatch(r'projects/([0-9]+)/locations/global',str(key.get('parent','')))
        if not match or not re.fullmatch(re.escape(match[0])+r'/keys/[A-Za-z0-9_-]+',str(key.get('name',''))):
            raise ValueError('invalid key identity')
        number=match[1]
        project=read('https://cloudresourcemanager.googleapis.com/v3/projects/'+number)
        pid=project.get('projectId')
        if project.get('name') != 'projects/'+number or not isinstance(pid,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',pid):
            raise ValueError('project identity mismatch')
        billing=read('https://cloudbilling.googleapis.com/v1/projects/'+pid+'/billingInfo')
        enabled=billing.get('billingEnabled')
        if billing.get('projectId') != pid or type(enabled) is not bool:raise ValueError('billing identity missing')
        requests_state.check()
        return {'state':'billing_enabled' if enabled else 'billing_disabled','project_id':pid,'billing_enabled':enabled}
    except requests_state.Cancelled:
        raise
    except _ReadFailure as exc:
        code={401:'PROVIDER_ACCOUNT_AUTH_REQUIRED',403:'PROVIDER_ACCOUNT_ACCESS_REQUIRED',429:'PROVIDER_ACCOUNT_RATE_LIMITED'}.get(exc.status,'PROVIDER_BILLING_CHECK_FAILED')
        return {'state':'unverified','reason_code':code,'http_status':exc.status}
    except PermissionError:
        return {'state':'unverified','reason_code':'PROVIDER_ACCOUNT_AUTH_REQUIRED'}
    except Exception:
        _record_failure('modules/gemini_billing.py:verify')
        return {'state':'unverified','reason_code':'PROVIDER_BILLING_CHECK_FAILED'}
    finally:
        if session is not None:session.close()


# A short account snapshot, not an atomic price/quota guarantee.
import hashlib
import math
import threading
import time

RECHECK_SECONDS = 30
_lock = threading.RLock()
_verified = {}


def _receipt_path(owner, tier):
    from config import DATA_DIR
    if not isinstance(owner,str) or not re.fullmatch(r'[\w-]{1,100}',owner):
        raise PermissionError('Geçerli kullanıcı gerekli.')
    if tier not in ('free','paid'):raise ValueError('Geçersiz Gemini katmanı.')
    return DATA_DIR / 'gemini_billing' / owner / (tier+'.json')


def _fingerprint(owner, key):
    return hashlib.sha256((owner+'\0'+key).encode('utf-8')).hexdigest()


def receipt(owner, api_key, *, tier='free'):
    """Read only; no OAuth, network or legacy migration in status queries."""
    from modules.publish_services import _read_private_json
    path=_receipt_path(owner,tier)
    if not isinstance(api_key,str) or not api_key or not path.exists():return None
    try:
        row=_read_private_json(path,migrate=False)
        if not isinstance(row,dict) or row.get('owner')!=owner or row.get('tier')!=tier or row.get('fingerprint')!=_fingerprint(owner,api_key):return None
        at=row.get('checked_at');result=row.get('result')
        if type(at) not in (int,float) or not math.isfinite(at) or at<=0 or not isinstance(result,dict):return None
        state=result.get('state')
        if state not in ('billing_disabled','billing_enabled','unverified'):return None
        if state!='unverified':
            if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',str(result.get('project_id',''))):return None
            if type(result.get('billing_enabled')) is not bool or result['billing_enabled']!=(state=='billing_enabled'):return None
        return row
    except (OSError,ValueError,TypeError):return None


def check(owner, api_key, *, tier='free', interactive=False, force=False):
    """Persist an exact-key result; restart always requires a fresh Google check."""
    from modules.publish_services import _write_private_json
    if not owner or owner!=llm.current_user():raise PermissionError('Aktif kullanıcı değişmiş.')
    if privacy.mode() in ('yerel','gizli'):raise PermissionError('Bulut hesap kontrolü kapalı.')
    path=_receipt_path(owner,tier)
    if not isinstance(api_key,str) or not api_key.strip():return {'state':'unverified','reason_code':'PROVIDER_CONFIGURATION_REQUIRED'}
    with _lock:
        identity=(str(path),_fingerprint(owner,api_key));old=receipt(owner,api_key,tier=tier)
        if not force and old and _verified.get(identity)==old['checked_at'] and 0<=time.time()-old['checked_at']<RECHECK_SECONDS:return old['result']
        _verified.pop(identity,None)
        result=verify(owner,api_key,interactive=interactive)
        row={'owner':owner,'tier':tier,'fingerprint':identity[1],'checked_at':time.time(),'result':result}
        try:_write_private_json(path,row)
        except Exception:
            _record_failure('modules/gemini_billing.py:receipt_save')
            return {'state':'unverified','reason_code':'PROVIDER_BILLING_RECEIPT_SAVE_FAILED'}
        _verified[identity]=row['checked_at']
        return result


def require_free(owner, api_key):
    from modules.failure_policy import ProviderExhaustedError
    result=check(owner,api_key)
    if result.get('state')!='billing_disabled':
        code='PROVIDER_BILLING_ENABLED' if result.get('state')=='billing_enabled' else result.get('reason_code','PROVIDER_BILLING_UNVERIFIED')
        raise ProviderExhaustedError('Gemini ücretsiz projesinde faturalamanın kapalı olduğu doğrulanamadı. Faturalamayı kontrol et.',reason_code=code,recovery_class='user_action_required')
    return result
