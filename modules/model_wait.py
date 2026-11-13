"""Bound model-only waits; late text never executes a tool or writes a delivery."""
from contextvars import copy_context, ContextVar
from contextlib import contextmanager
from modules.diagnostics import record_failure as _record_failure
import threading
import time
import secrets
from modules import llm,requests_state

_LOCK=threading.Lock()
_PENDING={}
DEFAULT_SECONDS=60
_CHECK=ContextVar("model_parent_check",default=None)
_FOREGROUND=ContextVar("model_wait_foreground",default=None)

class ModelWaitTimeout(RuntimeError):
    """Bounded wait expired; existing failure policy identifies a timeout."""


@contextmanager
def guard(check):
    token=_CHECK.set(check)
    try:yield
    finally:_CHECK.reset(token)


@contextmanager
def foreground(factory):
    """Hand the interaction layer back to this thread while it waits on a provider.

    `factory()` must return a context manager; it wraps each bounded provider wait
    started inside this scope, on this thread only. The provider call itself runs in
    a copied context and clears the hook: a background thread never owns the
    microphone. Waiting, cancellation, the deadline and the late-answer fence are
    unchanged whether or not a factory is installed.
    """
    token=_FOREGROUND.set(factory)
    try:yield
    finally:_FOREGROUND.reset(token)


@contextmanager
def _foreground_scope(boundary):
    """A broken hook can never change what a provider wait does or returns."""
    if boundary is None:
        yield
        return
    scope = None
    entered = False
    try:
        scope = boundary()
        scope.__enter__()
        entered = True
    except Exception:
        _record_failure('modules/model_wait.py:foreground')
    if not entered:
        yield
        return
    try:
        yield
    finally:
        try:
            scope.__exit__(None, None, None)
        except Exception:
            _record_failure('modules/model_wait.py:foreground_exit')



@contextmanager
def interactive_wait():
    """Lend the mic to the listener during an in-thread Brain provider route.

    Primary semantic understanding uses smart_router.run rather than ask().
    This opt-in scope has the SAME failure-safe local foreground hook as ask,
    but does not add a worker, change provider routing, or release as_user.
    The model still runs synchronously: queued follow-ups are not executed here.
    """
    with _foreground_scope(_FOREGROUND.get()):
        yield


def ask(prompt,system='',max_tokens=2000,*,seconds=None,check=None,ask_fn=None,**kwargs):
    seconds=DEFAULT_SECONDS if seconds is None else seconds
    owner=llm.current_user()
    if not owner:raise PermissionError('Model beklemesi için kullanıcı bağlamı gerekli.')
    check=check or _CHECK.get() or requests_state.check
    boundary=_FOREGROUND.get()
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
        if time.monotonic()>=deadline:raise ModelWaitTimeout('Model sırası bekleme süresi doldu; çağrı başlatılmadı.')
        pending['done'].wait(min(.1,max(0,deadline-time.monotonic())))
    def work():
        _FOREGROUND.set(None)      # the provider thread never owns the caller's foreground hook
        try:
            # This claim surrounds the actual provider thread, not the waiting
            # foreground turn. A timed-out caller never releases an active model
            # connection; model_wait._PENDING also fences late replies.
            from modules import interactive_resource_gate
            with interactive_resource_gate.claim(
                    "llm", owner=owner, operation_id=secrets.token_hex(16)):
                with requests_state.budget(max(.001,deadline-time.monotonic()),cancel=cancelled):
                    if ask_fn is None:
                        box['answer']=llm.ask(prompt,system=system,max_tokens=max_tokens,**kwargs)
                    else:
                        box['answer']=ask_fn(prompt,system,max_tokens=max_tokens,**kwargs)
                    requests_state.check()
        except BaseException as exc:box['error']=exc
        finally:
            box['routes']=llm.take_route()
            with _LOCK:
                if _PENDING.get(owner) is entry:_PENDING.pop(owner,None)
                done.set()
    threading.Thread(target=context.run,args=(work,),daemon=True,name='jarvis-model-wait').start()
    try:
        with _foreground_scope(boundary):
            while not done.wait(min(.1,max(0,deadline-time.monotonic()))):
                check()
                if time.monotonic()>=deadline:
                    raise ModelWaitTimeout('Model '+str(seconds)+' saniyede yanıt vermedi; işlem duraklatıldı. Geç yanıt araç çalıştıramaz veya teslim dosyası yazamaz.')
    except BaseException:
        cancelled.set()
        with _LOCK:entry['abandoned']=True
        raise
    check()
    for text,ok in box.get('routes',[]):llm.note_route(text,ok)
    if 'error' in box:
        exc=box['error']
        if isinstance(exc,TimeoutError):raise ModelWaitTimeout(str(exc)) from None
        raise exc
    return box['answer']
