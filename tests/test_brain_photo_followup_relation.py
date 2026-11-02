from __future__ import annotations

import unittest

from modules.brain_contracts import ActiveContext, ContextReference, ConversationRelation
from modules.brain_understanding import understand


OWNER = "hamdi"
RID = "req-photo-followup"


def pending_photo() -> ContextReference:
    return ContextReference(
        id="pending_photo",
        kind="pending_state",
        source="engine_commands",
        owner=OWNER,
        provenance={
            "path": "C:/Users/Hamdi/Pictures/photo.jpg",
            "t": 1.0,
            "origin_request_id": "photo-origin",
        },
    )


def decide(text: str, *, with_pending_photo: bool = True):
    refs = (pending_photo(),) if with_pending_photo else ()
    active = ActiveContext(owner=OWNER, request_id=RID, pending_references=refs)
    return understand(
        owner=OWNER,
        request_id=RID,
        text=text,
        active_context=active,
        candidates=refs,
        references=(),
    )


class PhotoFollowupRelationTests(unittest.TestCase):
    def test_photo_operation_answers_the_pending_photo_question(self):
        for text in ("analiz et", "ne yazıyor"):
            with self.subTest(text=text):
                result = decide(text)
                self.assertIs(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)

    def test_unrelated_message_does_not_belong_to_pending_photo(self):
        result = decide("yarın toplantım var")
        self.assertIs(result.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_photo_words_without_pending_photo_do_not_create_pending_relation(self):
        result = decide("analiz et", with_pending_photo=False)
        self.assertIsNot(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)


if __name__ == "__main__":
    unittest.main()
