import engine_source
"""Actual pending-action branches with OS and messaging adapters replaced."""
import ast
from pathlib import Path
import queue
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from modules import brain_entry
from modules.confirmation import decision
from modules.session_state import SessionState

ROOT = Path(__file__).resolve().parents[1]


class ConfirmationTests(unittest.TestCase):
    def test_denial_wins_over_yes_inside_sentence(self):
        for text in ('evet ama gönderme', 'tamam, kapatma', 'hayır evet', 'onaylamıyorum', 'evet düzenleme', 'tamam yapma'):
            with self.subTest(text=text):
                self.assertIs(decision(text, extra=('gönder', 'düzenle')), False)

    def test_unrelated_sentences_are_not_approval(self):
        for text in ('evet sonra konuşalım', 'tamam mı', 'onaylamak ne demek', 'bu dosyayı gönder', 'tamam başka soru'):
            self.assertIsNone(decision(text))

    def test_only_clear_short_approvals_and_context_specific_words_are_accepted(self):
        for text in ('evet', 'Tamam!', 'onaylıyorum', 'olur'):
            self.assertIs(decision(text), True)
        self.assertIsNone(decision('gönder'))
        self.assertIs(decision('gönder', extra=('gönder',)), True)

    def branch(self, condition, ns):
        tree = engine_source.tree()
        handle = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'handle')
        node = next(n for n in ast.walk(handle) if isinstance(n, ast.If) and ast.unparse(n.test) == condition)
        fn = ast.FunctionDef(name='run_branch', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[node, ast.Return(value=ast.Constant(value=None))], decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'real-confirmation-branch', 'exec'), ns)
        return ns['run_branch']()

    def test_shutdown_denial_never_calls_os_shutdown(self):
        for text in ('tamam kapatma', 'evet ama kapatma', 'hayır evet', 'evet sonra konuşalım'):
            with self.subTest(text=text):
                session = SessionState(pending_confirm='shutdown')
                system = Mock()
                self.branch('_session().pending_confirm', {'_session': lambda: session, 'cmd_lower': text, 'decision': decision, 'system_control': system, 'privacy': Mock(), 'brain_entry': brain_entry})
                system.shutdown_pc.assert_not_called()
                self.assertIsNone(session.pending_confirm)

    def test_close_app_requires_clear_approval_before_window_close(self):
        for text in ('evet ama kapatma', 'hayır evet', 'tamam kapatma'):
            with self.subTest(text=text):
                session = SessionState(pending_confirm={'action': 'close_app', 'name': 'Not Defteri'})
                system = Mock()
                self.branch('_session().pending_confirm', {
                    '_session': lambda: session, 'cmd_lower': text, 'decision': decision,
                    'system_control': system, 'privacy': Mock(), 'brain_entry': brain_entry,
                })
                system.close_application.assert_not_called()
                self.assertIsNone(session.pending_confirm)

        session = SessionState(pending_confirm={'action': 'close_app', 'name': 'Not Defteri'})
        system = Mock()
        system.close_application.return_value = 'Not Defteri pencerelerinin kapandığını doğruladım.'
        result = self.branch('_session().pending_confirm', {
            '_session': lambda: session, 'cmd_lower': 'evet', 'decision': decision,
            'system_control': system, 'privacy': Mock(), 'brain_entry': brain_entry,
        })
        self.assertIn('kapandığını doğruladım', result)
        system.close_application.assert_called_once_with('Not Defteri')

    def test_folder_denial_does_not_move_files(self):
        session = SessionState(pending_organize={'plan': [], 'label': 'Belgeler'})
        files = Mock()
        result = self.branch('_session().pending_organize is not None', {'_session': lambda: session, 'cmd_lower': 'evet ama düzenleme', 'decision': decision, 'files': files, 'privacy': Mock(), 'brain_entry': brain_entry})
        self.assertIn('dokunmadım', result)
        files.apply_organize.assert_not_called()

    def message(self, session, text):
        tree = engine_source.tree()
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_message_step')
        profile = SimpleNamespace(slug='hamdi', data={'contacts': {'Ebru': '905551112233'}})
        # Alıcı güvenliği: gönderim yalnız çözümlenmiş kişiyle başlar; bu asgari sözleşme mock'ta da
        # temsil edilir (tek ad eşleşmesi + tek geçerli numara + maskeli numara).
        messaging = Mock()
        messaging.name_matches.return_value = ['Ebru']
        messaging.contact_matches.return_value = [('Ebru', '905551112233')]
        messaging.mask_phone.return_value = '…2233'
        ns = {'_session': lambda: session, 'load_approve': lambda: True, 're': re, 'profile': profile, 'messaging': messaging, 'threading': SimpleNamespace(Thread=Mock()), 'requests_state': Mock(), 'privacy': Mock(), '_emit_for': Mock(), 'pc_profile': lambda: profile, 'events': queue.Queue(), 'secrets': SimpleNamespace(token_hex=lambda size: 'background-id')}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'real-message-confirmation', 'exec'), ns)
        return ns['_message_step'](text, text.lower()), ns

    def test_message_denial_never_starts_sender(self):
        session = SessionState(pending_msg={'to': 'Ebru', 'text': 'Merhaba', 'stage': 'confirm'})
        result, ns = self.message(session, 'evet ama gönderme')
        self.assertIn('göndermedim', result)
        ns['threading'].Thread.assert_not_called()
        self.assertIsNone(session.pending_msg)

    def test_message_content_containing_cancel_word_is_kept_as_content(self):
        session = SessionState(pending_msg={'to': 'Ebru', 'text': '', 'stage': 'text'})
        result, ns = self.message(session, 'Toplantı iptal edildi')
        self.assertIn('Toplantı iptal edildi', result)
        self.assertEqual(session.pending_msg['stage'], 'confirm')
        self.assertEqual(session.pending_msg['text'], 'Toplantı iptal edildi')
        ns['threading'].Thread.assert_not_called()

    def test_clear_message_approval_starts_sender_once(self):
        session = SessionState(pending_msg={'to': 'Ebru', 'text': 'Merhaba', 'stage': 'confirm'})
        result, ns = self.message(session, 'evet gönder')
        self.assertIn('gönderiyorum', result)
        ns['threading'].Thread.assert_called_once()
        self.assertIsNone(session.pending_msg)
