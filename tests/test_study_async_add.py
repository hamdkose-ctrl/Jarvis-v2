import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class _Profile:
    slug = "deneme"

    def __init__(self):
        self.data, self._n = {}, 0

    def _new_id(self):
        self._n += 1
        return self._n

    def save(self):
        pass


class StudyAsyncAddTests(unittest.TestCase):
    def test_add_runs_in_background_and_dedups(self):
        from modules import study
        with tempfile.TemporaryDirectory() as td, patch.object(study, "ROOT", Path(td) / "study"):
            src = Path(td) / "kitap.txt"
            src.write_text("Hücre canlıların en küçük yapı birimidir.\\n\\nEvrim konusu.", encoding="utf-8")
            prof = _Profile()
            r = study.add_async(prof, str(src))
            self.assertTrue(r.get("pending"))
            again = study.add_async(prof, str(src))
            self.assertTrue(again.get("already") or again.get("exists"))   # ikinci deneme ikinci kez okumaz
            for _ in range(100):
                if not [j for j in study.pending(prof) if j["state"] == "running"]:
                    break
                time.sleep(0.05)
            st = study.status(prof)
            self.assertEqual([d["title"] for d in st["books"]], ["kitap.txt"])
            self.assertEqual(st["pending"], [])
            self.assertTrue(study.add_async(prof, str(src)).get("exists"))


if __name__ == "__main__":
    unittest.main()
