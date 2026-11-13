"""BRAIN-03: typed read-only mail source choice keeps Gmail/Outlook parity."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import brain_core_map, engine_intents, google_api, outlook, worktrack


def read(source, *, outlook_on, google_on):
    runtime = SimpleNamespace(profile=SimpleNamespace(slug="test-owner"))
    ready = None if google_on else google_api.SETUP_HELP
    plan = brain_core_map.core_plan("mail.read", {"source": source})
    assert plan == ("mail_read", {"source": source})
    with patch("modules.requests_state.check"), \
         patch.object(google_api, "important",
                      return_value=[{"who": "Ayşe", "subject": "Not", "starred": True}]), \
         patch.object(google_api, "_ready", return_value=ready), \
         patch.object(google_api, "connected", return_value=google_on), \
         patch.object(google_api, "unread_mail",
                      return_value="GMAIL-OKUNMAMIS"), \
         patch.object(outlook, "installed", return_value=outlook_on), \
         patch.object(outlook, "unread_mail",
                      side_effect=lambda *a, **k: k.get("prefix", "") + "OUTLOOK-LISTE"):
        return engine_intents.dispatch(runtime, *plan, "önemli maillerim", "önemli maillerim")


class SourceChoiceTests(unittest.TestCase):
    def test_both_available_gmail_answers_and_names_the_work_mail_way(self):
        response = read("important", outlook_on=True, google_on=True)
        self.assertIn("Gmail", response)
        self.assertIn("Ayşe", response)
        self.assertIn("iş maillerimi kontrol et", response)

    def test_only_gmail_has_no_outlook_hint(self):
        response = read("important", outlook_on=False, google_on=True)
        self.assertIn("Ayşe", response)
        self.assertNotIn("Outlook", response)

    def test_outlook_only_says_it_cannot_rank_and_lists_unread(self):
        response = read("important", outlook_on=True, google_on=False)
        self.assertIn("OUTLOOK-LISTE", response)
        self.assertIn("Gmail bağlı değil", response)
        self.assertIn("önem", response)

    def test_neither_says_so_clearly(self):
        response = read("important", outlook_on=False, google_on=False)
        self.assertIn("Google bağlantısı kurulu değil", response)
        self.assertIn("Outlook", response)

    def test_work_important_always_uses_outlook_unread_not_gmail_ranking(self):
        for outlook_on, google_on in ((True, True), (True, False), (False, False)):
            with self.subTest(outlook=outlook_on, google=google_on):
                response = read("work_important",
                                outlook_on=outlook_on, google_on=google_on)
                self.assertIn("OUTLOOK-LISTE", response)
                self.assertIn("önem", response)

    def test_explicit_combined_read_names_both_providers(self):
        result = read("combined", outlook_on=True, google_on=True)
        self.assertIn("Gmail:", result)
        self.assertIn("İş (Outlook):", result)

    def test_work_priority_without_mail_stays_work_report_not_mail_read(self):
        with patch.object(worktrack, "report", return_value="ISTAKIP"):
            self.assertEqual(worktrack.handle("önceliklerim neler"), "ISTAKIP")

    def test_rejects_model_supplied_mail_effect_or_unrecognized_source(self):
        for payload in ({"source": "send"}, {"source": "inbox", "recipient": "Ali"},
                        {"source": "work", "body": "secret"}, {}):
            with self.subTest(payload=payload):
                self.assertIsNone(brain_core_map.core_plan("mail.read", payload))


if __name__ == "__main__":
    unittest.main()
