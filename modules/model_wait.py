"""Bound model-only waits; late text never executes a tool or writes a delivery."""
from contextvars import copy_context, ContextVar
from contextlib import contextmanager
import threading
import time
from modules import llm,requests_state

_LOCK=threading.Lock()
_PENDING={}
DEFAULT_SECONDS=60
_CHECK=ContextVar("model_parent_check",default=None)

@contextmanager
def guard(check):
    token=_CHECK.set(check)
    try:yield
    finally:_CHECK.reset(token)



def ask(prompt,system='',max_tokens=2000,*,seconds=None,check=None,**kwargs):
    seconds=DEFAULT_SECONDS if seconds is None else seconds
    owner=llm.current_user()
    if not owner:raise PermissionError('Model beklemesi için kullanıcı bağlamı gerekli.')
    check=check or _CHECK.get() or requests_state.check
    check();done=threading.Event();box={};context=copy_context()
    deadline=time.monotonic()+seconds
    cancelled=threading.Event()
    entry={'done':done,'abandoned':False}
    while True:
        check()
        with _LOCK:
            pending=_PENDING.get(owner)
            if pending is None or pending['done'].is_set():
                _PENDING[owner]=entry;break
            if pending['abandoned']:
                raise RuntimeError('Önceki zaman aşımına uğrayan model çağrısı henüz kapanmadı; ikinci çağrı başlatılmadı.')
        if time.monotonic()>=deadline:raise RuntimeError('Model sırası bekleme süresi doldu; çağrı başlatılmadı.')
        pending['done'].wait(min(.1,max(0,deadline-time.monotonic())))
    def work():
        try:
            with requests_state.budget(max(.001,deadline-time.monotonic()),cancel=cancelled):
                box['answer']=llm.ask(prompt,system=system,max_tokens=max_tokens,**kwargs)
                requests_state.check()
        except BaseException as exc:box['error']=exc
        finally:
            box['routes']=llm.take_route()
            with _LOCK:
                if _PENDING.get(owner) is entry:_PENDING.pop(owner,None)
                done.set()
    threading.Thread(target=context.run,args=(work,),daemon=True,name='jarvis-model-wait').start()
    try:
        while not done.wait(min(.1,max(0,deadline-time.monotonic()))):
            check()
            if time.monotonic()>=deadline:
                raise RuntimeError('Model '+str(seconds)+' saniyede yanıt vermedi; işlem duraklatıldı. Geç yanıt araç çalıştıramaz veya teslim dosyası yazamaz.')
    except BaseException:
        cancelled.set()
        with _LOCK:entry['abandoned']=True
        raise
    check()
    for text,ok in box.get('routes',[]):llm.note_route(text,ok)
    if 'error' in box:
        exc=box['error']
        if isinstance(exc,TimeoutError):raise RuntimeError(str(exc)) from None
        raise exc
    return box['answer']
