import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from modules import study


class Profile:
    slug = 'mode-session-fixture'
    def __init__(self):
        self.data = {'study': {'mode': 'source', 'docs': [
            {'id': 1, 'title': 'Hücre.txt', 'kind': 'book'},
            {'id': 2, 'title': 'Motor.txt', 'kind': 'book'}]}}
    def save(self):
        pass


class StudyModeSessionTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = patch.object(study, 'ROOT', Path(self.tmp.name))
        self.root.start(); self.addCleanup(self.root.stop)
        d = Path(self.tmp.name) / self.p.slug
        d.mkdir()
        (d / '1.txt').write_text('Hücre zarı seçici geçirgendir.\n\nÇekirdek kalıtsal bilgiyi taşır.', encoding='utf8')
        (d / '2.txt').write_text('Motor statoru manyetik alan oluşturur.', encoding='utf8')

    def test_source_short_answer_keeps_question_and_selected_source(self):
        with patch.object(study.llm, 'ask', side_effect=['Hücre zarının görevi nedir?', 'Doğru, seçici geçirgenlik.']) as model:
            study.ask_source(self.p, 'Bir soru sor', 1, 'source')
            reply = study.ask_source(self.p, 'Seçici geçirgenlik', 1, 'source')
            self.assertIn('Hücre zarının görevi nedir?', model.call_args.args[0])
            self.assertNotIn('Motor statoru', model.call_args.args[0])
            self.assertEqual(len(reply['turns']), 4)

    def test_source_switch_drops_other_document_conversation(self):
        with patch.object(study.llm, 'ask', return_value='Hücreye özel eski yanıt'):
            study.ask_source(self.p, '', 1, 'source')
        with patch.object(study.llm, 'ask', return_value='Motor açıklaması') as model:
            study.ask_source(self.p, '', 2, 'source')
            self.assertNotIn('Hücreye özel eski yanıt', model.call_args.args[0])

    def test_next_section_advances_and_end_is_visible_without_model(self):
        with patch.object(study, '_chunks', return_value=['Hücre zarı', 'Çekirdek']), patch.object(study.llm, 'ask', return_value='Açıklama') as model:
            study.ask_source(self.p, '', 1, 'source')
            reply = study.ask_source(self.p, 'devam et', 1, 'source')
            self.assertEqual(reply['section'], 2)
            self.assertIn('[Bölüm 2] Çekirdek', model.call_args.args[0])
            last = study.ask_source(self.p, 'devam et', 1, 'source')
            self.assertIn('son bölüm', last['turns'][-1]['text'])
            self.assertEqual(model.call_count, 2)

    def test_deleted_source_cannot_be_restored_by_late_response(self):
        def model(*args, **kwargs):
            study.remove(self.p, 1)
            return 'Geç yanıt'
        with patch.object(study.llm, 'ask', side_effect=model):
            with self.assertRaisesRegex(ValueError, 'kaldırıldı'):
                study.ask_source(self.p, '', 1, 'source')
        self.assertNotIn('source_session', self.p.data['study'])

    def test_math_followup_keeps_equation_without_biology_topic_lock(self):
        self.p.data['study'].update(mode='math', lesson_context={'topic': 'Hücre'})
        with patch.object(study, '_search_items', return_value=[]), patch('modules.studyexam.focus', return_value=[]), patch.object(study.llm, 'ask', side_effect=['x = 3\nKONU: Denklem', 'Yerine koy: 2 × 3 + 4 = 10\nKONU: Denklem']) as model:
            study.ask(self.p, '2x + 4 = 10', 'math')
            study.ask(self.p, 'Neden 3?', 'math')
            self.assertIn('2x + 4 = 10', model.call_args.args[0])
            self.assertNotIn('AKTİF KONU: Hücre', model.call_args.kwargs['system'])
            self.assertIn('ters işlemle kontrol', model.call_args.kwargs['system'])
            self.assertEqual(len(self.p.data['study']['math_turns']), 4)

    def test_math_bridge_does_not_forward_unrelated_selected_source(self):
        from web_study_sources import WebStudySources
        bridge = WebStudySources()
        bridge._study_dependencies = SimpleNamespace(study=study, current_profile=lambda:self.p, llm=SimpleNamespace(set_user_context=lambda slug:None))
        with patch.object(study, 'ask', return_value='x = 3') as answer, patch.object(study, 'ask_source') as source:
            result = bridge.study_answer_with_context('2x + 4 = 10', 'math', 1)
            answer.assert_called_once_with(self.p, '2x + 4 = 10', 'math')
            source.assert_not_called()
            self.assertEqual(result['text'], 'x = 3')
