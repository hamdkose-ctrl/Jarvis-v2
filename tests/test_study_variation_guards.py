"""Regression guards for study API input/session variations."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules.study_services import StudyServices
from web_study import WebStudy


class StudyVariationGuardsTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(slug='variation-user', data={'study': {}})
        self.study = Mock()
        self.exams = Mock()
        self.services = StudyServices(
            current_profile=lambda: self.profile,
            study=self.study,
            exams=self.exams,
            media=Mock(),
            llm=Mock(),
            privacy=Mock(),
            config=Mock(),
            events=Mock(),
        )
        self.bridge = WebStudy(self.services)

    def test_single_course_string_is_one_key_not_characters(self):
        self.exams.set_courses.return_value = []
        self.bridge.study_set_courses('BİYOLOJİ – 1|441')
        self.exams.set_courses.assert_called_once_with(self.profile, ['BİYOLOJİ – 1|441'])

    def test_course_selection_deduplicates_and_drops_empty_values(self):
        self.exams.set_courses.return_value = []
        self.bridge.study_set_courses([' matematik ', '', 'matematik', None, 'fizik'])
        self.exams.set_courses.assert_called_once_with(self.profile, ['matematik', 'fizik'])

    def test_missing_attempt_id_is_bound_to_current_question(self):
        self.profile.data['study']['quiz_attempt'] = {'id': 'attempt-1', 'qid': 'question-1'}
        self.exams.quiz_answer.return_value = {'ok': True}
        result = self.bridge.study_quiz_answer('question-1', 'A', '')
        self.assertEqual(result, {'ok': True})
        self.exams.quiz_answer.assert_called_once_with(self.profile, 'question-1', 'A', 'attempt-1')

    def test_stale_question_without_attempt_id_is_rejected_before_grading(self):
        self.profile.data['study']['quiz_attempt'] = {'id': 'attempt-new', 'qid': 'question-new'}
        with self.assertRaisesRegex(ValueError, 'artık aktif değil'):
            self.bridge.study_quiz_answer('question-old', 'B', '')
        self.exams.quiz_answer.assert_not_called()

    def test_missing_mock_session_id_is_bound_to_current_session(self):
        self.profile.data['study']['mock_session'] = {'id': 'mock-7', 'qids': ['question-1']}
        self.exams.mock_answer.return_value = {'status': {'answered': 1}}
        result = self.bridge.study_mock_answer('question-1', 'C', '')
        self.assertEqual(result, {'status': {'answered': 1}})
        self.exams.mock_answer.assert_called_once_with(self.profile, 'question-1', 'C', 'mock-7')


if __name__ == '__main__':
    unittest.main()
