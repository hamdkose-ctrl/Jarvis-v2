import unittest
from modules import goal_executor


class NewsErrorRenderTests(unittest.TestCase):
    def job(self, messages, feedback):
        return {'state': 'blocked', 'goals': [], 'steps': [
                    {'id': str(i), 'tool': 'research', 'state': 'failed'} for i in range(len(messages))],
                'outputs': {str(i): {'state': 'failed', 'text': text} for i, text in enumerate(messages)},
                'feedback': feedback}

    def test_same_step_and_feedback_error_is_shown_once(self):
        job = self.job(['Kaynak HTTP error.', 'Kaynak HTTP error.'], [' kayNAK   HTTP   ERROR. '])
        rendered = ' '.join(goal_executor.render(job).casefold().split())
        self.assertEqual(rendered.count('kaynak http error.'), 1)

    def test_different_errors_remain_visible(self):
        rendered = goal_executor.render(self.job(['Kaynak açılamadı.'], ['Başka haber bulunamadı.']))
        self.assertIn('Kaynak açılamadı.', rendered)
        self.assertIn('Başka haber bulunamadı.', rendered)


if __name__ == '__main__':
    unittest.main()
