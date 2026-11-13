"""BRAIN-03: real observations -> model envelope -> Core -> existing workers.

External model transport is fake; no preselected IDs or semantic results are
injected. Temporary Profile, history and allowed file roots are real.
"""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import json
import time
from unittest.mock import patch

import test_engine_modular  # noqa: F401 (headless dependencies)
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from test_brain_primary_understanding import action, envelope
from modules import brain_entry, brain_model_understanding, history, nxapi, tasks


class ObservationParityTests(_CanonicalAuthorityHarness):
    def model_turn(self, text, capability=None, arguments=None, slots=(), *, sources=None,
                   raw=None, error=None):
        row = action(capability_id=capability, arguments=arguments or {}, reference_slots=list(slots))
        if sources is not None:
            row['argument_sources'] = sources
        raw = raw if raw is not None else envelope(
            operation='direct_action' if capability else 'chat', confidence='HIGH',
            actions=[row] if capability else [])
        seen = []

        def transport(owner, prompt, send, **kwargs):
            seen.append(json.loads(prompt.split('\\n', 1)[0]))
            if error:
                raise error
            kwargs['validator'](raw)
            return raw

        with patch('modules.llm.current_user', return_value=self.owner), \
             patch('modules.llm.provider', return_value='groq'), \
             patch('modules.llm.privacy.mode', return_value='normal'), \
             patch('modules.smart_router.selection', return_value={'candidates': ['groq']}), \
             patch('modules.smart_router.run', side_effect=transport) as model:
            entry, output, _, feedback = self.turn_real(text, model_understanding=True)
        self.assertEqual(model.call_count, 1)
        return entry, output, feedback, seen[0]

    @contextmanager
    def file_inventory(self, age):
        saved = dict(nxapi._FILE_CACHE)
        root = Path(self.temp.name)
        target = root / 'rapor.txt'
        target.write_text('Rapor metni', encoding='utf-8')
        rows = [{'path': str(target), 'name': target.name, 'mtime': target.stat().st_mtime}]
        with nxapi._FILE_CACHE_LOCK:
            nxapi._FILE_CACHE.update(rows=None if age == 'empty' else rows,
                                    ts=time.monotonic() if age == 'fresh' else 0)
        try:
            with patch.object(nxapi, '_roots', return_value=[root]), \
                 patch.object(nxapi, '_scan_files', return_value=rows) as scanner, \
                 patch.object(self.ctx.docs, 'summarize', return_value='ÖZET') as worker:
                yield target, scanner, worker
        finally:
            with nxapi._FILE_CACHE_LOCK:
                nxapi._FILE_CACHE.clear()
                nxapi._FILE_CACHE.update(saved)

    def test_cold_expired_and_fresh_file_mentions_reach_the_same_worker_once(self):
        for age in ('empty', 'expired', 'fresh'):
            with self.subTest(age=age), self.file_inventory(age) as (path, scan, worker):
                entry, result, _, payload = self.model_turn(
                    'rapor.txt dosyasını özetle', 'files.read', {'operation': 'summarize'}, ['file_0'])
                self.assertIn('ÖZET', result)
                self.assertEqual(brain_entry.core_plan(entry)[1]['path'], str(path))
                self.assertEqual(len(payload['file_candidates']), 1)
                worker.assert_called_once_with(str(path))
                self.assertEqual(scan.call_count, 0 if age == 'fresh' else 1)
                # Discovery refreshes the owner's shared cache, rather than walking it again.
                history.append(self.owner, 'user', 'rapor.txt dosyasını özetle')
                self.model_turn('rapor.txt dosyasını özetle', 'files.read',
                                {'operation': 'summarize'}, ['file_0'])
                self.assertEqual(scan.call_count, 0 if age == 'fresh' else 1)

    def test_ordinary_chat_keeps_cold_and_expired_inventory_scan_free(self):
        for age in ('empty', 'expired'):
            with self.subTest(age=age), self.file_inventory(age) as (_, scan, worker):
                self.model_turn('merhaba')
                scan.assert_not_called()
                worker.assert_not_called()

    def test_file_observation_does_not_authorize_an_effect_when_model_says_chat(self):
        with self.file_inventory('empty') as (_, _, worker):
            self.model_turn('rapor.txt dosyasını açma')
            worker.assert_not_called()

    def test_tasks_and_history_cannot_hide_a_single_note_or_file(self):
        for index in range(70):
            tasks.add(self.ctx.profile, f'İlgisiz görev {index}')
        note = self.ctx.profile.add_note_item('Market listesi')
        for index in range(15):
            history.append(self.owner, 'assistant', f'Eski cevap {index}')
        entry, result, _, offered = self.model_turn(
            'ilk notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
        self.assertIn('Notu sildim', result)
        self.assertEqual(brain_entry.core_plan(entry)[1]['id'], str(note['id']))
        self.assertEqual(len(offered['note_candidates']), 1)
        self.assertLessEqual(len(entry.candidates), 40)
        self.ctx.profile.add_note_item('Başka not')
        with self.file_inventory('fresh') as (_, _, worker):
            entry, _, _, offered = self.model_turn(
                'rapor.txt dosyasını özetle', 'files.read', {'operation': 'summarize'}, ['file_0'])
            self.assertEqual(len(offered['file_candidates']), 1)
            self.assertIn('note', Counter(ref.kind for ref in entry.candidates))
            self.assertLessEqual(len(entry.candidates), 40)
            worker.assert_called_once()

    def read_note(self):
        self.ctx.profile.add_note_item('Market süt listesi')
        first = self.ctx.profile.data['items'][0]
        _, output, _, payload = self.model_turn(
            'market notunu göster', 'notes.read', {'notes': {'which': 'one'}}, ['note_0'])
        self.assertIn(first['text'], output, (payload['note_candidates'], brain_model_understanding.proposal_diagnostic()))
        history.append(self.owner, 'user', 'market notunu göster')
        history.append(self.owner, 'assistant', output)
        return first

    def test_named_read_then_deictic_delete_binds_the_delivered_record(self):
        note = self.read_note()
        untouched = self.ctx.profile.add_note_item('Toplantı listesi')
        entry, output, _, offered = self.model_turn(
            'o notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
        self.assertEqual([row['preview'] for row in offered['note_candidates']], [note['text']])
        self.assertIn('Notu sildim', output)
        self.assertEqual(self.ctx.profile.data['items'], [untouched])
        self.assertEqual(brain_entry.core_plan(entry)[1]['id'], str(note['id']))
        self.assertIsNone(self.ctx._session().last_note)

    def test_unique_search_result_publishes_a_real_note_referent(self):
        self.ctx.profile.add_note_item('Market süt listesi')
        self.ctx.profile.add_note_item('Toplantı')
        self.model_turn('notlarda market ara', 'notes.read', {'notes': {'which': 'search', 'query': 'market'}})
        _, output, _, _ = self.model_turn('o notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
        self.assertIn('Notu sildim', output)
        self.assertEqual([row['text'] for row in self.ctx.profile.data['items']], ['Toplantı'])

    def test_ambiguous_search_does_not_reuse_the_previous_single_note(self):
        self.read_note()
        self.ctx.profile.add_note_item('Market ekmek')
        self.model_turn('notlarda market ara', 'notes.read', {'notes': {'which': 'search', 'query': 'market'}})
        before = list(self.ctx.profile.data['items'])
        _, _, _, payload = self.model_turn('o notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
        self.assertEqual(payload['note_candidates'], [])
        self.assertEqual(self.ctx.profile.data['items'], before)

    def test_changed_expired_foreign_reset_and_superseded_referents_fail_closed(self):
        for change in ('changed', 'expired', 'foreign', 'reset', 'topic'):
            with self.subTest(change=change):
                self.ctx.profile.data['items'] = []
                self.ctx._session().last_note = None
                note = self.read_note()
                if change == 'changed':
                    note['text'] = 'Dışarıdan düzenlendi'
                elif change == 'expired':
                    self.ctx._session().last_note['at'] = time.time() - 901
                elif change == 'foreign':
                    self.ctx._session().last_note['owner'] = 'other'
                elif change == 'reset':
                    self.ctx._sessions.reset(self.owner)
                else:
                    self.model_turn('merhaba')
                _, result, _, payload = self.model_turn(
                    'o notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
                self.assertEqual(payload['note_candidates'], [])
                self.assertNotIn('Notu sildim', result)
                self.assertEqual(self.ctx.profile.data['items'], [note])

    def make_tasks(self):
        done = tasks.add(self.ctx.profile, 'Bitmiş iş')
        tasks.toggle(self.ctx.profile, done['id'])
        open_task = tasks.add(self.ctx.profile, 'Açık iş')
        return done, open_task

    def preview_clear(self):
        entry, output, feedback, _ = self.model_turn(
            'tamamlanan görevleri temizle', 'tasks.manage', {'operation': 'clear_done'})
        self.assertEqual(brain_entry.core_plan(entry), ('tasks_manage', {'operation': 'clear_done'}))
        self.assertIn('onaylıyor musun', output)
        self.assertEqual(feedback.result_status, 'needs_input')

    def test_clear_completed_tasks_requires_one_snapshot_bound_confirmation(self):
        done, open_task = self.make_tasks()
        self.preview_clear()
        self.assertEqual(self.ctx.profile.data['tasks'], [done, open_task])
        result = self.turn_real('evet')[1]
        self.assertIn('1 tamamlanmış görevi sildim', result)
        self.assertEqual(self.ctx.profile.data['tasks'], [open_task])
        self.assertIsNone(self.ctx._session().pending_confirm)

    def test_completed_task_confirmation_rejects_changed_scope_or_owner_and_expiry(self):
        for change in ('new_done', 'edited', 'reopened', 'owner', 'expired', 'cancel'):
            with self.subTest(change=change):
                self.ctx.profile.data['tasks'] = []
                self.ctx._session().pending_confirm = None
                done, _ = self.make_tasks()
                self.preview_clear()
                if change == 'new_done':
                    later = tasks.add(self.ctx.profile, 'Sonradan tamamlanan')
                    tasks.toggle(self.ctx.profile, later['id'])
                elif change == 'edited':
                    done['text'] = 'Yeni açıklama'
                elif change == 'reopened':
                    tasks.toggle(self.ctx.profile, done['id'])
                elif change == 'owner':
                    self.ctx._session().pending_confirm['owner'] = 'other'
                elif change == 'expired':
                    self.ctx._session().pending_confirm['expires'] = time.time() - 1
                before = list(self.ctx.profile.data['tasks'])
                if change == 'owner':
                    # Canonical State rejects a foreign owner before a handler
                    # can run; the worker independently fences direct approval.
                    with self.assertRaises(ValueError):
                        self.turn_real('evet')
                    self.assertIn('onayı geçersiz', tasks.clear_done_confirmed(
                        self.ctx.profile, self.ctx._session().pending_confirm))
                    self.assertEqual(self.ctx.profile.data['tasks'], before)
                    self.ctx._session().pending_confirm = None
                    continue
                output = self.turn_real('hayır' if change == 'cancel' else 'evet')[1]
                self.assertNotIn('görevi sildim', output)
                self.assertEqual(self.ctx.profile.data['tasks'], before)
                self.assertIsNone(self.ctx._session().pending_confirm)

    def test_new_open_task_is_preserved_without_expanding_the_approved_delete_scope(self):
        _, open_task = self.make_tasks()
        self.preview_clear()
        later = tasks.add(self.ctx.profile, 'Sonradan eklenen açık iş')
        self.turn_real('evet')
        self.assertEqual(self.ctx.profile.data['tasks'], [open_task, later])

    def test_failed_completed_task_save_restores_memory_and_does_not_claim_success(self):
        self.make_tasks()
        self.preview_clear()
        before = list(self.ctx.profile.data['tasks'])
        with patch.object(self.ctx.profile, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.turn_real('evet')
        self.assertEqual(self.ctx.profile.data['tasks'], before)

    def test_no_completed_tasks_does_not_open_an_empty_confirmation(self):
        tasks.add(self.ctx.profile, 'Açık iş')
        _, output, _, _ = self.model_turn('tamamlanan görevleri temizle', 'tasks.manage', {'operation': 'clear_done'})
        self.assertIn('tamamlanmış görevin yok', output)
        self.assertIsNone(self.ctx._session().pending_confirm)

    def test_invalid_model_target_is_not_reported_as_a_provider_outage(self):
        entry, output, feedback, _ = self.model_turn(
            'o notu sil', 'notes.write', {'operation': 'delete'}, ['note_0'])
        self.assertIn('MODEL_PROPOSAL_REJECTED', entry.understanding.reason_codes)
        self.assertEqual(feedback.reason_code, 'BRAIN_MODEL_PROPOSAL_REJECTED')
        self.assertEqual(brain_model_understanding.proposal_diagnostic()['reason_code'], 'ACTION_REFERENCE_INVALID')
        self.assertNotIn('model şu anda kullanılamıyor', output)
        self.assertIn('doğrulayamadım', output)

    def test_malformed_response_and_transport_outage_have_different_fail_closed_results(self):
        for options, expected in (({'raw': '{'}, 'MODEL_PROPOSAL_REJECTED'),
                                  ({'error': TimeoutError('offline')}, 'MODEL_UNAVAILABLE')):
            with self.subTest(options=options):
                entry, _, _, _ = self.model_turn('not al: süt', 'notes.add', {'text': 'süt'},
                                                 sources={'text': 'süt'}, **options)
                self.assertIn(expected, entry.understanding.reason_codes)
                self.assertEqual(self.ctx.profile.data['items'], [])
