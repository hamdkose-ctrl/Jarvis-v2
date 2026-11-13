"""VOICE F5: the user decides whether a finished background job is also spoken.

The audit measured that a canonical research result, a scheduled task and a source
watch update reached the assistant view, the phone and the log — and never the
speaker. The fix hands the same notice to the single speech queue, but reading a
long job aloud while the user is elsewhere is not a silent default: the switch
lives in Ayarlar › Ses and the written notice is unaffected either way.

These tests pin the whole user flow, not only the function: the value the page
sends is the value the bridge stores, the value the bridge stores is the value the
delivery code reads, and the row on the page is the row that sends it.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import web                                                     # noqa: E402
from modules import event_channels, event_fanout               # noqa: E402

NX = os.path.join(os.path.dirname(__file__), "..", "webui", "nx.js")


def source():
    with open(NX, encoding="utf-8") as handle:
        return handle.read()


class ResultAnnouncementSwitch(unittest.TestCase):
    def test_the_switch_is_off_until_the_user_turns_it_on(self):
        # Nothing about a background result may become audible by accident.
        for stored in ({}, {"voice_announce_results": False}, {"other": 1}):
            with self.subTest(stored=stored), patch("config.load_settings", return_value=stored):
                self.assertFalse(event_channels.announce_speech())
        with patch("config.load_settings", return_value={"voice_announce_results": True}):
            self.assertTrue(event_channels.announce_speech())

    def test_a_broken_settings_read_never_starts_speaking(self):
        # The delivery path runs on the scheduler thread: a config fault may cost
        # the audio, never the written notice or the worker.
        with self.assertLogs('jarvis', level='ERROR') as captured, \
                patch("config.load_settings", side_effect=OSError("bozuk ayar")):
            self.assertFalse(event_channels.announce_speech())
        self.assertIn('event_channels.py:announce_speech', captured.output[0],
                      "sessiz kapılma nedenini kaybetmesin: arıza ölçülü susturma, sessiz tahmin değil")

    def test_the_fanout_carries_the_channel_instead_of_refusing_it(self):
        # A name the fanout did not know would raise inside dispatch and turn the
        # notice into a failed channel for every event, not a spoken one.
        heard = []
        result = event_fanout.dispatch({"source": "s", "kind": "k", "payload": {}},
                                       {"voice": lambda event: heard.append(event)}, ["voice"])
        self.assertEqual(result, {"voice": "delivered"})
        self.assertEqual(heard, [{"source": "s", "kind": "k", "payload": {}}])

    def test_the_bridge_stores_what_the_page_sends(self):
        bridge = web.Bridge.__new__(web.Bridge)
        with patch.object(web.config, "save_settings") as save, patch.object(web, "_wakeword"):
            bridge.settings_save({"voice_announce_results": True})
            save.assert_called_once_with(voice_announce_results=True)
            bridge.settings_save({"voice_announce_results": 0})
            self.assertEqual(save.call_args.kwargs["voice_announce_results"], False)
            bridge.settings_save({"wake_beep": True})
            self.assertNotIn("voice_announce_results", save.call_args.kwargs,
                             "bir istek anahtarı taşımadığında onu icat etmez")

    def test_the_bridge_shows_the_stored_choice_to_the_page(self):
        from modules import local_stt
        bridge = web.Bridge.__new__(web.Bridge)
        for stored, shown in (({}, False), ({"voice_announce_results": True}, True),
                              ({"voice_announce_results": False}, False)):
            with self.subTest(stored=stored), \
                    patch.object(web.config, "load_settings", return_value=stored), \
                    patch.object(web.config, "INPUT_DEVICE", None), \
                    patch.object(web, "llm", Mock(model_names=Mock(return_value=["m", []]))), \
                    patch.object(web, "_wakeword", Mock(mode=Mock(return_value="auto"))), \
                    patch.object(web, "_wake_note", Mock(return_value="")), \
                    patch.object(local_stt, "beam_size", Mock(return_value=5)), \
                    patch.object(web, "_p", Mock(slug="alice")), \
                    patch.object(web, "_aname", Mock(return_value="Jarvis")):
                self.assertIs(bridge.settings()["voice_announce_results"], shown)

    def test_the_voice_page_offers_the_switch_once_and_saves_it(self):
        js = source()
        self.assertEqual(js.count("sel('vres',"), 1, "satır tek yerde tanımlı, iki yüzey de onu çağırır")
        self.assertEqual(js.count("vresField(st,sel)+"), 2, "yan sayfa bölümü ve Ayarlar satırı")
        save_line = js.split("ACT.vsave=")[1].split("\n")[0]
        self.assertIn("voice_announce_results:$('#vres').value==='1'", save_line,
                      "Kaydet düğmesi seçimi taşır")


if __name__ == "__main__":
    unittest.main()
