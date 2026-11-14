"""Core-owned presentation adoption in existing Profile and SessionState.

No classifier, model call, independent store, permission or effect execution.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import math
import time
import uuid

from modules import persona_contract as contract

_CURRENT = ContextVar('jarvis_persona_request',default=None)
LEARNED_TTL = 30*86400
SESSION_TTL = 24*3600


def _record(owner,key,value,source,rid,now,quote=''):
    return {'version':contract.VERSION,'owner':owner,'key':key,'value':value,
            'source':source,'request_id':rid,'updated_at':now,'created_at':now,
            'expires_at':now+LEARNED_TTL if source=='user.learned' else None,
            'confidence':1.,'evidence_digest':hashlib.sha256(quote.encode()).hexdigest()}


def _valid(row,owner,key,now):
    if not isinstance(row,dict):return False
    stamp=row.get('updated_at');expiry=row.get('expires_at');confidence=row.get('confidence')
    return (row.get('version')==contract.VERSION and row.get('owner')==owner and row.get('key')==key
            and row.get('value') in contract.PREFERENCES[key]
            and type(stamp) in (int,float) and math.isfinite(stamp) and stamp<=now
            and (expiry is None or (type(expiry) in (int,float) and math.isfinite(expiry) and now<expiry))
            and type(confidence) in (int,float) and .8<=confidence<=1.)


def _persist(profile,changes,rid,now,source=None):
    from modules import file_resource_guard,personalization
    with personalization._LOCK,file_resource_guard.claim_paths(profile.path,profile.path.with_suffix('.tmp')):
        before=deepcopy(profile.data)
        candidate=json.loads(profile.path.read_text(encoding='utf-8')) if profile.path.exists() else deepcopy(before)
        if not isinstance(candidate,dict) or not isinstance(candidate.get('prefs'),dict):
            raise ValueError('Profil kaydı geçersiz; tercih yazılmadı.')
        store=candidate.setdefault('presentation_preferences',{'version':contract.VERSION,'explicit':{},'learned':{}})
        if not isinstance(store,dict) or store.get('version')!=contract.VERSION:
            raise ValueError('Persona sürümü geçersiz; tercih yazılmadı.')
        for change in changes:
            key,value,scope=(change[name] for name in ('key','value','scope'))
            rows=store.setdefault(scope,{})
            if not isinstance(rows,dict):raise ValueError('Tercih kayıtları geçersiz.')
            if value is None:
                rows.pop(key,None)
                if scope=='explicit':candidate['prefs'].pop(key,None)
                continue
            origin=source or 'user.'+scope
            row=_record(profile.slug,key,value,origin,rid,now,change.get('evidence_quote',''))
            previous=rows.get(key,{})
            if scope=='learned':
                prior=(isinstance(previous,dict) and previous.get('value')==value
                       and previous.get('owner')==profile.slug and previous.get('expires_at',0)>now)
                seen=list(previous.get('seen_requests',[])) if prior else []
                if rid in seen:continue
                seen=(seen+[rid])[-32:]
                row.update(seen_requests=seen,observations=len(seen),confidence=min(.4+.2*(len(seen)-1),1.))
                if prior:row['created_at']=previous.get('created_at',now)
            rows[key]=row
            if scope=='explicit':candidate['prefs'][key]=value
        profile.data.clear();profile.data.update(candidate)
        try:profile.save()
        except BaseException:
            profile.data.clear();profile.data.update(before)
            raise


def set_preference(profile,key,value,*,source='user.ui'):
    if not isinstance(key,str) or key not in contract.PREFERENCES or (value is not None and (not isinstance(value,str) or value not in contract.PREFERENCES[key])):
        raise ValueError('Sunum tercihi geçersiz.')
    _persist(profile,[{'key':key,'value':value,'scope':'explicit'}],uuid.uuid4().hex,time.time(),source)


def reset(profile,key,scope,session=None):
    if not isinstance(key,str) or key not in contract.PREFERENCES or scope not in ('explicit','learned','session'):
        raise ValueError('Tercih silme kapsamı geçersiz.')
    if scope=='session':
        if session is None:raise ValueError('Tercihin kullanıcı oturumu bulunamadı.')
        getattr(session,'presentation_preferences',{}).pop(key,None)
    else:_persist(profile,[{'key':key,'value':None,'scope':scope}],uuid.uuid4().hex,time.time())


def effective(profile,*,session=None,request_id=None,now=None):
    from modules.personalization import _LOCK
    now=time.time() if now is None else now
    current=_CURRENT.get()
    if session is None and current is not None and current[0]==profile.slug:
        _,session,request_id=current
    with _LOCK:
        store=deepcopy(profile.data.get('presentation_preferences',{}))
        prefs=dict(profile.data.get('prefs',{}))
    store=store if isinstance(store,dict) and store.get('version')==contract.VERSION else {}
    result={}
    for key,default in contract.DEFAULTS.items():
        row={'value':default,'source':'default','confidence':1.}
        learned=store.get('learned',{});explicit=store.get('explicit',{})
        learned=learned.get(key) if isinstance(learned,dict) else None
        explicit=explicit.get(key) if isinstance(explicit,dict) else None
        if _valid(learned,profile.slug,key,now):row=learned
        # Historical non-default UI values remain explicit, without inventing timestamps.
        legacy=prefs.get(key)
        if isinstance(legacy,str) and legacy in contract.PREFERENCES[key] and legacy!=default:
            row={'value':legacy,'source':'legacy.ui','confidence':1.}
        if _valid(explicit,profile.slug,key,now):row=explicit
        if session is not None:
            session_rows=getattr(session,'presentation_preferences',{})
            temporary=session_rows.get(key) if isinstance(session_rows,dict) else None
            if _valid(temporary,profile.slug,key,now):row=temporary
            turn=getattr(session,'presentation_turn',None)
            if isinstance(turn,dict) and turn.get('request_id')==request_id:
                candidate=turn.get('values',{}).get(key)
                if _valid(candidate,profile.slug,key,now):row=candidate
        result[key]=dict(row)
    return result


def view(profile,session=None):
    from modules.personalization import _LOCK
    values=effective(profile,session=session)
    with _LOCK:stored=deepcopy(profile.data.get('presentation_preferences',{}))
    learned=stored.get('learned',{}) if isinstance(stored,dict) else {}
    explicit=stored.get('explicit',{}) if isinstance(stored,dict) else {}
    controls=[]
    for key,row in values.items():
        controls.append({'key':key,'label':contract.LABELS[key],'options':list(contract.PREFERENCES[key]),
            'selected':row['value'] if row['source'] in ('user.ui','user.explicit','legacy.ui') else '',
            'effective':row['value'],'source_label':contract.SOURCES.get(row['source'],'Varsayılan'),
            'has_learned':isinstance(learned,dict) and key in learned})
        if isinstance(explicit,dict) and _valid(explicit.get(key),profile.slug,key,time.time()):
            controls[-1]['selected']=explicit[key]['value']
    return {'version':contract.VERSION,'owner':profile.slug,'effective':values,'stored':stored,'controls':controls}


def manage(profile,action,session=None):
    if action['operation']=='preference.reset':
        reset(profile,action['key'],action['scope'],session)
        return 'Seçtiğin yanıt tercihini kaldırdım.'
    if action['operation']!='preference.list':raise ValueError('Persona işlemi geçersiz.')
    rows=effective(profile,session=session)
    text='Sunum tercihleri: '+ '; '.join(f'{contract.LABELS[key]}: {row["value"]} ({contract.SOURCES.get(row["source"],"Varsayılan")})' for key,row in rows.items())
    learned=profile.data.get('presentation_preferences',{}).get('learned',{})
    for key,row in learned.items():
        if key in contract.PREFERENCES and isinstance(row,dict) and type(row.get('confidence')) in (int,float):
            text+=f'; Öğrenilmiş öneri: {contract.LABELS[key]}={row.get("value")} (güven %{round(row["confidence"]*100)})'
    return text


@contextmanager
def request_scope(runtime,entry,command):
    from modules import requests_state
    reader=getattr(runtime,'_session',None)
    session=reader() if callable(reader) else None
    semantic=entry.understanding
    changes=getattr(semantic,'presentation',()) if semantic is not None else ()
    if changes:
        active_request=requests_state._current.get()
        runtime_rid=getattr(runtime,'_cur_rid',None)
        if (entry.owner!=runtime.profile.slug or semantic.owner!=entry.owner
                or semantic.request_id!=entry.request_id or command!=entry.text or entry.batch_child
                or entry.stage!='understanding' or 'MODEL_DECIDED' not in semantic.reason_codes
                or entry.source not in ('yazı','ses','telefon') or semantic.needs_input
                or (runtime_rid is not None and runtime_rid!=entry.request_id)
                or (active_request is not None and active_request!=(entry.owner,entry.request_id))):
            raise ValueError('Persona kullanıcı/istek sınırı uyuşmuyor.')
        changes=contract.validate_changes(changes,command)
        requests_state.check()
        from modules import learning
        permanent=[change for change in changes if change['scope']=='explicit'
                   or (change['scope']=='learned' and learning.enabled(runtime.profile))]
        now=time.time()
        if session is None and any(change['scope'] in ('turn','session') for change in changes):
            raise ValueError('Geçici tercih için mevcut kullanıcı oturumu gerekli.')
        if permanent:_persist(runtime.profile,permanent,entry.request_id,now)
        if session is not None:
            for change in changes:
                scope,key=change['scope'],change['key']
                if scope not in ('turn','session'):continue
                row=_record(entry.owner,key,change['value'],'user.'+scope,entry.request_id,now,change['evidence_quote'])
                row['expires_at']=now+SESSION_TTL
                if scope=='session':
                    if not hasattr(session,'presentation_preferences'):session.presentation_preferences={}
                    session.presentation_preferences[key]=row
                else:
                    turn=getattr(session,'presentation_turn',None)
                    if not isinstance(turn,dict) or turn.get('request_id')!=entry.request_id:
                        session.presentation_turn={'request_id':entry.request_id,'values':{}}
                    session.presentation_turn['values'][key]=row
    token=_CURRENT.set((entry.owner,session,entry.request_id))
    try:yield
    finally:_CURRENT.reset(token)


def prompt(profile):
    values=effective(profile)
    text=' '.join(f'{key}={row["value"]}.' for key,row in values.items() if key!='verbosity')
    return (f'Persona {contract.VERSION}: {contract.FIXED} Kullanıcı tercihi: yanıt uzunluğu='
            f'{values["verbosity"]["value"]}. Kısa tercihinde doğrudan özetle; orta tercihinde yeterli açıklama; '
            'uzun tercihinde gerekli ayrıntı ve örnekleri ver. Metin/ekran gerektiğinde liste ve kod gösterebilir. '
            'Sunum ayarları (yalnız üslup, zorunlu uyarıları veya onayı gizleme): '+text)
