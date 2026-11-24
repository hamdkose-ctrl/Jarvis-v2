"""PC ajanı 3. dilim: tıkla/yaz güvenlik kuralları (UIA ve pencere taklit)."""
import unittest
from unittest.mock import patch

from modules import pc_hands

WIN = {"title": "Not Defteri", "hwnd": 42, "pid": 7, "app": "notepad"}


def _ctl(name, kind="ControlType.Button", cid="c1", patterns=None):
    return {"id": cid, "name": name, "type": kind, "patterns": patterns or []}


class FakeUI:
    calls = []
    error = None

    def act(self, snapshot, action, *, read_only=False):
        if FakeUI.error:
            raise FakeUI.error
        FakeUI.calls.append(action)
        return {"ok": True}


class Hands(unittest.TestCase):
    def setUp(self):
        FakeUI.calls = []
        FakeUI.error = None
        pc_hands._last_action.clear()

    def _patch(self, controls, match=WIN, calls=None):
        calls = calls if calls is not None else []
        return (
            patch.object(pc_hands.pc_awareness, "find_window",
                         lambda q: {"match": match, "reason": "" if match else "missing"}),
            patch.object(pc_hands.pc_awareness, "controls",
                         lambda w: {"controls": controls, "window": w}),
            patch("modules.desktop_uia.DesktopUI", FakeUI),
        )

    def test_click_invokes_matching_control(self):
        p1, p2, p3 = self._patch([_ctl("Kaydet"), _ctl("Kapat", cid="c2")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "done")
        self.assertEqual(FakeUI.calls[0]["op"], "invoke")
        self.assertEqual(FakeUI.calls[0]["control"], "c1")

    def test_risky_click_needs_confirmation_and_does_nothing(self):
        p1, p2, p3 = self._patch([_ctl("Sil")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "sil")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(FakeUI.calls, [])

    def test_risky_click_runs_with_confirmation(self):
        p1, p2, p3 = self._patch([_ctl("Sil")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "sil", confirm=True)
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_missing_control_does_not_guess(self):
        p1, p2, p3 = self._patch([_ctl("Kaydet")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "yazdır")
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(FakeUI.calls, [])

    def test_ambiguous_control_asks_once(self):
        p1, p2, p3 = self._patch([_ctl("Kaydet", cid="a"), _ctl("Kaydet ve kapat", cid="b")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("Hangisi?", result["text"])
        self.assertEqual(FakeUI.calls, [])

    def test_same_control_twice_is_blocked(self):
        p1, p2, p3 = self._patch([_ctl("Kaydet")])
        with p1, p2, p3:
            self.assertEqual(pc_hands.click("not defteri", "kaydet")["status"], "done")
            second = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(second["status"], "repeat")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_type_text_never_targets_password(self):
        p1, p2, p3 = self._patch([_ctl("Password", kind="ControlType.Edit")])
        with p1, p2, p3:
            result = pc_hands.type_text("not defteri", "password", "gizli")
        self.assertEqual(FakeUI.calls, [])           # şifre alanı hiç okunmaz
        self.assertNotEqual(result["status"], "done")

    def test_type_text_uses_set_value_when_available(self):
        p1, p2, p3 = self._patch([_ctl("Ad", kind="ControlType.Edit", patterns=["value"])])
        with p1, p2, p3:
            result = pc_hands.type_text("not defteri", "ad", "Hamdi")
        self.assertEqual(result["status"], "done")
        self.assertEqual(FakeUI.calls[0]["op"], "set_value")
        self.assertEqual(FakeUI.calls[0]["value"], "Hamdi")

    def test_abort_stops_before_action(self):
        import threading
        event = threading.Event(); event.set()
        p1, p2, p3 = self._patch([_ctl("Kaydet")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "kaydet", abort=event)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(FakeUI.calls, [])

    def test_uia_failure_is_reported_honestly(self):
        from modules.desktop_uia import NotSent
        FakeUI.error = NotSent("Pencere değişti.")
        p1, p2, p3 = self._patch([_ctl("Kaydet")])
        with p1, p2, p3:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "not_sent")
        self.assertIn("değişti", result["text"])

    def test_no_window_reports_instead_of_clicking(self):
        p1, p2, p3 = self._patch([], match=None)
        with p1, p2, p3:
            result = pc_hands.click("chrome", "kapat")
        self.assertEqual(result["status"], "no_window")

    def test_risk_words_are_detected_turkish(self):
        for word in ("Sil", "SİL", "Ödeme yap", "gönder", "kaldır"):
            self.assertTrue(pc_hands.is_risky(word), word)
        for word in ("Kaydet", "Yeni dosya", "Ara"):
            self.assertFalse(pc_hands.is_risky(word), word)


if __name__ == "__main__":
    unittest.main()
