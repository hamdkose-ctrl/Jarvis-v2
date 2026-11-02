"""Engine dependency/state composition. Business logic lives in focused modules."""
from __future__ import annotations
from functools import partial
from importlib import import_module
from contextvars import ContextVar

from modules.diagnostics import record_failure as _record_failure
from modules import tr_speech_sets
import difflib
import json
import logging
import os
import subprocess
import queue
import re
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import quote_plus
from config import ANNOUNCE_UNKNOWN, ASSISTANT_NAME, DATA_DIR, MODEL, SESSION_SECONDS, WAKE_ALIASES, WAKE_WORD
from datetime import datetime, timedelta
from modules import richtext, typo, weather, when as whenmod
from modules import browser, plugins, privacy
from modules import codegen, desktop, docs, files, google_api, agents, history, kb, media, messaging, notify, output, tasks, system_control, translate as tr, vision, voice
from modules import live
from modules.llm import ask, ask_image, chat
from modules import llm as _llm
import concurrent.futures as _cf
import contextlib
from modules import requests_state
import secrets
from modules.llm import transcribe as llm_transcribe
from modules.personalization import (Profile, delete_user, display_name, get_active, list_users, migrate_legacy,
                                     rename_user,
                                     set_active, slugify)
from modules.session_state import SessionStore
_DELETED_COMMAND_FIELD = object()

def _command_field(variable, name):
    value = variable.get()
    if value is _DELETED_COMMAND_FIELD:
        raise AttributeError(name)
    return value

class _AnyAbort:
    """voice.listen için birden fazla Event'i tek abort nesnesi gibi gösterir."""
    def __init__(self, *events_):
        self.events = events_

    def is_set(self) -> bool:
        return any(e.is_set() for e in self.events)
_DEPENDENCIES = ['ANNOUNCE_UNKNOWN', 'ASSISTANT_NAME', 'DATA_DIR', 'MODEL', 'Profile', 'RotatingFileHandler', 'SESSION_SECONDS', 'SessionStore', 'WAKE_ALIASES', 'WAKE_WORD', '_AnyAbort', '_cf', '_llm', '_record_failure', 'agents', 'ask', 'ask_image', 'browser', 'chat', 'codegen', 'contextlib', 'datetime', 'delete_user', 'desktop', 'difflib', 'display_name', 'docs', 'files', 'get_active', 'google_api', 'history', 'json', 'kb', 'list_users', 'live', 'llm_transcribe', 'logging', 'media', 'messaging', 'migrate_legacy', 'notify', 'os', 'output', 'plugins', 'privacy', 'queue', 'quote_plus', 're', 'rename_user', 'requests_state', 'richtext', 'secrets', 'set_active', 'slugify', 'subprocess', 'sys', 'system_control', 'tasks', 'tempfile', 'threading', 'time', 'timedelta', 'tr', 'typo', 'vision', 'voice', 'weather', 'whenmod']
_HANDLERS = {'engine_context': ('_get_profile',
                    '_session',
                    'pc_profile',
                    'match_user',
                    'as_user',
                    '_voice_opts',
                    '_parse_voice',
                    '_set_voice',
                    '_switch_user',
                    '_user_command'),
 'engine_output': ('emit',
                   '_emit_route',
                   'set_share',
                   'set_sleep',
                   '_short_for_speech',
                   '_finalize',
                   '_doc_ready_line',
                   '_table_chat',
                   '_conversation_summary',
                   '_copy_text'),
 'engine_voice': ('_pc_context',
                  '_live_prompt',
                  '_recent_turns',
                  'live_session_opened',
                  '_live_session_end',
                  '_live_vocab',
                  '_sounds_like_wake',
                  'find_wake',
                  '_is_jarvis_name',
                  '_strip_wake',
                  'list_input_devices'),
 'engine_live_brain': ('_live_command',),
 'engine_background': ('_start_hang_watch',
                       '_emit_for',
                       '_reminder_tick',
                       '_reminder_loop',
                       '_handoff_notice',
                       '_learning_notice',
                       '_google_health'),
 'engine_queue': ('submit', 'submit_audio', 'submit_photo', '_reject_queued_input'),
 'engine_sequence': ('_split_steps', '_run_steps', '_close_jarvis'),
 'engine_commands': ('handle_request',),
 'engine_loop': ('main',),
 'engine_tools': ('_tr_lower',
                  '_numbers',
                  '_has_word',
                  '_web_search',
                  '_weather',
                  '_city_in',
                  '_volume_step',
                  '_file_command',
                  '_study_media_topic',
                  '_study_intent',
                  '_translate_file',
                  '_plain',
                  '_note_text',
                  '_add_note',
                  '_fix_word',
                  '_note_fix',
                  '_keep_photo',
                  '_photo_action',
                  '_sys_prompt',
                  '_notes_text',
                  '_agenda_text',
                  '_add_event',
                  '_planner_command',
                  'load_approve',
                  '_message_step',
                  '_contact_command',
                  '_macro_key',
                  '_macro_teach',
                  '_macro_run',
                  '_macro_manage',
                  '_screen_ocr',
                  '_brief_facts',
                  '_daily_briefing',
                  '_morning_brief',
                  '_mail_handle',
                  '_extra_commands')}


