"""Live component behavior with fake sessions; no audio device or cloud service."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_engine_modular as fixtures
from modules import live,requests_state

class LiveComponentTests(unittest.TestCase):
    def live(self):
        instance=live.Live.__new__(live.Live)
        instance.emit=Mock();instance._in_buf=[];instance._out_buf=[]
        instance._recent_user=[];instance._convo=[];instance._suppress_output_turns=0
        instance._tools_running=0
        return instance

    def test_transcripts_stay_in_their_own_instance_and_flush_once(self):
        first=self.live();second=self.live()
        first._in_buf=[' hamdi ',' sorusu '];second._in_buf=[' ebru ']
        first._out_buf=['ilk ','yanıt']
        with patch.object(live,'apply_fixes',side_effect=lambda text:'düzeltildi '+text):
            self.assertEqual(first._flush_transcripts(),'ilk yanıt')
            second._flush_user();self.assertEqual(first._flush_transcripts(),'')
        self.assertEqual(first._convo,[('user','düzeltildi hamdi sorusu'),('assistant','ilk yanıt')])
        self.assertEqual(second._convo,[('user','düzeltildi ebru')])
        self.assertEqual(first._recent_user,['hamdi sorusu'])
        self.assertEqual(first.emit.call_count,2)

    def test_already_displayed_answer_is_not_emitted_again(self):
        instance=self.live();instance._suppress_output_turns=1;instance._out_buf=['answer']
        self.assertEqual(instance._flush_transcripts(),'answer')
        instance.emit.assert_not_called();self.assertEqual(instance._convo,[])
        self.assertEqual(instance._suppress_output_turns,0)

    def test_cancelled_preparation_does_not_execute_direct_operation(self):
        instance=self.live();operation=Mock()
        instance.prepare_tool=Mock(side_effect=requests_state.Cancelled('stop'))
        with self.assertRaises(requests_state.Cancelled):asyncio.run(instance._direct_tool(operation,'arg'))
        operation.assert_not_called();instance.prepare_tool.assert_called_once_with(operation,'arg')

    def test_failed_direct_tool_cleans_counter_and_responds_to_same_call(self):
        instance=self.live();instance._tools_running=1
        instance.wants_sleep=lambda:False
        instance.prepare_tool=Mock(side_effect=requests_state.Cancelled('stop'))
        sent=[]
        async def respond(**kwargs):sent.extend(kwargs['function_responses'])
        session=SimpleNamespace(send_tool_response=respond)
        fc=SimpleNamespace(name='yanlis_duyma',args={'dogru':'takvimi aç'},id='original-call')
        with patch('modules.learning.learn_mishearing') as fix:
            asyncio.run(instance._run_tool(session,fc))
        fix.assert_not_called();self.assertEqual(instance._tools_running,0)
        self.assertEqual(sent[0].id,'original-call')
        self.assertEqual(sent[0].name,'yanlis_duyma')
        self.assertIn('Yapamadım',sent[0].response['sonuc'])

    def test_uuid_phone_suffix_preserved_but_real_phones_redacted(self):
        from modules import privacy
        identifier='a'*22+'5551234567'
        text=privacy.redact('id="'+identifier+'" tel=05551234567; +90 555 123 45 67',force=True)
        self.assertIn(identifier,text)
        self.assertNotIn('05551234567',text)
        self.assertNotIn('+90 555 123 45 67',text)
        self.assertEqual(text.count('[telefon gizlendi]'),2)
        self.assertIn('[telefon gizlendi]',privacy.redact('a5551234567b',force=True))
