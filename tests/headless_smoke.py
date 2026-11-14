"""Real PC/WebUI imports and Core/domain flow with explicit model decisions.

Hardware/provider boundaries are fake; this smoke does not measure language quality.
"""
import sys
import types
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    stub = types.ModuleType('pyautogui'); stub.__getattr__ = lambda attr: MagicMock(); sys.modules['pyautogui'] = stub
import main, web
from modules import brain_context, brain_entry, pc_guide
from modules.brain_contracts import RequestKind


@contextmanager
def model_decision(capability=None, arguments=None, *, references=(), question=None):
    def model(current, text, *, active_context=None):
        return replace(current,
            request_kind=RequestKind.CLARIFY if question else RequestKind.CAPABILITY if capability else RequestKind.CHAT,
            capability_hint=capability, references=tuple(references),
            arguments={'original_text': text, **(arguments or {}), **({'question': question} if question else {})},
            ambiguities=('MODEL_CLARIFICATION_REQUIRED',) if question else (),
            reason_codes=current.reason_codes + (('MODEL_CLARIFICATION_REQUIRED',) if question else ()), needs_input=bool(question))
    with patch.object(brain_entry, 'apply_model_understanding', side_effect=model):
        yield


def canonical(command, rid, capability=None, arguments=None, **kwargs):
    runtime = main._runtime
    owner = runtime.profile.slug
    runtime.requests_state.register(owner, rid)
    with model_decision(capability, arguments, **kwargs), runtime.requests_state.activate(owner, rid):
        entry = brain_entry.prepare(runtime, owner=owner, request_id=rid, text=command,
                                    source='yazı', model_understanding=True)
        return brain_entry.handoff(runtime, entry, runtime.handle, command)[0]


with patch.object(pc_guide, 'handle', return_value='Önce şu klasörü aç.') as coach:
    assert canonical('PC yardımı: fotoğraf gönderme', 'smoke-guide', 'pc.guide.start',
                     {'goal': 'fotoğraf gönderme'}) == 'Önce şu klasörü aç.'
    coach.assert_called_once()
with patch.object(pc_guide, 'stop') as stop, \
     patch.object(main.voice, 'stop_speaking') as voice_stop, \
     patch.object(main.requests_state, 'cancel_unambiguous',
                  return_value=('none', None)) as scoped, \
     patch.object(main.requests_state, 'cancel') as cancel_all:
    main.submit('dur', 'yazı', main.pc_profile().name)
    scoped.assert_called_once_with(main.pc_profile().slug)
    cancel_all.assert_not_called()
    stop.assert_not_called()  # Bare stop cannot cancel an unrelated guide.
    main.submit('rehberi durdur', 'yazı', main.pc_profile().name)
    stop.assert_called_once_with(main.pc_profile().slug)
    cancel_all.assert_not_called()
    assert voice_stop.call_count == 2
text = 'The pump must be inspected tomorrow.'
main.emit('user', text)
main.emit('assistant', 'Kısa özet')
active = brain_context.build_active_context(owner=main.profile.slug, request_id='smoke-history',
                                           session_store=main._runtime._sessions, profile=main.profile)
source = next(ref for ref in active.recent_references if ref.provenance.get('role') == 'user'
              and ref.provenance.get('text') == text)
with patch.object(main.tr, 'translate', return_value='Pompa yarın kontrol edilmeli.') as translate:
    result = canonical('metni çevir', 'headless-translate-1', 'text.translate',
        {'translate': {'target': 'Türkçe', 'text': text, 'origin': 'user', 'turn_id': source.id}}, references=(source,))
    assert translate.call_args.args[0] == text
main.emit('assistant', result)
with patch.object(main, 'ask', return_value='| İş | Zaman |\n|---|---|\n| Pompa kontrolü | Yarın |'):
    table = canonical('bunu tabloya çevir', 'smoke-table', 'conversation.table', {})
assert main.last_doc[0] == table
main.emit('assistant', table)
with patch.object(main._runtime, 'chat', return_value='Tamam.'):
    assert canonical('tamam', 'smoke-chat') == 'Tamam.'
web.bridge.chat_reset(); assert main.last_doc is None
assert canonical('çevir', 'headless-translate-2', question='Bu sohbette çevrilecek bir metin yok; hangi metni çevireyim?').startswith('Bu sohbette')
print('Headless: gerçek PC/WebUI, Core rehber→çeviri→tablo→sohbet→reset akışı geçti (açık model önerileri; dil/donanım kabulü değil).')
