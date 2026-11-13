"""BRAIN-03: factual level followups and site-vs-app typed routing.

Semantic model choices are stubbed. Real Brain prepare/handoff, Core argument
validators and the existing domain executors run in an isolated EngineContext.
These tests do NOT claim live Turkish understanding or PC device acceptance.
"""
from dataclasses import replace
from unittest.mock import Mock, patch, call
import unittest
import webbrowser

from modules import brain_core_map, brain_entry, media, session_state
from modules.brain_contracts import RequestKind
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from test_brain_primary_understanding import (
    OWNER, action, deterministic, eligible, envelope,
)
from modules.brain_model_understanding import propose


class BareLevelModelContractTests(unittest.TestCase):
    def proposal(self, text, *, property="volume", level=20, last_property=None):
        raw = envelope(actions=[
            action(capability_id="pc.level.set",
                   arguments={"property": property, "level": level})],
            confidence="HIGH")
        current = deterministic(text)
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            return propose(
                owner=OWNER, text=text, current=current,
                arguments=current.arguments,
                last_verified_level_property=last_property)

    def test_bare_number_requires_last_verified_same_property(self):
        accepted = self.proposal("20", last_property="volume")
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.actions[0].capability_id, "pc.level.set")
        self.assertEqual(brain_core_map.core_plan(
            "pc.level.set", accepted.actions[0].arguments),
            ("level_set", {"property": "volume", "level": 20}))

        for previous, target, amount in (
            (None, "volume", 20),
            ("brightness", "volume", 20),
            ("volume", "brightness", 20),
            ("volume", "volume", 50),
            ("volume", "volume", True),
        ):
            with self.subTest(previous=previous, target=target, amount=amount):
                self.assertIsNone(
                    self.proposal("20", property=target,
                                  level=amount, last_property=previous))

    def test_unscoped_out_of_range_bare_number_is_not_a_level_command(self):
        self.assertIsNone(
            self.proposal("200", property="volume", level=100,
                          last_property="volume"))

    def test_model_prompt_exposes_bounded_property_without_legacy_guess(self):
        captured = []
        current = deterministic("50")
        raw = envelope(actions=[action(
            capability_id="pc.level.set",
            arguments={"property": "brightness", "level": 50})],
            confidence="HIGH")
        def fake(owner, prompt, send, **kwargs):
            captured.append(prompt)
            return raw
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", side_effect=fake):
            result = propose(owner=OWNER, text="50", current=current,
                             arguments=current.arguments,
                             last_verified_level_property="brightness")
        self.assertIsNotNone(result)
        self.assertEqual(len(captured), 1)
        self.assertIn('"last_verified_level_property": "brightness"', captured[0])
        self.assertIn("last_verified_level_property", captured[0])


