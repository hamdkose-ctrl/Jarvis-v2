"""Model meaning may replace an artifact heuristic; pending owners still own their turn."""
import unittest
from modules.brain_contracts import Confidence, ContextReference, ConversationRelation, PendingOwner, RequestKind
from test_brain_model_understanding_surfaces import asked, asked_apply, make_result, model_answer


class ModelDecisionAuthorityTests(unittest.TestCase):
    def artifact_context(self):
        return make_result(request_kind=RequestKind.CAPABILITY,
            conversation_relation=ConversationRelation.CONTINUE_ACTIVE,
            references=(ContextReference(id='last_doc',kind='artifact',source='session_state',owner='hamdi'),))

    def test_chat_can_override_a_save_guess_with_only_an_artifact_in_context(self):
        result=asked_apply(model_answer(confidence='HIGH'), 'Artık dosya istemiyorum.', self.artifact_context())
        self.assertEqual(result.request_kind,RequestKind.CHAT)
        self.assertEqual(result.confidence,Confidence.HIGH)
        self.assertIsNone(result.capability_hint)

    def test_clarification_is_adopted_instead_of_silently_returning_the_guess(self):
        raw=model_answer(operation='clarify',confidence='HIGH',
            clarification={'required':True,'question':'Hangi sonucu kastettin?','reason_code':'TARGET_MISSING'})
        result=asked_apply(raw,'O sonucu sakla.',make_result())
        self.assertEqual(result.request_kind,RequestKind.CLARIFY)
        self.assertTrue(result.needs_input)
        self.assertEqual(result.arguments['question'],'Hangi sonucu kastettin?')

    def test_a_real_pending_owner_cannot_be_replaced_by_the_model(self):
        pending=make_result(conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
                            pending_owner=PendingOwner.APP_CLARIFY)
        self.assertIsNone(asked(model_answer(confidence='HIGH'),'Cevabım bu.',pending,protected_relation=True))

    def test_model_clarification_reaches_the_existing_entry_question_path(self):
        from types import SimpleNamespace
        from modules import brain_entry
        raw=model_answer(operation='clarify',confidence='MEDIUM',
            clarification={'required':True,'question':'Neyi karşılaştırmamı istersin?','reason_code':'TARGET_MISSING'})
        result=asked_apply(raw,'Karşılaştır.',make_result())
        entry=SimpleNamespace(state_gate=SimpleNamespace(reason_code=None),understanding=result)
        self.assertEqual(brain_entry.clarification(entry),'Neyi karşılaştırmamı istersin?')

    def test_rejection_code_distinguishes_pending_fence_and_resets_for_the_next_call(self):
        from modules.brain_model_understanding import proposal_diagnostic
        pending=make_result(conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
                            pending_owner=PendingOwner.APP_CLARIFY)
        asked(model_answer(),'Cevabım.',pending,protected_relation=True)
        self.assertEqual(proposal_diagnostic()['reason_code'],'PROTECTED_RELATION')
        asked(model_answer(),'Başka konu.',make_result())
        self.assertEqual(proposal_diagnostic()['status'],'accepted')
        self.assertIsNone(proposal_diagnostic()['reason_code'])

    def test_rejected_arguments_are_not_retained_in_diagnostics(self):
        import json
        from modules.brain_model_understanding import proposal_diagnostic
        raw=json.loads(model_answer(operation='direct_action',confidence='MEDIUM'))
        raw['actions']=[{'action_id':'a1','capability_id':'documents.export',
            'arguments':{'path':'SECRET_CONTENT'},'reference_slots':[], 'depends_on':[], 'argument_sources':None}]
        self.assertIsNone(asked(json.dumps(raw),'Sakla.',make_result()))
        diagnostic=proposal_diagnostic()
        self.assertIn(diagnostic['reason_code'],{'ARGUMENTS_INVALID','ARGUMENT_AUTHORITY_FIELD'})
        self.assertEqual(diagnostic['capabilities'],['documents.export'])
        self.assertNotIn('SECRET',repr(diagnostic))
