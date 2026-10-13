"""Klasör izleme: kural komutları, yeni dosya tespiti, inmekte olan dosya, kota ve döngü önleme."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import nxapi, watcher


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.down = self.home / "Downloads"
        self.down.mkdir(parents=True)
        (self.down / "eski.pdf").write_bytes(b"old")
        self.enterContext(patch.object(watcher, "DATA_DIR", self.tmp / "data"))
        self.enterContext(patch.object(nxapi, "HOME", self.home))
        self.enterContext(patch.object(nxapi, "FILES_DIR", self.home / "Documents" / "Jarvis Dosyaları"))
        for d in (watcher._STATE, watcher._RECENT, watcher._PENDING):
            d.clear()
        watcher.OUTPUTS.clear()
        self.sent = []

    def add(self, command="İndirilenler'i izle, PDF gelince haber ver"):
        reply = watcher.handle("hamdi", command)
        time.sleep(0.02)                           # eski.pdf kuraldan önce; sonra yazılanlar yeni sayılır
        return reply, watcher.load("hamdi")[-1]

    def tick(self):
        watcher.tick("hamdi", self.sent.append)

    def test_rule_commands_parse_folder_kind_and_action(self):
        reply, rule = self.add("İndirilenler'i izle, PDF gelince önemli yerleri tablo yap")
        self.assertIn("izliyorum", reply)
        self.assertEqual((Path(rule["folder"]), rule["exts"], rule["action"]), (self.down, [".pdf"], "workbench"))
        (self.home / "Desktop").mkdir()
        watcher.handle("hamdi", "Masaüstünü izle, Excel gelince özetle")
        self.assertEqual(watcher.load("hamdi")[-1]["exts"], [".csv", ".xlsm", ".xlsx"])
        self.assertEqual(watcher.load("hamdi")[-1]["action"], "summary")
        self.assertIn("İndirilenler: PDF gelince", watcher.handle("hamdi", "izlenen klasörler"))
        self.assertIsNone(watcher.handle("hamdi", "bu videoyu izle"))
        self.assertIsNone(watcher.handle("hamdi", "videoyu izlemeyi durdur"))
        self.assertIn("anlayamadım", watcher.handle("hamdi", "İndirilenler'i izle, PDF gelince dans et"))
        self.assertEqual(watcher.handle("hamdi", "Masaüstü izlemesini durdur"), "1 izleme kuralı kapatıldı.")
        self.assertEqual(watcher.handle("hamdi", "izlemeyi durdur"), "1 izleme kuralı kapatıldı.")
        self.assertIsNone(watcher.handle("hamdi", "izlemeyi durdur"))   # kural yoksa başka komutlara kalır

    def test_folder_outside_user_folders_is_refused(self):
        with patch.object(nxapi, "allowed", return_value=None):
            self.assertIn("izleyemem", watcher.handle("hamdi", "İndirilenler'i izle, PDF gelince haber ver"))

    def test_new_file_waits_until_size_is_stable_and_old_files_are_ignored(self):
        self.add()
        (self.down / "yeni.pdf.crdownload").write_bytes(b"x")
        (self.down / "yeni.pdf").write_bytes(b"12")
        (self.down / "not.txt").write_bytes(b"x")
        self.tick()
        self.assertEqual(self.sent, [])                    # ilk görüş: boyut takibe alındı
        (self.down / "yeni.pdf").write_bytes(b"1234")      # hâlâ iniyor
        self.tick()
        self.assertEqual(self.sent, [])
        self.tick()
        self.assertEqual(self.sent, ["İndirilenler klasörüne yeni dosya geldi: yeni.pdf"])
        self.tick()
        self.assertEqual(len(self.sent), 1)                # aynı dosya ikinci kez işlenmez
        watcher._STATE.clear()                             # Jarvis yeniden başladı
        self.tick()
        self.tick()
        self.assertEqual(len(self.sent), 1)

    def test_workbench_output_does_not_trigger_again(self):
        self.add("İndirilenler'i izle, dosya gelince tablo yap")
        (self.down / "sartname.pdf").write_bytes(b"x")
        out = self.down / "sartname_tablo.xlsx"

        def fake(owner, paths, instruction):
            out.write_bytes(b"x")
            return f"Hazır: {out}\n\n| a |"
        with patch("modules.workbench.handle", side_effect=fake) as handle:
            self.tick()
            self.tick()
            self.tick()
            self.tick()
        handle.assert_called_once_with("hamdi", [str(self.down / "sartname.pdf")], "tablo yap")
        self.assertTrue(self.sent[0].startswith("sartname.pdf geldi. Hazır:"))

    def test_hourly_limit_holds_extra_files_until_asked(self):
        self.add()
        for i in range(7):
            (self.down / f"f{i}.pdf").write_bytes(b"x")
        self.tick()
        self.tick()
        self.assertEqual(sum("yeni dosya geldi" in s for s in self.sent), watcher.HOURLY_LIMIT)
        self.assertIn("2 yeni dosya bekliyor", self.sent[-1])
        self.assertEqual(watcher.handle("hamdi", "bekleyen dosyaları işle").count("yeni dosya geldi"), 2)
        self.assertEqual(watcher.handle("hamdi", "bekleyen dosyaları işle"), "Bekleyen dosya yok.")

    def test_missing_folder_pauses_rule_without_crashing(self):
        self.add()
        self.down.rename(self.home / "silindi")
        self.tick()
        self.tick()
        self.assertEqual(self.sent, ["İndirilenler klasörüne erişemiyorum; izlemeyi duraklattım."])
        self.assertTrue(watcher.load("hamdi")[0]["paused"])

    def test_processing_error_is_reported_not_raised(self):
        self.add("İndirilenler'i izle, PDF gelince özetle")
        (self.down / "bozuk.pdf").write_bytes(b"x")
        with patch.object(watcher.docs, "summarize", side_effect=RuntimeError("x")):
            self.tick()
            self.tick()
        self.assertIn("hata oldu", self.sent[0])

    def test_loop_runs_only_the_active_pc_user_with_their_key(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.add()
        stop = Mock()
        stop.wait.side_effect = [False, True]
        runtime = SimpleNamespace(stop_event=stop, pc_profile=lambda: SimpleNamespace(slug="hamdi", data={"prefs": {}}),
                                  _llm=Mock(), _emit_for=Mock(), notify=Mock())
        with patch.object(watcher, "tick") as tick:
            watcher.loop(runtime)
        runtime._llm.set_user_context.assert_called_once_with("hamdi")
        self.assertEqual(tick.call_args.args[0], "hamdi")


if __name__ == "__main__":
    unittest.main()
