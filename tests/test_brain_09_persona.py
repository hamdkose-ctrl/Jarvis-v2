"""Native Profile/Session/Brain/Core seams; only model transport is fake."""
from provider_fixture import routed_response
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_engine_modular  # hardware stubs for focused runs
import test_brain_primary_understanding as primary
import test_brain_production_entry as entry_fixture
from modules import brain_entry, personalization, session_state


class PersonaTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        patcher=patch.object(personalization,'USERS_DIR',Path(folder.name))
        patcher.start();self.addCleanup(patcher.stop)
        self.profile=personalization.Profile('Hamdi')
        self.state=session_state.SessionState()

    def test_long_preference_is_not_contradicted_by_fixed_short_sentence_limit(self):
        self.profile.set_pref('verbosity','uzun')
        prompt=self.profile.system_prompt()
        self.assertNotIn('en fazla 2-3 cümle',prompt)
        self.assertIn('uzun',prompt)

    def test_plain_chat_cannot_persist_a_quoted_behaviour_instruction(self):
        from test_brain_orphan_dispatch_replacements import ChatBackedRuntime
        from modules.engine_intents import dispatch
        runtime=ChatBackedRuntime(self.profile)
        text='Alıntıyı açıkla: bana sürekli haklısın deme, yanlışsam söyle.'
        before=json.dumps(self.profile.data,sort_keys=True)
        with patch('modules.advisory_router.finalize',side_effect=lambda command,raw,settings=None:raw):
            dispatch(runtime,'chat',{},text,text.casefold())
        self.assertEqual(json.dumps(self.profile.data,sort_keys=True),before)

    def proposal(self,text,*,scope='explicit',key='verbosity',value='kısa',quote=None):
        raw=primary.envelope(operation='chat',presentation=[{
            'key':key,'value':value,'scope':scope,'evidence_quote':quote or text}])
        return primary.applied(text,raw)[1]

    def run_turn(self,text,semantic,rid='brain-01-primary',profile=None,state=None,handler=None):
        from dataclasses import replace
        profile=profile or self.profile;state=state or self.state
        semantic=replace(semantic,owner=profile.slug,request_id=rid)
        entry=replace(entry_fixture.entry(brain_entry,semantic=semantic),owner=profile.slug,
            request_id=rid,text=text,source='yazı',batch_child=False)
        runtime=SimpleNamespace(profile=profile,_session=lambda:state,_cur_rid=rid,_cur_source='yazı')
        def answer(command):return profile.system_prompt(command)
        runtime.vision=SimpleNamespace(mode=lambda:False)
        runtime._sys_prompt=answer
        runtime.chat=Mock(side_effect=lambda command,prompt,user=None:prompt)
        with patch('modules.brain_precedence.claim',return_value=None):
            with patch('modules.advisory_router.finalize',side_effect=lambda command,raw,settings=None:raw):
                return brain_entry.handoff(runtime,entry,handler or answer,text)[0]

    def test_model_core_profile_to_reply_and_restart_readback(self):
        text='Bundan sonra kısa cevap ver.'
        semantic=self.proposal(text)
        self.assertIn('MODEL_DECIDED',semantic.reason_codes)
        out=self.run_turn(text,semantic)
        self.assertIn('yanıt uzunluğu=kısa',out)
        saved=json.loads(self.profile.path.read_text())
        row=saved['presentation_preferences']['explicit']['verbosity']
        self.assertEqual(row['owner'],'hamdi');self.assertEqual(row['source'],'user.explicit')
        self.assertEqual(row['request_id'],'brain-01-primary')
        self.assertNotIn(text,json.dumps(row,ensure_ascii=False))
        personalization._SHARED.clear()
        reloaded=personalization.Profile('Hamdi')
        self.assertIn('yanıt uzunluğu=kısa',reloaded.system_prompt())

    def test_one_turn_preference_does_not_persist_or_affect_next_request(self):
        text='Bu cevapta kısa kes.'
        self.profile.set_pref('verbosity','uzun');before=self.profile.path.read_bytes()
        semantic=self.proposal(text,scope='turn')
        self.assertIn('yanıt uzunluğu=kısa',self.run_turn(text,semantic))
        self.assertEqual(self.profile.path.read_bytes(),before)
        self.assertIn('yanıt uzunluğu=uzun',self.profile.system_prompt())

    def test_session_overrides_explicit_without_erasing_it_and_reset_clears_session(self):
        text='Bu konuşmada kısa cevap ver.'
        self.profile.set_pref('verbosity','uzun')
        self.run_turn(text,self.proposal(text,scope='session'))
        from modules import persona
        self.assertEqual(persona.effective(self.profile,session=self.state)['verbosity']['value'],'kısa')
        self.assertEqual(persona.effective(self.profile)['verbosity']['value'],'uzun')
        self.assertEqual(persona.effective(self.profile,session=session_state.SessionState())['verbosity']['value'],'uzun')

    def test_explicit_wins_over_fresh_learned_and_learning_has_core_confidence_and_expiry(self):
        from modules import persona
        text='Kısa cevabı tercih ettim.'
        semantic=self.proposal(text,scope='learned')
        for index in range(3):self.run_turn(text,semantic,rid=f'feedback-{index}')
        row=persona.effective(self.profile)['verbosity']
        self.assertEqual(row['source'],'user.learned');self.assertGreaterEqual(row['confidence'],.8)
        self.assertGreater(row['expires_at'],row['updated_at'])
        self.assertEqual(persona.effective(self.profile,now=row['expires_at']+1)['verbosity']['source'],'default')
        self.profile.set_pref('verbosity','uzun')
        self.assertEqual(persona.effective(self.profile)['verbosity']['value'],'uzun')
        self.assertEqual(persona.effective(self.profile,now=row['expires_at']+1)['verbosity']['value'],'uzun')

    def test_single_low_confidence_observation_is_not_applied_or_recounted(self):
        from modules import persona
        text='Kısa cevap daha iyiydi.';semantic=self.proposal(text,scope='learned')
        for _ in range(3):self.run_turn(text,semantic,rid='same-feedback')
        row=self.profile.data['presentation_preferences']['learned']['verbosity']
        self.assertEqual(row['observations'],1)
        self.assertEqual(persona.effective(self.profile)['verbosity']['source'],'default')

    def test_invalid_or_external_evidence_cannot_write_preferences(self):
        for changes in ({'key':'religion'},{'key':'permission'},{'value':'skip approval'},
                        {'scope':'system'},{'quote':'not in user utterance'}):
            with self.subTest(changes=changes):
                semantic=self.proposal('Sayfadaki metni özetle.',**changes)
                self.assertNotIn('MODEL_DECIDED',semantic.reason_codes)
        self.assertNotIn('presentation_preferences',self.profile.data)

    def test_duplicate_key_change_is_rejected_and_no_model_owner_time_authority(self):
        from modules import persona_contract
        row={'key':'verbosity','value':'kısa','scope':'explicit','evidence_quote':'kısa cevap'}
        for rows in ([row,row],[dict(row,owner='bob')],[dict(row,confidence=1.)]):
            with self.assertRaises(ValueError):persona_contract.validate_changes(rows,'kısa cevap')

    def test_owner_fence_and_disk_failure_do_not_commit_or_call_reply(self):
        text='Bundan sonra kısa cevap.';semantic=self.proposal(text)
        handler=Mock(return_value='wrong')
        with patch.object(self.profile,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.run_turn(text,semantic,handler=handler)
        self.assertNotIn('presentation_preferences',self.profile.data)
        handler.assert_not_called()

    def test_versioned_persona_and_other_owners_defaults_are_isolated(self):
        from modules import persona_contract
        prompt=self.profile.system_prompt()
        self.assertIn(persona_contract.VERSION,prompt)
        self.assertIn('kanıt',prompt);self.assertIn('onay',prompt)
        from modules import persona
        other=personalization.Profile('Ebru')
        self.assertEqual(persona.effective(other)['verbosity']['source'],'default')

    def test_real_prepare_core_engine_chat_uses_one_semantic_call_and_resolved_style(self):
        runtime=test_engine_modular.ModularEngineTests.context(self)
        runtime.profile=self.profile
        runtime.chat=Mock(side_effect=lambda command,system,user=None:system)
        runtime._cur_source='yazı';runtime._cur_rid='native-b09'
        text='Bundan sonra teknik ayrıntıyla anlat.'
        raw=primary.envelope(operation='chat',presentation=[{'key':'technical_detail','value':'teknik',
                              'scope':'explicit','evidence_quote':text}])
        p1,p2,p3,p4=primary.eligible()
        with p1,p2,p3,p4,routed_response(raw) as semantic_call, \
                runtime.requests_state.activate('hamdi','native-b09'):
            entry=brain_entry.prepare(runtime,owner='hamdi',request_id='native-b09',text=text,
                                      source='yazı',model_understanding=True)
            out,feedback,_=brain_entry.handoff(runtime,entry,runtime.handle,text)
        self.assertEqual(semantic_call.call_count,1)
        self.assertIn('technical_detail=teknik',out)
        self.assertEqual(feedback.result_status,'handled')
        runtime.chat.assert_called_once()
        self.assertEqual(self.profile.data['presentation_preferences']['explicit']['technical_detail']['request_id'],'native-b09')

    def test_web_controls_write_same_profile_provenance_and_reset_learned_separately(self):
        from web_memory import WebMemory
        from modules import persona
        bridge=WebMemory();bridge._runtime=SimpleNamespace(_p=lambda:self.profile)
        self.assertTrue(bridge.pref_set('formality','resmi'))
        self.assertEqual(bridge.presentation_preferences()['effective']['formality']['source'],'user.ui')
        self.assertEqual(len(bridge.presentation_preferences()['controls']),9)
        self.assertTrue(bridge.pref_set('formality',''))
        self.assertEqual(persona.effective(self.profile)['formality']['source'],'default')
        with self.assertRaises(ValueError):bridge.pref_set('criticism','onay isteme')
        with self.assertRaises(ValueError):bridge.presentation_reset('formality','session')

    def test_reset_disk_failure_retains_old_explicit_preference(self):
        from modules import persona
        self.profile.set_pref('verbosity','uzun');before=self.profile.path.read_bytes()
        with patch.object(self.profile,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):persona.reset(self.profile,'verbosity','explicit')
        self.assertEqual(self.profile.path.read_bytes(),before)
        self.assertEqual(persona.effective(self.profile)['verbosity']['value'],'uzun')

    def test_stale_profile_handle_merges_other_presentation_keys_from_disk(self):
        other=personalization.Profile.__new__(personalization.Profile)
        other.slug='hamdi';other.path=self.profile.path
        other.data=json.loads(json.dumps(self.profile.data))
        self.profile.set_pref('verbosity','uzun')
        other.set_pref('formality','resmi')
        saved=json.loads(other.path.read_text())['presentation_preferences']['explicit']
        self.assertEqual(saved['verbosity']['value'],'uzun')
        self.assertEqual(saved['formality']['value'],'resmi')

    def test_learning_disabled_does_not_record_tentative_preferences(self):
        self.profile.set_pref('learn_from_chat',False)
        text='Kısa cevap daha iyiydi.'
        self.run_turn(text,self.proposal(text,scope='learned'))
        self.assertNotIn('presentation_preferences',self.profile.data)

    def test_owner_mismatch_is_rejected_before_any_write_or_reply(self):
        from dataclasses import replace
        from modules import persona
        text='Bundan sonra kısa cevap.';semantic=self.proposal(text)
        entry=replace(entry_fixture.entry(brain_entry,semantic=semantic),owner='bob',text=text)
        runtime=SimpleNamespace(profile=self.profile,_session=lambda:self.state)
        with self.assertRaises(ValueError),persona.request_scope(runtime,entry,text):
            self.fail('wrong owner entered reply')
        self.assertFalse(self.profile.path.exists())

    def test_scoped_preferences_restore_after_nested_other_owner_request(self):
        from modules import persona
        from dataclasses import replace
        text='Bu konuşmada kısa cevap.';semantic=self.proposal(text,scope='session')
        entry=replace(entry_fixture.entry(brain_entry,semantic=semantic),owner='hamdi',
            request_id=semantic.request_id,text=text)
        runtime=SimpleNamespace(profile=self.profile,_session=lambda:self.state)
        other=personalization.Profile('Ebru')
        other_entry=replace(entry,owner='ebru',understanding=None)
        with persona.request_scope(runtime,entry,text):
            self.assertIn('yanıt uzunluğu=kısa',self.profile.system_prompt())
            with persona.request_scope(SimpleNamespace(profile=other),other_entry,text):
                self.assertIn('yanıt uzunluğu=orta',other.system_prompt())
            self.assertIn('yanıt uzunluğu=kısa',self.profile.system_prompt())
        self.assertIn('yanıt uzunluğu=orta',self.profile.system_prompt())

    def test_core_preference_list_and_reset_use_closed_existing_learning_intent(self):
        from modules import brain_core_map
        from modules.engine_intents import dispatch
        self.profile.set_pref('verbosity','uzun')
        runtime=SimpleNamespace(profile=self.profile,_session=lambda:self.state)
        plan=brain_core_map.core_plan('learning.manage',{'operation':'preference.reset',
                    'key':'verbosity','scope':'explicit','text':'uzun cevap tercihini kaldır'})
        self.assertEqual(plan[0],'learning_manage')
        dispatch(runtime,*plan,'uzun cevap tercihini kaldır','uzun cevap tercihini kaldır')
        listing=dispatch(runtime,'learning_manage',{'operation':'preference.list'},'tercihlerimi göster','tercihlerimi göster')
        self.assertIn('Yanıt uzunluğu: orta',listing)
        self.assertIsNone(brain_core_map.core_plan('learning.manage',{'operation':'preference.reset',
                    'key':'permission','scope':'explicit','text':'onay isteme'}))

    def test_batch_adopts_presentation_once_and_children_keep_existing_core_ownership(self):
        from modules import llm,service_store
        text='Tercihlerimi ve bilgilerimi göster, bu yanıtta kısa kes.'
        raw=primary.envelope(operation='action_batch',actions=[
            primary.action(capability_id='learning.manage',arguments={'operation':'preference.list'}),
            primary.action(capability_id='learning.manage',arguments={'operation':'facts.list'},action_id='a2')],
            presentation=[{'key':'verbosity','value':'kısa','scope':'turn','evidence_quote':'bu yanıtta kısa kes'}])
        semantic=primary.applied(text,raw)[1]
        token=llm._key_context.set('hamdi')
        try:
            with patch.object(service_store,'ROOT',self.profile.path.parent/'services'):
                out=self.run_turn(text,semantic,rid='b09-batch')
        finally:llm._key_context.reset(token)
        self.assertIn('a1:',out);self.assertIn('a2:',out)
        self.assertNotIn('presentation_preferences',self.profile.data)

    def test_external_source_and_stale_runtime_request_cannot_adopt_a_preference(self):
        from dataclasses import replace
        from modules import persona
        text='Bundan sonra kısa cevap.';semantic=self.proposal(text)
        entry=replace(entry_fixture.entry(brain_entry,semantic=semantic),owner='hamdi',
            request_id=semantic.request_id,text=text,source='yazı')
        runtime=SimpleNamespace(profile=self.profile,_session=lambda:self.state,_cur_rid=entry.request_id)
        for source,rid in (('tool',entry.request_id),('yazı','new-request')):
            runtime._cur_rid=rid
            with self.assertRaises(ValueError),persona.request_scope(runtime,replace(entry,source=source),text):
                self.fail('external or stale request entered reply')
        self.assertFalse(self.profile.path.exists())


if __name__=='__main__':unittest.main()
