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
from provider_fixture import routed_response, routed_plan

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

    def test_a_spaced_locative_yields_the_city_the_base_wrote(self):
        # DENETİM GERİLEMESİ (RED→GREEN): taban kalıbı `(.+?)(?:['’]?(?:da|de|ta|te))?` idi, yani
        # boşluklu bulunma halini DÜŞÜRÜYORDU. İlk dilim denemesinde bu yoktu ve "şehrim İzmir de"
        # hiç öneri üretmiyordu — tabanın tanıdığı bir biçimi bozan gerileme, burada RED pinlendi.
        # Küme kapalıdır (`_CITY_SPACED_LOCATIVES`); kesme işaretli biçim zaten çalışıyordu.
        for text, expected in (("şehrim İzmir de", "İzmir"), ("konumum İstanbul de", "İstanbul"),
                               ("şehrim Bolu'da", "Bolu"), ("şehrim İzmir de olsun", "İzmir"),
                               ("yaşadığım şehir Ankara'da", "Ankara")):
            with self.subTest(text=text):
                self.assertEqual(self._hint(text), understanding.WEATHER_CITY_SET_CAPABILITY)
                self.assertEqual(
                    brain_core_map.core_plan(self._hint(text), self._arguments(text)),
                    ("city_set", {"location": expected}))

    def test_a_polite_or_hedged_clear_request_is_still_a_reset(self):
        # DENETİM GERİLEMESİ (RED→GREEN): taban `(şehrimi|konumumu)\s+(sıfırla|sil|unut)` ankonjenli
        # `search`ti, yani "haydi şehrimi sil" ve "şehrimi siler misin" de tercihi siliyordu. Tüm-
        # cümle kuralına geçiş bu biçimleri de düşürdü; kapalı baş-dolgu, fiil ve kibar-yardımcı
        # kümeleriyle geri alınır — ankonjenlik geri gelmez (aşağıdaki negatif test pinler).
        for text in ("şehrimi siler misin", "haydi şehrimi sil", "rica etsem konumumu unut",
                     "şehrimi unutur musun", "hadi konumumu sıfırla", "şehrimi silebilir misin",
                     "rica etsem şehrimi temizler misin", "haydi şehrimi sil lütfen"):
            with self.subTest(text=text):
                self.assertEqual(self._hint(text), understanding.WEATHER_CITY_RESET_CAPABILITY)

    def test_a_hedge_does_not_reopen_the_anconjunct_clear_scan(self):
        # Kibarlık kümeleri cümlenin BAŞINDA ve SONUNDA dizilir; ortada kalan fiil başka bir sahibin
        # işidir. Genişleme ankonjen taramaya dönüşürse ölçülen BLOCKER geri gelir — negatif pin.
        for text in ("kural ekle: haydi şehrimi sil", "yarın şehrimi siler misin",
                     "telefonumdan konumumu siler misin", "rica etsem şehrimi silmeyi öğret",
                     "haydi şehrimi silmemi söylüyor", "şehrimi siler misin bak",
                     "diyor ki şehrimi sil"):
            with self.subTest(text=text):
                self.assertNotIn(self._hint(text),
                                 (understanding.WEATHER_CITY_SET_CAPABILITY,
                                  understanding.WEATHER_CITY_RESET_CAPABILITY))

    def test_a_predicate_about_the_city_is_never_taken_as_its_name(self):
        # Taban `(.+?)` yargıyı da adı da olduğu gibi pref'e yazıyordu; ölçülen üç biçim
        # ("değişti", "oldu", "hava durumu") hâlâ geçiyordu ve denetimde yeniden ölçüldü. Kapalı
        # kümeler bunları ayıklar: "oldu" ek, "midir" soru, ötekiler işlev sözcüğü.
        self.assertEqual(brain_core_map.core_plan(
            self._hint("şehrim Ankara oldu"), self._arguments("şehrim Ankara oldu")),
            ("city_set", {"location": "Ankara"}))
        for text in ("şehrim İzmir midir", "şehrim değişti", "şehrim Ankara hava durumu",
                     "şehrim İstanbul mu", "konumum taşındı"):
            with self.subTest(text=text):
                # Ölçülen: "şehrim Ankara hava durumu" artık HAVA okuması önerir (tanıyıcının
                # kendi sahibi); sözleşme hiçbir tercih yazma önerisi üretmemesidir.
                self.assertNotIn(self._hint(text),
                                 (understanding.WEATHER_CITY_SET_CAPABILITY,
                                  understanding.WEATHER_CITY_RESET_CAPABILITY))
                self.assertEqual(self._arguments(text), {})

    def test_the_proposal_the_brain_makes_is_always_the_one_core_accepts(self):
        # İKİ KATMANLI RED YÜZEYİ KORUMASI: Brain önerir, Core hükmünü bağımsız verir. Brain'in
        # kabul ettiği her biçim Core'da da doğrulanmalıdır; aksi hâlde kullanıcı "güvenli biçimde
        # doğrulayamadım" redi görür — emekli edilen kapının böyle bir yüzeyi yoktu (ölçülen BLOCKER).
        corpus = ["şehrim İzmir", "şehrim İzmir.", "konumum Ankara olsun", "şehrim İzmir'dir",
                  "şehrim İzmir'de", "yaşadığım şehir Muğla", "şehrim Yeni Delhi",
                  "Jarvis, şehrim Uşak", "şehrim Iğdır", "şehrim Şırnak",
                  "şehrim Ordu", "şehrim Burdur", "şehrim Bolu de olsun",
                  "şehrim İzmir dir", "konumum Ankara dır", "şehrim İzmir de",
                  "şehrimi sıfırla", "konumumu sil", "şehrimi unut lütfen",
                  "haydi şehrimi sil", "rica etsem konumumu unut", "şehrimi siler misin"]
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

    def test_the_spaced_locative_and_the_polite_clear_reach_the_same_effect(self):
        # Gerileme kullanıcı görünüründe ölçülür: taban bu iki biçimde tercihi YAZIYORDU/SİLİYORDU;
        # kanonical zincir de aynı etkiyi üretmeli, yoksa kapı daralmış olur.
        entry, out, handle, _feedback = self.turn("şehrim İzmir de")
        self.assertEqual(entry.understanding.capability_hint, understanding.WEATHER_CITY_SET_CAPABILITY)
        handle.assert_not_called()
        self.assertEqual(self.turn_real("şehrim İzmir de")[1], SET_REPLY.format(city="İzmir"))
        self.assertEqual(self.ctx.profile.data["prefs"].get("city"), "İzmir")
        self.turn_real("konumum Ankara")
        self.turn_real("haydi şehrimi siler misin")
        self.assertNotIn("city", self.ctx.profile.data["prefs"])

    def test_conditional_prefixes_never_authorize_a_preference_effect(self):
        for text in ("rica edersem şehrimi sil", "edersem şehrimi sil",
                     "rica edersem şehrim İzmir olsun", "ne şehrimi sil",
                     "rica şehrimi sil", "etsem şehrimi sil", "ne olur şehrim İzmir"):
            with self.subTest(text=text):
                self.ctx.profile.set_pref("city", "Ankara")
                entry, _out, _handle, _feedback = self.turn(text)
                plan = brain_entry.core_plan(entry)
                self.assertTrue(plan is None or plan[0] not in {"city_set", "city_reset"})
                self.assertEqual(self.ctx.profile.data["prefs"]["city"], "Ankara")

    def test_reported_speech_questions_and_negation_write_no_preference(self):
        for text in ("şehrim İzmir olsun de", "şehrim İzmir olsun olsun",
                     "şehrim İzmir'dir de", "şehrim İzmir’dir de", "konumum Ankara'dır de",
                     "şehrim İzmir?!", "şehrim İzmir? lütfen", "şehrim? İzmir",
                     "şehrim İzmir değildi", "şehrim İzmir olmaz", "şehrim İzmir değilse"):
            with self.subTest(text=text):
                self.ctx.profile.set_pref("city", "Ankara")
                entry, _out, _handle, _feedback = self.turn(text)
                plan = brain_entry.core_plan(entry)
                self.assertTrue(plan is None or plan[0] not in {"city_set", "city_reset"})
                self.assertEqual(self.ctx.profile.data["prefs"]["city"], "Ankara")

    def test_polite_reset_punctuation_preserves_the_explicit_request(self):
        for text in ("haydi şehrimi siler misin?", "rica etsem şehrimi siler misin?",
                     "ne olur konumumu unut", "şehrimi silebilir misin?!",
                     "şehrimi siler misin? lütfen"):
            with self.subTest(text=text):
                self.ctx.profile.set_pref("city", "Ankara")
                entry, out, handle, _feedback = self.turn(text)
                self.assertEqual(brain_entry.core_plan(entry), ("city_reset", {}))
                handle.assert_not_called()
                self.assertEqual(out, CLEAR_REPLY)
                self.assertNotIn("city", self.ctx.profile.data["prefs"])

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
                routed_response(raw):
            return model.propose(owner=self.OWNER, text=understanding._norm(text),
                                 current=current, arguments=dict(current.arguments))

    def test_preference_write_requires_words_from_the_current_user(self):
        from modules import brain_model_understanding as model
        self.assertIsNone(self._ask("bugün hava nasıl", self._envelope(
            "weather.city.set", {"location": "izmir"})))
        row = json.loads(self._envelope("weather.city.set", {"location": "izmir"}))
        row["actions"][0]["argument_sources"] = {"location": "İzmir"}
        proposal = self._ask("şehrim İzmir olsun", json.dumps(row))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].arguments["location"], "izmir")
        row["actions"][0]["argument_sources"] = {"location": "Ankara"}
        self.assertIsNone(self._ask("şehrim İzmir olsun", json.dumps(row)))

    def test_final_cutover_has_no_legacy_city_exception(self):
        from modules import brain_model_understanding as model
        self.assertEqual(set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertEqual(model._supplied_schema("weather.city.set")["argument_sources"], ["location"])

    def test_a_model_proposed_weather_read_is_still_allowed(self):
        # Yasak yalnız tercih YAZMASI/SİLMESİ içindir: okuma zarf kararının normal yeteneğidir.
        proposal = self._ask("yarın izmirde hava nasıl", self._envelope(
            "weather.read", {"location": "izmir"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, "weather.read")

    def test_city_reset_is_an_explicit_typed_empty_argument_action(self):
        proposal = self._ask("kayıtlı şehrimi sil", self._envelope("weather.city.reset", {}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, "weather.city.reset")
        self.assertEqual(brain_core_map.core_plan("weather.city.reset", proposal.actions[0].arguments), ("city_reset", {}))

    def test_the_prompt_catalogue_does_not_advertise_a_denied_capability(self):        # Zarf yasakları modelden GELSE bir değeri reddeder; prompt yasağı olmayan bir yeteneği
        # "seçebilirsin" diye ilan ederse sözleşme içten tutarsız olur ve her seçim fail-closed
        # düşer. Ölçülen katalog: yasak küme ilan edilmez, okuma yeteneği ilan edilmeye devam eder.
        from modules import brain_model_understanding as model
        from modules.brain_core_map import CORE_INTENTS
        captured: dict[str, str] = {}

        def fake_run(request, spec, text, system, **kwargs):
            captured["payload"] = text
            return self._envelope("weather.read", {"location": "izmir"})

        current = self._current("bugün hava nasıl")
        with patch("modules.llm.current_user", return_value=self.OWNER), \
                patch("modules.llm.provider", return_value="groq"), \
                patch("modules.llm.privacy.mode", return_value="normal"), \
                patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
                routed_plan(count=1), patch("modules.llm.dispatch", side_effect=fake_run):
            self.assertIsNotNone(model.propose(
                owner=self.OWNER, text="bugün hava nasıl", current=current,
                arguments=dict(current.arguments)))
        payload, _end = json.JSONDecoder().raw_decode(
            captured["payload"][captured["payload"].index("{"):])
        advertised = set(payload["allowed"]["capability_id"])
        self.assertEqual(advertised & set(model._MODEL_DENIED_CAPABILITIES), set())
        self.assertIn("weather.read", advertised)
        self.assertFalse(payload["current"]["current_output"]["available"])
        self.assertNotIn("documents.export", advertised)
        self.assertEqual(advertised, set(CORE_INTENTS) - set(model._MODEL_DENIED_CAPABILITIES) - {"documents.export"})
        self.assertEqual(set(payload["allowed"]["argument_schema"]), advertised)
