"""Engine-side sinks for ``event_fanout``: one event, every enabled channel.

Channels are chosen per profile (``prefs.event_channels``); by default the
assistant view, the phone (ntfy, when the user enabled it) and the log.
"""
from __future__ import annotations

import json

from modules import event_fanout

DEFAULT_CHANNELS = ('ui', 'ntfy', 'log')


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

    sinks = {
        'ui': lambda _event: runtime._emit_for(profile, 'assistant', text),
        'ntfy': ntfy,
        'log': lambda _event: runtime.log.info('Olay %s/%s: %s', event['source'], event['kind'], owner),
    }
    result = event_fanout.dispatch(event, sinks, channels(prefs))
    if 'delivered' not in result.values():
        # Durable callers (source events) keep the record undelivered and retry.
        raise RuntimeError('Olay hiçbir kanala teslim edilemedi.')
    return result
