"""Engine-side sinks for ``event_fanout``: one event, every enabled channel.

Channels are chosen per profile (``prefs.event_channels``); by default the
assistant view, the phone (ntfy, when the user enabled it) and the log. The
speaker is a fourth channel, off until the user asks for it (Ayarlar › Ses).
"""
from __future__ import annotations

import json

from modules import event_fanout
from modules.diagnostics import record_failure as _record_failure

DEFAULT_CHANNELS = ('ui', 'ntfy', 'log')
# A result that could not reach the speaker this soon is not news any more: the
# written notice already exists and stale audio would answer a question the user
# stopped asking. The single speech queue applies the bound itself, so a queued
# notice expires instead of being read out late.
SPEECH_TTL_SECONDS = 300.0


def render(event: dict) -> str:
    payload = event['payload']
    if isinstance(payload.get('text'), str) and payload['text'].strip():
        return payload['text'].strip()
    if event['source'] == 'whatsapp' and event['kind'] == 'incoming_batch':
        return ('WhatsApp: ' + str(payload.get('messages', 0)) + ' yeni mesaj, ' + str(payload.get('deliveries', 0)) +
                ' teslim kaydı. Gelen kutusu görevden okunabilir.')
    summary = json.dumps(payload, ensure_ascii=False)
    return 'Olay (' + event['source'] + ' · ' + event['kind'] + '): ' + (summary[:500] + ('…' if len(summary) > 500 else ''))


def channels(prefs: dict) -> list[str]:
    chosen = prefs.get('event_channels') if isinstance(prefs, dict) else None
    if not isinstance(chosen, list) or not chosen:
        chosen = list(DEFAULT_CHANNELS)
    result = []
    for channel in chosen:
        if channel == 'ntfy' and not prefs.get('ntfy_topic'):
            continue
        if isinstance(channel, str) and channel not in result:
            result.append(channel)
    return result or ['ui']


def announce_speech() -> bool:
    """Whether the speaker is asked for at all — the user's call, off by default.

    A scheduled task or a finished research run is written news the user may be
    nowhere near, so reading it aloud cannot be the silent default. The switch is
    the one in Ayarlar › Ses, and it costs nothing when the lane is absent: the
    engine loop still drops notices whose owner is not the foreground user.
    """
    try:
        from config import load_settings
        return bool(load_settings().get("voice_announce_results", False))
    except Exception:
        # A broken settings read keeps the speaker off — never guesses it on — but
        # the user has to be able to find out why their results went silent.
        _record_failure('modules/event_channels.py:announce_speech')
        return False


def speech_identity(event: dict) -> dict:
    """Name the result the utterance announces, in the vocabulary the queue owns.

    Every payload already carries a stable record id (``canonical:<job>``, an
    event id or a queue id); without it the same result would be spoken again on
    a retry, and the user's "dur" could not tell this notice from an answer.
    """
    payload = event['payload']
    record = (payload.get('event_id') or payload.get('job_id')
              or payload.get('queue_id') or '')
    event_id = str(record) if record else f"{event['source']}:{event['kind']}"
    identity = {'event_id': event_id, 'ttl_seconds': SPEECH_TTL_SECONDS}
    goal = payload.get('goal_id')
    if isinstance(goal, str) and goal.strip():
        identity['goal_id'] = goal.strip()
    version = payload.get('state_version')
    if type(version) is int and version >= 0:
        identity['state_version'] = version
    return identity


def deliver(runtime, owner: str, event: dict, *, title: str = 'Jarvis') -> dict | None:
    profile = next((runtime._get_profile(name) for name in runtime.list_users()
                    if runtime._get_profile(name).slug == owner), None)
    if profile is None:
        return None
    prefs = profile.data.get('prefs', {}) if isinstance(getattr(profile, 'data', None), dict) else {}
    text = render(event)

    def ntfy(_event):
        if not runtime.notify.send(prefs['ntfy_topic'], title, text[:3000]):
            raise ConnectionError('ntfy bildirimi gönderilemedi.')

    def voice(_event):
        # The same seam a reminder already uses: hand the words to the engine loop,
        # which owns the single speech lane. Nothing here blocks, waits for the
        # provider or plays audio, so a hung speaker can never stall the scheduler.
        runtime.events.put(("say", text, owner, speech_identity(event)))

    def ui(_event):
        # A swallowed window-callback error is not a delivery: the engine
        # returns False only when the UI sink really failed, and the fan-out
        # records that channel as failed instead of receipting "delivered".
        if runtime._emit_for(profile, 'assistant', text) is False:
            raise RuntimeError('Arayüz geri çağırması olayı işleyemedi.')

    chosen = channels(prefs)
    if announce_speech() and 'voice' not in chosen:
        chosen.append('voice')
    sinks = {
        'ui': ui,
        'ntfy': ntfy,
        'log': lambda _event: runtime.log.info('Olay %s/%s: %s', event['source'], event['kind'], owner),
        'voice': voice,
    }
    result = event_fanout.dispatch(event, sinks, chosen)
    if 'delivered' not in result.values():
        # Durable callers (source events) keep the record undelivered and retry.
        raise RuntimeError('Olay hiçbir kanala teslim edilemedi.')
    return result
