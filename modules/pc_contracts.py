"""Common bounded PC operation input and execution records; never grants permission."""
import copy
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import threading
import uuid
from functools import wraps
from config import DATA_DIR
from modules import requests_state
from modules.diagnostics import record_failure as _record_failure

CATALOG={
 'set_volume':(('level',),(int,),'device_setting'),
 'change_volume_by_delta':(('delta',),(int,),'device_setting'),
 'set_mute':(('on',),(bool,),'device_setting'),
 'set_brightness':(('level',),(int,),'device_setting'),
 'media_control':(('action',),(str,),'media_control'),
 'open_application':(('app_name',),(str,),'application_open'),
 'close_application':(('app_name',),(str,),'application_close'),
 'shutdown_pc':((),(),'system_shutdown'),
 'cancel_shutdown':((),(),'system_shutdown_cancel'),
 'window_action':(('target','action'),(str,str),'window_control'),
 'window_shortcut':(('target','shortcut'),(str,str),'window_input'),
}
ROOT=DATA_DIR/'pc_operations'
_LOCK=threading.RLock()
_LAST=ContextVar('jarvis_pc_result',default=None)

def prepare(action,args,kwargs,owner=None):
    if action not in CATALOG:raise ValueError('PC işlemi kayıtlı değil.')
    names,types,risk=CATALOG[action]
    if len(args)>len(names) or set(kwargs)-set(names)-({'hwnd'} if action=='window_action' else set()):
        raise ValueError('PC girdisi desteklenmeyen alan içeriyor.')
    values=dict(zip(names,args))
    if set(values)&set(kwargs):raise ValueError('PC girdisi iki kez verilmiş.')
    values.update(kwargs)
    if any(n not in values or type(values[n]) is not t for n,t in zip(names,types)):
        raise ValueError('PC girdi türü veya alanı geçersiz.')
    if any(not values[n].strip() or len(values[n])>300 or '\x00' in values[n] for n,t in zip(names,types) if t is str):
        raise ValueError('PC metin girdisi geçersiz.')
    if 'hwnd' in values and values['hwnd'] is not None and (type(values['hwnd']) is not int or values['hwnd']<=0):
        raise ValueError('Pencere kimliği geçersiz.')
    if action=='window_action' and values['action'] not in ('focus','minimize','maximize','restore'):
        raise ValueError('Pencere işlemi geçersiz.')
    if action=='media_control' and values['action'] not in ('play_pause','durdur','oynat','next','sonraki','prev','önceki'):
        raise ValueError('Medya işlemi geçersiz.')
    request=requests_state._current.get()
    if owner is None:
        from modules import llm
        owner=request[0] if request else llm._key_context.get()
    if owner is not None and (not isinstance(owner,str) or not re.fullmatch(r'[\w-]{1,100}',owner)):
        raise ValueError('PC işlem kullanıcısı geçersiz.')
    if request and request[0]!=owner:raise PermissionError('PC işlemi ve istek kullanıcısı eşleşmiyor.')
    record={'version':1,'id':uuid.uuid4().hex,'owner':owner,'request_id':request[1] if request else None,
            'capability':action,'risk':risk,'replay_safe':False,'state':'running','scope':'pending'}
    persist(record);_LAST.set(copy.deepcopy(record));return record

def finish(record,result=None,error=False):
    action=record['capability']
    if error:ok=False
    elif action in ('shutdown_pc','cancel_shutdown'):ok=result is True
    elif action in ('open_application','close_application'):ok=getattr(result,'ok',False) is True
    elif action in ('window_action','window_shortcut'):ok=isinstance(result,dict) and result.get('ok') is True
    elif action=='change_volume_by_delta':ok=type(result) is int
    else:ok=result is True
    record={**record,'state':'done' if ok else 'failed',
            'scope':'adapter_result' if ok else 'unverified'}
    if action in ('shutdown_pc','cancel_shutdown') and ok:record['scope']='dispatch_only'
    _LAST.set(copy.deepcopy(record));persist(record);return record

def last_result():return copy.deepcopy(_LAST.get())

def call(action,target,args,kwargs,owner=None):
    record=prepare(action,args,kwargs,owner)
    try:result=target(*args,**kwargs)
    except Exception:
        _record_failure('modules/pc_contracts.py:call')
        finish(record,error=True);raise
    finish(record,result);return result

def instrument(action,target):
    @wraps(target)
    def wrapped(*args,**kwargs):return call(action,target,args,kwargs)
    wrapped._pc_contract=True
    return wrapped

def persist(record):
    # Only operation identity/status is retained: no command text, file paths,
    # account values or credentials. A missing owner never uses another profile.
    if record['owner'] is None:return
    with _LOCK:
        ROOT.mkdir(parents=True,exist_ok=True)
        path=ROOT/(record['owner']+'.json');tmp=path.with_suffix('.tmp')
        if ROOT.is_symlink() or path.is_symlink() or tmp.is_symlink():raise ValueError('PC kayıt yolu sembolik bağ olamaz.')
        if path.exists() and path.stat().st_size>1_000_000:raise ValueError('PC işlem kaydı sınırı aşıyor.')
        rows=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError('PC işlem kaydı bozuk.')
        rows=[r for r in rows if r.get('id')!=record['id']]+[record]
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(rows[-200:],f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
