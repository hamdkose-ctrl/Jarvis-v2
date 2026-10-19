"""Bot cursor/inbox transaction regressions using isolated real SQLite databases; no polling."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import bot_updates, llm, requests_state, service_store


CHAT = '12345'
TOKEN = 'synthetic-test-bot-token'


def update(uid, text='Merhaba', chat=12345):
    return {'update_id': uid, 'message': {'chat': {'id': chat}, 'text': text, 'date': 1700000000}}


class BotUpdatesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(service_store, 'ROOT', Path(temporary.name) / 'outbox')
        root.start()
        self.addCleanup(root.stop)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        request = requests_state._current.set(None)
        self.addCleanup(requests_state._current.reset, request)
        self.key, previous = bot_updates.cursor('alice', TOKEN)
        self.assertIsNone(previous)

    @contextmanager
    def owner(self, name):
        token = llm._key_context.set(name)
        try:
            yield
        finally:
            llm._key_context.reset(token)

    def snapshot(self, owner='alice'):
        with self.owner(owner), service_store.database(owner) as db:
            messages = [tuple(row) for row in db.execute('SELECT * FROM incoming ORDER BY service,event_id')]
            cursors = [tuple(row) for row in db.execute('SELECT * FROM bot_cursors ORDER BY bot_key')]
        return messages, cursors

    def messages(self, owner='alice'):
        with self.owner(owner), service_store.database(owner) as db:
            return [dict(row) for row in db.execute('SELECT * FROM incoming ORDER BY event_id')]

    def test_initial_cursor_key_is_stable_and_token_scoped(self):
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, None))
        other_key, other_cursor = bot_updates.cursor('alice', 'another-synthetic-token')
        self.assertNotEqual(other_key, self.key)
        self.assertIsNone(other_cursor)
        self.assertEqual(len(self.key), 64)
        self.assertNotIn(TOKEN, self.key)

    def test_save_inserts_messages_and_uses_maximum_unordered_update_id(self):
        bot_updates.save('alice', self.key, [update(9, 'dokuz'), update(2, 'iki'), update(6, 'altı')], CHAT)
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 9))
        rows = self.messages()
        self.assertEqual(len(rows), 3)
        row = next(row for row in rows if row['event_id'] == self.key + ':6')
        self.assertEqual((row['service'], row['kind'], row['source'], row['text'], row['remote_time'], row['payload']),
                         ('telegram', 'message', CHAT, 'altı', '1700000000', '{}'))
        self.assertIsInstance(row['received'], float)

    def test_cursor_does_not_move_back_when_a_smaller_id_arrives(self):
        bot_updates.save('alice', self.key, [update(20)], CHAT)
        bot_updates.save('alice', self.key, [update(3)], CHAT)
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 20))
        self.assertEqual(len(self.messages()), 2)

    def test_another_chat_is_not_saved_but_cursor_advances(self):
        bot_updates.save('alice', self.key, [update(4, 'bizim'), update(30, 'başka', chat=999)], CHAT)
        self.assertEqual([row['text'] for row in self.messages()], ['bizim'])
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 30))

    def test_non_text_and_missing_message_are_skipped_but_acknowledged(self):
        updates = [update(1, None), update(2, 123), update(3, ['text']), {'update_id': 8}]
        bot_updates.save('alice', self.key, updates, CHAT)
        self.assertEqual(self.messages(), [])
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 8))

    def test_long_text_is_truncated_to_4096_characters(self):
        text = 'ğ' * 4096 + 'SON'
        bot_updates.save('alice', self.key, [update(1, text)], CHAT)
        self.assertEqual(self.messages()[0]['text'], text[:4096])
        self.assertEqual(len(self.messages()[0]['text']), 4096)

    def test_invalid_update_id_rolls_back_the_entire_batch(self):
        bot_updates.save('alice', self.key, [update(5, 'önceki')], CHAT)
        before = self.snapshot()
        for invalid in (-1, True, False, '7'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    bot_updates.save('alice', self.key, [update(50, 'geri alınmalı'), update(invalid), update(60)], CHAT)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 5))

    def test_invalid_batch_preserves_an_unset_cursor_and_empty_inbox(self):
        bot_updates.save('alice', self.key, [], CHAT)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            bot_updates.save('alice', self.key, [update(4), update(-1)], CHAT)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, None))

    def test_duplicate_update_has_one_row_and_keeps_original_text(self):
        bot_updates.save('alice', self.key, [update(7, 'ilk'), update(7, 'ikinci')], CHAT)
        bot_updates.save('alice', self.key, [update(7, 'üçüncü')], CHAT)
        self.assertEqual([row['text'] for row in self.messages()], ['ilk'])
        self.assertEqual(bot_updates.cursor('alice', TOKEN), (self.key, 7))

    def test_different_tokens_keep_separate_cursors_and_event_ids(self):
        other_key, _ = bot_updates.cursor('alice', 'another-synthetic-token')
        bot_updates.save('alice', self.key, [update(10, 'bir')], CHAT)
        bot_updates.save('alice', other_key, [update(3, 'iki')], CHAT)
        self.assertEqual(len(self.messages()), 2)
        self.assertEqual(bot_updates.cursor('alice', TOKEN)[1], 10)
        self.assertEqual(bot_updates.cursor('alice', 'another-synthetic-token')[1], 3)

    def test_two_users_have_separate_messages_and_cursors(self):
        bot_updates.save('alice', self.key, [update(12, 'Alice')], CHAT)
        alice_before = self.snapshot()
        with self.owner('bob'):
            bob_key, previous = bot_updates.cursor('bob', TOKEN)
            self.assertEqual(bob_key, self.key)
            self.assertIsNone(previous)
            bot_updates.save('bob', bob_key, [update(4, 'Bob')], CHAT)
            self.assertEqual(bot_updates.cursor('bob', TOKEN), (bob_key, 4))
        self.assertEqual(self.snapshot(), alice_before)
        self.assertEqual([row['text'] for row in self.messages('bob')], ['Bob'])
        self.assertEqual([row['text'] for row in self.messages()], ['Alice'])


if __name__ == '__main__':
    unittest.main()
