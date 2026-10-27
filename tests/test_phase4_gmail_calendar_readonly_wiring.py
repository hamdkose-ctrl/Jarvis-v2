import unittest
from unittest.mock import Mock, patch

from modules import account_tools, llm


class Phase4GmailCalendarReadonlyWiringTests(unittest.TestCase):
    def setUp(self):
        token = llm._key_context.set("alice")
        self.addCleanup(llm._key_context.reset, token)

    def test_gmail_thread_uses_readonly_adapter_and_returns_receipt(self):
        gmail = Mock()
        thread = {"id": "thread_123", "messages": [{"id": "message_1", "subject": "Plan"}]}
        with patch("modules.google_api._service", return_value=gmail) as service, \
             patch("modules.gmail_calendar_readonly.read_thread", return_value=thread) as reader, \
             patch.object(account_tools.privacy, "blocked", return_value=None):
            result = account_tools.run("alice", {
                "service": "gmail", "operation": "read_thread", "thread_id": "thread_123",
            })

        service.assert_called_once_with("gmail", "v1", interactive=False)
        reader.assert_called_once_with(gmail, "thread_123")
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["snapshot"]["thread"], thread)


if __name__ == "__main__":
    unittest.main()
