"""BRAIN-03 dilim 1: şehir/konum yazma kapısı Brain→Core kanonical kararına taşınır.

Envanter yeri: `JARVIS_BRAIN_MIGRATION_MAP_V1.md` §13.1 "şehir set/reset regex" satırı
(BRAIN-MIG-099). Retire edilen kapı `modules/engine_commands.py` içindeki iki ham regex'ti;
ikisi de kullanıcının kendi tercih dosyasına **yazma** yetkisini ham cümleden seçiyordu:

    m = runtime.re.match(r"^(?:şehrim|konumum|yaşadığım şehir)\\s+(.+?)...", cmd_lower)
    runtime.profile.set_pref("city", city)
    if runtime.re.search(r"(şehrimi|konumumu)\\s+(sıfırla|sil|unut)", cmd_lower): ...

Bu dosya RED olarak yazıldı: kapı retire edilmeden önce kanonical `weather.city.set`/`weather.city.reset`
planı, Core validator'ı ve intent sahibi yoktur. Parite testleri (aynı yanıt metni, aynı pref
 sonucu) hem tabanda hem sonra geçmelidir. Bilinçli daraltmalar ayrı testlerde pinlidir:
sor/fiil biçimli "şehir adı" artık pref YAZMAZ, içinde "şehrimi sil" geçen başka sahibin
cümlesi artık tercihi SİLMEZ — ikisi de tabanın ölçülen kusuruydu.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_brain_pr3_raw_text_authority as pr3a  # noqa: E402  (kanonical harness'ın tek sahibi)
from modules import brain_core_map, brain_entry  # noqa: E402
from modules import brain_understanding as understanding  # noqa: E402

ENGINE_COMMANDS = ROOT / "modules" / "engine_commands.py"

# Retire edilen gramerin tam alıntıları — parity sözleşmesi bu iki kalıptır.
LEGACY_SET_PATTERN = r"^(?:şehrim|konumum|yaşadığım şehir)\s+(.+?)(?:['’]?(?:da|de|ta|te))?\s*(?:olsun|dır|dir)?$"
LEGACY_CLEAR_PATTERN = r"(şehrimi|konumumu)\s+(sıfırla|sil|unut)"

SET_REPLY = "Şehrini {city} olarak kaydettim; hava durumuna bu şehre göre bakacağım."
CLEAR_REPLY = "Kayıtlı şehrini sildim; artık bulunduğun konuma göre bakacağım."


def _handle_body() -> ast.FunctionDef:
    tree = ast.parse(ENGINE_COMMANDS.read_text(encoding="utf-8"), filename=str(ENGINE_COMMANDS))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "handle":
            return node
    raise AssertionError("modules/engine_commands.py::handle bulunamadı")


def _raw_city_door_in_handle() -> list[str]:
    """`handle` gövdesinde ham cümleden şehir pref'i seçen her sözdizimi kanıtı."""
    hits: list[str] = []
    for node in ast.walk(_handle_body()):
        if isinstance(node, ast.Attribute) and node.attr in {"match", "search", "fullmatch"}:
            source = ast.unparse(node)
            if "şehir" in source or "konum" in source:
                hits.append(source)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "şehrim" in node.value or "konumum" in node.value or "şehrimi" in node.value:
                hits.append(node.value[:60])
        if isinstance(node, ast.keyword) and node.arg == "key" \
                and isinstance(node.value, ast.Constant) and node.value.value == "city":
            hits.append("pref key 'city'")
    return hits


