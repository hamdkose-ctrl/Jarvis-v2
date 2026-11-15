"""Dilim 4: model-owned intent, session-bound output, no legacy text fallback.

Mock envelopes prove wiring and effect isolation, not real-model Turkish accuracy.
"""
from provider_fixture import routed_plan
import uuid
import dataclasses
import json
from pathlib import Path
from unittest.mock import Mock, patch

import test_engine_modular  # supplies the repository's headless hardware fixture
import test_brain_pr3_raw_text_authority as fixtures
from test_brain_b3_finance_authority import _model_envelope
from modules import brain_core_map, brain_entry, diagnose, engine_intents
from modules.brain_contracts import ConversationRelation, RequestKind


class OutputDiagnoseTests(fixtures._CanonicalAuthorityHarness):
    def setUp(self):
        super().setUp()
        self.doc = ('Rapor içeriği', None, 'rapor')
        self.ctx._session().last_doc = self.doc
        self.saved = Path(self.temp.name) / 'rapor.txt'
        self.saved.write_text(self.doc[0])
        self.save = Mock(return_value=str(self.saved))
        self.ctx.output.save_text_result = self.save
        self.probes = Mock(return_value=[{'name': 'Test', 'status': 'ok', 'detail': 'OK'}])
        self.model = Mock(return_value=_model_envelope('chat'))
        self.enterContext(routed_plan(count=1))
        for target, value in (
            ('modules.llm.current_user', lambda: self.owner),
            ('modules.llm.provider', lambda: 'groq'),
            ('modules.llm.privacy.mode', lambda: 'normal'),
            ('modules.smart_router.selection', lambda *a, **k: {'candidates': ['groq']}),
            ('modules.llm.dispatch', self.model),
            ('modules.diagnose.run', self.probes),
        ):
            p = patch(target, value); p.start(); self.addCleanup(p.stop)

    def prepared(self):
        from modules import requests_state
        rid = 'export-test-' + uuid.uuid4().hex
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            return brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid,
                text='Az önce hazırladığını bilgisayarımda tutmak istiyorum.', source='yazı', model_understanding=True)

    def proposal(self, capability, arguments=None):
        self.model.return_value = _model_envelope('direct_action', arguments, capability=capability)

    def test_model_can_export_without_a_deterministic_hint(self):
        self.proposal('documents.export')
        entry, out, *_ = self.turn_real('Az önce hazırladığını bilgisayarımda tutmak istiyorum.', model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, 'documents.export')
        self.save.assert_called_once_with(*self.doc)
        self.assertIn(str(self.saved), out)
        self.model.assert_called_once()

    def test_a_short_contextual_request_does_not_need_a_keyword_hint(self):
        self.proposal('documents.export')
        _, out, *_ = self.turn_real('bunu kaydet', model_understanding=True)
        self.save.assert_called_once_with(*self.doc)
        self.assertIn(str(self.saved), out)

    def test_model_chat_overrides_the_save_guess_in_the_real_handoff(self):
        envelope=json.loads(_model_envelope('chat'))
        envelope['confidence']='HIGH'
        self.model.return_value=json.dumps(envelope)
        entry, *_=self.turn_real('Raporu dosyaya yazmanı istemedim.',model_understanding=True)
        self.assertEqual(entry.understanding.request_kind.value,'CHAT')
        self.save.assert_not_called();self.probes.assert_not_called()

    def test_model_question_is_delivered_without_executing_an_action(self):
        self.ctx._session().last_doc=None
        envelope=json.loads(_model_envelope('clarify'))
        envelope.update(confidence='HIGH',clarification={
            'required':True,'question':'Hangi sonucu saklamamı istiyorsun?','reason_code':'OUTPUT_MISSING'})
        self.model.return_value=json.dumps(envelope)
        entry,out,*_=self.turn_real('Sonucu bilgisayarımda tut.',model_understanding=True)
        self.assertEqual(entry.understanding.request_kind.value,'CLARIFY')
        self.assertEqual(out,'Hangi sonucu saklamamı istiyorsun?')
        self.save.assert_not_called();self.probes.assert_not_called()

    def test_a_deterministic_low_guess_cannot_veto_the_model(self):
        from modules.brain_contracts import Confidence
        self.proposal('documents.export')
        envelope = json.loads(self.model.return_value)
        envelope['confidence'] = 'HIGH'
        self.model.return_value = json.dumps(envelope)
        real = brain_entry.understand
        def low_guess(**kwargs):
            return dataclasses.replace(real(**kwargs), confidence=Confidence.LOW)
        with patch.object(brain_entry, 'understand', side_effect=low_guess):
            self.turn_real('Hazırladığın sonucu sakla.', model_understanding=True)
        self.save.assert_called_once_with(*self.doc)

    def test_model_sees_only_output_metadata_not_document_content(self):
        self.proposal('documents.export')
        self.turn_real('Hazırladığın sonucu sakla.', model_understanding=True)
        prompt = self.model.call_args.args[2]
        self.assertIn('session_artifacts', prompt)
        self.assertIn('last_doc', prompt)
        self.assertNotIn('Rapor içeriği', prompt)

    def test_cancellation_does_not_turn_into_a_diagnosis(self):
        from modules import requests_state
        self.model.side_effect = requests_state.Cancelled('cancelled')
        with self.assertRaises(requests_state.Cancelled):
            self.turn_real('sistemi kontrol et', model_understanding=True)
        self.probes.assert_not_called()

    def test_the_real_output_adapter_writes_the_bound_result(self):
        from modules import output
        self.saved.unlink()
        self.saved = Path(self.temp.name) / 'rapor.docx'
        self.ctx.output.save_text_result = output.save_text_result
        self.proposal('documents.export')
        with patch.object(output, '_save_path', return_value=str(self.saved)):
            _, out, *_ = self.turn_real('Hazırladığın sonucu sakla.', model_understanding=True)
        from docx import Document
        self.assertIn(self.doc[0], '\n'.join(p.text for p in Document(self.saved).paragraphs))
        self.assertIn(str(self.saved), out)

    def test_model_can_diagnose_without_a_deterministic_hint(self):
        self.proposal('system.diagnose')
        entry, out, *_ = self.turn_real('Jarvis bir süredir aksıyor, nerede takıldığını inceleyebilir misin?', model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, 'system.diagnose')
        self.probes.assert_called_once_with(speak_flag=False, user_slug=self.owner)
        self.save.assert_not_called()
        self.assertTrue(out)

    def test_chat_and_irony_never_run_legacy_save_or_diagnosis(self):
        for text in ('çıktı al', 'sistemi kontrol et', 'Harika, yine bütün sistem tıkır tıkır çalışıyor(!)'):
            with self.subTest(text=text):
                self.turn_real(text, model_understanding=True)
        self.save.assert_not_called(); self.probes.assert_not_called()

    def test_model_failure_never_falls_back_to_the_old_phrases(self):
        self.model.side_effect = RuntimeError('provider unavailable')
        for text in ('çıktı al', 'sistemi kontrol et'):
            self.turn_real(text, model_understanding=True)
        self.save.assert_not_called(); self.probes.assert_not_called()

    def test_model_cannot_inject_an_export_target_or_diagnosis_action(self):
        for capability, args in (('documents.export', {'path':'/tmp/invented'}),
                                 ('documents.export', {'document_digest':'fake'}),
                                 ('system.diagnose', {'repair':True})):
            with self.subTest(capability=capability, args=args):
                self.proposal(capability, args)
                self.turn_real('Lütfen ilgilen.', model_understanding=True)
        self.save.assert_not_called(); self.probes.assert_not_called()

    def test_a_correction_chat_turn_keeps_its_relation_and_runs_no_effect(self):
        envelope = json.loads(_model_envelope('chat'))
        envelope['conversation_relation'] = 'CORRECTION'
        self.model.return_value = json.dumps(envelope)
        entry, out, *_ = self.turn_real('Onu ben istememiştim.', model_understanding=True)
        # Modelin anlamı prepare/handoff yoluna olduğu gibi iner: bağımsız düzeltme turu.
        self.assertEqual(entry.understanding.conversation_relation,
                         ConversationRelation.CORRECTION)
        self.assertEqual(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertIsNone(entry.understanding.capability_hint)
        self.save.assert_not_called()
        self.probes.assert_not_called()

    def test_missing_document_rejects_unoffered_export_without_effect_or_false_success(self):
        self.ctx._session().last_doc = None
        self.proposal('documents.export')
        _, out, *_ = self.turn_real('Bunu bilgisayarıma kaydet.', model_understanding=True)
        self.save.assert_not_called()
        self.probes.assert_not_called()
        self.assertIn('hiçbir işlem başlatmadım', out.casefold())

    def test_cancelled_dialog_does_not_claim_success(self):
        self.proposal('documents.export'); self.save.return_value = None
        _, out, *_ = self.turn_real('Son hazırladığını sakla.', model_understanding=True)
        self.assertEqual(out, 'Kaydetme iptal edildi.')
        self.save.assert_called_once()

    def test_unverified_saved_path_is_not_success(self):
        self.proposal('documents.export'); self.save.return_value = str(self.saved)+'-missing'
        _, out, *_ = self.turn_real('Son hazırladığını sakla.', model_understanding=True)
        self.assertNotIn('Çıktıyı kaydettim:', out)

    def test_stale_document_is_not_replaced_silently(self):
        self.proposal('documents.export')
        entry = self.prepared()
        plan = brain_entry.core_plan(entry)
        self.assertIsNotNone(plan)
        self.ctx._session().last_doc = ('Başka içerik', None, 'rapor')
        engine_intents.dispatch(self.ctx, plan[0], plan[1], entry.text, entry.text.casefold())
        self.save.assert_not_called()

    def test_another_owner_cannot_consume_the_export_plan(self):
        self.proposal('documents.export')
        entry = self.prepared()
        plan = brain_entry.core_plan(entry)
        self.assertIsNotNone(plan)
        args = {**plan[1], 'document_owner':'other-owner'}
        engine_intents.dispatch(self.ctx, plan[0], args, entry.text, entry.text.casefold())
        self.save.assert_not_called()

    def test_old_text_recognizers_are_physically_removed(self):
        from modules import command_manager
        self.assertFalse(hasattr(command_manager, '_OUTPUT_SAVE'))
        self.assertFalse(hasattr(command_manager, '_output_save_admin'))
        self.assertFalse(hasattr(diagnose, 'requested'))

    def test_core_has_closed_empty_model_arguments(self):
        for capability in ('documents.export', 'system.diagnose'):
            self.assertIsNotNone(brain_core_map.core_plan(capability, {}))
            self.assertIsNone(brain_core_map.core_plan(capability, {'unexpected':1}))
