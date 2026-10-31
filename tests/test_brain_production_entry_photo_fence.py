from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.brain_contracts import ActiveContext


OWNER = "hamdi"
RID = "req-photo-current"


class BrainProductionPhotoFenceTests(unittest.TestCase):
    def test_current_photo_artifact_request_id_mismatch_fails_closed(self):
        from modules import brain_entry

        runtime = SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER, name="Hamdi", data={}),
            _sessions=object(),
            flags={"sleep": False},
            _pending_photo={},
        )
        photo = brain_entry.photo_artifact(
            owner=OWNER,
            request_id="other-request",
            path="C:/photo.jpg",
        )
        active = ActiveContext(owner=OWNER, request_id=RID)
        with patch.object(brain_entry, "_build_context", return_value=active), \
             patch.object(brain_entry, "_state_refs", return_value=()):
            with self.assertRaises(ValueError):
                brain_entry.prepare(
                    runtime,
                    owner=OWNER,
                    request_id=RID,
                    text="buna bak",
                    source="telefon",
                    artifact=photo,
                )


if __name__ == "__main__":
    unittest.main()
