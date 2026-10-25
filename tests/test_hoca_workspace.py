"""modules/hoca_workspace.py — domain sözleşmesi testleri (model/ağ gerektirmez)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import file_worker, hoca_workspace as hw


def _profile():
    p = SimpleNamespace(data={})
    p.save = lambda: None
    return p


class CourseTests(unittest.TestCase):
    def test_add_and_list_course(self):
        p = _profile()
        c = hw.add_course(p, "Matematik", "lgs")
        self.assertEqual(c["name"], "Matematik")
        self.assertEqual(c["level"], "lgs")
        self.assertFalse(c["exam_enabled"])
        self.assertEqual([x["name"] for x in hw.list_courses(p)], ["Matematik"])

    def test_duplicate_name_rejected_case_insensitive(self):
        p = _profile()
        hw.add_course(p, "Matematik")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.add_course(p, "matematik")

    def test_empty_name_rejected(self):
        p = _profile()
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.add_course(p, "   ")

    def test_unknown_level_falls_back_to_genel(self):
        p = _profile()
        c = hw.add_course(p, "Tarih", "lise2")
        self.assertEqual(c["level"], "genel")

    def test_ids_increment(self):
        p = _profile()
        a = hw.add_course(p, "Fizik")
        b = hw.add_course(p, "Kimya")
        self.assertEqual((a["id"], b["id"]), (1, 2))


class SourceTests(unittest.TestCase):
    def test_add_source_requires_existing_course(self):
        p = _profile()
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.add_source(p, 999, "kitap", "fizik.pdf")

    def test_add_source_unknown_type_rejected(self):
        p = _profile()
        c = hw.add_course(p, "Fizik")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.add_source(p, c["id"], "ses_dosyasi", "x.mp3")

    def test_exam_source_auto_enables_exam_tracking(self):
        p = _profile()
        c = hw.add_course(p, "Fizik")
        self.assertFalse(hw.get_course(p, c["id"])["exam_enabled"])
        hw.add_source(p, c["id"], "çıkmış_soru", "2025-lgs.pdf")
        self.assertTrue(hw.get_course(p, c["id"])["exam_enabled"])

    def test_regular_source_does_not_enable_exam_tracking(self):
        p = _profile()
        c = hw.add_course(p, "Fizik")
        hw.add_source(p, c["id"], "kitap", "ders-kitabi.pdf")
        self.assertFalse(hw.get_course(p, c["id"])["exam_enabled"])


class AssignmentTests(unittest.TestCase):
    def test_add_and_list_assignment(self):
        p = _profile()
        c = hw.add_course(p, "Kimya")
        a = hw.add_assignment(p, c["id"], "Ödev 1", due="2026-11-03")
        self.assertFalse(a["done"])
        self.assertEqual(hw.list_assignments(p, c["id"]), [a])

    def test_list_assignments_all_courses(self):
        p = _profile()
        c1 = hw.add_course(p, "Kimya")
        c2 = hw.add_course(p, "Fizik")
        hw.add_assignment(p, c1["id"], "Ödev A")
        hw.add_assignment(p, c2["id"], "Ödev B")
        self.assertEqual(len(hw.list_assignments(p)), 2)

    def test_empty_title_rejected(self):
        p = _profile()
        c = hw.add_course(p, "Kimya")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.add_assignment(p, c["id"], "")

    def test_bad_origin_falls_back_to_manual(self):
        p = _profile()
        c = hw.add_course(p, "Kimya")
        a = hw.add_assignment(p, c["id"], "Ödev", origin="weird")
        self.assertEqual(a["origin"], "manual")


class SessionTests(unittest.TestCase):
    def test_record_and_get_session(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.record_session(p, c["id"], "Mitokondri", unclear="ATP üretimi", next_step="krebs döngüsü")
        s = hw.get_session(p, c["id"], "Mitokondri")
        self.assertEqual(s["unclear"], ["ATP üretimi"])
        self.assertEqual(s["next_step"], "krebs döngüsü")
        self.assertEqual(s["solved"], [])

    def test_session_accumulates_across_calls(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.record_session(p, c["id"], "Mitokondri", solved="soru 1")
        hw.record_session(p, c["id"], "Mitokondri", solved="soru 2")
        self.assertEqual(hw.get_session(p, c["id"], "Mitokondri")["solved"], ["soru 1", "soru 2"])

    def test_next_step_overwrites_not_accumulates(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.record_session(p, c["id"], "Mitokondri", next_step="adım 1")
        hw.record_session(p, c["id"], "Mitokondri", next_step="adım 2")
        self.assertEqual(hw.get_session(p, c["id"], "Mitokondri")["next_step"], "adım 2")

    def test_get_session_missing_topic_returns_none(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        self.assertIsNone(hw.get_session(p, c["id"], "Hiç işlenmemiş konu"))

    def test_empty_topic_rejected(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.record_session(p, c["id"], "   ")


class SourceReadingTests(unittest.TestCase):
    """İkinci bir dosya okuyucu kurulmadı: file_worker.extract() yeniden kullanılıyor."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(file_worker, "allowed_roots", return_value=[self.root])
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_read_source_text_from_txt_file(self):
        f = self.root / "ders-notu.txt"
        f.write_text("Mitokondri ATP üretir.", encoding="utf-8")
        self.assertIn("Mitokondri", hw.read_source_text(str(f)))

    def test_read_source_text_missing_file_raises(self):
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.read_source_text(str(self.root / "yok.txt"))

    def test_read_source_text_outside_allowed_root_raises(self):
        outside = Path(tempfile.mkdtemp()) / "disari.txt"
        outside.write_text("x", encoding="utf-8")
        try:
            with self.assertRaises(hw.HocaWorkspaceError):
                hw.read_source_text(str(outside))
        finally:
            outside.unlink()

    def test_course_context_none_when_no_readable_source(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.add_source(p, c["id"], "video", "https://youtube.com/watch?v=x")
        self.assertIsNone(hw.course_context(c))

    def test_course_context_joins_readable_sources(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        f = self.root / "kitap.txt"
        f.write_text("Hücre zarı seçici geçirgendir.", encoding="utf-8")
        hw.add_source(p, c["id"], "kitap", str(f), label="Biyoloji Kitabı")
        ctx = hw.course_context(hw.get_course(p, c["id"]))
        self.assertIsNotNone(ctx)
        self.assertIn("Hücre zarı", ctx["text"])
        self.assertIn("Biyoloji Kitabı", ctx["text"])
        self.assertTrue(ctx["full"])
        self.assertEqual(ctx["warnings"], [])

    def test_course_context_skips_unreadable_and_reports_warning(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.add_source(p, c["id"], "kitap", str(self.root / "yok.pdf"), label="Eksik kitap")
        self.assertIsNone(hw.course_context(hw.get_course(p, c["id"])))


SUBTASK_PLAN = '{"subtasks":[{"title":"Kaynak araştırması","due":"2026-11-01"},{"title":"Taslak yazımı","due":"2026-11-05"},{"title":"Son okuma","due":"2026-11-08"}]}'


class DecomposeAssignmentTests(unittest.TestCase):
    """4a: büyük ödev/projeyi alt görevlere bölme (tek model çağrısı, salt-okunur kaynak gerektirmez)."""

    def test_unknown_course_id_raises(self):
        p = _profile()
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.decompose_assignment(p, 999, "Dönem projesi")

    def test_creates_parent_and_subtasks(self):
        from modules import llm
        p = _profile()
        c = hw.add_course(p, "Tarih")
        with patch.object(llm, "ask", return_value=SUBTASK_PLAN):
            result = hw.decompose_assignment(p, c["id"], "Dönem projesi", due="2026-11-10")
        self.assertEqual(result["parent"]["title"], "Dönem projesi")
        self.assertEqual(result["parent"]["origin"], "manual")
        self.assertEqual(len(result["subtasks"]), 3)
        self.assertTrue(all(s["origin"] == "decomposed" for s in result["subtasks"]))
        self.assertTrue(all(s["parent_id"] == result["parent"]["id"] for s in result["subtasks"]))
        all_assignments = hw.list_assignments(p, c["id"])
        self.assertEqual(len(all_assignments), 4)  # 1 asıl + 3 alt görev

    def test_too_few_subtasks_raises_and_parent_still_recorded(self):
        from modules import llm
        p = _profile()
        c = hw.add_course(p, "Tarih")
        with patch.object(llm, "ask", return_value='{"subtasks":[{"title":"Tek adım"}]}'):
            with self.assertRaises(hw.HocaWorkspaceError):
                hw.decompose_assignment(p, c["id"], "Dönem projesi")
        # Asıl ödev model hatasından önce eklendiği için kayıtta kalır (kullanıcı elle alt görev ekleyebilir).
        self.assertEqual(len(hw.list_assignments(p, c["id"])), 1)

    def test_malformed_model_answer_raises(self):
        from modules import llm
        p = _profile()
        c = hw.add_course(p, "Tarih")
        with patch.object(llm, "ask", return_value="bozuk cevap, json yok"):
            with self.assertRaises(hw.HocaWorkspaceError):
                hw.decompose_assignment(p, c["id"], "Dönem projesi")

    def test_model_call_failure_raises_hoca_workspace_error(self):
        from modules import llm
        p = _profile()
        c = hw.add_course(p, "Tarih")
        with patch.object(llm, "ask", side_effect=RuntimeError("ağ hatası")):
            with self.assertRaises(hw.HocaWorkspaceError):
                hw.decompose_assignment(p, c["id"], "Dönem projesi")


class TermOverviewTests(unittest.TestCase):
    """4b: tüm derslerin ödev/deadline'larını tarihe göre sıralı, salt-okunur gösterim."""

    def test_empty_when_no_assignments(self):
        p = _profile()
        hw.add_course(p, "Biyoloji")
        self.assertEqual(hw.term_overview(p), [])

    def test_sorted_by_date_across_courses(self):
        p = _profile()
        bio = hw.add_course(p, "Biyoloji")
        tarih = hw.add_course(p, "Tarih")
        hw.add_assignment(p, bio["id"], "Geç ödev", due="2026-12-01")
        hw.add_assignment(p, tarih["id"], "Erken ödev", due="2026-11-01")
        overview = hw.term_overview(p)
        self.assertEqual([x["title"] for x in overview], ["Erken ödev", "Geç ödev"])
        self.assertEqual(overview[0]["course_name"], "Tarih")

    def test_undated_items_come_last_in_creation_order(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.add_assignment(p, c["id"], "Tarihli", due="2026-11-01")
        hw.add_assignment(p, c["id"], "Önce eklenen serbest")
        hw.add_assignment(p, c["id"], "Sonra eklenen serbest")
        overview = hw.term_overview(p)
        self.assertEqual([x["title"] for x in overview], ["Tarihli", "Önce eklenen serbest", "Sonra eklenen serbest"])

    def test_non_iso_due_text_treated_as_undated(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.add_assignment(p, c["id"], "Serbest tarih", due="gelecek hafta")
        hw.add_assignment(p, c["id"], "Gerçek tarih", due="2026-11-01")
        overview = hw.term_overview(p)
        self.assertEqual([x["title"] for x in overview], ["Gerçek tarih", "Serbest tarih"])

    def test_done_excluded_by_default_and_included_on_request(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Bitmiş ödev", due="2026-11-01")
        course = hw.get_course(p, c["id"])
        next(x for x in course["assignments"] if x["id"] == a["id"])["done"] = True
        self.assertEqual(hw.term_overview(p), [])
        self.assertEqual(len(hw.term_overview(p, include_done=True)), 1)

    def test_original_assignment_record_not_mutated(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Ödev", due="2026-11-01")
        hw.term_overview(p)
        self.assertNotIn("course_id", a)
        self.assertNotIn("course_name", a)


class AssignmentGradeTests(unittest.TestCase):
    """4c-1: ödev/sınav bazlı not kaydı + ağırlıklı ders notu."""

    def test_set_grade_and_read_back(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Vize")
        hw.set_assignment_grade(p, c["id"], a["id"], 80, max_score=100, weight=2)
        course = hw.get_course(p, c["id"])
        self.assertEqual(course["assignments"][0]["grade"], {"score": 80.0, "max": 100.0, "weight": 2.0})

    def test_grade_defaults_to_100_max_and_weight_1(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Kısa sınav")
        hw.set_assignment_grade(p, c["id"], a["id"], 45)
        course = hw.get_course(p, c["id"])
        self.assertEqual(course["assignments"][0]["grade"], {"score": 45.0, "max": 100.0, "weight": 1.0})

    def test_unknown_assignment_id_raises(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.set_assignment_grade(p, c["id"], 999, 80)

    def test_zero_or_negative_max_score_raises(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Vize")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.set_assignment_grade(p, c["id"], a["id"], 80, max_score=0)

    def test_negative_score_or_weight_raises(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Vize")
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.set_assignment_grade(p, c["id"], a["id"], -5)
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.set_assignment_grade(p, c["id"], a["id"], 80, weight=-1)

    def test_resetting_grade_overwrites_not_accumulates(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a = hw.add_assignment(p, c["id"], "Vize")
        hw.set_assignment_grade(p, c["id"], a["id"], 50)
        hw.set_assignment_grade(p, c["id"], a["id"], 90)
        course = hw.get_course(p, c["id"])
        self.assertEqual(course["assignments"][0]["grade"]["score"], 90.0)

    def test_course_grade_none_when_no_grades(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        hw.add_assignment(p, c["id"], "Ödev")
        result = hw.course_grade(p, c["id"])
        self.assertIsNone(result["value"])
        self.assertEqual(result["graded_count"], 0)
        self.assertEqual(result["total_count"], 1)

    def test_course_grade_weighted_average(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a1 = hw.add_assignment(p, c["id"], "Vize")
        a2 = hw.add_assignment(p, c["id"], "Final")
        hw.set_assignment_grade(p, c["id"], a1["id"], 60, max_score=100, weight=1)
        hw.set_assignment_grade(p, c["id"], a2["id"], 90, max_score=100, weight=2)
        # (60*1 + 90*2) / 3 = 80
        result = hw.course_grade(p, c["id"])
        self.assertEqual(result["value"], 80.0)
        self.assertEqual(result["graded_count"], 2)
        self.assertEqual(result["total_count"], 2)

    def test_course_grade_normalizes_different_max_scores(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a1 = hw.add_assignment(p, c["id"], "Kısa sınav")  # 8/10 = %80
        a2 = hw.add_assignment(p, c["id"], "Final")  # 70/100 = %70
        hw.set_assignment_grade(p, c["id"], a1["id"], 8, max_score=10, weight=1)
        hw.set_assignment_grade(p, c["id"], a2["id"], 70, max_score=100, weight=1)
        result = hw.course_grade(p, c["id"])
        self.assertEqual(result["value"], 75.0)

    def test_ungraded_assignment_excluded_from_average(self):
        p = _profile()
        c = hw.add_course(p, "Biyoloji")
        a1 = hw.add_assignment(p, c["id"], "Vize")
        hw.add_assignment(p, c["id"], "Henüz notsuz")
        hw.set_assignment_grade(p, c["id"], a1["id"], 70)
        result = hw.course_grade(p, c["id"])
        self.assertEqual(result["value"], 70.0)
        self.assertEqual(result["graded_count"], 1)
        self.assertEqual(result["total_count"], 2)

    def test_unknown_course_id_raises(self):
        p = _profile()
        with self.assertRaises(hw.HocaWorkspaceError):
            hw.course_grade(p, 999)


if __name__ == "__main__":
    unittest.main()
