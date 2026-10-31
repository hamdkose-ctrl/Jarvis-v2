from __future__ import annotations

import unittest

from modules.brain_contracts import ActiveContext, ContextReference
from modules.brain_gates import exact_state_gate


OWNER = "hamdi"
RID = "req-gates-event-review"


class EventConflictGateReviewTests(unittest.TestCase):
    def test_event_conflict_positive_protocol_keeps_existing_bounded_variants(self):
        pending = ContextReference(
            id="pending_event_title",
            kind="pending_state",
            source="session_state",
            owner=OWNER,
            provenance={"value": {"confirm": ["Toplantı", "2026-11-01T10:00", None]}},
        )
        active = ActiveContext(owner=OWNER, request_id=RID, pending_references=(pending,))
        for text in ("ekle", "yine de ekle", "ekle gitsin"):
            with self.subTest(text=text):
                result = exact_state_gate(
                    owner=OWNER,
                    request_id=RID,
                    text=text,
                    active_context=active,
                )
                self.assertTrue(result.matched)
                self.assertEqual(result.protocol, "session.pending_event_title.confirm")
                self.assertEqual(result.selection, "yes")


if __name__ == "__main__":
    unittest.main()
