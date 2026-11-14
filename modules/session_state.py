"""User-owned conversation state; request contexts never swap shared dictionaries."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading
import time

@dataclass
class SessionState:
    presentation_preferences: dict = field(default_factory=dict)
    presentation_turn: object = None
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
    pending_desktop: object = None
    pending_visual: object = None
    last_visual: object = None
    last_command: str = ''
    last_property: object = None   # 'volume' | 'brightness': son başarıyla ayarlanan seviye özelliği
    last_property_at: float = 0.0
    last_note: object = None  # owner/id/digest/time only; Profile remains the note store
    speech_override: object = None
    _in_macro: bool = False
    _in_multi: bool = False

LEVEL_PROPERTIES = frozenset({"volume", "brightness"})
LEVEL_PROPERTY_TTL = 600.0   # 10 dk: daha eski "son özellik" bağlam sayılmaz, tekrar sorulur
NOTE_REFERENCE_TTL = 900.0


def remember_note(state, owner, ident, digest):
    state.last_note = {"owner": owner, "id": str(ident), "digest": digest, "at": time.time()}


def clear_note(state):
    state.last_note = None


def fresh_note(state, owner, now=None):
    row = getattr(state, "last_note", None)
    if not isinstance(row, dict) or row.get("owner") != owner:
        return None
    at = row.get("at")
    now = time.time() if now is None else now
    if (type(at) not in (int, float) or not 0 <= now - at <= NOTE_REFERENCE_TTL
            or not isinstance(row.get("id"), str) or not row["id"]
            or not isinstance(row.get("digest"), str) or len(row["digest"]) != 64):
        return None
    return dict(row)


def remember_property(state, name):
    """Record the level property that was just verified as set; unknown names are ignored."""
    if name in LEVEL_PROPERTIES:
        state.last_property = name
        state.last_property_at = time.time()


def clear_property(state):
    """Retire a previous confirmed level target when the conversation changes.

    Only a verified level-setting result may open this one-turn follow-up
    context again; it is never a general-purpose natural-language classifier.
    """
    state.last_property = None
    state.last_property_at = 0.0


def fresh_property(state, now=None):
    """Return 'volume'/'brightness' only while valid and fresh, else None."""
    name = getattr(state, "last_property", None)
    at = getattr(state, "last_property_at", 0.0)
    if name not in LEVEL_PROPERTIES or not isinstance(at, (int, float)) or isinstance(at, bool):
        return None
    now = time.time() if now is None else now
    return name if 0 <= now - at <= LEVEL_PROPERTY_TTL else None


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
