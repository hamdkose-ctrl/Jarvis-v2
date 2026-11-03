"""PR3A: `engine_commands.handle()` ham metinden capability/effect seçmeyi bırakır.

Üretim zinciri sınanır: `brain_entry.prepare → handoff → EngineContext.handle`.
Canonical sahibi (State/Fast/Understanding/Core) turu aldığında legacy handler çağrılmaz;
etki tam bir kez, doğrulanmış Core intent'i üzerinden uygulanır. Bu dosya RED olarak
yazıldı: dallar henüz retire edilmediği için canonical effect testleri düşer.
"""
from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import app_actions, brain_context, brain_entry, brain_precedence
from modules import brain_understanding as understanding
from modules import desktop_agent, engine_runtime, goal_executor, job_front, personalization
from modules import requests_state
from modules import history as history_mod
from modules.brain_contracts import ActiveContext, ContextReference, ConversationRelation, RequestKind
from modules.brain_understanding import (APP_CLOSE_CAPABILITY, APP_OPEN_CAPABILITY, AUDIO_CAPABILITY,
                                         SHUTDOWN_REQUEST_CAPABILITY)
from modules.system_control import APPS as STATIC_APPS
from modules.system_control import ApplicationResult

ROOT = Path(__file__).resolve().parents[1]
ENGINE_COMMANDS = ROOT / "modules" / "engine_commands.py"


def _isolate_profiles(case, root: Path) -> None:
    users = root / "users"
    users.mkdir(exist_ok=True)
    for target, attr, value in ((personalization, "USERS_DIR", users),
                                (personalization, "ACTIVE_FILE", root / "active_user.txt")):
        state_patch = patch.object(target, attr, value)
        state_patch.start()
        case.addCleanup(state_patch.stop)