class WeatherCityPlanContractTests(unittest.TestCase):
    """Kanonical sözleşme: hint → Core intent → doğrulanmış argüman, tek sahibinden."""

    def test_the_capabilities_exist_and_are_core_mapped(self):
        self.assertEqual(understanding.WEATHER_CITY_SET_CAPABILITY, "weather.city.set")
        self.assertEqual(understanding.WEATHER_CITY_RESET_CAPABILITY, "weather.city.reset")
        self.assertIn("weather.city.set", brain_core_map.CORE_INTENTS)
        self.assertIn("weather.city.reset", brain_core_map.CORE_INTENTS)
        self.assertEqual(brain_core_map.CORE_INTENTS["weather.city.set"][0], "city_set")
        self.assertEqual(brain_core_map.CORE_INTENTS["weather.city.reset"][0], "city_reset")

    def test_the_set_proposal_carries_only_a_validated_city_token(self):
        validate = brain_core_map.CORE_INTENTS[understanding.WEATHER_CITY_SET_CAPABILITY][1]
        # Kanonikal girdi Brain'in normalize ettiği küçük harfli token'lardır; hüküm `_weather_args`
        # ile aynı `_CITY` sözleşmesidir, yoksa hava ve şehir iki farklı kural görür.
        self.assertEqual(validate({"location": "izmir"}), {"location": "İzmir"})
        self.assertEqual(validate({"location": "ankara"}), {"location": "Ankara"})
        self.assertEqual(validate({"location": "muğla"}), {"location": "Muğla"})
        self.assertEqual(validate({"location": "ığdır"}), {"location": "Iğdır"})
        self.assertEqual(validate({"location": "yeni delhi"}), {"location": "Yeni Delhi"})
        for bad in ("", "  ", "İzmir 12", "a", "ab", "x" * 31, None, 5, ["izmir"],
                    # Üç kelimeyi aşan öneri biçim sözleşmesi dışındadır; "yeni delhi edirne gibi".
                    "yeni delhi edirne ankara", "izmir 12", "izmir'dir", "izmir, ankara"):
            with self.subTest(location=bad):
                self.assertIsNone(validate({"location": bad}))

    def test_core_holds_the_form_rule_and_brain_holds_the_meaning_rule(self):
        # Katman sözleşmesi: Core işlev sözcüğü listesi TUTMAZ (ikinci bir anlam otoritesi olmaz);
        # biçimce geçerli ama anlamca şehir olmayan öbek, Brain önermediği için pref'e yazılmaz.
        validate = brain_core_map.CORE_INTENTS[understanding.WEATHER_CITY_SET_CAPABILITY][1]
        self.assertEqual(validate({"location": "çok sıcak"}), {"location": "Çok Sıcak"})
        for text in ("şehrim çok sıcak", "şehrim güzel", "şehrim İstanbul çok güzel"):
            with self.subTest(text=text):
                self.assertIsNone(understanding._weather_city_request(understanding._norm(text)))

    def test_the_location_value_uses_the_same_core_rule_as_the_weather_location(self):
        # Şehir ve hava aynı `_CITY`+büyük harf sözleşmesini paylaşır; iki ayrı hüküm doğamaz.
        weather = brain_core_map.CORE_INTENTS["weather.read"][1]
        validate = brain_core_map.CORE_INTENTS[understanding.WEATHER_CITY_SET_CAPABILITY][1]
        for token in ("izmir", "ankara", "muğla", "iğdır", "malatya"):
            with self.subTest(token=token):
                self.assertEqual(validate({"location": token}), weather({"location": token}))

    def test_the_set_proposal_is_rejected_without_a_location_slot(self):
        validate = brain_core_map.CORE_INTENTS[understanding.WEATHER_CITY_SET_CAPABILITY][1]
        self.assertIsNone(validate({}))

    def test_the_clear_proposal_takes_no_argument(self):
        validate = brain_core_map.CORE_INTENTS[understanding.WEATHER_CITY_RESET_CAPABILITY][1]
        self.assertEqual(validate({}), {})
        # Silme isteği bir şehir adı taşıyorsa bu ikinci bir hedef seçimidir: Core reddeder.
        self.assertIsNone(validate({"location": "İzmir"}))

    def test_a_rejected_location_proposal_produces_no_core_plan(self):
        self.assertIsNone(brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY, {}))
        self.assertIsNone(
            brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY, {"location": "izmir 12"}))


    def test_core_judges_city_form_only_and_never_the_model_path_effect(self):
        # Merge öncesi denetim NOTU (ikinci boşluk): BRAIN-01 zarfı `weather.city.set`'i
        # `CORE_INTENTS` katalogundan ötüri önerebiliyor. Core ANLAM listesi tutmaz (tutsa
        # ikinci semantic authority olurdu), bu yüzden biçim hükmü harfi/haneyi denetler ama
        # "çok sıcak" gibi şeklen geçerli bir değeri reddetmez — ölçüldü. O hâlde kapanış
        # doğru katmanda: tercih YAZMASI/SİLMESİ modelin önerebileceği bir yetenek değildir
        # (`WeatherCityModelEnvelopeTests`), Core'un biçim hükmü ise aynen kalır.
        from modules import brain_model_understanding
        self.assertIn(understanding.WEATHER_CITY_SET_CAPABILITY, brain_core_map.CORE_INTENTS)
        self.assertEqual(
            brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY, {"location": "izmir"}),
            ("city_set", {"location": "İzmir"}))
        # Biçim hükmü reddettikleri (rakam/boş/apostroflü biçimler):
        for malformed in ("İzmir 12", "", "İz'mir", "12"):
            with self.subTest(location=malformed):
                self.assertIsNone(
                    brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY,
                                             {"location": malformed}))
        # Biçim hükmü KABUL ettikleri: Core'un reddetme yetkisi anlamda değildir.
        self.assertEqual(
            brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY,
                                     {"location": "çok sıcak"}),
            ("city_set", {"location": "Çok Sıcak"}))
        self.assertTrue(brain_model_understanding._supplied_schema(
            understanding.WEATHER_CITY_SET_CAPABILITY))


