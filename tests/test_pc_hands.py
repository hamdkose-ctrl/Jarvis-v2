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


class Confirmation(unittest.TestCase):
    """Onay akışı: sor → "onaylıyorum" → çalıştır (tek kullanımlık, süreli)."""

    def setUp(self):
        pc_hands._last_action.clear()
        pc_hands._pending.clear()
        FakeUI.calls = []
        FakeUI.error = None

    def _setup(self, controls=None):
        return (
            patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}),
            patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": controls or [_ctl("Sil")], "window": w}),
            patch("modules.desktop_uia.DesktopUI", FakeUI),
            patch.object(pc_hands, "_screen_unchanged", lambda action: False),
        )

    def test_confirmation_runs_the_asked_action(self):
        p1, p2, p3, p4 = self._setup()
        with p1, p2, p3, p4:
            asked = pc_hands.click("not defteri", "sil")
            self.assertEqual(asked["status"], "needs_confirmation")
            self.assertEqual(FakeUI.calls, [])              # henüz yapılmadı
            done = pc_hands.confirm_pending()
        self.assertEqual(done["status"], "done")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_confirmation_is_single_use(self):
        p1, p2, p3, p4 = self._setup()
        with p1, p2, p3, p4:
            pc_hands.click("not defteri", "sil")
            pc_hands.confirm_pending()
            second = pc_hands.confirm_pending()
        self.assertEqual(second["status"], "none")
        self.assertEqual(len(FakeUI.calls), 1)

    def test_without_pending_the_answer_is_honest(self):
        self.assertEqual(pc_hands.confirm_pending()["status"], "none")

    def test_expired_confirmation_does_not_run(self):
        p1, p2, p3, p4 = self._setup()
        with p1, p2, p3, p4:
            pc_hands.click("not defteri", "sil")
            pc_hands._pending["at"] -= pc_hands.PENDING_SECS + 5
            result = pc_hands.confirm_pending()
        self.assertEqual(result["status"], "expired")
        self.assertEqual(FakeUI.calls, [])

    def test_new_risky_request_replaces_the_pending_one(self):
        p1, p2, p3, p4 = self._setup([_ctl("Sil"), _ctl("Kaldır", cid="c2")])
        with p1, p2, p3, p4:
            pc_hands.click("not defteri", "sil")
            pc_hands.click("not defteri", "kaldır")
            done = pc_hands.confirm_pending()
        self.assertEqual(done["status"], "done")
        self.assertEqual(FakeUI.calls[0]["control"], "c2")   # son sorulan çalışır


