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

    def test_a_chat_correction_in_a_free_artifact_turn_is_adopted(self):
        result = asked_apply(model_answer(confidence='HIGH', conversation_relation='CORRECTION'),
                             'Onu ben istememiştim.', self.artifact_context())
        self.assertEqual(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)
        # Modelin anlamı korunur: sahipliği olmayan serbest turda CORRECTION etiketi
        # kanonikal değere yazılmaz, bağımsız düzeltme turu olarak kalır.
        self.assertEqual(result.conversation_relation, ConversationRelation.CORRECTION)

    def test_independent_chat_correction_preserves_the_real_pending_owner(self):
        pending = make_result(conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
                              pending_owner=PendingOwner.APP_CLARIFY)
        result = asked(model_answer(confidence='HIGH', conversation_relation='CORRECTION'),
                       'Onu ben istememiştim.', pending, protected_relation=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.operation, 'chat')
        self.assertIs(result.conversation_relation, ConversationRelation.CORRECTION)
        self.assertIs(pending.pending_owner, PendingOwner.APP_CLARIFY)

    def test_goal_card_does_not_turn_independent_chat_correction_into_goal_effect(self):
        owned = make_result(request_kind=RequestKind.CAPABILITY,
            conversation_relation=ConversationRelation.CONTINUE_ACTIVE,
            references=(ContextReference(id='last_doc', kind='artifact', source='session_state',
                                         owner='hamdi'),
                        ContextReference(id='goal-1', kind='goal', source='goal_state', owner='hamdi')))
        result = asked(model_answer(confidence='HIGH', conversation_relation='CORRECTION'),
                       'Onu ben istememiştim.', owned, protected_relation=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.operation, 'chat')
        self.assertEqual(result.actions, ())
        self.assertIs(owned.request_kind, RequestKind.CAPABILITY)

    def test_an_action_proposal_cannot_use_the_free_correction_path(self):
        from modules.brain_model_understanding import proposal_diagnostic
        raw = model_answer(operation='direct_action', confidence='HIGH',
                           conversation_relation='CORRECTION',
                           actions=[{'action_id': 'a1', 'capability_id': 'system.diagnose',
                                     'arguments': {}, 'reference_slots': [], 'depends_on': [],
                                     'argument_sources': None}])
        self.assertIsNone(asked(raw, 'Onu ben istememiştim.', self.artifact_context(),
                                protected_relation=True))
        self.assertEqual(proposal_diagnostic()['reason_code'], 'PROTECTED_CORRECTION_ACTION')

    def test_clarification_is_adopted_instead_of_silently_returning_the_guess(self):
        raw=model_answer(operation='clarify',confidence='HIGH',
            clarification={'required':True,'question':'Hangi sonucu kastettin?','reason_code':'TARGET_MISSING'})
        result=asked_apply(raw,'O sonucu sakla.',make_result())
        self.assertEqual(result.request_kind,RequestKind.CLARIFY)
        self.assertTrue(result.needs_input)
        self.assertEqual(result.arguments['question'],'Hangi sonucu kastettin?')

    def test_a_real_pending_owner_is_not_consumed_by_independent_model_chat(self):
        # A NEW_REQUEST is not an answer to the pending app clarification.
        # Model may chat independently, but the State owner must remain
        # unchanged and no pending command may run as a side effect.
        pending=make_result(conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
                            pending_owner=PendingOwner.APP_CLARIFY)
        decision=asked(model_answer(confidence='HIGH'),'Cevabım bu.',pending,protected_relation=True)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.operation, 'chat')
        self.assertIs(decision.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIs(pending.pending_owner, PendingOwner.APP_CLARIFY)

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
        pending = make_result(request_kind=RequestKind.CAPABILITY,
                              conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
                              pending_owner=PendingOwner.APP_CLARIFY)
        # A claimed ANSWER_TO_PENDING cannot replace a pending capability's
        # owner with CHAT; it is not an independent NEW_REQUEST.
        rejected = asked(model_answer(conversation_relation='ANSWER_TO_PENDING'),
                         'Cevabım.', pending, protected_relation=True)
        self.assertIsNone(rejected)
        self.assertEqual(proposal_diagnostic()['reason_code'], 'PROTECTED_REQUEST_KIND')
        accepted = asked(model_answer(), 'Başka konu.', make_result())
        self.assertIsNotNone(accepted)
        self.assertEqual(proposal_diagnostic()['status'], 'accepted')
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