class WeatherCityUnderstandingTests(unittest.TestCase):
    """Tanıyıcı, retire edilen iki regex ile birebir aynı biçimleri görür — fazlasını değil."""

    def _hint(self, text):
        return understanding._capability_hint(understanding._norm(text), understanding.TemporalNeed.STATIC)

    def test_every_retired_set_shape_is_a_city_set_capability(self):
        for text in ("şehrim İzmir", "konumum Ankara", "yaşadığım şehir İzmir",
                     "şehrim İzmir olsun", "konumum Ankara olsun", "şehrim İzmir'dir",
                     "şehrim İzmir'de", "Şehrim İzmir", "şehrim    izmir",
                     # Taban `(.+?)` çok kelimeli adı da alıyordu ("şehrim Yeni Delhi"i olduğu gibi
                     # yazıyordu); emeklilik bu biçimi korur, yalnız Türkçe büyük harf hükmünü düzeltir.
                     "şehrim Yeni Delhi", "konumum Kırıkkale",
                     # Sesli yüzey noktalama taşır: taban "izmir."i olduğu gibi pref'e yazıyordu.
                     # Hitap/dolgu kümesi kapalıdır (`_CITY_FILLERS`); taban `^` yüzünden "Jarvis,
                     # şehrim İzmir"i kaçırıyordu — bu genişleme bilinçlidir, kelime taraması değildir.
                     "şehrim İzmir.", "Şehrim İzmir!", "şehrim: İzmir", "Jarvis, şehrim İzmir",
                     # Ölçülen denetim BLOCKER'ı: taban `\s*(?:olsun|dır|dir)?$` boşluklu aorist
                     # ekini de düşürüyordu — "şehrim İzmir dir" tabanda "İzmir" yazdırdı. İlk
                     # dilim denemesi ekleri yalnız kesme işaretli sanıp "İzmir Dir" üretti:
                     # tabanın DOĞRU yaptığı bir biçimi bozan gerileme, burada RED olarak pinlendi.
                     "şehrim İzmir dir", "konumum Ankara dır", "şehrim İzmir olur"):
            with self.subTest(text=text):
                self.assertEqual(self._hint(text), understanding.WEATHER_CITY_SET_CAPABILITY)

    def test_every_retired_clear_shape_is_a_city_reset_capability(self):
        for text in ("şehrimi sıfırla", "konumumu sil", "şehrimi unut", "Şehrimi Sıfırla",
                     "lütfen konumumu sil", "şehrimi temizle", "şehrimi sil lütfen",
                     "şehrimi sıfırla."):
            with self.subTest(text=text):
                self.assertEqual(self._hint(text), understanding.WEATHER_CITY_RESET_CAPABILITY)

    def test_the_clear_rule_is_a_whole_sentence_rule(self):
        # Taban kalıbı ankonjenli `search`ti: içinde "şehrimi sil" geçen HER cümleyi çalıştırırdı.
        # Kapı artık cascade'in önünde plan olarak yürüdüğü için bu genişlik başka sahibin işini
        # silerdi (ölçülen BLOCKER); kalıbın sahipliği tüm cümleye daraltıldı.
        for text in ("kural ekle: şehrimi sil", "whatsapp ile şehrimi unut gönder",
                     "telefonumdan konumumu sil", "yarın şehrimi sıfırlamayı hatırlat",
                     "şehrimi silme", "şehrimi sil demedim", "bana şehrimi silmeyi öğret",
                     "şehrimizi konuş", "şehrimiz İzmir", "konumumuza bak"):
            with self.subTest(text=text):
                self.assertNotIn(self._hint(text),
                                 (understanding.WEATHER_CITY_SET_CAPABILITY,
                                  understanding.WEATHER_CITY_RESET_CAPABILITY))

    def test_the_recognizer_is_a_full_sentence_rule_not_a_keyword_scan(self):
        # Retire edilen set kalıbı `^...$` zincirliydi; kelime taramasına dönerse sohbet yutulur.
        for text in ("şehrimiz İzmir", "şehirde yaşamak güzel", "İzmir şehri nasıl",
                     "şehrim关于", "konumumuza bak", "bu şehir neresi",
                     "şehrim İzmir ve hava güzel", "şehrim İzmir. Hava nasıl?",
                     "hava durumu için şehrim İzmir mi diyeyim", "şehrim güzel"):
            with self.subTest(text=text):
                self.assertNotIn(self._hint(text),
                                 (understanding.WEATHER_CITY_SET_CAPABILITY,
                                  understanding.WEATHER_CITY_RESET_CAPABILITY))

    def test_a_city_value_that_is_not_a_name_is_not_proposed_at_all(self):
        # Retire edilen kapı `(.+?)` kabul ediyordu: "şehrim çok sıcak" pref'i bozuyordu (ölçülen kusur).
        # Emeklilikte bu sınıf Brain'de geri çevrilir; Core-red yüzeyine ("güvenli biçimde
        # doğrulayamadım") düşmez. Beklentiler bu ayrımı pinler.
        for text in ("şehrim çok sıcak", "şehrim İstanbul çok güzel", "konumum bilinmiyor",
                     "şehrim nerede", "şehrim nerde", "şehrim nerelerde", "konumum 12"):
            with self.subTest(text=text):
                self.assertIsNone(self._hint(text))
                # `core_plan(None, …)` tek başına hiçbir şey iddia etmez; asıl sözleşme şu ki
                # tanıyıcı ateşlenmediyse önerilen ARGÜMAN da yoktur, dolayısıyla plan kurulamaz.
                self.assertEqual(self._arguments(text), {})
                self.assertIsNone(brain_core_map.core_plan(self._hint(text), self._arguments(text)))

    def _arguments(self, text):
        normalized = understanding._norm(text)
        return understanding._weather_city_arguments(normalized) or {}

    def test_the_argument_is_the_spoken_city_token(self):
        # Beyin yalnız söylenen biçimi önerir; Türkçe büyük/küçük harf ve geçerlilik hükmü Core'un.
        self.assertEqual(self._arguments("şehrim izmir"), {"location": "izmir"})
        self.assertEqual(self._arguments("şehrim Ankara'dır"), {"location": "ankara"})
        self.assertEqual(self._arguments("konumum Muğla"), {"location": "muğla"})
        self.assertEqual(self._arguments("şehrim İzmir'de"), {"location": "izmir"})
        # Noktalama ve hitap öneriye sızmaz: taban "izmir."i olduğu gibi taşıyordu.
        self.assertEqual(self._arguments("şehrim İzmir."), {"location": "izmir"})
        self.assertEqual(self._arguments("Jarvis, şehrim İzmir"), {"location": "izmir"})
        # Çok kelimeli ad tabanda kaydediliyordu; burada da tek öneri olarak taşınır.
        self.assertEqual(self._arguments("şehrim Yeni Delhi"), {"location": "yeni delhi"})

    def test_a_spaced_copula_yields_the_city_the_base_wrote(self):
        # DENETİM BLOCKER'ı (bu turda RED→GREEN): taban `\s*(?:olsun|dır|dir)?$` boşluklu aorist
        # ekini de düşürüyordu, yani "şehrim İzmir dir" tabanda "İzmir" yazdırıyordu. İlk dilim
        # denemesi eki yalnız kesme işaretli sanıp "İzmir Dir" yazdı — tabanın DOĞRU yaptığı bir
        # biçimi bozan gerileme. Boşluklu ek düşürülür, BİRLEŞİK yazım adın parçası kalır
        # ("Boludur" tabanla aynı sonuç; "Burdur"u "Bur"a çevirmemek bu ayrımın gerekçesidir).
        for text, expected in (("şehrim İzmir dir", "İzmir"), ("konumum Ankara dır", "Ankara"),
                               ("şehrim İzmir olur", "İzmir"),
                               ("şehrim Yeni Delhi dir", "Yeni Delhi"),
                               ("şehrim Boludur", "Boludur")):
            with self.subTest(text=text):
                self.assertEqual(self._hint(text), understanding.WEATHER_CITY_SET_CAPABILITY)
                self.assertEqual(
                    brain_core_map.core_plan(self._hint(text), self._arguments(text)),
                    ("city_set", {"location": expected}))

    def test_the_proposal_the_brain_makes_is_always_the_one_core_accepts(self):
        # İKİ KATMANLI RED YÜZEYİ KORUMASI: Brain önerir, Core hükmünü bağımsız verir. Brain'in
        # kabul ettiği her biçim Core'da da doğrulanmalıdır; aksi hâlde kullanıcı "güvenli biçimde
        # doğrulayamadım" redi görür — emekli edilen kapının böyle bir yüzeyi yoktu (ölçülen BLOCKER).
        corpus = ["şehrim İzmir", "şehrim İzmir.", "konumum Ankara olsun", "şehrim İzmir'dir",
                  "şehrim İzmir'de", "yaşadığım şehir Muğla", "şehrim Yeni Delhi",
                  "Jarvis, şehrim Uşak", "şehrim Iğdır", "şehrim Şırnak",
                  "şehrim İzmir dir", "konumum Ankara dır",
                  "şehrimi sıfırla", "konumumu sil", "şehrimi unut lütfen"]
        for text in corpus:
            with self.subTest(text=text):
                normalized = understanding._norm(text)
                hint = understanding._weather_city_request(normalized)
                self.assertIsNotNone(hint)
                self.assertIsNotNone(
                    brain_core_map.core_plan(hint, self._arguments(text)))

    def test_clear_carries_no_target(self):
        self.assertEqual(self._arguments("şehrimi sıfırla"), {})


