"""User-owned conversation state; request contexts never swap shared dictionaries."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import threading

@dataclass
class SessionState:
    pending_weather_location: bool = False
    pending_confirm: object = None
    pending_action: object = None
    pending_organize: object = None
    pending_msg: object = None
    pending_level: object = None
    pending_voice: object = None
    pending_event_title: object = None
    last_doc: object = None
    pending_app: object = None
    pending_request: object = None
    pending_desktop: object = None
    pending_visual: object = None
    last_visual: object = None
    last_command: str = ''
    speech_override: object = None
    _in_macro: bool = False
    _in_multi: bool = False

class SessionStore:
    def __init__(self):
        self._states = {}
        self._lock = threading.RLock()
        self._owner = ContextVar('jarvis_session_owner', default=None)

    def get(self, fallback):
        owner = self._owner.get() or fallback
        with self._lock:
            return self._states.setdefault(owner, SessionState())

    def for_owner(self, owner):
        with self._lock:
            return self._states.setdefault(owner, SessionState())

    def reset(self, owner):
        with self._lock:
            self._states[owner] = SessionState()

    @contextmanager
    def use(self, owner):
        token = self._owner.set(owner)
        try:
            yield self.get(owner)
        finally:
            self._owner.reset(token)
