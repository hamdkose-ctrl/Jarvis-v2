"""Karar 2 Aşama C: the canonical Scheduler owns every new desktop task.

The native engine stays the executor and keeps its own action-approval and
permission-consent artifacts. This front door decides only WHO may hand it a
new physical task: the typed ``PC görevi`` sentence becomes one typed canonical
goal, and the Core card of that goal is the only effect approval. Control and
answer sentences stay with the engine, which refuses them for Scheduler-created
tasks; a native job written before this stage carries no origin and therefore
remains controllable.
"""
import re

from modules import requests_state

_CREATE = re.compile(r'^pc\s+görev(?:i)?(?=[:\s])', re.I)


def _admit(owner, text, target, goal):
    from modules import canonical_goal_flow, task_queue
    request = requests_state._current.get()
    if (not isinstance(request, tuple) or len(request) != 2
            or request[0] != owner or not isinstance(request[1], str) or not request[1]):
        raise PermissionError('Masaüstü hedefi için açık owner/RID komut kimliği gerekli.')
    if not task_queue.scheduler_active():
        return 'Canonical Scheduler hazır değil; masaüstü görevi başlatılmadı.'
    _identity, reply = canonical_goal_flow.try_create(
        owner, request[1], text, direct_tasks=[
            {'id': 'pc', 'agent': 'desktop', 'depends': [],
             'input': {'target': target, 'goal': goal}},
        ])
    return reply


def dispatch(owner, command, *, current=None, source='yazı'):
    """Reply text for a canonical decision, or None for the native engine.

    None means this stage deliberately leaves the sentence to the engine:
    reads, cancel, consent, control and answer forms, free language the
    context-aware intent router already owns, and the engine's own
    active-user refusal. The ownership rule itself is not duplicated here.
    """
    from modules import desktop_agent
    text = str(command or '').strip()
    if not _CREATE.match(text):
        return None
    if source == 'telefon' or (current and current() != owner):
        return None
    parsed = desktop_agent.parse_task(text)
    if parsed is None or isinstance(parsed, str):
        return None
    return _admit(owner, text, *parsed)
