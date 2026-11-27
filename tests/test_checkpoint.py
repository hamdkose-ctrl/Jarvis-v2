"""Geri dönüş noktası: veri yedeği alınır, geri alma canlı veriye dokunmadan prova edilir."""
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from modules import checkpoint


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        (self.data / "users").mkdir()
        (self.data / "users" / "hamdi.json").write_text('{"ad": "Hamdi"}', encoding="utf-8")
        (self.data / "settings.json").write_text('{"ses": true}', encoding="utf-8")
        heavy = self.data / "models"
        heavy.mkdir()
        (heavy / "buyuk.bin").write_bytes(b"x" * 2048)
        p = patch.object(checkpoint, "_data", return_value=self.data)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(checkpoint, "_git_sha", return_value="abc1234")
        p.start(); self.addCleanup(p.stop)

    def test_create_writes_a_backup_with_manifest_and_without_rebuildable_folders(self):
        result = checkpoint.create("deneme")
        self.assertTrue(result["ok"])
        self.assertEqual(result["files"], 2)
        with zipfile.ZipFile(result["path"]) as bundle:
            names = bundle.namelist()
            manifest = json.loads(bundle.read("MANIFEST.json"))
        self.assertIn("users/hamdi.json", names)
        self.assertIn("settings.json", names)
        self.assertNotIn("models/buyuk.bin", names)
        self.assertEqual(manifest["commit"], "abc1234")

    def test_restore_extracts_to_a_side_folder_and_leaves_live_data_alone(self):
        name = checkpoint.create()["name"]
        (self.data / "users" / "hamdi.json").write_text('{"ad": "bozuldu"}', encoding="utf-8")
        result = checkpoint.restore(name)
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"], 0)
        self.assertEqual((self.data / "users" / "hamdi.json").read_text(encoding="utf-8"), '{"ad": "bozuldu"}')
        side = Path(result["folder"]) / "users" / "hamdi.json"
        self.assertEqual(side.read_text(encoding="utf-8"), '{"ad": "Hamdi"}')

    def test_restore_with_apply_copies_the_backup_over_live_data(self):
        name = checkpoint.create()["name"]
        (self.data / "users" / "hamdi.json").write_text('{"ad": "bozuldu"}', encoding="utf-8")
        result = checkpoint.restore(name, apply=True)
        self.assertEqual(result["applied"], 2)
        self.assertEqual((self.data / "users" / "hamdi.json").read_text(encoding="utf-8"), '{"ad": "Hamdi"}')

    def test_missing_backup_is_reported_not_raised(self):
        result = checkpoint.restore("yok.zip")
        self.assertFalse(result["ok"])
        self.assertIn("bulunamad", result["error"])

    def test_only_the_newest_five_are_kept(self):
        for index in range(7):
            path = checkpoint._dir() / f"2026010{index}-000000.zip"
            path.write_bytes(b"x")
        checkpoint.create()
        self.assertLessEqual(len(checkpoint.items()), checkpoint.KEEP)

    def test_daily_backup_runs_once_and_then_stays_quiet(self):
        first = checkpoint.maybe_daily()
        self.assertIsNotNone(first)
        self.assertIsNone(checkpoint.maybe_daily())

    def test_summary_lists_backups_with_human_sizes(self):
        checkpoint.create()
        text = checkpoint.summary()
        self.assertIn("Geri dönüş noktaları (1/5)", text)
        self.assertIn("MB", text)

    def test_cli_list_and_create_exit_codes(self):
        self.assertEqual(checkpoint.main(["list"]), 0)
        self.assertEqual(checkpoint.main(["restore"]), 2)


if __name__ == "__main__":
    unittest.main()
