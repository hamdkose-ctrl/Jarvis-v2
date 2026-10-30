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
            if response.status_code != 200:raise ValueError('response rejected')
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
    except PermissionError:
        return {'state':'unverified','reason_code':'PROVIDER_ACCOUNT_AUTH_REQUIRED'}
    except Exception:
        _record_failure('modules/gemini_billing.py:verify')
        return {'state':'unverified','reason_code':'PROVIDER_BILLING_CHECK_FAILED'}
    finally:
        if session is not None:session.close()
