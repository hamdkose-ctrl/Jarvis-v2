"""Mail cevaplarında kullanıcı tarafından açıkça seçilen alıcıyı korur."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import goal_tools, outbox, requests_state, service_store


OWNER = 'reply_recipient_fixture'
AHMET = 'ahmet@example.org'
SENDER = 'arsiv@collector.example.net'


class ReplyRecipientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root_patch = patch.object(service_store, 'ROOT', self.root / 'outbox')
        self.root_patch.start()
        self.request_token = requests_state._current.set(None)
        profile = SimpleNamespace(slug=OWNER, data={'contacts': {'Ahmet': AHMET}})
        self.runtime = SimpleNamespace(profile=profile, _cur_source='yazı', pc_profile=lambda: profile, emit=Mock())
        self.dependencies = {'mail': {'state': 'done', 'snapshot': {
            'operation': 'read_message', 'message': {'from': SENDER, 'subject': 'Durum'}}}}

    def tearDown(self):
        requests_state._current.reset(self.request_token)
        self.root_patch.stop()
        self.tmp.cleanup()

    def execute(self, request, destination):
        data = {'service': 'gmail', 'destination': destination, 'subject': 'Yanıt', 'text': 'Kısa cevap'}
        identity = {'job_id': 'job1', 'task_id': 'send', 'request': request}
        with patch.object(goal_tools.task_agents, 'worker', return_value={'state': 'done', 'text': 'taklit gönderim'}) as worker:
            result = goal_tools.execute(self.runtime, 'publish', data, self.dependencies, identity)
        return result, worker

    def test_named_contact_reply_keeps_named_destination(self):
        result, worker = self.execute("Ahmet'e cevap gönder", AHMET)
        self.assertEqual(result['state'], 'done')
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[1]['input']['destination'], AHMET)

    def test_named_contact_reply_rejects_mail_sender_swap(self):
        with self.assertRaises(goal_tools.NotStarted):
            self.execute("Ahmet'e cevap gönder", SENDER)

    def test_unnamed_reply_still_accepts_verified_mail_sender(self):
        result, worker = self.execute('Bu maile cevap gönder', SENDER)
        self.assertEqual(result['state'], 'done')
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[1]['input']['destination'], SENDER)

    def test_grant_cannot_override_named_reply_destination(self):
        outbox.grant(OWNER, 'gmail', SENDER, seconds=3600)
        with self.assertRaises(goal_tools.NotStarted):
            self.execute("Ahmet'e cevap gönder", SENDER)


if __name__ == '__main__':
    unittest.main()
