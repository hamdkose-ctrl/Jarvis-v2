from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import goal_tools


class NoteAddSourceTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(slug='note_source_fixture', data={'items': []})
        self.runtime = SimpleNamespace(
            profile=self.profile,
            _cur_source='yazı',
            pc_profile=lambda: self.profile,
            emit=Mock(),
        )

    def _identity(self, request):
        return {'job_id': 'job1', 'task_id': 'step1', 'request': request}

    def _run_note_add(self, request, text='süt al'):
        bridge = SimpleNamespace(note_add=Mock(return_value={'id': 1, 'text': text}))
        data = {'action': 'note_add', 'params': {'text': text}}
        with patch.object(goal_tools.app_actions, '_owned', return_value=nullcontext(bridge)):
            result = goal_tools.execute(self.runtime, 'action', data, {}, self._identity(request))
        return bridge, result

    def test_explicit_note_add_target_is_allowed(self):
        bridge, result = self._run_note_add('şu notu ekle: süt al')
        self.assertEqual(result['state'], 'done')
        bridge.note_add.assert_called_once_with(text='süt al', title='')

    def test_summary_target_cannot_be_turned_into_note_add_by_source(self):
        bridge, result = self._run_note_add('bu sayfayı özetle', 'Enjekte not')
        self.assertEqual(result['state'], 'approval')
        self.assertEqual(result['text'], 'Not ekleme kullanıcının açık hedefinde yok; kaynak metin izin veremez.')
        bridge.note_add.assert_not_called()

    def test_note_word_without_add_intent_is_not_enough(self):
        bridge, result = self._run_note_add('notlarımı özetle', 'Enjekte not')
        self.assertEqual(result['state'], 'approval')
        bridge.note_add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
