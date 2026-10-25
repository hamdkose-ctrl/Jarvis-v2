"""study.py:lesson()'ın hoca_workspace per-ders kaynağına bağlanması (3. adım)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_worker, hoca_workspace, llm, study


class Profile:
    slug = "hamdi"

    def __init__(self):
        self.data = {}

    def save(self):
        pass


class LessonCourseLinkTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(file_worker, "allowed_roots", return_value=[self.root])
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_unknown_course_id_is_explicit_error(self):
        with self.assertRaises(ValueError):
            study.lesson(self.p, "Hücre", course_id=999)

    def test_course_name_used_when_course_not_given(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre.") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            study.lesson(self.p, "Hücre", course_id=course["id"])
        self.assertIn("Hücre", ask.call_args[0][0])
        self.assertIn("Biyoloji", ask.call_args[0][0])

    def test_course_book_source_is_used_as_lesson_source(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        book = self.root / "kitap.txt"
        book.write_text("Mitokondri hücrenin enerji santralidir.", encoding="utf-8")
        hoca_workspace.add_source(self.p, course["id"], "kitap", str(book), label="Biyoloji Kitabı")
        with patch.object(llm, "ask", return_value="## Konu nedir?\nMitokondri.") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            lesson = study.lesson(self.p, "Mitokondri", course_id=course["id"])
        self.assertIn("Mitokondri hücrenin enerji santralidir", ask.call_args[0][0])
        self.assertIn("Biyoloji Kitabı", lesson["sources"])
        self.assertFalse(lesson["no_book"])

    def test_no_course_source_keeps_legacy_no_book_detection(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre.") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            lesson = study.lesson(self.p, "Hücre", course_id=course["id"])
        self.assertTrue(lesson["no_book"])
        self.assertIn("Kitap yüklenmedi", ask.call_args[0][0])

    def test_legacy_call_without_course_id_is_unaffected(self):
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre.") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            lesson = study.lesson(self.p, "Hücre", "Biyoloji")
        self.assertTrue(lesson["no_book"])
        self.assertEqual(lesson["sources"], [])


class LessonSessionMemoryTests(unittest.TestCase):
    """3. adım (Seçenek A): ders anlatımı bitince otomatik oturum notu, tekrar girişte resume hint."""

    def setUp(self):
        self.p = Profile()

    def test_normal_lesson_records_next_step(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre.") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            study.lesson(self.p, "Hücre", course_id=course["id"])
        session = hoca_workspace.get_session(self.p, course["id"], "Hücre")
        self.assertIn("anlatıldı", session["next_step"])
        self.assertEqual(session["unclear"], [])

    def test_simpler_lesson_records_unclear(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        with patch.object(llm, "ask", return_value="## Sade anlatım") as ask, \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            study.lesson(self.p, "Hücre", course_id=course["id"], simpler=True)
        session = hoca_workspace.get_session(self.p, course["id"], "Hücre")
        self.assertIn("Hücre", session["unclear"])

    def test_second_call_surfaces_prior_session_as_resume(self):
        course = hoca_workspace.add_course(self.p, "Biyoloji")
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre."), \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            study.lesson(self.p, "Hücre", course_id=course["id"], simpler=True)
            with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre.") as ask:
                lesson = study.lesson(self.p, "Hücre", course_id=course["id"])
        self.assertEqual(lesson["resume"]["unclear"], ["Hücre"])
        self.assertIn("net değildi", ask.call_args[0][0])

    def test_no_course_id_does_not_touch_session_memory(self):
        with patch.object(llm, "ask", return_value="## Konu nedir?\nHücre."), \
             patch.object(llm, "embed", side_effect=ValueError("no embed")):
            study.lesson(self.p, "Hücre", "Biyoloji")
        self.assertEqual(self.p.data.get("hoca_courses", []), [])


if __name__ == "__main__":
    unittest.main()
