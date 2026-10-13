"""Extracted task and voice bridges keep profile and action boundaries."""
from datetime import datetime
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import test_engine_modular as fixtures
from web_tasks import WebTasks
from web_voice import WebVoice

class TaskVoiceBridgeTests(unittest.TestCase):
    def test_task_calls_remain_with_each_profile(self):
        profiles=[SimpleNamespace(name='hamdi'),SimpleNamespace(name='ebru')]
        tasks=Mock()
        for p in profiles:
            bridge=WebTasks();bridge._runtime=SimpleNamespace(_p=lambda p=p:p,tasks=tasks)
            bridge.task_add('work','tomorrow')
        self.assertEqual([call.args[0] for call in tasks.add.call_args_list],profiles)

    def test_invalid_event_does_not_write_profile(self):
        profile=SimpleNamespace(add_event=Mock())
        bridge=WebTasks();bridge._runtime=SimpleNamespace(_p=lambda:profile,re=re,datetime=datetime)
        for title,when in [('meeting','2026-02-30'),('meeting','bad-date'),('','2026-10-10')]:
            with self.assertRaises(ValueError):bridge.event_add(title,when)
        profile.add_event.assert_not_called()
        bridge.event_add(' meeting ','2026-10-10T10:30')
        profile.add_event.assert_called_once_with('meeting','2026-10-10T10:30')

    def voice(self):
        profile=SimpleNamespace(set_pref=Mock())
        bridge=WebVoice();bridge._runtime=SimpleNamespace(_p=lambda:profile,engine=SimpleNamespace(events=Mock()),voice=SimpleNamespace(VOICES={'woman':('Kadın',)}),config=Mock(),_live=lambda:SimpleNamespace(enabled=lambda:False))
        bridge._runtime.config.load_settings.return_value = {}
        return bridge,profile

    def test_invalid_voice_changes_neither_preference_nor_speech(self):
        bridge,profile=self.voice()
        self.assertFalse(bridge.voice_set('invalid'))
        profile.set_pref.assert_not_called();bridge._runtime.engine.events.put.assert_not_called()

    def test_rate_is_bounded_and_saved_on_current_profile(self):
        bridge,profile=self.voice();bridge.rate_set(200)
        profile.set_pref.assert_called_once_with('rate',40)
        bridge._runtime.engine.events.put.assert_called_once_with(('say','Böyle konuşuyorum.'))

    def test_live_voice_selection_uses_current_session_preview(self):
        bridge,profile=self.voice();session=SimpleNamespace(preview=Mock())
        bridge._runtime._live=lambda:SimpleNamespace(enabled=lambda:True,VOICE_INFO={'Kore':'woman'},get=lambda:session)
        self.assertTrue(bridge.voice_set('Kore'))
        session.preview.assert_called_once_with('Kore','Merhaba, sesim böyle.')
        profile.set_pref.assert_not_called();bridge._runtime.config.save_settings.assert_not_called()