class EngineContext:
    def is_exported(self, name):
        """Public facade contract; consumers need not inspect the export set."""
        return name in self._exported

    def __init__(self):
        self._command_source = ContextVar('engine_command_source', default='')
        self._command_rid = ContextVar('engine_command_rid', default=None)
        self._command_typo_pass = ContextVar('engine_command_typo_pass', default=False)
        self._command_typo_orig = ContextVar('engine_command_typo_orig', default='')
        for name in _DEPENDENCIES:
            setattr(self, name, globals()[name])
        for module, names in _HANDLERS.items():
            component = import_module('modules.' + module)
            for name in names:
                setattr(self, name, partial(getattr(component, name), self))
        self.handle = self.handle_request   # tek giriş: yazım düzeltme yeniden denemesi dahil
        for name in ('_live_prompt', '_live_command'):
            setattr(self, name, self._pc_context(getattr(self, name)))
        from modules.pc_steps import ReportedControl
        # PC actions report visible steps to the chat; the actions themselves are unchanged.
        self.system_control = ReportedControl(system_control, lambda text, status, step_id, detail:
                                              self.emit('step', text, f'{status}|{step_id}|{detail}'))
        _initialize(self)
        self._exported = set(vars(self)) | {'last_doc', 'speech_override', '_cur_source', '_cur_rid', '_typo_pass', '_typo_orig'}

    @property
    def _cur_source(self):
        return _command_field(self._command_source, '_cur_source')

    @_cur_source.setter
    def _cur_source(self, value):
        self._command_source.set(value)

    @_cur_source.deleter
    def _cur_source(self):
        self._command_source.set(_DELETED_COMMAND_FIELD)

    @property
    def _cur_rid(self):
        return _command_field(self._command_rid, '_cur_rid')

    @_cur_rid.setter
    def _cur_rid(self, value):
        self._command_rid.set(value)

    @_cur_rid.deleter
    def _cur_rid(self):
        self._command_rid.set(_DELETED_COMMAND_FIELD)

    @property
    def _typo_pass(self):
        return _command_field(self._command_typo_pass, '_typo_pass')

    @_typo_pass.setter
    def _typo_pass(self, value):
        self._command_typo_pass.set(value)

    @_typo_pass.deleter
    def _typo_pass(self):
        self._command_typo_pass.set(_DELETED_COMMAND_FIELD)

    @property
    def _typo_orig(self):
        return _command_field(self._command_typo_orig, '_typo_orig')

    @_typo_orig.setter
    def _typo_orig(self, value):
        self._command_typo_orig.set(value)

    @_typo_orig.deleter
    def _typo_orig(self):
        self._command_typo_orig.set(_DELETED_COMMAND_FIELD)

    def __getattr__(self, name):
        if name in ('last_doc', 'speech_override'):
            return getattr(self._session(), name)
        raise AttributeError(name)

    def set_public(self, name, value):
        if name in ('last_doc', 'speech_override'):
            setattr(self._session(), name, value)
        else:
            setattr(self, name, value)


