"""PC ajanı 3. dilim: tıkla/yaz güvenlik kuralları (UIA ve pencere taklit)."""
import threading
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
            patch.object(pc_hands, "_screen_unchanged", lambda action: False),
        )

    def test_click_invokes_matching_control(self):
        p1, p2, p3, _ = self._patch([_ctl("Kaydet"), _ctl("Kapat", cid="c2")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "done")
        self.assertEqual(FakeUI.calls[0]["op"], "invoke")
        self.assertEqual(FakeUI.calls[0]["control"], "c1")

    def test_risky_click_needs_confirmation_and_does_nothing(self):
        p1, p2, p3, _ = self._patch([_ctl("Sil")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "sil")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(FakeUI.calls, [])

    def test_risky_click_runs_with_confirmation(self):
        p1, p2, p3, _ = self._patch([_ctl("Sil")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "sil", confirm=True)
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_missing_control_does_not_guess(self):
        p1, p2, p3, _ = self._patch([_ctl("Kaydet")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "yazdır")
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(FakeUI.calls, [])

    def test_ambiguous_control_asks_once(self):
        p1, p2, p3, _ = self._patch([_ctl("Kaydet", cid="a"), _ctl("Kaydet ve kapat", cid="b")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("Hangisi?", result["text"])
        self.assertEqual(FakeUI.calls, [])

    def test_same_control_twice_is_blocked(self):
        p1, p2, p3, _ = self._patch([_ctl("Kaydet")])
        with p1, p2, p3, _:
            self.assertEqual(pc_hands.click("not defteri", "kaydet")["status"], "done")
            second = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(second["status"], "repeat")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_type_text_never_targets_password(self):
        p1, p2, p3, _ = self._patch([_ctl("Password", kind="ControlType.Edit")])
        with p1, p2, p3, _:
            result = pc_hands.type_text("not defteri", "password", "gizli")
        self.assertEqual(FakeUI.calls, [])           # şifre alanı hiç okunmaz
        self.assertNotEqual(result["status"], "done")

    def test_type_text_uses_set_value_when_available(self):
        p1, p2, p3, _ = self._patch([_ctl("Ad", kind="ControlType.Edit", patterns=["value"])])
        with p1, p2, p3, _:
            result = pc_hands.type_text("not defteri", "ad", "Hamdi")
        self.assertEqual(result["status"], "done")
        self.assertEqual(FakeUI.calls[0]["op"], "set_value")
        self.assertEqual(FakeUI.calls[0]["value"], "Hamdi")

    def test_abort_stops_before_action(self):
        import threading
        event = threading.Event(); event.set()
        p1, p2, p3, _ = self._patch([_ctl("Kaydet")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "kaydet", abort=event)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(FakeUI.calls, [])

    def test_uia_failure_is_reported_honestly(self):
        from modules.desktop_uia import NotSent
        FakeUI.error = NotSent("Pencere değişti.")
        p1, p2, p3, _ = self._patch([_ctl("Kaydet")])
        with p1, p2, p3, _:
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "not_sent")
        self.assertIn("değişti", result["text"])

    def test_no_window_reports_instead_of_clicking(self):
        p1, p2, p3, _ = self._patch([], match=None)
        with p1, p2, p3, _:
            result = pc_hands.click("chrome", "kapat")
        self.assertEqual(result["status"], "no_window")

    def test_risk_words_are_detected_turkish(self):
        for word in ("Sil", "SİL", "Ödeme yap", "gönder", "kaldır"):
            self.assertTrue(pc_hands.is_risky(word), word)
        for word in ("Kaydet", "Yeni dosya", "Ara"):
            self.assertFalse(pc_hands.is_risky(word), word)


class Verification(unittest.TestCase):
    """4. dilim: bastım demek yetmez, ekran değişti mi?"""

    def setUp(self):
        pc_hands._last_action.clear()

    def test_unchanged_screen_is_reported_not_retried(self):
        FakeUI.calls = []
        FakeUI.error = None
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}),              patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [_ctl("Kaydet")], "window": w}),              patch("modules.desktop_uia.DesktopUI", FakeUI):
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "no_change")
        self.assertIn("ekran değişmedi", result["text"])
        self.assertEqual(len(FakeUI.calls), 1)          # yine de tek deneme

    def test_changed_screen_reports_done(self):
        FakeUI.calls = []
        FakeUI.error = None
        states = iter([[_ctl("Kaydet")], [_ctl("Kaydet"), _ctl("Kaydedildi", cid="c9")]])
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}),              patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": next(states), "window": w}),              patch("modules.desktop_uia.DesktopUI", FakeUI):
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "done")


if __name__ == "__main__":
    unittest.main()


class KeyboardFallback(unittest.TestCase):
    """UIA metin alanını göremiyorsa (Windows 11 Not Defteri) klavye yedeği."""

    def setUp(self):
        pc_hands._last_action.clear()

    def test_fallback_is_used_when_control_is_missing(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch.object(pc_hands, "type_with_keyboard", return_value={"status": "done", "text": "yapıştırdım"}) as kb:
            result = pc_hands.type_text("not defteri", "metin", "merhaba")
        self.assertEqual(result["status"], "done")
        self.assertEqual(kb.call_count, 1)

    def test_fallback_can_be_disabled(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch.object(pc_hands, "type_with_keyboard") as kb:
            result = pc_hands.type_text("not defteri", "metin", "merhaba", allow_keyboard_fallback=False)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(kb.call_count, 0)

    def test_respects_abort_before_pasting(self):
        event = threading.Event(); event.set()
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus") as focus:
            result = pc_hands.type_with_keyboard("not defteri", "merhaba", abort=event)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(focus.call_count, 0)
