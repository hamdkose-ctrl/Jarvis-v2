from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_engine_modular as fixtures
from modules import brain_entry, engine_commands
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


class PhotoFollowupHandlerAuthorityTests(unittest.TestCase):
    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def _entry_and_runtime(self, text: str):
        runtime = self.context()
        owner = runtime.profile.slug
        path = "C:/Users/Hamdi/Pictures/photo.jpg"
        runtime._pending_photo[owner] = {
            "path": path,
            "t": runtime.time.time(),
            "origin_request_id": "photo-origin",
        }
        runtime._llm.set_user_context = Mock()
        runtime._photo_action = Mock(return_value="PHOTO_ACTION")
        runtime._split_steps = Mock(return_value=("fallback-step",))
        runtime._run_steps = Mock(return_value="CONTINUED")
        entry = brain_entry.prepare(
            runtime,
            owner=owner,
            request_id=f"rid-{text}",
            text=text,
            source="telefon",
        )
        return runtime, entry, path

    def _handle(self, runtime, entry, text: str):
        with patch("modules.requests_state.check"), \
             patch("modules.command_manager.engine_control", return_value=None), \
             patch("modules.job_front.wants", return_value=False), \
             patch("modules.goal_executor.active", return_value=False), \
             patch("modules.goal_executor.handle", return_value=None), \
             patch("modules.command_manager.dispatch", return_value=None), \
             patch("modules.command_execution.continue_app", return_value=None), \
             brain_entry.bind(entry):
            return engine_commands.handle(runtime, text)

    def test_handler_follows_canonical_photo_relation_even_if_legacy_regex_says_no(self):
        runtime, entry, path = self._entry_and_runtime("analiz et")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        runtime._PHOTO_INTENT = SimpleNamespace(search=Mock(return_value=False))

        result = self._handle(runtime, entry, "analiz et")

        self.assertEqual(result, "PHOTO_ACTION")
        runtime._photo_action.assert_called_once_with(path, "analiz et")
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_handler_ignores_legacy_regex_when_canonical_relation_is_new_request(self):
        text = "önce kahve sonra çay"
        runtime, entry, _path = self._entry_and_runtime(text)
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        runtime._PHOTO_INTENT = SimpleNamespace(search=Mock(return_value=True))

        result = self._handle(runtime, entry, text)

        self.assertEqual(result, "CONTINUED")
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)


if __name__ == "__main__":
    unittest.main()
