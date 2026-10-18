"""Live transkript tamponları; gerçek oturum, ağ veya ses kullanılmaz."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import live_transcripts, stt_guard


class LiveTranscriptsTests(unittest.TestCase):
    def setUp(self):
        self.services = SimpleNamespace(log=Mock(), apply_fixes=lambda text: text)
        self.live = SimpleNamespace(
            _in_buf=[], _out_buf=[], _recent_user=[], _convo=[],
            _suppress_output_turns=0, _tools_running=False, emit=Mock(),
        )
        self.live._flush_user = lambda: live_transcripts.flush_user(self.live, self.services)
        self.reject = self.enterContext(patch.object(stt_guard, "reject", return_value=None))
        self.note_said = self.enterContext(patch.object(stt_guard, "note_said"))

    def test_flush_user_joins_parts_and_applies_fixes(self):
        self.live._in_buf = ["  servis ", "", " ışığı  "]
        self.services.apply_fixes = Mock(return_value="Jarvis ışığı")

        live_transcripts.flush_user(self.live, self.services)

        self.reject.assert_called_once_with("servis ışığı")
        self.services.apply_fixes.assert_called_once_with("servis ışığı")
        self.assertEqual(self.live._in_buf, [])
        self.assertEqual(self.live._recent_user, ["servis ışığı"])
        self.assertEqual(self.live._convo, [("user", "Jarvis ışığı")])
        self.live.emit.assert_called_once_with("user", "Jarvis ışığı", "ses")

    def test_flush_user_rejected_text_is_discarded(self):
        for reason in ("foreign", "echo"):
            with self.subTest(reason=reason):
                self.reject.return_value = reason
                self.live._in_buf = ["  duyulan ", " söz "]
                self.services.apply_fixes = Mock()

                live_transcripts.flush_user(self.live, self.services)

                self.assertEqual(self.live._in_buf, [])
                self.assertEqual(self.live._convo, [])
                self.assertEqual(self.live._recent_user, [])
                self.live.emit.assert_not_called()
                self.services.apply_fixes.assert_not_called()

    def test_flush_user_whitespace_emits_nothing(self):
        self.live._in_buf = [" ", "\t", "\n"]

        live_transcripts.flush_user(self.live, self.services)

        self.assertEqual(self.live._in_buf, [])
        self.assertEqual(self.live._convo, [])
        self.assertEqual(self.live._recent_user, [])
        self.live.emit.assert_not_called()
        self.reject.assert_not_called()

    def test_flush_transcripts_emits_joined_assistant_text(self):
        self.live._out_buf = ["  Mer", "haba", " dünya.  "]

        text = live_transcripts.flush_transcripts(self.live, self.services)

        self.assertEqual(text, "Merhaba dünya.")
        self.assertEqual(self.live._out_buf, [])
        self.assertEqual(self.live._convo, [("assistant", text)])
        self.live.emit.assert_called_once_with("assistant", text, "ses")
        self.note_said.assert_called_once_with(text)

    def test_flush_transcripts_suppresses_one_output_turn(self):
        self.live._out_buf = [" Tekrar ", "gösterme. "]
        self.live._suppress_output_turns = 2

        text = live_transcripts.flush_transcripts(self.live, self.services)

        self.assertEqual(text, "Tekrar gösterme.")
        self.assertEqual(self.live._out_buf, [])
        self.assertEqual(self.live._suppress_output_turns, 1)
        self.assertEqual(self.live._convo, [])
        self.live.emit.assert_not_called()
        self.note_said.assert_called_once_with(text)

    def test_flush_transcripts_logs_silence_only_without_running_tools(self):
        for running in (False, True):
            with self.subTest(tools_running=running):
                self.services.log.reset_mock()
                self.live.emit.reset_mock()
                self.live._in_buf = [" Merhaba "]
                self.live._tools_running = running

                text = live_transcripts.flush_transcripts(self.live, self.services)

                self.assertEqual(text, "")
                self.assertEqual(self.live._in_buf, [])
                self.live.emit.assert_called_once_with("user", "Merhaba", "ses")
                messages = [call.args[0] for call in self.services.log.info.call_args_list]
                self.assertEqual(any("cevap vermedi" in message for message in messages), not running)
                self.note_said.assert_not_called()


if __name__ == "__main__":
    unittest.main()
