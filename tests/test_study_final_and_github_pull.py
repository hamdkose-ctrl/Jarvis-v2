import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class Profile:
    slug = "hamdi"
    def __init__(self, docs=None):
        self.data = {"study": {"mode": "teacher", "docs": docs or [], "progress": []}, "events": []}
        self.n = 100
    def _new_id(self):
        self.n += 1; return self.n
    def save(self):
        pass
    def add_event(self, title, when):
        self.data["events"].append({"id": self._new_id(), "title": title, "when": when})
    def delete_event(self, eid):
        self.data["events"] = [e for e in self.data["events"] if e["id"] != eid]


SAMPLE = """(441) BİYOLOJİ – 1
1. Soru bir? A) a B) b C) c D) d
2. Soru iki? A) a B) b C) c D) d
3. Soru üç? A) a B) b C) c D) d
CEVAP ANAHTARI
(441) BİYOLOJİ – 1
1. A
2. B
3. C
"""


class FinalStudyTests(unittest.TestCase):
    def test_same_year_sessions_have_unique_question_ids(self):
        from modules import study, studyexam
        docs = [
            {"id": 1, "title": "a.pdf", "kind": "exam", "year": 2025, "period": "1. Dönem", "session": "1. Oturum", "chars": 100},
            {"id": 2, "title": "b.pdf", "kind": "exam", "year": 2025, "period": "1. Dönem", "session": "2. Oturum", "chars": 100},
        ]
        p = Profile(docs)
        with tempfile.TemporaryDirectory() as td, patch.object(study, "ROOT", Path(td)):
            d = Path(td) / p.slug; d.mkdir(parents=True)
            (d / "1.txt").write_text(SAMPLE, encoding="utf-8")
            (d / "2.txt").write_text(SAMPLE, encoding="utf-8")
            b = next(iter(studyexam.bank(p).values()))
            ids = [q["id"] for q in b["items"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(any("#1#2025#1" in x for x in ids))
            self.assertTrue(any("#2#2025#1" in x for x in ids))

    def test_topic_lock_is_in_lesson_system_prompt(self):
        from modules import study, llm
        p = Profile([{"id": 2, "title": "kitap.txt", "kind": "book", "chars": 40}])
        with tempfile.TemporaryDirectory() as td, patch.object(study, "ROOT", Path(td)):
            d = Path(td) / p.slug; d.mkdir(parents=True)
            (d / "2.txt").write_text("Hücre zarı fosfolipit yapıdadır.", encoding="utf-8")
            seen = {}
            def fake(prompt, system=None, max_tokens=0):
                seen["system"] = system or ""
                return "## Konu nedir?\nHücre zarı."
            with patch.object(llm, "ask", fake), patch.object(llm, "embed", side_effect=ValueError("no embed")):
                study.lesson(p, "Hücre zarı", "Biyoloji")
            self.assertIn("AKTİF KONU KİLİDİ", seen["system"])
            self.assertIn("Hücre zarı", seen["system"])
            self.assertIn("başka bir konuya", seen["system"])

    def test_wrong_book_and_mock_exam_flow(self):
        from modules import study, studyexam
        docs = [{"id": 1, "title": "a.pdf", "kind": "exam", "year": 2025, "period": "1. Dönem", "session": "1. Oturum", "chars": 100}]
        p = Profile(docs)
        with tempfile.TemporaryDirectory() as td, patch.object(study, "ROOT", Path(td)):
            d = Path(td) / p.slug; d.mkdir(parents=True)
            (d / "1.txt").write_text(SAMPLE, encoding="utf-8")
            mk = next(iter(studyexam.bank(p)))
            p.data["study"]["courses"] = [mk]
            # Konu etiketi hazırmış gibi davran; deneme ve yanlış defteri yapay zekâ gerektirmesin.
            for q in studyexam.bank(p)[mk]["items"]:
                p.data["study"].setdefault("topics", {}).setdefault(mk, {})[q["id"]] = "Temel Konu"
            q = studyexam.quiz_next(p, mk)
            studyexam.quiz_answer(p, q["id"], next(c for c in q["options"] if c != studyexam._find(p,q["id"])[1]["answer"]))
            w = studyexam.wrong_summary(p)
            self.assertEqual(len(w["active"]), 1)
            m = studyexam.mock_start(p, 10)
            self.assertTrue(m["active"]); self.assertEqual(m["total"], 3)
            cur = m["current"]
            ans = studyexam._find(p, cur["id"])[1]["answer"]
            r = studyexam.mock_answer(p, cur["id"], ans)
            self.assertEqual(r["status"]["answered"], 1)

    def test_pdf_page_metadata_is_used_in_search(self):
        from modules import study, llm
        p = Profile([{"id": 2, "title": "kitap.pdf", "kind": "book", "chars": 80}])
        with tempfile.TemporaryDirectory() as td, patch.object(study, "ROOT", Path(td)):
            d = Path(td) / p.slug; d.mkdir(parents=True)
            (d / "2.txt").write_text("Giriş.\n\nMotor koruma rölesi açıklaması.", encoding="utf-8")
            (d / "2.pages.json").write_text(json.dumps({"pages": ["Giriş", "Motor koruma rölesi açıklaması"]}), encoding="utf-8")
            with patch.object(llm, "embed", side_effect=ValueError("no embed")):
                hit = study._search_items(p, "motor koruma", top=1, kind="book")[0]
            self.assertEqual(hit["page"], 2)


class GitHubStateTests(unittest.TestCase):
    def test_remote_ahead_when_local_matches_base(self):
        import updater
        with patch.object(updater, "status", return_value={}), \
             patch.object(updater, "latest", return_value={"sha": "remote", "msg": "new", "date": ""}), \
             patch.object(updater, "_state", return_value={"sha": "base"}), \
             patch.object(updater, "_source_changes_against", side_effect=lambda sha, limit=120: ["web.py"] if sha == "remote" else []), \
             patch.object(updater, "_compare_commits", return_value="ahead"), \
             patch.object(updater, "_save_state"):
            st = updater.verify_sync()
        self.assertEqual(st["sync_state"], "remote_ahead")


if __name__ == "__main__":
    unittest.main()