class CanonicalLevelAndSiteTests(_CanonicalAuthorityHarness):
    def typed(self, text, capability, fields):
        def selected(evidence, utterance, *, active_context=None):
            self.assertEqual(utterance, text)
            return replace(evidence, request_kind=RequestKind.CAPABILITY,
                           capability_hint=capability,
                           arguments={"original_text": text, **fields},
                           needs_input=False, ambiguities=(), actions=())
        with patch.object(brain_entry, "apply_model_understanding", side_effect=selected):
            return self.turn(text, handler=self.ctx.handle,
                             model_understanding=True)

    def test_verified_80_50_20_sequence_reuses_level_context(self):
        self.ctx.system_control.set_volume.return_value = True
        for text, target in (("sesi 80 yap", 80), ("50", 50), ("20", 20)):
            with self.subTest(text=text):
                self.ctx.system_control.current_volume.return_value = target
                entry, response, _handler, feedback = self.typed(
                    text, "pc.level.set", {"property": "volume", "level": target})
                self.assertEqual(feedback.result_status, "handled")
                self.assertIn(f"yüzde {target} yaptım", str(response))
                self.assertEqual(session_state.fresh_property(self.ctx._session()), "volume")
                if text == "50":
                    self.assertTrue(any(
                        ref.id == "last_property" and ref.provenance.get("value") == "volume"
                        for ref in entry.active_context.recent_references))
        self.assertEqual(self.ctx.system_control.set_volume.call_args_list,
                         [call(80), call(50), call(20)])

    def test_verified_brightness_60_to_30_reuses_brightness_not_volume(self):
        self.ctx.system_control.set_brightness_verified.return_value = True
        self.typed("parlaklığı 60 yap", "pc.level.set",
                   {"property": "brightness", "level": 60})
        self.assertEqual(session_state.fresh_property(self.ctx._session()), "brightness")
        entry, response, _handler, feedback = self.typed(
            "30", "pc.level.set", {"property": "brightness", "level": 30})
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("yüzde 30", str(response))
        self.assertTrue(any(
            ref.id == "last_property" and ref.provenance.get("value") == "brightness"
            for ref in entry.active_context.recent_references))
        self.ctx.system_control.set_volume.assert_not_called()
        self.assertEqual(self.ctx.system_control.set_brightness_verified.call_args_list,
                         [call(60), call(30)])

    def test_topic_change_closes_level_context(self):
        self.ctx.system_control.set_volume.return_value = True
        self.ctx.system_control.current_volume.return_value = 80
        self.typed("sesi 80 yap", "pc.level.set", {"property": "volume", "level": 80})
        self.assertEqual(session_state.fresh_property(self.ctx._session()), "volume")
        def chat(evidence, text, *, active_context=None):
            return replace(evidence, request_kind=RequestKind.CHAT,
                           capability_hint=None,
                           arguments={"original_text": text},
                           needs_input=False, ambiguities=(), actions=())
        with patch.object(brain_entry, "apply_model_understanding", side_effect=chat):
            self.turn("hava nasıl", handler=self.ctx.handle, model_understanding=True)
        self.assertIsNone(session_state.fresh_property(self.ctx._session()))

    def test_youtube_site_prefers_existing_web_worker_not_windows_app(self):
        controller = Mock(open=Mock(return_value=True))
        with patch.object(media.webbrowser, "get", return_value=controller) as browser:
            entry, response, handler, feedback = self.typed(
                "Chrome'da YouTube aç", "media.search",
                {"service": "youtube_home", "browser": "chrome"})
        self.assertEqual(entry.understanding.capability_hint, "media.search")
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("Chrome", str(response))
        browser.assert_called_once_with("chrome")
        controller.open.assert_called_once_with("https://www.youtube.com", new=2)
        self.ctx.system_control.open_application.assert_not_called()

    def test_default_youtube_home_uses_default_browser(self):
        with patch.object(media.webbrowser, "open", return_value=True) as opened:
            _entry, response, _handler, feedback = self.typed(
                "YouTube aç", "media.search", {"service": "youtube_home"})
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("doğrulamadım", str(response))
        opened.assert_called_once_with("https://www.youtube.com", new=2)
        self.ctx.system_control.open_application.assert_not_called()

    def test_requested_browser_missing_never_falls_back_or_claims_opened(self):
        with patch.object(media.webbrowser, "get", side_effect=webbrowser.Error("not registered")), \
             patch.object(media.webbrowser, "open") as other:
            _entry, response, _handler, feedback = self.typed(
                "Firefox üzerinden YouTube'u aç", "media.search",
                {"service": "youtube_home", "browser": "firefox"})
        self.assertEqual(feedback.result_status, "failed")
        self.assertIn("kabul edilmedi", str(response))
        other.assert_not_called()
        self.ctx.system_control.open_application.assert_not_called()

    def test_explicit_youtube_application_keeps_the_app_target(self):
        self.typed("YouTube uygulamasını aç", "app.open", {"app": "youtube"})
        self.ctx.system_control.open_application.assert_called_once_with("youtube")

    def test_site_phrasings_are_routed_by_the_same_typed_worker(self):
        # No lexical recognizer is tested: semantic proposals are controlled;
        # the actual live-model holdout is a separate acceptance gate.
        for text, browser in (
            ("YouTube'u Chrome ile aç", "chrome"),
            ("Chrome'da YouTube aç", "chrome"),
            ("Firefox üzerinden YouTube'u aç", "firefox"),
        ):
            with self.subTest(text=text):
                controller = Mock(open=Mock(return_value=True))
                with patch.object(media.webbrowser, "get", return_value=controller) as getter:
                    _entry, _response, _handler, feedback = self.typed(
                        text, "media.search",
                        {"service": "youtube_home", "browser": browser})
                self.assertEqual(feedback.result_status, "handled")
                getter.assert_called_once_with(browser)
                controller.open.assert_called_once_with("https://www.youtube.com", new=2)

    def test_explicit_chrome_application_is_not_a_youtube_site(self):
        _entry, _response, _handler, feedback = self.typed(
            "Chrome aç", "app.open", {"app": "chrome"})
        self.assertEqual(feedback.result_status, "handled")
        self.ctx.system_control.open_application.assert_called_once_with("chrome")


class BrowserPreferenceCoreTests(unittest.TestCase):
    def test_browser_is_only_allowed_for_youtube_site_home(self):
        self.assertEqual(brain_core_map.core_plan(
            "media.search", {"service": "youtube_home", "browser": "chrome"}),
            ("media_search", {"service": "youtube_home", "browser": "chrome"}))
        self.assertIsNone(brain_core_map.core_plan(
            "media.search", {"service": "youtube_home", "browser": "powershell"}))
        self.assertIsNone(brain_core_map.core_plan(
            "media.search", {"service": "youtube", "query": "video", "browser": "chrome"}))
        self.assertIsNone(brain_core_map.core_plan(
            "app.open", {"app": "Chrome'da YouTube", "browser": "chrome"}))


if __name__ == "__main__":
    unittest.main()