class _CanonicalAuthorityHarness(unittest.TestCase):
    """Geçici EngineContext; canlı kullanıcı state'i ve kişisel Goal kaydı okunmaz."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        _isolate_profiles(self, Path(self.temp.name))
        root_logger = engine_runtime.logging.getLogger()
        previous_handlers = set(root_logger.handlers)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()

        def close_test_handlers():
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()

        self.addCleanup(close_test_handlers)
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.emit = Mock()
        self.ctx.chat = Mock(return_value="CHAT")
        self.ctx.system_control = Mock(
            windows_settings=Mock(return_value=None),
            APPS=dict(STATIC_APPS),
            set_volume=Mock(return_value=True),
            set_brightness_verified=Mock(return_value=True),
            is_muted=Mock(return_value=False),
            set_mute=Mock(return_value=True),
            current_volume=Mock(return_value=40),
            media_control=Mock(),
            shutdown_pc=Mock(return_value=True),
            cancel_shutdown=Mock(return_value=True),
            close_application=Mock(return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True)),
            open_application=Mock(return_value=ApplicationResult("Chrome penceresi açık; açılışını doğruladım.", ok=True)),
        )
        self.ctx.desktop = Mock(screenshot=Mock(return_value="EKRAN GÖRÜNTÜSÜ"), system_status=Mock(return_value="SISTEM"))
        self.ctx._weather = Mock(return_value="HAVA")
        self.ctx.voice = Mock(stop_speaking=Mock())
        self.ctx._volume_step = Mock(return_value="SES AYARLANDI")
        self.ctx.privacy = Mock(blocked=Mock(return_value=None), audit=Mock())
        self.ctx.threading = Mock()
        self.ctx._close_jarvis = Mock(return_value="JARVIS KAPANDI")
        self.ctx.set_sleep = Mock(return_value="UYKU")
        self.ctx._DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
        self.ctx.time = Mock(
            # Front gate'ler (planner/not düzeltme) saat damgası okur; sahte Mock aritmetiği
            # zinciri patlatır. Canonical tur gerçekçi, sayısal bir zaman bekler.
            time=Mock(return_value=1_762_185_600.0),
            strftime=Mock(side_effect=lambda fmt: {"%H:%M": "14:32"}.get(fmt, "Bugün 03.11.2026, ")),
            localtime=Mock(return_value=SimpleNamespace(tm_wday=0)),
        )

        goals = Path(self.temp.name) / "goals"
        history_root = Path(self.temp.name) / "history"
        for target, attr, value in ((goal_executor, "STORE", goals), (history_mod, "DIR", history_root)):
            state_patch = patch.object(target, attr, value)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        # İstek günlüğü import anında canlı kullanıcı dosyasına bağlanır: turn'ler testi geçici
        # kayda yazmalı, `~/.jarvis/requests.json`'ı hiç değiştirmemeli.
        journal_patch = patch.object(requests_state, "_journal", Path(self.temp.name) / "requests.json")
        journal_patch.start()
        self.addCleanup(journal_patch.stop)
        saved_records = dict(requests_state._records)
        requests_state._records.clear()
        self.addCleanup(requests_state._records.update, saved_records)
        for target, attr in ((job_front, "observe"), (desktop_agent, "_load")):
            state_patch = patch.object(target, attr, return_value=None)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.run_goal = Mock(return_value="GOAL_RUN")
        run_patch = patch.object(goal_executor, "run", self.run_goal)
        run_patch.start()
        self.addCleanup(run_patch.stop)

    def turn(self, text, handler=None, source="yazı"):
        rid = "pr3a-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source=source)
            handle = handler or Mock(return_value="HANDLER")
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle, feedback

    def turn_real(self, text, source="yazı"):
        return self.turn(text, handler=self.ctx.handle, source=source)


class AppTargetAuthorityTests(_CanonicalAuthorityHarness):
    def test_direct_app_open_is_understood_and_executed_by_core(self):
        entry, out, handle, _ = self.turn("chrome uygulamasını aç")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, "app.open")
        self.ctx.system_control.open_application.assert_called_once_with("chrome")
        handle.assert_not_called()
        self.assertIn("Chrome penceresi açık", out)

    def test_direct_app_close_only_opens_the_existing_confirmation(self):
        entry, out, handle, _ = self.turn("chrome'u kapat")
        self.assertEqual(entry.understanding.capability_hint, "app.close")
        self.assertEqual(self.ctx._session().pending_confirm, {"action": "close_app", "name": "chrome'u"})
        self.ctx.system_control.close_application.assert_not_called()
        handle.assert_not_called()
        self.assertIn("onaylıyor musun", out)

    def test_app_grammar_never_claims_jarvis_pages_or_windows_settings(self):
        for text in ("ayarları aç", "wifi ayarlarını aç", "hafıza sayfasını aç"):
            with self.subTest(text=text):
                entry, out, handle, _ = self.turn(text)
                self.assertNotIn(entry.understanding.capability_hint, {"app.open", "app.close"})

    def test_a_web_page_target_is_never_an_app_target(self):
        # "indirme sayfasını aç" bir web sayfası isteğidir; raw metin ikinci kez yorumlanıp
        # uygulama hedefi seçilmez. Sahibi araştırma/tarayıcı yolu, hint'i korur.
        entry, _out, _handle, _ = self.turn("windows terminal indirme sayfasını aç")
        self.assertIsNone(entry.understanding.capability_hint)
        # Kontrol: gerçek bir uygulama hedefi aynı gramerde app.open olarak tanınmaya devam eder.
        real = self.turn("hesap makinesini aç")[0]
        self.assertEqual(real.understanding.capability_hint, "app.open")

    def test_bare_open_writes_the_typed_app_question_from_understanding(self):
        entry, out, handle, _ = self.turn("aç")
        self.assertTrue(entry.understanding.needs_input)
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        pending = self.ctx._session().pending_action
        self.assertEqual(pending.get("proposal"), {"kind": "app.open"})
        handle.assert_not_called()
        self.assertEqual(out, "Neyi açmamı istiyorsun?")

    def test_bare_close_writes_the_typed_close_question(self):
        entry, out, handle, _ = self.turn("kapat")
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        self.assertEqual(self.ctx._session().pending_action.get("proposal"), {"kind": "app.close"})
        handle.assert_not_called()
        self.assertEqual(out, "Neyi kapatmamı istiyorsun?")

    def test_spoken_close_with_a_period_keeps_the_canonical_clarify(self):
        # Emekli edilen ham dal cümleyi `strip(" .!?")` ile okuyordu; sesli yazım noktalamayla
        # gelir ("Kapat."). Çıplak fiil tanıyıcısı canonical tarafta da aynı pariteyi korumalı.
        entry, out, handle, _ = self.turn("Kapat.", source="ses")
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        self.assertEqual(self.ctx._session().pending_action.get("proposal"), {"kind": "app.close"})
        handle.assert_not_called()
        self.assertEqual(out, "Neyi kapatmamı istiyorsun?")

    def test_spoken_close_question_form_keeps_the_canonical_clarify(self):
        entry, out, handle, _ = self.turn("Kapatır mısın?", source="ses")
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        self.assertEqual(self.ctx._session().pending_action.get("proposal"), {"kind": "app.close"})
        handle.assert_not_called()
        self.assertEqual(out, "Neyi kapatmamı istiyorsun?")

    def test_spoken_open_question_form_keeps_the_canonical_clarify(self):
        entry, out, handle, _ = self.turn("Açar mısın?", source="ses")
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        self.assertEqual(self.ctx._session().pending_action.get("proposal"), {"kind": "app.open"})
        handle.assert_not_called()
        self.assertEqual(out, "Neyi açmamı istiyorsun?")

    def test_bare_open_does_not_become_the_open_message_body(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        entry, out, _, _ = self.turn_real("aç")
        self.assertIn("APP_TARGET_MISSING", entry.understanding.ambiguities)
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
        self.assertEqual(session.pending_action.get("proposal"), {"kind": "app.open"})
        self.assertEqual(out, "Neyi açmamı istiyorsun?")

    def test_spoken_close_grammar_forms_keep_the_retired_branch_parity(self):
        # Emekli edilen ham dal (`(.+?) kapat|kapatsana|kapa$`) bu formları tek uygulamaya
        # bağlıyordu; parite canonical tanıyıcıda sürer ve etki yine yalnız onaydalındır.
        for text, proposed in (("Paint kapatsana", {"action": "close_app", "name": "paint"}),
                               ("VLC kapat", {"action": "close_app", "name": "vlc"})):
            with self.subTest(text=text):
                entry, out, handle, _ = self.turn(text)
                self.assertEqual(entry.understanding.capability_hint, "app.close")
                self.assertEqual(self.ctx._session().pending_confirm, proposed, text)
                self.ctx.system_control.close_application.assert_not_called()
                handle.assert_not_called()
                self.assertIn("kaydedilmemiş", out, text)

    def test_close_grammar_does_not_outrank_the_notes_front_gate(self):
        # "Not Defteri kapat" baseline'de de not planner'ına düşüyordu (ham app-close dalı
        # handle'da planner'ın SONRASINDAYDI). PR3A bu sıralamayı değiştirmez: front gate
        # cevabı Core app.close planını gölger, hiçbir kapatma onayı açılmaz.
        entry, out, handle, _ = self.turn("Not Defteri kapat")
        self.assertEqual(entry.understanding.capability_hint, "app.close")
        self.assertIsNone(self.ctx._session().pending_confirm, out)
        self.assertNotIn("kaydedilmemiş", out)
        self.ctx.system_control.close_application.assert_not_called()
        handle.assert_not_called()

    def test_blocked_close_targets_stay_with_their_own_canonical_owners(self):
        # Ham dalın hedef-yasak listesi canonical sahipde yaşıyor: ses/müzik/bilgisayar/ekran
        # bir uygulama kapatma önerisi üretmez; kendi tipli yolları (veya yürütücü) karar verir.
        for text, hint in (("Sesi kapat", AUDIO_CAPABILITY),
                           ("Bilgisayarı kapat", SHUTDOWN_REQUEST_CAPABILITY),
                           ("Müziği kapat", None),
                           ("Ekranı kapat", None)):
            with self.subTest(text=text):
                entry, _out, _handle, _ = self.turn(text)
                self.assertEqual(entry.understanding.capability_hint, hint, text)
                self.assertNotEqual(entry.understanding.capability_hint, "app.close", text)
                pending = self.ctx._session().pending_confirm
                self.assertFalse(isinstance(pending, dict) and pending.get("action") == "close_app", text)
                self.ctx.system_control.close_application.assert_not_called()

    def test_close_chain_is_handed_to_the_goal_runner_not_to_one_app(self):
        # "Ayarları aç ve Bluetooth'u kapat" iki adımlıktır: tek bir uygulama hedefi uydurulmaz,
        # cümle bütün olarak yürütücüye devredilir (`outcome_contracts.open_only_request` hükmü).
        entry, _out, _handle, _feedback = self.turn("Ayarları aç ve Bluetooth’u kapat")
        self.assertIsNone(entry.understanding.capability_hint)
        self.assertNotIn("app", entry.understanding.arguments)
        self.assertIsNone(self.ctx._session().pending_confirm)
        self.ctx.system_control.close_application.assert_not_called()


    def test_installed_app_names_ending_like_a_converb_are_single_app_targets(self):
        # Kurulu uygulama adları sabit APPS ile sınırlı değil (Windows Start Menu'den de çözülür).
        # 'WinZip' ve '7zip' gibi -ip/-up ile biten adlar zincir sanılmaz: tek uygulama isteği
        # yine app.open olur ve etki doğrulanmış Core `app_open` intent'inden yürür.
        for text, name in (("WinZip aç", "winzip"), ("7zip aç", "7zip"), ("WinZip'i aç", "winzip'i")):
            with self.subTest(text=text):
                entry, out, handle, _ = self.turn(text)
                self.assertEqual(entry.understanding.capability_hint, "app.open", text)
                self.assertEqual(str(entry.understanding.arguments.get("app") or "").casefold(), name, text)
                handle.assert_not_called()
                self.ctx.system_control.open_application.assert_called_once_with(name)
                self.assertIn("Chrome penceresi açık", out, text)
                self.ctx.system_control.open_application.reset_mock()

    def test_converb_looking_close_targets_are_single_app_targets(self):
        entry, _out, _handle, _ = self.turn("WinZip kapat")
        self.assertEqual(entry.understanding.capability_hint, "app.close")
        self.assertEqual(self.ctx._session().pending_confirm, {"action": "close_app", "name": "winzip"})


class AppChainGuardTests(unittest.TestCase):
    """Zincir filtresi uygulama adına özel bir istisna listesi değildir.

    Converb kanadı ancak bir eylem fiili gövdesine bitişik ek olarak zincir sayar; herhangi bir
    kelimenin son iki-üç harfi fiilimsi eki varsayılmaz (`WinZip`, `7zip` kurulu bir uygulama adıdır
    ve cümlede tek eylem vardır)."""

    CONVERB_SUFFIXES = ("ıp", "ip", "up", "üp", "arak", "erek")
    NON_VERB_NAME_STEMS = ("winz", "7z", "klip", "dot", "snap", "hex", "quick")

    def test_name_like_converb_tails_are_never_chains(self):
        for stem in self.NON_VERB_NAME_STEMS:
            for suffix in self.CONVERB_SUFFIXES:
                name = stem + suffix
                with self.subTest(name=name):
                    self.assertEqual(understanding._app_request(f"{name} aç"),
                                     (APP_OPEN_CAPABILITY, {"app": name}))

    def test_verb_converb_chains_are_not_one_app_target(self):
        for text in ("chrome'u kapatıp aç", "chrome'u açıp kapat", "vlc'yi çalıştırıp kapat",
                     "excel'i açıp a1 hücresine merhaba yaz", "chrome'u kapatarak aç"):
            with self.subTest(text=text):
                self.assertIsNone(understanding._app_request(text))

    def test_connective_and_punctuation_chains_are_not_one_app_target(self):
        for text in ("ayarları aç ve bluetooth'u kapat", "excel'i aç, a1'e merhaba yaz",
                     "chrome'u aç sonra kapat", "chrome'u aç; kapat"):
            with self.subTest(text=text):
                self.assertIsNone(understanding._app_request(text))

    def test_single_app_requests_keep_their_typed_capability(self):
        for text, kind, target in (("chrome aç", APP_OPEN_CAPABILITY, "chrome"),
                                   ("winzip kapat", APP_CLOSE_CAPABILITY, "winzip")):
            with self.subTest(text=text):
                self.assertEqual(understanding._app_request(text), (kind, {"app": target}))

    APP_NAME_LITERALS = ("winzip", "7zip", "chrome", "vlc", "paint", "excel",
                         "not defteri", "hesap makinesi")

    def _chain_source(self):
        """Zincir filtresinin kaynak bölgesi: dört modül düzeyi desen + `_app_chain` gövdesi."""
        tree = ast.parse(inspect.getsource(understanding))
        wanted = {"_APP_CONNECTIVE", "_APP_ACTION_STEMS", "_APP_CONVERB", "_APP_ACTION_TOKEN"}
        parts = [node for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets)]
        parts += [node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_app_chain"]
        self.assertEqual(len(parts), 5, "zincir filtresinin sahibi bu beş bildirimdir")
        return "\n".join(ast.unparse(node) for node in parts)

    def test_chain_filter_is_a_verb_rule_not_an_app_name_list(self):
        source = self._chain_source().casefold()
        for name in self.APP_NAME_LITERALS:
            self.assertNotIn(name, source, name)

    def test_bare_word_tail_rule_is_not_relocated_into_the_new_owner(self):
        # Emekli edilen kural: `\w+` + fiilimsi eki. Yardımcıya taşınarak "fix" yapılamaz.
        self.assertNotIn(r"\w+(?:", self._chain_source().replace(" ", ""))


class WeatherAuthorityTests(_CanonicalAuthorityHarness):
    def test_rain_question_reaches_the_canonical_weather_owner(self):
        entry, out, handle, _ = self.turn("yağmur yağacak mı")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertTrue(str(entry.understanding.capability_hint or "").startswith("weather.read"))
        self.ctx._weather.assert_called_once()
        handle.assert_not_called()
        self.assertEqual(out, "HAVA")

    def test_airport_is_not_a_weather_request(self):
        entry, out, handle, _ = self.turn("havaalanı nerede")
        self.assertFalse(str(entry.understanding.capability_hint or "").startswith("weather."))
        self.ctx._weather.assert_not_called()

    def test_the_legacy_surface_city_parser_is_gone_not_relocated(self):
        # Şehir çıkaran ham regex dalı retire edildiğinde tek çağıranı `_city_in` caller-zero kaldı.
        # Yardımcı başka bir yüzeye taşınmaz: şehri Understanding canonical olarak çözer.
        from modules import engine_runtime, engine_tools
        self.assertFalse(hasattr(engine_tools, "_city_in"))
        self.assertNotIn("_city_in", engine_runtime._HANDLERS["engine_tools"])
        self.assertFalse(hasattr(self.ctx, "_WEATHER_STOP"))


class LevelAuthorityTests(_CanonicalAuthorityHarness):
    def test_screen_light_is_a_brightness_level_request(self):
        entry, out, handle, _ = self.turn("ekran ışığını 50 yap")
        self.assertEqual(entry.understanding.capability_hint, "pc.level.set")
        self.ctx.system_control.set_brightness_verified.assert_called_once_with(50)
        handle.assert_not_called()
        self.assertEqual(out, "Ekran parlaklığını yüzde 50 olarak ayarladım.")

    def test_bare_number_asks_the_level_question_canonically(self):
        entry, out, handle, _ = self.turn("70 yap")
        self.assertEqual(entry.understanding.ambiguities, ("level target unspecified",))
        self.assertEqual(self.ctx._session().pending_level, 70)
        handle.assert_not_called()
        self.assertEqual(out, "Yüzde 70, ses mi parlaklık mı?")

    def test_pending_level_answer_selects_volume_from_the_state_gate(self):
        self.ctx._session().pending_level = 70
        entry, out, handle, _ = self.turn("ses")
        self.assertEqual(entry.state_gate.protocol, "session.pending_level.select")
        self.ctx.system_control.set_volume.assert_called_once_with(70)
        handle.assert_not_called()
        self.assertEqual(out, "Ses seviyesini yüzde 70 yaptım.")
        self.assertIsNone(self.ctx._session().pending_level)

    def test_pending_level_answer_selects_brightness_with_the_ekran_word(self):
        self.ctx._session().pending_level = 70
        entry, out, handle, _ = self.turn("ekran")
        self.assertEqual(entry.state_gate.protocol, "session.pending_level.select")
        self.ctx.system_control.set_brightness_verified.assert_called_once_with(70)
        handle.assert_not_called()
        self.assertEqual(out, "Ekran parlaklığını yüzde 70 olarak ayarladım.")

    def test_explicit_level_request_does_not_become_an_open_message_body(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        entry, out, _, _ = self.turn_real("70 yap")
        self.assertEqual(entry.understanding.ambiguities, ("level target unspecified",))
        self.assertEqual(session.pending_level, 70)
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
        self.assertEqual(out, "Yüzde 70, ses mi parlaklık mı?")

    def test_fresh_last_property_keeps_the_bare_number_effect_canonical(self):
        from modules import session_state
        session_state.remember_property(self.ctx._session(), "volume")
        entry, out, handle, _ = self.turn("70 yap")
        self.assertEqual(entry.understanding.capability_hint, "pc.level.set")
        self.ctx.system_control.set_volume.assert_called_once_with(70)
        handle.assert_not_called()


class AudioAuthorityTests(_CanonicalAuthorityHarness):
    def test_mute_is_an_explicit_audio_action(self):
        entry, out, handle, _ = self.turn("sessize al")
        self.assertEqual(entry.understanding.capability_hint, "pc.audio.action")
        self.ctx.system_control.set_mute.assert_called_once_with(True)
        handle.assert_not_called()
        self.assertEqual(out, "Sesi kapattım, bilgisayar sessizde.")

    def test_mute_is_idempotent_and_does_not_flip(self):
        self.ctx.system_control.is_muted = Mock(return_value=True)
        entry, out, handle, _ = self.turn("sessize al")
        self.ctx.system_control.set_mute.assert_not_called()
        handle.assert_not_called()
        self.assertEqual(out, "Ses zaten kapalı (sessizde).")

    def test_unmute_reports_the_kept_level(self):
        entry, out, handle, _ = self.turn("sessizi kaldır")
        self.assertEqual(entry.understanding.capability_hint, "pc.audio.action")
        self.ctx.system_control.set_mute.assert_called_once_with(False)
        handle.assert_not_called()
        self.assertEqual(out, "Sessizi kaldırdım. Ses yüzde 40.")

    def test_open_volume_raises_when_not_muted(self):
        _, out, handle, _ = self.turn("sesi aç")
        self.ctx._volume_step.assert_called_once_with(15, "arttırdım")
        self.ctx.system_control.set_mute.assert_not_called()
        handle.assert_not_called()

    def test_open_volume_lifts_mute_when_muted(self):
        self.ctx.system_control.is_muted = Mock(return_value=True)
        _, out, handle, _ = self.turn("sesi aç")
        self.ctx.system_control.set_mute.assert_called_once_with(False)
        self.ctx._volume_step.assert_not_called()
        handle.assert_not_called()
        self.assertEqual(out, "Sessizi kaldırdım. Ses yüzde 40.")

    def test_raise_and_lower_use_the_existing_delta_owner(self):
        _, _, handle, _ = self.turn("sesi yükselt")
        self.ctx._volume_step.assert_called_once_with(15, "arttırdım")
        handle.assert_not_called()
        self.ctx._volume_step.reset_mock()
        _, _, handle, _ = self.turn("sesi kıs")
        self.ctx._volume_step.assert_called_once_with(-10, "kıstım")
        handle.assert_not_called()

    def test_sound_topic_without_an_action_is_not_audio(self):
        entry, _, _, _ = self.turn("ses tonun nasıl")
        self.assertNotEqual(entry.understanding.capability_hint, "pc.audio.action")
        self.ctx.system_control.set_mute.assert_not_called()
        self.ctx._volume_step.assert_not_called()


class MediaAuthorityTests(_CanonicalAuthorityHarness):
    def test_media_stop_is_a_core_media_action(self):
        entry, out, handle, _ = self.turn("müziği kes")
        self.assertEqual(entry.understanding.capability_hint, "pc.media.action")
        self.ctx.system_control.media_control.assert_called_once_with("play_pause")
        handle.assert_not_called()
        self.assertEqual(out, "Medya oynatıcısı tetiklendi.")

    def test_next_media(self):
        entry, out, handle, _ = self.turn("sonraki müzik")
        self.assertEqual(entry.understanding.capability_hint, "pc.media.action")
        self.ctx.system_control.media_control.assert_called_once_with("next")
        handle.assert_not_called()

    def test_previous_media(self):
        _, _, handle, _ = self.turn("önceki müzik")
        self.ctx.system_control.media_control.assert_called_once_with("prev")
        handle.assert_not_called()

    def test_media_topic_is_not_an_action(self):
        entry, _, _, _ = self.turn("müzik hakkında konuşalım")
        self.assertNotEqual(entry.understanding.capability_hint, "pc.media.action")
        self.ctx.system_control.media_control.assert_not_called()


class ScreenAuthorityTests(_CanonicalAuthorityHarness):
    def test_screenshot_is_a_capture_capability(self):
        entry, out, handle, _ = self.turn("ekran görüntüsü al")
        self.assertEqual(entry.understanding.capability_hint, "screen.capture")
        self.ctx.desktop.screenshot.assert_called_once_with()
        handle.assert_not_called()
        self.assertEqual(out, "EKRAN GÖRÜNTÜSÜ")

    def test_screenshot_word_is_recognized(self):
        entry, _, handle, _ = self.turn("screenshot al")
        self.assertEqual(entry.understanding.capability_hint, "screen.capture")
        self.ctx.desktop.screenshot.assert_called_once_with()
        handle.assert_not_called()

    def test_screenshot_analysis_stays_a_screen_analysis_request(self):
        entry, _, _, _ = self.turn("ekran görüntüsünü analiz et")
        self.assertEqual(entry.understanding.capability_hint, "screen.analyze")
        self.assertNotEqual(entry.understanding.capability_hint, "screen.capture")


class ShutdownAuthorityTests(_CanonicalAuthorityHarness):
    def test_shutdown_request_only_asks_for_confirmation(self):
        entry, out, handle, _ = self.turn("bilgisayarı kapat")
        self.assertEqual(entry.understanding.capability_hint, "pc.shutdown.request")
        self.assertEqual(self.ctx._session().pending_confirm, "shutdown")
        self.ctx.system_control.shutdown_pc.assert_not_called()
        handle.assert_not_called()
        self.assertEqual(out, "Bilgisayarı kapatmamı onaylıyor musun? Evet ya da hayır de.")

    def test_shutdown_cancel_reaches_the_existing_cancel_owner(self):
        entry, out, handle, _ = self.turn("kapatmayı iptal")
        self.assertEqual(entry.understanding.capability_hint, "pc.shutdown.cancel")
        self.ctx.system_control.cancel_shutdown.assert_called_once_with()
        handle.assert_not_called()
        self.assertEqual(out, "Zamanlanmış bilgisayar kapatma işlemini iptal ettim.")

    def test_shutdown_confirmation_stays_a_bounded_state_consumer(self):
        _, _, _, _ = self.turn("bilgisayarı kapat")
        _, out, _, _ = self.turn_real("evet")
        self.ctx.system_control.shutdown_pc.assert_called_once_with()
        self.ctx.privacy.audit.assert_any_call("bilgisayarı kapatma", "60 sn zamanlandı")
        self.assertIsNone(self.ctx._session().pending_confirm)
        self.assertIn("60 saniye", out)

    def test_meta_talk_about_shutdown_does_not_ask_for_confirmation(self):
        entry, _, _, _ = self.turn("bilgisayarı kapatma hakkında konuşalım")
        self.assertNotEqual(entry.understanding.capability_hint, "pc.shutdown.request")
        self.assertIsNone(self.ctx._session().pending_confirm)


class FastAuthorityTests(_CanonicalAuthorityHarness):
    def test_fast_clock_is_dispatched_once_without_the_legacy_branch(self):
        entry, out, handle, _ = self.turn("saat kaç")
        self.assertEqual(entry.fast_gate.protocol, "fast.time.read")
        handle.assert_not_called()
        self.assertEqual(out, "Saat 14:32")

    def test_fast_date_is_dispatched_once(self):
        entry, out, handle, _ = self.turn("tarih ne")
        self.assertEqual(entry.fast_gate.protocol, "fast.date.read")
        handle.assert_not_called()
        self.assertEqual(out, "Bugün 03.11.2026, Pazartesi")

    def test_fast_system_status_is_dispatched_once(self):
        entry, out, handle, _ = self.turn("sistem durumu")
        self.assertEqual(entry.fast_gate.protocol, "fast.system.status")
        handle.assert_not_called()
        self.assertEqual(out, "SISTEM")

    def test_fast_speech_stop_owns_the_effect(self):
        with patch.object(requests_state, "cancel", Mock()) as cancel:
            entry, out, handle, _ = self.turn("konuşmayı durdur")
        self.assertEqual(entry.fast_gate.protocol, "fast.speech.stop")
        self.ctx.voice.stop_speaking.assert_called_once_with()
        cancel.assert_called_once_with(self.owner)
        handle.assert_not_called()
        self.assertEqual(out, "Konuşmayı durdurdum.")

    def test_fast_mic_toggle_uses_the_existing_typed_action(self):
        voice = Mock(return_value="Mikrofon kapatıldı.")
        with patch.object(app_actions, "voice", voice):
            entry, out, handle, _ = self.turn("mikrofonu kapat")
        self.assertEqual(entry.fast_gate.protocol, "fast.mic.toggle")
        voice.assert_called_once()
        self.assertEqual(voice.call_args.args[0], {"action": "set_flag", "params": {"name": "mic", "value": False}})
        handle.assert_not_called()
        self.assertEqual(out, "Mikrofon kapatıldı.")

    def test_bounded_engine_control_remains_its_existing_owner(self):
        entry, out, _, _ = self.turn_real("uyu")
        self.assertEqual(entry.fast_gate.protocol, "fast.engine.sleep")
        self.ctx.set_sleep.assert_called_once_with(True, announce=False)
        self.assertEqual(out, "UYKU")


class MultiStepAuthorityTests(_CanonicalAuthorityHarness):
    def test_each_step_keeps_its_own_canonical_owner_and_effect_once(self):
        _, out, _, _ = self.turn_real("önce sesi kıs sonra sonraki müzik")
        self.ctx._volume_step.assert_called_once_with(-10, "kıstım")
        self.ctx.system_control.media_control.assert_called_once_with("next")
        self.assertIn("1.", out)
        self.assertIn("2.", out)


class NegativeMatrixTests(_CanonicalAuthorityHarness):
    def test_meta_language_never_selects_a_capability(self):
        cases = {
            "kapat ne demek": "app.close",
            "sesi kıs ne demek": "pc.audio.action",
            "müziği kes ne demek": "pc.media.action",
        }
        for text, hint in cases.items():
            with self.subTest(text=text):
                entry, _, _, _ = self.turn(text)
                self.assertNotEqual(entry.understanding.capability_hint, hint)
        self.ctx.system_control.media_control.assert_not_called()
        self.ctx._volume_step.assert_not_called()

    def test_weather_exclusions_hold(self):
        for text in ("hava yolu nasıl açılır", "hava kuvvetleri nedir"):
            with self.subTest(text=text):
                entry, _, _, _ = self.turn(text)
                self.assertFalse(str(entry.understanding.capability_hint or "").startswith("weather."))
        self.ctx._weather.assert_not_called()

    def test_mic_settings_question_is_not_the_fast_toggle(self):
        entry, _, _, _ = self.turn("mikrofonun ayarları nerede")
        self.assertFalse(entry.fast_gate.matched)
        self.assertNotEqual(entry.understanding.capability_hint, "fast.mic.toggle")


class EngineCommandsStructuralGuardTests(unittest.TestCase):
    """Retired inline semantic branches must not come back as raw-text selectors."""

    FORBIDDEN_CALLS = {
        "_weather", "_volume_step", "ask_clarification", "open_app",
        "media_control", "set_mute", "is_muted", "current_volume",
        "set_volume", "set_brightness_verified", "cancel_shutdown",
    }
    # Exact branch-selector literals (`"x" in cmd_lower` / tuple membership). Response texts are
    # allowed to mention the same words; only the selector constants are forbidden.
    FORBIDDEN_EXACT = {
        "bilgisayarı kapat", "pc kapat", "kapatmayı iptal", "kapatma iptal",
        "ekran görüntüsü", "screenshot", "ekran ışığı", "sistem durumu",
        "sonraki", "önceki", "müzik", "şarkı", "mikrofon", "hava durumu",
    }
    # Regex selectors are recognized by their metacharacters, so long user-facing sentences are safe.
    FORBIDDEN_TOKENS = {
        "sessize", "sessizi", "parlakl", "ekran ışığı", "ekran görüntü",
        "screenshot", "sistem durumu", "sonraki", "önceki", "müzi", "şarkı",
        "bilgisayarı kapat", "pc kapat", "kapatma", "yağmur yağacak", "mikrofon",
        "saat", "günlerden", "hava",
    }

    # Regex selectors carry pattern syntax (`\b`, groups, classes, alternation, anchors); a bare
    # quantifier such as the "?" of a user-facing question is not. Only pattern-shaped literals
    # are checked against FORBIDDEN_TOKENS, so response sentences stay legal.
    _REGEX_SYNTAX = "\\^$[]()|"

    def _handle_ast(self):
        tree = ast.parse(ENGINE_COMMANDS.read_text(encoding="utf-8"))
        handle = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle")
        return handle

    def test_handle_calls_no_retired_effect_selector(self):
        called = {
            node.func.attr
            for node in ast.walk(self._handle_ast())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(sorted(called & self.FORBIDDEN_CALLS), [])

    def test_handle_keeps_no_retired_raw_text_patterns(self):
        literals = {
            node.value for node in ast.walk(self._handle_ast())
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        exact = {row for row in literals if row.strip().casefold() in self.FORBIDDEN_EXACT}
        self.assertEqual(sorted(exact), [])
        regexps = {row for row in literals if any(ch in row for ch in self._REGEX_SYNTAX)}
        leaked = {
            row for row in regexps
            if any(token in row.casefold() for token in self.FORBIDDEN_TOKENS)
        }
        self.assertEqual(sorted(leaked), [])

    def test_app_actions_import_is_gone_after_the_raw_writers_retired(self):
        imports = {
            alias.name for node in ast.walk(self._handle_ast())
            if isinstance(node, ast.ImportFrom) and node.module == "modules"
            for alias in node.names
        }
        self.assertNotIn("app_actions", imports)


if __name__ == "__main__":
    unittest.main()
