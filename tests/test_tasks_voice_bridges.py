"""Extracted task and voice bridges keep profile and action boundaries."""
from datetime import datetime
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
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
        profile=SimpleNamespace(slug='alice', data={'prefs':{}}, set_pref=Mock())
        bridge=WebVoice();bridge._runtime=SimpleNamespace(_p=lambda:profile,engine=SimpleNamespace(events=Mock()),voice=SimpleNamespace(VOICES={'woman':('Kadın',)}),config=Mock())
        bridge._runtime.config.load_settings.return_value = {}
        return bridge,profile

    def _edge_lane(self, *keys):
        from modules.voice_core import VoiceCatalog, VoiceSpec
        catalog=VoiceCatalog(tuple(VoiceSpec(k, k.title(), 'edge', f'tr-TR-{k.title()}Neural') for k in keys))
        lane=Mock();lane.catalog=catalog;lane.check_voice.side_effect=catalog.require
        return lane

    def test_invalid_voice_changes_neither_preference_nor_speech(self):
        # A lane is active but the identity is not in the installed catalog:
        # the selection is rejected by the exact-voice check, not by a missing owner.
        bridge,profile=self.voice()
        with patch('modules.voice_runtime.active',return_value=self._edge_lane('woman')):
            self.assertFalse(bridge.voice_set('invalid'))
        profile.set_pref.assert_not_called();bridge._runtime.engine.events.put.assert_not_called()

    def test_rate_is_bounded_and_saved_on_current_profile(self):
        bridge,profile=self.voice();bridge.rate_set(200)
        profile.set_pref.assert_called_once_with('rate',40)
        bridge._runtime.engine.events.put.assert_called_once_with(('say','Böyle konuşuyorum.'))

    def test_voice_selection_previews_through_single_owner_not_live(self):
        # Selecting an installed identity writes the profile voice and previews it
        # through the single owner's speech event; the retired Gemini Live
        # session.preview path is never used.
        bridge,profile=self.voice()
        with patch('modules.voice_runtime.active',return_value=self._edge_lane('woman')):
            self.assertTrue(bridge.voice_set('woman'))
        profile.set_pref.assert_called_once_with('voice','woman')
        bridge._runtime.engine.events.put.assert_called_once_with(('say','Merhaba, seçtiğin ses böyle.','alice'))