class KeyboardClick(unittest.TestCase):
    """UIA iç düğmeyi görmüyorsa (Hesap Makinesi) klavyeyle aynı iş yapılır."""

    def setUp(self):
        pc_hands._last_action.clear()
        pc_hands._pending.clear()

    def test_key_names_are_mapped(self):
        self.assertEqual(pc_hands.key_for("7"), "7")
        self.assertEqual(pc_hands.key_for("artı"), "+")
        self.assertEqual(pc_hands.key_for("eşittir"), "=")
        self.assertIsNone(pc_hands.key_for("kaydet"))          # tahmin yok

    def test_click_falls_back_to_keyboard(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch.object(pc_hands, "click_with_keyboard", return_value={"status": "done", "text": "tuşladım"}) as kb:
            result = pc_hands.click("hesap makinesi", "7")
        self.assertEqual(result["status"], "done")
        self.assertEqual(kb.call_count, 1)

    def test_unknown_target_does_not_press_anything(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch("pyautogui.press") as press:
            result = pc_hands.click("hesap makinesi", "buğday")
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(press.call_count, 0)


class PointClick(unittest.TestCase):
    """Fare yedeği: yalnız açıkça söylenen nokta, her zaman onayla."""

    def setUp(self):
        pc_hands._pending.clear()

    def test_point_click_always_asks_first(self):
        with patch("pyautogui.click") as click:
            result = pc_hands.click_point(500, 300)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(click.call_count, 0)

    def _screen(self):
        """Ekran görüntüsünü taklit et: CI'da gerçek ekran yok, test ona bağlı kalmasın."""
        import numpy as np
        return (patch("pyautogui.size", return_value=(20, 20)),
                patch("PIL.ImageGrab.grab", return_value=np.zeros((20, 20, 3), dtype="uint8")))

    def test_confirmation_runs_the_point_click(self):
        size, grab = self._screen()
        with size, grab, patch("pyautogui.click") as click, patch.object(pc_hands, "_two_points", lambda b: True):
            pc_hands.click_point(500, 300)
            done = pc_hands.confirm_pending()
        self.assertEqual(done["status"], "done")
        click.assert_called_once_with(500, 300)

    def test_unchanged_screen_is_reported(self):
        size, grab = self._screen()
        with size, grab, patch("pyautogui.click"), patch.object(pc_hands, "_two_points", lambda b: False):
            result = pc_hands.click_point(10, 10, confirm=True)
        self.assertEqual(result["status"], "no_change")

    def test_failure_is_reported_honestly(self):
        with patch("pyautogui.click", side_effect=RuntimeError("ekran kilitli")):
            result = pc_hands.click_point(5, 5, confirm=True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("tıklayamadım", result["text"])


class OcrFallback(unittest.TestCase):
    """UIA ve klavye yetmediğinde ekranda yazıyı bulup onaya sunar."""

    def setUp(self):
        pc_hands._pending.clear()

    def test_found_text_becomes_a_confirmation_request(self):
        seen = {"status": "ok", "point": {"x": 120, "y": 240}, "word": {"text": "Kaydet"}}
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch.object(pc_hands, "key_for", return_value=None), \
             patch("modules.pc_vision.find_text", return_value=seen):
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIn("120,240", result["text"])

    def test_missing_text_keeps_the_honest_not_found(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands.pc_awareness, "controls", lambda w: {"controls": [], "window": w}), \
             patch.object(pc_hands, "key_for", return_value=None), \
             patch("modules.pc_vision.find_text", return_value={"status": "missing", "words": []}):
            result = pc_hands.click("not defteri", "kaydet")
        self.assertEqual(result["status"], "not_found")


class TypeVerification(unittest.TestCase):
    """Yapıştırdım demek yetmez: metin ekranda göründü mü?"""

    def setUp(self):
        pc_hands._last_action.clear()

    def test_invisible_text_is_reported(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "_paste", return_value=True), \
             patch.object(pc_hands, "_text_visible", return_value=False):
            result = pc_hands.type_with_keyboard("chrome", "youtube")
        self.assertEqual(result["status"], "no_change")
        self.assertIn("görünmüyor", result["text"])

    def test_visible_text_is_done(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "_paste", return_value=True), \
             patch.object(pc_hands, "_text_visible", return_value=True):
            result = pc_hands.type_with_keyboard("chrome", "youtube")
        self.assertEqual(result["status"], "done")

    def test_unreadable_screen_does_not_claim_success(self):
        with patch("modules.pc_vision.read_screen", return_value=[]):
            self.assertFalse(pc_hands._text_visible("youtube"))


class BrowserAddressBar(unittest.TestCase):
    """Tarayıcıda adres çubuğu: yalnız tarayıcıda denenir, sonuç ölçülür."""

    def setUp(self):
        pc_hands._last_action.clear()

    def test_browser_detection(self):
        self.assertTrue(pc_hands.is_browser({"title": "Google Chrome", "app": "chrome"}))
        self.assertTrue(pc_hands.is_browser({"title": "YouTube - Microsoft Edge", "app": "msedge"}))
        self.assertFalse(pc_hands.is_browser({"title": "Adsız - Not Defteri", "app": "notepad"}))

    def test_non_browser_is_refused(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}):
            result = pc_hands.type_address_bar("not defteri", "youtube")
        self.assertEqual(result["status"], "not_browser")

    def test_browser_uses_shortcut_and_verifies(self):
        browser = {"title": "Google Chrome", "app": "chrome", "hwnd": 7}
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": browser, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "_paste", return_value=True), \
             patch.object(pc_hands, "_text_visible", return_value=True), \
             patch("pyautogui.hotkey") as hotkey:
            result = pc_hands.type_address_bar("chrome", "youtube")
        self.assertEqual(result["status"], "done")
        hotkey.assert_called_once_with("ctrl", "l")


class EnsureWindow(unittest.TestCase):
    """Pencere hazırlığı: yoksa açmayı dene, donmuşsa bekle, sonunda dürüst ol."""

    def test_missing_window_is_reported(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": None, "reason": "missing"}):
            result = pc_hands.ensure_window("yok", timeout=0.2)
        self.assertEqual(result["status"], "no_window")

    def test_opener_is_tried_once(self):
        calls = []
        def opener(name):
            calls.append(name)
            raise RuntimeError("açılamadı")
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": None, "reason": "missing"}):
            result = pc_hands.ensure_window("yok", timeout=0.2, opener=opener)
        self.assertEqual(result["status"], "no_window")
        self.assertEqual(len(calls), 1)

    def test_frozen_window_times_out(self):
        frozen = {"title": "Uygulama (Yanıt vermiyor)", "hwnd": 3}
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": frozen, "reason": ""}):
            result = pc_hands.ensure_window("uygulama", timeout=0.2)
        self.assertEqual(result["status"], "frozen")

    def test_healthy_window_is_ok(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}):
            self.assertEqual(pc_hands.ensure_window("not defteri")["status"], "ok")


class AmbiguousWindow(unittest.TestCase):
    """İki aynı pencere: "pencere yok" demek yanlış — tek soru sorulur."""

    def test_two_windows_produce_a_question(self):
        windows = [{"title": "Adsız 1 - Not Defteri", "hwnd": 1}, {"title": "Adsız 2 - Not Defteri", "hwnd": 2}]
        with patch.object(pc_hands.pc_awareness, "find_window",
                          lambda q: {"match": None, "reason": "ambiguous", "candidates": windows}):
            result = pc_hands.find_control("not defteri", "kaydet")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("Hangisinde", result["text"])
        self.assertIn("2 pencere", result["text"])

    def test_missing_window_is_still_no_window(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": None, "reason": "missing"}):
            result = pc_hands.find_control("not defteri", "kaydet")
        self.assertEqual(result["status"], "no_window")


class Clipboard(unittest.TestCase):
    """Kopyala/yapıştır: panoyu doğrula, 'yaptım' demekle yetinme."""

    def test_copy_reports_empty_clipboard(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "read_clipboard", return_value="aynı"), \
             patch("pyautogui.hotkey"):
            result = pc_hands.copy_selection("not defteri")
        self.assertEqual(result["status"], "no_change")
        self.assertIn("Panoda metin yok", result["text"])

    def test_copy_detects_new_text(self):
        texts = iter(["eski", "yeni metin"])
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "read_clipboard", side_effect=lambda: next(texts)), \
             patch("pyautogui.hotkey"):
            result = pc_hands.copy_selection("not defteri")
        self.assertEqual(result["status"], "done")
        self.assertIn("yeni metin", result["text"])

    def test_paste_verifies_on_screen(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "write_clipboard", return_value=True), \
             patch.object(pc_hands, "_paste", return_value=True), \
             patch.object(pc_hands, "_text_visible", return_value=True):
            result = pc_hands.paste_text("not defteri", "merhaba")
        self.assertEqual(result["status"], "done")

    def test_paste_that_does_not_show_is_reported(self):
        with patch.object(pc_hands.pc_awareness, "find_window", lambda q: {"match": WIN, "reason": ""}), \
             patch.object(pc_hands, "_focus", return_value=True), \
             patch.object(pc_hands, "write_clipboard", return_value=True), \
             patch.object(pc_hands, "_paste", return_value=True), \
             patch.object(pc_hands, "_text_visible", return_value=False):
            result = pc_hands.paste_text("not defteri", "merhaba")
        self.assertEqual(result["status"], "no_change")
        self.assertIn("görünmüyor", result["text"])

    def test_empty_payload_is_refused(self):
        self.assertEqual(pc_hands.paste_text("not defteri", "   ")["status"], "no_change")
