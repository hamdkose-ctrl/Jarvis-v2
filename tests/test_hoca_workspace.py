"""modules/hoca_workspace.py — domain sözleşmesi testleri (model/ağ gerektirmez)."""
import unittest
from types import SimpleNamespace

from modules import hoca_workspace as hw


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


if __name__ == "__main__":
    unittest.main()
