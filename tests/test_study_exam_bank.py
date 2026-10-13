import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SAMPLE = """(441) BİYOLOJİ – 1 21
(443) BİYOLOJİ – 3 22
ADAYLARIN DİKKATİNE!
(441) BİYOLOJİ – 1
1.  Aşağıdakilerden hangisi canlıların ortak özelliği değildir?
A) Hücreden oluşma B) Üreme
C) Fotosentez yapma D) Metabolizma
2.  Hücre zarının yapısında hangisi
bulunmaz?
A) Fosfolipit
B) Protein
C) Kolesterol
D) Selüloz
1. OTURUM
22
3.  Sınıflandırmada en küçük birim hangisidir?
A) Tür B) Cins C) Aile D) Takım
(443) BİYOLOJİ – 3
1.  Kalıtımla ilgili hangisi doğrudur?
A) a B) b C) c D) d
2.  Mutasyon nedir?
A) a B) b C) c D) d
3.  Genotip nedir?
A) a B) b C) c D) d
2025-2026 ÖĞRETİM YILI CEVAP ANAHTARI
(441) BİYOLOJİ – 1
1.  C
2.  D
3.  A
(443) BİYOLOJİ – 3
1.  B
2.  A
3.  C
"""


class ExamParseTests(unittest.TestCase):
    def test_parse_courses_questions_and_key(self):
        from modules import studyexam as se
        c = se.parse(SAMPLE)
        bio1 = next(v for v in c.values() if v["code"] == "441")
        self.assertEqual(bio1["name"], "BİYOLOJİ – 1")
        self.assertEqual([q["n"] for q in bio1["questions"]], [1, 2, 3])
        self.assertEqual(bio1["questions"][1]["options"]["D"], "Selüloz")
        self.assertEqual(bio1["questions"][1]["text"], "Hücre zarının yapısında hangisi bulunmaz?")
        self.assertEqual(bio1["answers"], {1: "C", 2: "D", 3: "A"})
        self.assertEqual(len(c), 2)                       # içindekiler satırları ders sayılmaz


class _Profile:
    slug = "deneme"

    def __init__(self, docs):
        self.data, self._n = {"study": {"mode": "teacher", "docs": docs, "progress": []}, "events": []}, 50

    def _new_id(self):
        self._n += 1
        return self._n

    def save(self):
        pass

    def add_event(self, title, when):
        self.data["events"].append({"id": self._new_id(), "title": title, "when": when})

    def delete_event(self, eid):
        self.data["events"] = [e for e in self.data["events"] if e["id"] != eid]


class StudyFlowTests(unittest.TestCase):
    def test_suggest_quiz_and_plan(self):
        import json
        from modules import llm, study, studyexam as se
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "study"
            (root / "deneme").mkdir(parents=True)
            (root / "deneme" / "1.txt").write_text(SAMPLE, encoding="utf-8")
            (root / "deneme" / "2.txt").write_text("Biyoloji 1 kitabı: hücre zarı...", encoding="utf-8")
            prof = _Profile([{"id": 1, "title": "Sorular 2025.pdf", "kind": "exam", "year": 2025, "chars": 900},
                             {"id": 2, "title": "Biyoloji_1.pdf", "kind": "book", "chars": 40}])

            def fake_ask(prompt, system=None, max_tokens=0):
                ids = [ln[1:ln.index("]")] for ln in prompt.split("\n") if ln.startswith("[") and "#" in ln[:30]]
                return json.dumps({"t": {i: ("Hücre" if i.endswith("#2") else "Canlılar") for i in ids}})

            with patch.object(study, "ROOT", root), patch.object(llm, "ask", fake_ask):
                self.assertEqual(len(se.suggest_courses(prof)), 1)        # kitap adına göre BİYOLOJİ – 1 önerilir
                a = study.analyze_recent_exams(prof, force=True)
                self.assertEqual(a["source"], "kitapçık")
                self.assertEqual(a["question_count"], 3)
                q = se.quiz_next(prof)
                self.assertIn(q["year"], (2025,))
                r = se.quiz_answer(prof, q["id"], next(c for c in q["options"] if c != se._find(prof,q["id"])[1]["answer"]))
                self.assertFalse(r["ok"])
                self.assertIn(r["answer"], "ACD")
                p = se.set_plan_cfg(prof, {"minutes": 60, "days": [0, 1, 2, 3, 4, 5, 6], "time": "19:00"})
                self.assertEqual(len(p["days"]), 7)
                self.assertTrue(all(b["minutes"] > 0 for d in p["days"] for b in d["blocks"]))
                self.assertEqual(se.set_reminders(prof), 7)
                with patch.object(llm, "ask", lambda *a, **k: "## Konu nedir?\nUzun anlatım"):
                    les = study.lesson(prof, "Hücre", "BİYOLOJİ – 1", q["mk"])
                self.assertIn("Konu nedir", les["text"])
                self.assertFalse(les["no_book"])                    # Biyoloji_1.pdf kitap olarak var
                rq = se.related_questions(prof, "hücre zarı", k=3)
                self.assertTrue(rq and "Cevap" in rq[0]["chunk"])
                self.assertTrue(prof.data["events"][0]["when"].endswith("T19:00"))


if __name__ == "__main__":
    unittest.main()