class WeatherCityAuthorityHarnessTests(pr3a._CanonicalAuthorityHarness):
    """Gerçek üretim zinciri: prepare → handoff → Core intent; legacy handler hiç çağrılmaz."""

    def test_setting_the_city_is_a_canonical_plan_and_never_the_legacy_handler(self):
        for text in ("şehrim İzmir", "konumum Ankara olsun"):
            with self.subTest(text=text):
                entry, out, handle, feedback = self.turn(text)
                self.assertEqual(entry.understanding.capability_hint, understanding.WEATHER_CITY_SET_CAPABILITY)
                self.assertIsNotNone(brain_entry.core_plan(entry))
                handle.assert_not_called()
                self.assertEqual(feedback.result_status, "handled")
                self.assertNotIn("HANDLER", str(out))

    def test_the_spaced_copula_writes_the_same_preference_as_the_bare_statement(self):
        # Kullanıcı görünüründe tek ölçüt: söylenen ek Pref'i bozmamalı. Taban "şehrim İzmir dir"
        # için "İzmir" yazıyordu; emeklilikte "İzmir Dir" yazılması GERİLEME sayılır (BLOCKER).
        self.turn_real("şehrim İzmir dir")
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")
        self.turn_real("konumum Ankara dır")
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "Ankara")

    def test_clearing_the_city_is_a_canonical_plan_and_never_the_legacy_handler(self):
        entry, out, handle, feedback = self.turn("şehrimi sıfırla")
        self.assertEqual(entry.understanding.capability_hint, understanding.WEATHER_CITY_RESET_CAPABILITY)
        self.assertIsNotNone(brain_entry.core_plan(entry))
        handle.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")

    def test_the_set_reply_text_is_unchanged(self):
        out = self.turn_real("şehrim İzmir")[1]
        self.assertEqual(out, SET_REPLY.format(city="İzmir"))

    def test_the_retired_grammar_mangled_the_turkish_capital(self):
        # Ölçülen taban kusuru (head `755ddf6`, `engine_commands.py:268-272`): kapı `cmd_lower`
        # üzerinden `(.+?)` alıp `.title()` uyguluyordu; Türkçe noktalı İ böylece bozuldu ve
        # pref'e "Izmir" yazıldı. Kanonical yol bu düzeltmeyi yapar: Core `_location_args`,
        # `weather` intent'iyle aynı Türkçe büyük/küçük harf kuralını kullanır.
        legacy_captured = re.match(LEGACY_SET_PATTERN, "şehrim izmir").group(1).title()
        self.assertEqual(legacy_captured, "Izmir")
        self.assertEqual(
            brain_core_map.core_plan(understanding.WEATHER_CITY_SET_CAPABILITY,
                                     {"location": legacy_captured.lower()}),
            ("city_set", {"location": "İzmir"}))

    def test_the_retired_clear_reply_text_is_unchanged(self):
        self.ctx.profile.set_pref("city", "İzmir")
        out = self.turn_real("şehrimi sıfırla")[1]
        self.assertEqual(out, CLEAR_REPLY)

    def test_the_real_preference_written_by_the_canonical_path(self):
        self.turn_real("şehrim Ankara")
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "Ankara")

    def test_the_real_preference_cleared_by_the_canonical_path(self):
        self.turn_real("konumum İzmir")
        self.turn_real("şehrimi unut")
        self.assertNotIn("city", self.ctx.profile.data["prefs"])

    def test_an_unvalidated_city_sentence_writes_no_preference(self):
        # Retire edilen kapı `(.+?)` aldığı her şeyi yazıyordu. Kanonical zincirde Brain önerir,
        # Core `_CITY` ile reddeder: plan yoktur ve hiçbir tercih yazılmaz.
        self.ctx.profile.set_pref("city", "İzmir")
        for text in ("şehrim çok sıcak", "şehrim İstanbul çok güzel", "konumum bilinmiyor",
                     "şehrim nerede", "şehrim güzel"):
            with self.subTest(text=text):
                entry, out, _handle, _feedback = self.turn_real(text)
                self.assertIsNone(brain_entry.core_plan(entry))
                self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")
                # Yalnız "kaydettim" yokluğu zayıf kanıttı: Core-red mesajı da içermez. Emeklilik
                # sonrası beklenen, cümlenin HİÇ plan üretmemesi ve red yüzeyinin de görünmemesidir.
                self.assertNotIn("doğrulayamadım", str(out))
                self.assertIsNone(entry.understanding.capability_hint)

    def test_a_punctuated_city_statement_reaches_the_same_effect_as_the_bare_one(self):
        # Sesli yüzey noktalama taşır; taban "izmir."i pref'e yazıp sonra hiçbir şey demiyordu.
        out = self.turn_real("şehrim İzmir.")[1]
        self.assertEqual(out, SET_REPLY.format(city="İzmir"))
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")

    def test_a_question_about_the_city_never_deletes_or_writes_the_preference(self):
        self.ctx.profile.set_pref("city", "İzmir")
        for text in ("şehrim nerede", "şehrim nerde", "şehrim nerelerde"):
            with self.subTest(text=text):
                out = str(self.turn_real(text)[1])
                self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")
                self.assertNotIn("doğrulayamadım", out)

    def test_the_earlier_plan_claim_steals_no_other_owners_effect(self):
        # Emekli kapı cascade'İN İÇİNDEYDİ; plan olarak öne çıktığı için sıralama tersinesine
        # dönüştü (ölçülen BLOCKER). Kanıt seam'de: başka sahibin cümlesi şehir planı üretmezse
        # `dispatch`'in şehir kolu hiç çalışmaz ve pref'e dokunulmaz. Kanıt seam'de kalır; gerçek
        # `engine_commands.handle` turu bu cümlelerle posta/öğrenme işi yapabilir (kural).
        for text in ("kural ekle: şehrimi sil", "whatsapp ile şehrimi unut gönder",
                     "telefonumdan konumumu sil", "yarın şehrimi sıfırlamayı hatırlat"):
            with self.subTest(text=text):
                self.ctx.profile.set_pref("city", "İzmir")
                entry, _out, _handle, _feedback = self.turn(text)
                self.assertNotIn(entry.understanding.capability_hint,
                                 (understanding.WEATHER_CITY_SET_CAPABILITY,
                                  understanding.WEATHER_CITY_RESET_CAPABILITY))
                plan = brain_entry.core_plan(entry)
                self.assertTrue(plan is None or plan[0] not in {"city_set", "city_reset"},
                                f"{text!r} şehir planına dönüştü: {plan}")
                self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")

    def test_the_city_answer_to_an_open_weather_question_keeps_its_owner(self):
        # Hava sorusunun cevabı pref YAZMAZ: bounded `pending_weather_location` sahibi değişmedi.
        self.ctx.profile.set_pref("city", "İzmir")
        session = self.ctx._session()
        session.pending_weather_location = True
        self.turn_real("Adana")
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")
        self.assertFalse(session.pending_weather_location)


