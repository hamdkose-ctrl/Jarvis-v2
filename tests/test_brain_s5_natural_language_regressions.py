import unittest

from modules.brain_contracts import ActiveContext, ContextReference, ConversationRelation, RequestKind
from modules.brain_understanding import understand


OWNER = "hamdi"


class BrainS5NaturalLanguageRegressionTests(unittest.TestCase):
    def call(self, text, *, pending=()):
        active = ActiveContext(
            owner=OWNER,
            request_id="brain-s5-regression",
            pending_references=tuple(pending),
        )
        return understand(
            owner=OWNER,
            request_id="brain-s5-regression",
            text=text,
            active_context=active,
            candidates=tuple(pending),
            references=(),
        )

    def test_muzik_cal_is_a_typed_media_action(self):
        result = self.call("müzik çal")
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, "pc.media.action")
        self.assertEqual(result.arguments["media"], {"action": "play_pause"})

    def test_ara_verince_is_not_a_web_search_command(self):
        result = self.call("Biraz ara verince düşünceler toparlanıyor.")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)
        self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_infinitive_mention_of_action_is_not_an_execution_request(self):
        result = self.call("Bir şeyi merak etmek onu hemen yaptırmak anlamına gelmez.")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_unrelated_chat_supersedes_a_valid_pending_clarification(self):
        pending = ContextReference(
            id="pending_action",
            kind="pending_state",
            source="session_state",
            owner=OWNER,
            provenance={
                "field": "pending_action",
                "active": True,
                "value": {
                    "stage": "clarify",
                    "command": "rapor dosyasını aç",
                    "question": "Hangi rapor?",
                    "owner": OWNER,
                    "expires": 4102444800,
                },
            },
        )
        result = self.call("Bunu düşününce gülümsedim.", pending=(pending,))
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)
        self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)


if __name__ == "__main__":
    unittest.main()
