"""Mail cevaplarında kullanıcı tarafından açıkça seçilen alıcıyı korur."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import goal_tools, llm, outbox, requests_state, service_store


OWNER = 'reply_recipient_fixture'
AHMET = 'ahmet@example.org'
SENDER = 'arsiv@collector.example.net'


class ReplyRecipientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(service_store, 'ROOT', Path(self.tmp.name) / 'outbox')
        self.root_patch.start()
        self.key_token = llm._key_context.set(OWNER)
        self.request_token = requests_state._current.set(None)
        profile = SimpleNamespace(slug=OWNER, data={'contacts': {'Ahmet': AHMET}})
        self.runtime = SimpleNamespace(profile=profile, _cur_source='yazı', pc_profile=lambda: profile, emit=Mock())
        self.dependencies = {'mail': {'state': 'done', 'snapshot': {
            'operation': 'read_message', 'message': {'from': SENDER, 'subject': 'Durum'}}}}

    def tearDown(self):
        requests_state._current.reset(self.request_token)
        llm._key_context.reset(self.key_token)
        self.root_patch.stop()
        self.tmp.cleanup()

    def _execute(self, request, destination):
        data = {'service': 'gmail', 'destination': destination, 'subject': 'Yanıt', 'text': 'Kısa cevap'}
        identity = {'owner': OWNER, 'job_id': 'job1', 'task_id': 'send', 'request': request}
        return goal_tools.execute(self.runtime, 'publish', data, self.dependencies, identity)

    def test_named_contact_reply_keeps_named_destination(self):
        outbox.grant(OWNER, 'gmail', AHMET, seconds=3600)
        with patch.object(outbox.services, 'send', return_value={'remote_id': 'fake'}) as send:
            result = self._execute("Ahmet'e cevap gönder", AHMET)
        self.assertEqual(result['state'], 'done')
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1]['destination'], AHMET)

    def test_named_contact_reply_rejects_mail_sender_swap(self):
        with patch.object(goal_tools.task_agents, 'worker', return_value={'state': 'done', 'text': 'taklit'}) as worker:
            with self.assertRaises(goal_tools.NotStarted):
                self._execute("Ahmet'e cevap gönder", SENDER)
        worker.assert_not_called()

    def test_unnamed_reply_still_accepts_verified_mail_sender(self):
        with patch.object(outbox.services, 'send') as send:
            result = self._execute('Bu maile cevap gönder', SENDER)
        self.assertEqual(result['state'], 'approval')
        self.assertEqual(result['preview']['destination'], SENDER)
        send.assert_not_called()

    def test_grant_cannot_override_named_reply_destination(self):
        outbox.grant(OWNER, 'gmail', SENDER, seconds=3600)
        with patch.object(goal_tools.task_agents, 'worker', return_value={'state': 'done', 'text': 'taklit'}) as worker:
            with self.assertRaises(goal_tools.NotStarted):
                self._execute("Ahmet'e cevap gönder", SENDER)
        worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