def _initialize(runtime):
    runtime._manual_local_stt = False  # Effective microphone route, captured when VoiceSession starts.
    runtime._prefetch_pool = runtime._cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="onhazir")
    if not runtime.logging.getLogger().handlers:
        handler = runtime.RotatingFileHandler(runtime.DATA_DIR / "jarvis.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
        try:
            runtime.logging.basicConfig(
                handlers=[handler], level=runtime.logging.INFO,
                format="%(asctime)s %(levelname)s %(message)s",
            )
        finally:
            # Another initialization may have configured logging first.
            if handler not in runtime.logging.getLogger().handlers:
                handler.close()
    runtime.log = runtime.logging.getLogger("jarvis")
    runtime.threading.Thread(target=runtime.system_control.installed_apps, daemon=True).start()
    runtime.migrate_legacy()
    runtime._profile_lock = runtime.threading.RLock()
    runtime._profiles: dict = {}
    runtime.profile = runtime._get_profile(runtime.get_active())
    runtime._llm.set_user_context(runtime.profile.slug)
    runtime.events: runtime.queue.Queue = runtime.queue.Queue()
    runtime.stop_event = runtime.threading.Event()
    runtime.pause_listening = runtime.threading.Event()
    runtime.mic_cancel = runtime.threading.Event()
    runtime.audio_lock = runtime.threading.Lock()
    runtime.flags = {"speak": True, "mic": True, "sleep": False}
    runtime._ui = None
    runtime.event_log: list[dict] = []
    runtime._log_id = 0
    runtime._event_lock = runtime.threading.RLock()
    from modules.response_waiters import ResponseWaiters
    runtime.response_waiters = ResponseWaiters()
    runtime._sessions = runtime.SessionStore()
    runtime._execution_lock = runtime.threading.RLock()
    runtime._guest: str | None = None
    runtime._home = None
    runtime._cur_source = ""
    runtime._cur_rid: str | None = None
    runtime._DAYS = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar")
    runtime._WEATHER_STOP = tr_speech_sets.WEATHER_STOP
    runtime._FILE_CMD = runtime.re.compile(r'^((?:"[^"]{4,400}"\s+){1,10})(.+)$')   # bir veya birden çok tırnaklı dosya yolu + istek
    runtime._IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic")
    runtime._MEDIA_Q = runtime.re.compile(r"(görsel\w*|resim\w*|fotoğraf\w*|şekil\w*|video\w*|wikipedia\w*|vikipedi\w*|youtube\w*)"
                          r".{0,40}(göster|aç|ver|bul|getir)|(göster|aç|ver|bul|getir)\w*.{0,20}(görsel|resim|video)")
    runtime._NAME_SUFFIXES = tr_speech_sets.NAME_SUFFIXES
    runtime._NOTE_HEAD = runtime.re.compile(
        r"^(?:(?:bunu|şunu|bir)\s+)?(?:not\s+olarak\s+(?:ekle|kaydet|al|yaz)\w*|not\s+defterine\s+(?:ekle|yaz)\w*"
        r"|not\s+(?:al|et|düş|ekle|yaz)\w*|nota\s+(?:ekle|al|yaz)\w*|notlara\s+(?:ekle|yaz)\w*|not|hatırlatma)\s*[:,.\-]?\s+(.+)$")
    runtime._NOTE_TAIL = runtime.re.compile(r"^(.+?)[\s,]+(?:diye\s+)?(?:not\s+(?:al|et|ekle|düş)\w*|nota\s+(?:ekle|al|yaz)\w*|notlara\s+ekle\w*)[.!]?$")
    runtime._last_note: dict[str, float] = {}
    runtime._PHOTO_DIR = runtime.DATA_DIR / "fotograflar"
    runtime._pending_photo: dict[str, dict] = {}
    runtime._MACRO_SPLIT = runtime.re.compile(r"\s*(?:,|\bve\b|\bsonra\b|\bardından\b)\s*")
    runtime._VERB_END = runtime.re.compile(r"\s+(aç|başlat|çalıştır)$")
    runtime._NONAPP = runtime.re.compile(r"\b(sesi|ses seviyesi|parlaklık|youtube|spotify|müzi[kğ]|şarkı|hava durumu|saat kaç|notlarım|dosya)\b")
    runtime._STEP_SPLIT = runtime.re.compile(r"\s*(?:,\s*)?(?:ve\s+)?(?:daha\s+)?(?:sonra|ardından|akabinde)\s*,?\s+", runtime.re.I)
    runtime._typo_pass = False
    runtime._typo_orig = ""
    runtime._JARVIS_MISHEAR = tr_speech_sets.JARVIS_MISHEAR
    runtime._LEAD_WORDS = {"hey", "hay", "hei", "der"}