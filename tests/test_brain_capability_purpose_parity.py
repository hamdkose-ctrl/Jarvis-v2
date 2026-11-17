"""BRAIN-03 parity guard: every Core capability offered to the semantic model must carry a
purpose and precondition definition (docs/agents/gorev-cekirdegi.md). An undescribed capability
is invisible to the decider: measured 2026-11-17, the model answered live research requests with
hallucinated prose that Jarvis has no external research tool while research.search was offered
only as a bare name with a misleading "route": "PRIVATE" literal."""
import unittest

from modules.brain_core_map import CORE_INTENTS
from modules.brain_model_understanding import (
    _CAPABILITY_PURPOSES,
    _MODEL_DENIED_CAPABILITIES,
    _supplied_schema,
)


def _offered():
    return sorted(set(CORE_INTENTS) - _MODEL_DENIED_CAPABILITIES)


class CapabilityPurposeParityTests(unittest.TestCase):
    def test_every_offered_capability_has_a_purpose_entry(self):
        missing = [name for name in _offered() if name not in _CAPABILITY_PURPOSES]
        self.assertEqual([], missing, "offered capabilities without purpose definition")

    def test_purpose_entries_are_purpose_and_precondition_strings(self):
        for name, entry in _CAPABILITY_PURPOSES.items():
            with self.subTest(capability=name):
                self.assertIsInstance(entry, tuple)
                self.assertEqual(2, len(entry))
                for text in entry:
                    self.assertIsInstance(text, str)
                    self.assertTrue(text.strip(), f"{name} has an empty purpose/precondition")

    def test_purposes_never_describe_denied_or_unknown_capabilities(self):
        unknown = sorted(set(_CAPABILITY_PURPOSES) - set(CORE_INTENTS))
        self.assertEqual([], unknown, "purpose entries for capabilities Core does not own")

    def test_supplied_schema_shows_purpose_and_precondition_for_every_offered(self):
        for name in _offered():
            with self.subTest(capability=name):
                schema = _supplied_schema(name)
                self.assertIn("purpose", schema, name)
                self.assertIn("precondition", schema, name)

    def test_research_purpose_owns_the_public_live_reading(self):
        purpose, precondition = _CAPABILITY_PURPOSES["research.search"]
        self.assertIn("public", purpose)
        self.assertIn("live", purpose)
        # The PRIVATE route is a privacy-connection label; the definition must say it is not
        # an absence of web access, otherwise the decider falls back to chat refusal prose.
        self.assertIn("NOT", precondition)
        self.assertIn("PRIVATE", precondition)


if __name__ == "__main__":
    unittest.main()