class WeatherCityDoorRetirementGuardTests(unittest.TestCase):
    """Emeklilik yapısal kilidi: yüzeyde ham cümleden seçilen bir konum yazması kalmaz."""

    def test_engine_commands_handle_has_no_raw_city_door(self):
        self.assertEqual(_raw_city_door_in_handle(), [])

    def test_the_retired_patterns_are_not_relocated_into_another_legacy_surface(self):
        # §33: kalıp başka bir legacy yüzeye taşınarak "emekli" ilan edilmez. Tek serbest sahip
        # kanonical tanıyıcıdır (`brain_understanding`); yüzeyler ham cümleye bakamaz.
        legacy_surfaces = sorted(
            path for path in (ROOT / "modules").glob("*.py")
            if path.name != "brain_understanding.py")
        for path in legacy_surfaces:
            text = path.read_text(encoding="utf-8", errors="replace")
            with self.subTest(module=path.name):
                self.assertNotIn("yaşadığım şehir)\\s+", text)
                self.assertNotIn("şehrimi|konumumu", text)

    def test_the_legacy_surface_does_not_write_the_city_preference(self):
        source = ENGINE_COMMANDS.read_text(encoding="utf-8")
        self.assertNotIn('set_pref("city"', source)
        self.assertNotIn("'city'", source)
        self.assertNotIn('pop("city"', source)


