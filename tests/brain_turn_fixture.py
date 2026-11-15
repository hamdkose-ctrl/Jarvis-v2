"""Explicit model proposals for worker/parity tests, never language acceptance.

Callers supply the decision and arguments. No keyword router or live model is
hidden here; prepare, State/Fast, Core validators and production workers run.
"""
from modules import core_brain_adapter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid
from unittest.mock import patch

from modules import brain_entry, requests_state
from modules.brain_contracts import ContextReference, ConversationRelation, RequestKind


def turn(runtime, text, capability=None, arguments=None, *, references=(), relation=ConversationRelation.NEW_REQUEST):
    def proposal(current, utterance, *, active_context=None):
        return replace(current, request_kind=RequestKind.CAPABILITY if capability else RequestKind.CHAT,
                       capability_hint=capability, arguments=arguments or {'original_text': utterance},
                       references=tuple(references), conversation_relation=relation,
                       ambiguities=(), needs_input=False, actions=())
    owner = runtime.profile.slug
    rid = 'fixture-' + uuid.uuid4().hex[:12]
    with TemporaryDirectory() as folder, patch.object(requests_state, '_journal', Path(folder)/'requests.json'), \
         patch.object(brain_entry, 'apply_model_understanding', side_effect=proposal):
        requests_state.register(owner, rid)
        with requests_state.activate(owner, rid):
            entry = brain_entry.prepare(runtime, owner=owner, request_id=rid, text=text,
                                        source='yazı', model_understanding=True)
            result, feedback, _ = core_brain_adapter.handoff(runtime, entry, runtime.handle, text)
    return result


def note_change(runtime, text, note, operation, replacement=None):
    ref = ContextReference(id=str(note['id']), kind='note', source='profile.items',
                           owner=runtime.profile.slug, provenance={
                               key: note.get(key) for key in ('text', 'title', 'ts', 'photo')})
    fields = {'id': str(note['id']), 'operation': operation}
    if replacement is not None:
        fields['text'] = replacement
    return turn(runtime, text, 'notes.write', {'notes': fields}, references=(ref,))


def batch_model(*specs):
    """Explicit independent action fixtures; no sentence splitting."""
    def proposal(current, text, *, active_context=None):
        return replace(current, request_kind=RequestKind.CAPABILITY,
                       capability_hint=None, arguments={'original_text': text},
                       conversation_relation=ConversationRelation.NEW_REQUEST,
                       ambiguities=(), needs_input=False, actions=tuple(
                           {'action_id': f'a{i}', 'capability_id': capability,
                            'arguments': arguments, 'reference_slots': [], 'depends_on': []}
                           for i, (capability, arguments) in enumerate(specs, 1)))
    return proposal


def reminder_change(runtime, text, arguments, *, approve=True):
    result = turn(runtime, text, 'reminders.manage', arguments)
    pending = runtime._session().pending_confirm
    if approve and isinstance(pending, dict) and pending.get('action') in {'reminder_delete', 'reminder_modify'}:
        # Assert this has not mutated the event before explicit State approval.
        event = next(e for e in runtime.profile.data['events'] if e['id'] == pending['event_id'])
        assert event['when'] == pending['when']
        result = turn(runtime, 'evet')
    return result
