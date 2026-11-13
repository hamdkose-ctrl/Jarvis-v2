"""BRAIN-03 production continuations; model/device boundaries are fake."""
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import test_brain_pr3_raw_text_authority as fixtures
from modules import brain_core_map, brain_entry, brain_model_understanding, goal_executor, goal_resolver
from modules.brain_contracts import Confidence, ConversationRelation, GoalOperation, RequestKind, TemporalNeed
from test_brain_primary_understanding import envelope


class CompletionWiringTests(fixtures._CanonicalAuthorityHarness):
    def typed(self, text, capability, arguments, *, relation=ConversationRelation.NEW_REQUEST):
        def model(current, utterance, *, active_context=None):
            return replace(current, request_kind=RequestKind.CAPABILITY,
                           capability_hint=capability, arguments=arguments,
                           conversation_relation=relation, ambiguities=(), needs_input=False)
        with patch.object(brain_entry, 'apply_model_understanding', side_effect=model):
            return self.turn_real(text, model_understanding=True)

    def clock(self):
        now = datetime(2026, 10, 17, 10)
        self.ctx.datetime = SimpleNamespace(now=lambda: now)
        return now

    def approve(self):
        return self.turn_real('evet')[1]

    def test_meeting_prep_reaches_existing_read_worker_without_raw_selector(self):
        from modules import meeting_prep
        now = self.clock()
        with patch.object(self.ctx.privacy, 'blocked', return_value=None), \
             patch.object(meeting_prep, 'prepare', return_value='MEETING') as reader, \
             patch.object(meeting_prep, 'handle', side_effect=AssertionError('raw selector')):
            entry, output, _, feedback = self.typed(
                "Ayşe ile toplantıma hazırlan", 'calendar.read',
                {'view': 'meeting_prep', 'period': None, 'query': 'Ayşe'})
        self.assertEqual(output, 'MEETING')
        self.assertEqual(feedback.result_status, 'handled')
        reader.assert_called_once_with(self.ctx.profile, now, query='Ayşe')

    def test_model_correction_action_is_rejected_with_neutral_pending_evidence(self):
        self.ctx._session().pending_msg = {'stage': 'text', 'to': 'Ayşe'}
        raw = envelope(operation='direct_action', conversation_relation='CORRECTION',
                       actions=[{'action_id': 'a1', 'capability_id': 'notes.add',
                                 'arguments': {'text': 'yeni metin'},
                                 'argument_sources': {'text': 'yeni metin'},
                                 'reference_slots': [], 'depends_on': []}])
        with patch('modules.llm.current_user', return_value=self.owner), \
             patch('modules.llm.provider', return_value='groq'), \
             patch('modules.llm.privacy.mode', return_value='normal'), \
             patch('modules.smart_router.selection', return_value={'candidates': ['groq']}), \
             patch('modules.smart_router.run', return_value=raw), \
             patch.object(self.ctx, '_add_note', side_effect=AssertionError('correction wrote note')) as note:
            _, _, _, feedback = self.turn_real('hayır, yeni metin', model_understanding=True)
        self.assertEqual(feedback.result_status, 'failed')
        self.assertEqual(brain_model_understanding.proposal_diagnostic()['reason_code'], 'PROTECTED_CORRECTION_ACTION')
        self.assertEqual(self.ctx._session().pending_msg, {'stage': 'text', 'to': 'Ayşe'})
        note.assert_not_called()

    def test_model_owned_desktop_answer_reaches_only_desktop_worker(self):
        from modules import desktop_agent
        raw = brain_model_understanding.UnderstandingProposal(
            operation='chat', conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
            temporal_need=TemporalNeed.UNSURE, confidence=Confidence.HIGH)
        # Persisted native question must survive a missing in-memory session flag.
        self.ctx._session().pending_desktop = None
        with patch.object(brain_model_understanding, 'propose', return_value=raw), \
             patch.object(desktop_agent, 'consent_reply', return_value=None), \
             patch.object(desktop_agent, '_load', return_value={'id': 'pc1', 'status': 'question', 'question': 'Hangi pencere?'}), \
             patch.object(desktop_agent, 'answer_typed', return_value='PC ANSWER') as worker, \
             patch.object(desktop_agent, 'awaiting', return_value=True), \
             patch.object(desktop_agent, 'spoken', return_value='Bekliyor'):
            _, output, _, _ = self.turn_real('açık pencereyi kullan', model_understanding=True)
        self.assertEqual(output, 'PC ANSWER')
        self.assertEqual(worker.call_args.args[:2], (self.owner, 'açık pencereyi kullan'))
        self.assertEqual(worker.call_args.kwargs['expected_job_id'], 'pc1')
        self.assertEqual(worker.call_args.kwargs['expected_question'], 'Hangi pencere?')

    def test_clock_survives_artifact_binding_and_is_never_a_target_reference(self):
        from modules.brain_contracts import ContextReference
        self.clock()
        artifact = ContextReference(id='document', owner=self.owner, kind='artifact', source='test')
        active = brain_entry._build_context(self.ctx, self.owner, 'clock', artifact)
        self.assertTrue(active.current_time.startswith('2026-10-17T10:00:00'))
        pending = ContextReference(id='p', owner=self.owner, kind='pending_state', source='test')
        self.assertEqual(brain_entry._append_pending(active, pending).current_time, active.current_time)
        self.assertFalse(any(ref.id == 'current_time' for ref in active.recent_references))

    def test_failed_note_save_restores_the_observed_text(self):
        from brain_turn_fixture import note_change
        self.ctx.profile.add_note_item('eski metin')
        note = self.ctx.profile.data['items'][0]
        with patch.object(self.ctx.profile, 'save', side_effect=OSError('disk full')), \
             patch.object(self.ctx, '_record_failure'):
            with self.assertRaises(OSError):
                note_change(self.ctx, 'bu notu değiştir yeni metin', note, 'update', 'yeni metin')
        self.assertEqual(note['text'], 'eski metin')

    def test_development_request_cannot_apply_and_password_gate_is_real(self):
        from pathlib import Path
        from modules import developer
        with patch.object(developer, 'STORE', Path(self.temp.name) / 'development'), \
             patch.object(developer, '_AUTH', set()), \
             patch.object(developer, '_turn', return_value='DRAFT') as turn, \
             patch.object(developer, '_apply', return_value='APPLIED') as apply:
            _, output, _, _ = self.typed('taslak hazırla', 'development.manage',
                {'operation': 'request', 'goal': 'taslak hazırla'})
            self.assertIn('şifrenle', output)
            turn.assert_not_called()
            apply.assert_not_called()
            state = developer._load(self.owner)
            state['enabled'] = True
            with patch.object(developer, '_AUTH', {self.owner}), \
                 patch.object(developer, '_load', return_value=state), \
                 patch.object(developer, '_recover'):
                _, output, _, _ = self.typed('değişiklikleri uygula metnini açıkla', 'development.manage',
                    {'operation': 'request', 'goal': 'değişiklikleri uygula'})
                self.assertEqual(output, 'DRAFT')
                apply.assert_not_called()
                self.assertEqual(turn.call_args.args[2], 'değişiklikleri uygula')
                self.typed('değişiklikleri uygula?', 'development.manage', {'operation': 'apply'})
                apply.assert_not_called()
                self.typed('taslağı uygula', 'development.manage', {'operation': 'apply'})
                apply.assert_called_once_with(self.owner, state)

    def test_relative_reminder_waits_for_approval_and_invalidates_old_audio(self):
        from modules import voice_runtime
        self.clock()
        self.ctx.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        before = self.ctx.profile.data['events'][0]['when']
        with patch.object(voice_runtime, 'invalidate', return_value=1) as invalidated:
            _, output, _, _ = self.typed('İlaç için yarım saat ertele', 'reminders.manage',
                                        {'operation': 'postpone', 'title': 'İlaç', 'duration': 'yarım saat'})
            self.assertIn('onaylıyor musun', output)
            self.assertEqual(self.ctx.profile.data['events'][0]['when'], before)
            invalidated.assert_not_called()
            self.approve()
        self.assertEqual(self.ctx.profile.data['events'][0]['when'], '2026-10-18T09:30')
        invalidated.assert_called_once()

    def test_snooze_keeps_next_recurring_occurrence(self):
        self.ctx.profile.add_event('İlaç', '2026-10-17T09:30', repeat='daily')
        self.ctx.profile.due_events(self.clock())
        self.typed('İlaç 10 dakika sonra tekrar çalsın', 'reminders.manage',
                   {'operation': 'postpone', 'title': 'İlaç', 'duration': '10 dakika', 'occurrence': 'fired'})
        self.approve()
        event = self.ctx.profile.data['events'][0]
        self.assertEqual((event['when'], event['snooze']), ('2026-10-18T09:30', '2026-10-17T10:10'))

    def test_absolute_reminder_date_keeps_its_clock_and_checks_changed_notification(self):
        self.clock()
        self.ctx.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')
        self.typed('Toplantı cumaya kaysın', 'reminders.manage',
                   {'operation': 'postpone', 'title': 'Toplantı', 'schedule': 'cumaya'})
        self.assertEqual(self.ctx._session().pending_confirm['new_when'], '2026-10-23T10:00')
        event = self.ctx.profile.data['events'][0]
        event['fired'] = '2026-10-17T10:00'
        self.ctx.profile.save()
        self.assertIn('çalma durumu', self.approve())
        self.assertEqual(event['when'], '2026-10-19T10:00')

    def test_invalid_delay_and_mixed_absolute_relative_are_rejected_before_worker(self):
        for arguments in ({'operation': 'postpone', 'title': 'İlaç', 'duration': 'bir süre'},
                          {'operation': 'postpone', 'title': 'İlaç', 'duration': '10 dakika', 'schedule': 'yarın'},
                          {'operation': 'delete', 'target': 'all'},
                          {'operation': 'skip', 'title': 'İlaç', 'occurrence': 'fired'}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(brain_core_map.core_plan('reminders.manage', arguments))


class GoalAnswerWiringTests(unittest.TestCase):
    def test_explicit_model_answer_carries_user_text_to_the_selected_question(self):
        import test_brain_b5_goal_resolver as existing
        existing.GoalResolverTests.setUp(self)
        ident = existing.GoalResolverTests.seed(self, 'dosyayı incele', state='question')
        job = goal_executor.read_job(existing.OWNER, ident)
        job['question'] = 'Hangi dosyayı incelemeliyim?'
        goal_executor._save(job)
        offered = __import__('modules.brain_context', fromlist=['_goal_card'])._goal_card(
            existing.OWNER, goal_executor.read_job(existing.OWNER, ident))
        entry = existing.goal_entry(offered, operation=GoalOperation.CONTINUE,
                                    targets=(ident,), text='masaüstündeki rapor')
        entry.understanding = replace(entry.understanding,
                                      conversation_relation=ConversationRelation.ANSWER_TO_PENDING)
        with patch.object(goal_executor, 'run', return_value='ANSWER ACCEPTED') as run:
            result = goal_resolver.resolve(self.runtime, entry)
        self.assertEqual(result.message, 'ANSWER ACCEPTED')
        self.assertEqual(run.call_args.args[1], 'masaüstündeki rapor')
        self.assertEqual(run.call_args.kwargs['job_id'], ident)
        self.assertEqual(run.call_args.kwargs['expected_control'], goal_executor.control_key(job))


class ModelBindingContractTests(unittest.TestCase):
    """Real wire decoder and adapters, including response-validator pass."""
    owner = 'hamdi'

    def propose(self, capability, arguments, *, refs=(), sources=None, slots=(), turns=(), raw_text='istek'):
        from modules.brain_contracts import UnderstandingResult
        current = UnderstandingResult(owner=self.owner, request_id='binding', request_kind=RequestKind.CHAT,
                                      references=tuple(refs), arguments={'original_text': raw_text})
        raw = envelope(actions=[{'action_id': 'a1', 'capability_id': capability,
            'arguments': arguments, 'argument_sources': sources, 'reference_slots': list(slots), 'depends_on': []}])
        def transport(owner, payload, send, **kwargs):
            self.payload = payload
            kwargs['validator'](raw)
            return raw
        with patch('modules.llm.current_user', return_value=self.owner), \
             patch('modules.llm.provider', return_value='groq'), \
             patch('modules.llm.privacy.mode', return_value='normal'), \
             patch('modules.smart_router.selection', return_value={'candidates': ['groq']}), \
             patch('modules.smart_router.run', side_effect=transport), \
             patch.object(brain_model_understanding, '_record_failure'):
            return brain_model_understanding.propose(owner=self.owner, text=raw_text, current=current,
                arguments=current.arguments, turn_candidates=tuple(turns),
                recent_turns=tuple({'id': ref.id, 'role': ref.provenance['role'],
                                    'text': ref.provenance['text']} for ref in turns),
                current_time='2026-11-13T10:00:00+03:00')

    def test_every_advertised_core_capability_has_an_argument_contract(self):
        for capability in brain_core_map.CORE_INTENTS:
            with self.subTest(capability=capability):
                schema = brain_model_understanding._supplied_schema(capability)
                self.assertTrue(schema)
                self.assertNotIn('freeform', schema)

    def test_historical_translation_binds_full_source_from_an_offered_turn(self):
        import json
        from modules.brain_contracts import ContextReference
        source = 'Gerçek ve uzun konuşma metni. ' * 40
        ref = ContextReference(id='turn-1', owner=self.owner, kind='conversation_turn', source='history',
                               provenance={'role': 'assistant', 'text': source})
        proposal = self.propose('text.translate', {'translate': {
            'target': 'İngilizce', 'origin': 'assistant', 'turn_id': ref.id}}, turns=(ref,))
        self.assertIsNotNone(proposal)
        bound = proposal.actions[0].arguments['translate']['text']
        self.assertEqual(bound, source)
        payload = json.loads(self.payload.split('\\n', 1)[0])
        self.assertEqual(payload['recent_turns'][0]['id'], ref.id)
        self.assertEqual(len(payload['recent_turns'][0]['text']), 350)
        self.assertEqual(payload['current_time'], '2026-11-13T10:00:00+03:00')
        for invalid in (replace(ref, owner='başkası'), replace(ref, id='different'), replace(ref, source='unoffered'),
                        replace(ref, provenance={'role': 'user', 'text': source})):
            self.assertIsNone(self.propose('text.translate', {'translate': {
                'target': 'İngilizce', 'origin': 'assistant', 'turn_id': ref.id}}, turns=(invalid,)))
        self.assertIsNone(self.propose('text.translate', {'translate': {
            'target': 'İngilizce', 'origin': 'assistant', 'turn_id': ref.id, 'text': 'uydurma'}}, turns=(ref,)))

    def test_file_mutation_and_translation_use_observed_paths_only(self):
        from modules.brain_contracts import ContextReference
        from pathlib import Path
        from tempfile import TemporaryDirectory
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'report.txt'
        path.write_text('gerçek dosya', encoding='utf-8')
        self.file_path = str(path)
        allowed = patch('modules.nxapi.allowed', side_effect=lambda target: path if Path(target) == path else None)
        allowed.start(); self.addCleanup(allowed.stop)
        ref = ContextReference(id='f1', owner=self.owner, kind='file', source='files',
                               provenance={'path': self.file_path, 'name': 'report.txt'})
        proposal = self.propose('files.mutate', {'operation': 'rename', 'name': 'sonuç.txt'},
            sources={'name': 'sonuç.txt'}, slots=('file_0',), refs=(ref,), raw_text='adını sonuç.txt yap')
        self.assertIsNotNone(proposal)
        plan = brain_core_map.core_plan('files.mutate', proposal.actions[0].arguments)
        self.assertEqual(plan[1]['path'], self.file_path)
        self.assertEqual(plan[1]['name'], 'sonuç.txt')
        attached = self.propose('development.manage', {'operation': 'request', 'goal': 'taslak hazırla'},
            sources={'goal': 'taslak hazırla'}, slots=('file_0',), refs=(ref,), raw_text='taslak hazırla')
        self.assertIsNotNone(attached)
        self.assertEqual(brain_core_map.core_plan('development.manage', attached.actions[0].arguments)[1]['reference_paths'], (self.file_path,))
        self.assertIsNone(self.propose('development.manage', {'operation': 'request', 'goal': 'taslak hazırla',
            'reference_paths': [self.file_path]}, sources={'goal': 'taslak hazırla'}, refs=(ref,), raw_text='taslak hazırla'))
        self.assertIsNone(self.propose('files.mutate', {'operation': 'rename', 'name': 'başka.txt'},
            sources={'name': 'başka.txt'}, slots=('file_0',), refs=(ref,), raw_text='adını sonuç.txt yap'))
        translated = self.propose('files.read', {'operation': 'translate', 'target': 'İngilizce'},
                                 slots=('file_0',), refs=(ref,))
        self.assertIsNotNone(translated)
        self.assertEqual(brain_core_map.core_plan('files.read', translated.actions[0].arguments)[1],
                         {'operation': 'translate', 'path': self.file_path, 'target': 'İngilizce'})
        self.assertIsNone(self.propose('files.read', {'operation': 'translate', 'target': 'İngilizce',
            'path': '/forged.txt'}, slots=('file_0',), refs=(ref,)))

    def test_model_cannot_forge_original_text_to_authorize_development_apply(self):
        self.assertIsNone(self.propose('development.manage', {'operation': 'apply'}, raw_text='kod niye bozuk'))
        self.assertIsNone(self.propose('development.manage', {
            'operation': 'apply', 'original_text': 'değişiklikleri uygula'}, raw_text='kod niye bozuk'))
        self.assertIsNotNone(self.propose('development.manage', {'operation': 'apply'}, raw_text='değişiklikleri uygula'))
        self.assertIsNotNone(self.propose('development.manage', {'operation': 'request', 'goal': 'taslak hazırla'},
            sources={'goal': 'taslak hazırla'}, raw_text='taslak hazırla'))
        self.assertIsNone(self.propose('development.manage', {'operation': 'request', 'goal': 'dosyayı sil'},
            sources={'goal': 'dosyayı sil'}, raw_text='taslak hazırla'))

    def test_note_read_binds_offered_id_and_rejects_model_supplied_id(self):
        from modules.brain_contracts import ContextReference
        ref = ContextReference(id='42', owner=self.owner, kind='note', source='profile.items',
                               provenance={'text': 'market listesi'})
        proposal = self.propose('notes.read', {'notes': {'which': 'one'}}, slots=('note_0',), refs=(ref,))
        self.assertIsNotNone(proposal)
        self.assertEqual(brain_core_map.core_plan('notes.read', proposal.actions[0].arguments)[1]['id'], '42')
        self.assertIsNone(self.propose('notes.read', {'notes': {'which': 'one', 'id': '42'}}, refs=(ref,)))


class DesktopAnswerIdentityTests(unittest.TestCase):
    def test_stale_or_foreign_native_question_never_runs(self):
        from modules import desktop_agent
        job = {'id': 'pc1', 'status': 'question', 'question': 'Güncel soru?'}
        with patch.object(desktop_agent, '_load', return_value=job), \
             patch.object(desktop_agent, 'run') as run:
            for fields in ({'expected_job_id': 'stale', 'expected_question': 'Güncel soru?'},
                           {'expected_job_id': 'pc1', 'expected_question': 'Eski soru?'}):
                result = desktop_agent.answer_typed('hamdi', 'cevap', **fields, current=lambda: 'hamdi')
                self.assertIn('değişmiş', result)
            result = desktop_agent.answer_typed('hamdi', 'cevap', expected_job_id='pc1',
                expected_question='Güncel soru?', current=lambda: 'başkası')
            self.assertIn('aktif kullanıcısı', result)
            run.assert_not_called()
            self.assertNotIn('answer', job)