class WeatherCityModelEnvelopeTests(unittest.TestCase):
    """Kalıcı tercih yazması/silinmesi modelin önerdiği bir yetenek OLAMAZ.

    Denetimde ölçülen ikinci gerçek boşluk: bu PR `weather.city.set`/`weather.city.reset`'i
    `CORE_INTENTS` kataloğuna eklediği için BRAIN-01 zarfı o yeteneği artık önerebiliyor ve
    modelin yazdığı "çok sıcak" gibi bir değer Core'un BİÇİM hükmünden geçiyordu
    (`_city_set_args("çok sıcak")` → "Çok Sıcak") — ölçüldü: `core_plan(...) == ("city_set",
    {"location": "Çok Sıcak"})`. Core anlam listesi tutmaz (tutsa ikinci semantic authority
    olurdu), o hâlde yasak doğru yerde: tercih, kullanıcının kendi cümlesinden doğar.
    """

    OWNER = "b3-city-envelope"

    def _current(self, text):
        # Zarf testi Production'ın kendi satırı ile kurulur: `understand` güveni MEDIUM,
        # ilişkisi NEW_REQUEST üretiyor (ölçüldü) — elle yazılmış bir fixture, yüksek güvenli
        # bir zarfı `._apply_semantic_fences`teki güven tavanında düşürüp kontrolü sahte yapardı.
        from modules.brain_contracts import ActiveContext
        request_id = "r-city-envelope"
        return understanding.understand(
            owner=self.OWNER, request_id=request_id, text=text,
            active_context=ActiveContext(owner=self.OWNER, request_id=request_id),
            candidates=(), references=())

    def _envelope(self, capability, arguments):
        from modules.brain_model_understanding import SCHEMA_VERSION
        return json.dumps({
            "schema_version": SCHEMA_VERSION, "operation": "direct_action",
            "conversation_relation": "NEW_REQUEST", "temporal_need": "STATIC",
            "target_goal_ids": [], "goal": None, "clarification":
                {"required": False, "question": None, "reason_code": None},
            "confidence": "MEDIUM",
            "actions": [{"action_id": "a1", "capability_id": capability,
                         "arguments": arguments, "reference_slots": [], "depends_on": []}]})

    def _ask(self, text, raw):
        from modules import brain_model_understanding as model
        current = self._current(text)
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", return_value=raw):
            return model.propose(owner=self.OWNER, text=understanding._norm(text),
                                 current=current, arguments=dict(current.arguments))

    def test_a_model_proposed_preference_write_is_not_a_valid_proposal(self):
        for capability, arguments in (
                (understanding.WEATHER_CITY_SET_CAPABILITY, {"location": "çok sıcak"}),
                (understanding.WEATHER_CITY_SET_CAPABILITY, {"location": "izmir"}),
                (understanding.WEATHER_CITY_RESET_CAPABILITY, {})):
            with self.subTest(capability=capability):
                self.assertIsNone(self._ask("bugün hava nasıl", self._envelope(capability, arguments)))

    def test_the_denial_is_a_closed_capability_set_not_an_argument_key_rule(self):
        # `location` anahtarını yasaklamak hava OKUMASını da vururdu; yasak yetenek düzeyindedir
        # ve küme kapalıdır — kelime taraması, regex veya modelden gelen bir ad değildir.
        from modules import brain_model_understanding as model
        self.assertEqual(
            set(model._MODEL_DENIED_CAPABILITIES),
            {understanding.WEATHER_CITY_SET_CAPABILITY, understanding.WEATHER_CITY_RESET_CAPABILITY})

    def test_a_model_proposed_weather_read_is_still_allowed(self):
        # Yasak yalnız tercih YAZMASI/SİLMESİ içindir: okuma zarf kararının normal yeteneğidir.
        proposal = self._ask("yarın izmirde hava nasıl", self._envelope(
            "weather.read", {"location": "izmir"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, "weather.read")

    def test_denying_an_echoed_city_set_leaves_the_users_own_sentence_untouched(self):
        # Yasağın kullanıcı yüzü: "şehrim İzmir"de deterministik satır ZATEN weather.city.set
        # taşıyor. Model aynı yeteneği yankılarsa zarf öneriyi düşürür, `apply_model_understanding`
        # deterministik sonucu olduğu gibi korur — yani gerçek cümlelerin etkisi değişmez.
        text = "şehrim İzmir"
        deterministic = self._current(text)
        self.assertEqual(deterministic.capability_hint, understanding.WEATHER_CITY_SET_CAPABILITY)
        echoed = self._envelope(understanding.WEATHER_CITY_SET_CAPABILITY,
                                {"location": "İzmir"})
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", return_value=echoed):
            adopted = understanding.apply_model_understanding(deterministic, text)
        self.assertEqual(adopted, deterministic)
        self.assertEqual(adopted.capability_hint, understanding.WEATHER_CITY_SET_CAPABILITY)
        self.assertEqual(adopted.arguments.get("location"), "izmir")

    def test_the_prompt_catalogue_does_not_advertise_a_denied_capability(self):        # Zarf yasakları modelden GELSE bir değeri reddeder; prompt yasağı olmayan bir yeteneği
        # "seçebilirsin" diye ilan ederse sözleşme içten tutarsız olur ve her seçim fail-closed
        # düşer. Ölçülen katalog: yasak küme ilan edilmez, okuma yeteneği ilan edilmeye devam eder.
        from modules import brain_model_understanding as model
        from modules.brain_core_map import CORE_INTENTS
        captured: dict[str, str] = {}

        def fake_run(owner, text, send, *, route, exclude_providers):
            captured["payload"] = text
            return self._envelope("weather.read", {"location": "izmir"})

        current = self._current("bugün hava nasıl")
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                patch("modules.smart_router.run", side_effect=fake_run):
            self.assertIsNotNone(model.propose(
                owner=self.OWNER, text="bugün hava nasıl", current=current,
                arguments=dict(current.arguments)))
        payload, _end = json.JSONDecoder().raw_decode(
            captured["payload"][captured["payload"].index("{"):])
        advertised = set(payload["allowed"]["capability_id"])
        self.assertEqual(advertised & set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertIn("weather.read", advertised)
        self.assertEqual(advertised, set(CORE_INTENTS) - set(model._MODEL_DENIED_CAPABILITIES))
        self.assertEqual(set(payload["allowed"]["argument_schema"]), advertised)
