"""Tek giriş (motor birleştirme adım 3): çıplak "devam" ve "iptal" hedef işi yoksa açık görev işini bulur.

Hedef motoru (`goal_executor`) kullanıcıya bakan ana yüzdür; ama bir görev akışı (`task_agents`) yarım kalmışsa "devam" ve
"iptal" eskiden "Sürdürülecek kayıtlı hedef yok." diyor ya da sohbete düşüyordu. Burada model çağrısı, yeni depo veya yeni
onay yolu yoktur: yalnız var olan `continue_job`/`cancel_job` çağrılır. "evet/onayla" kelimeleri bilerek taşınmaz (dış gönderim
onayı yalnız açık "işlem onayla <kimlik>" ile verilir).
"""
import time

from modules.diagnostics import record_failure as _record_failure

_CONTINUE = frozenset({'devam', 'devam et', 'sürdür', 'surdür'})
_CANCEL = frozenset({'iptal', 'vazgeç', 'boşver'})
_OPEN = frozenset({'interrupted', 'incomplete', 'approval'})
_FRESH_SECONDS = 24 * 3600
_PENDING = ('pending_confirm', 'pending_action', 'pending_organize', 'pending_msg', 'pending_level', 'pending_voice',
            'pending_event_title', 'pending_app', 'pending_request', 'pending_desktop', 'pending_weather_location')


def _goal_open(owner):
    from modules import goal_executor
    try:
        job = goal_executor.latest(owner)
    except Exception:                                   # bozuk kayıt: eski davranış (hedef yoluna bırak)
        _record_failure('modules/job_front.py:_goal_open')
        return True
    return goal_executor.is_open(job)                   # bitmemiş ve bayat olmayan iş


def wants(cmd_lower):
    low = cmd_lower.strip(' .!?')
    return low in _CONTINUE or low in _CANCEL


def observe(owner):
    """Return the domain-owned resumable task view without consuming the request.

    Freshness remains owned here; Brain receives only this read-only observation
    and route() rechecks the real task before any continuation/cancellation.
    """
    from modules import task_agents
    try:
        job = task_agents.recent(owner)
    except Exception:
        _record_failure('modules/job_front.py:observe')
        return None
    if not isinstance(job, dict) or not job.get('id'):
        return None
    updated = job.get('updated')
    stale = not isinstance(updated, (int, float)) or time.time() - float(updated) > _FRESH_SECONDS
    return {
        'id': str(job['id']),
        'state': str(job.get('state') or ''),
        'updated': updated,
        'stale': stale,
    }


def route(owner, emit, cmd_lower, session, *, photo_pending=False, bounded=False):
    """Çıplak devam/iptal için açık görev işi yanıtı; uygun değilse None (eski yol aynen sürer).

    ``bounded=True`` yalnız canonical Exact State Gate bu utterance'ı job.resume
    veya job.cancel olarak eşleştirdiğinde kullanılır. Bu durumda unrelated
    session pending varlığı işi yutamaz; domain goal/freshness/owner kontrolleri
    yine burada yeniden uygulanır.
    """
    low = cmd_lower.strip(' .!?')
    if low not in _CONTINUE and low not in _CANCEL:
        return None
    if not bounded and any(getattr(session, name, None) for name in _PENDING):
        return None                                     # bekleyen soru kendi cevabını alır
    if photo_pending and low in _CANCEL:
        return None                                     # fotoğrafın mevcut iptal yanıtına bırak
    from modules import goal_executor
    if goal_executor.active() or _goal_open(owner):
        return None
    from modules import task_agents
    job = task_agents.recent(owner)
    if not job or job.get('state') not in _OPEN or time.time() - float(job.get('updated') or 0) > _FRESH_SECONDS:
        # Çıplak iptal, açık iş yokken modele gitmesin (eskiden 'Yeni sohbet başlat' onayına dönüşüyordu).
        return 'İptal edilecek açık görev yok.' if low in _CANCEL else None
    session.speech_override = 'Görev sonucu sohbet ekranında hazır.'
    if low in _CONTINUE:
        return task_agents.render(task_agents.continue_job(owner, emit=emit))
    cancelled = task_agents.cancel_job(owner)
    return task_agents.render(cancelled) if cancelled else 'İptal edilecek görev yok.'
