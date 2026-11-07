"""PR #530 güvenlik turu: dayanak denetimi kelime/sayı SINIRI ölçmek zorundadır.

Önceki turda `_arguments_are_grounded` hem alıntıyı hem değeri tüm noktalama ve boşlukları
silen tek bir katlanmış dizgiye indirgiyor ve sonra **alt dize** arıyordu. Bu, kullanıcının
söylemediği bir alıcıyı söylenmiş gibi gösterebilir: `whatsapp'tan kaligrafiye mesaj at`
cümlesinde `ali` dizisi `kaligrafiye`nin içindedir. Rehberde kayıtlı ve tekil bir "Ali"
varsa bu uydurma alıcı gerçek bir gönderime dönüşebilir.

Bu dosya açığı kapatır ve **genel** bir sınır doğrulaması ister: hiçbir özel isim, fiil veya
doğal dil kelime listesi eklenmez. Dayanak, kullanıcının cümlesinde bitişik **kelime/sayı
dizileri** olarak bulunmalı; alan değeri de o alıntının tam kelime/sayı dizileri olmalıdır.
Sayısal alanda (telefon) alt dize yeterli değildir, rakam dizisinin tamamı eşit olmalıdır.

Testler zarf düzeyinde (`_ask`: gerçek `_build` + dayanak denetimi) ve **üretim zinciri**
düzeyinde (`_MessageTurnHarness`: `prepare → handoff → EngineContext.handle`) ölçer; son
grupta yanıt metni değil `send_whatsapp` çağrısının hiç başlamaması ve oturum durumu esastır.
Bu zarflar BAĞLANTI kanıtıdır; modelin doğal dili anladığının kanıtı değildir (§16).
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_brain_b3_message_and_contacts_authority as b3  # noqa: E402
from test_brain_b3_message_and_contacts_authority import (  # noqa: E402
    CONFIRM_QUESTION, _chat_envelope, _envelope, _reply, _utterance_of,
)

_MESSAGE = b3._MESSAGE
_CONTACTS = b3._CONTACTS


def _keyed_run(rows):
    """Cümleye göre zarf döndüren sahte sağlayıcı (ağ yok)."""
    def run(owner, payload, send, *, route, exclude_providers):
        reply = rows.get(_utterance_of(payload))
        return _chat_envelope() if reply is None else _envelope(*reply)
    return run


def _send_zarf(recipient, recipient_span, body, body_span):
    """Alıcı ve gövdeyi kendi dayanak alıntılarıyla taşıyan mesaj zarfı."""
    return _envelope(_MESSAGE, {"recipient": recipient, "body": body},
                     {"recipient": recipient_span, "body": body_span})


class WordInternalSubstringTests(b3._ZarfHarness):
    """§2.A: bir kelimenin İÇİNDEN kesilen parça dayanak olamaz; öneri tümüyle düşer."""

    def test_a_recipient_cut_out_of_a_longer_word_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan kaligrafiye mesaj at",
            _send_zarf("ali", "kaligrafiye", "mesaj", "mesaj")))

    def test_a_recipient_cut_out_of_malik_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan malik'e mesaj at",
            _send_zarf("ali", "malik'e", "mesaj", "mesaj")))

    def test_a_recipient_cut_out_of_salih_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan salih'e mesaj at",
            _send_zarf("alih", "salih'e", "mesaj", "mesaj")))

    def test_a_recipient_cut_out_of_rahmetli_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan rahmetli'ye mesaj at",
            _send_zarf("ahmet", "rahmetli'ye", "mesaj", "mesaj")))

    def test_a_word_fragment_is_not_a_valid_source(self):
        # Değer gerçekten söylenmiş olsa bile alıntı kelimenin ortasından kesikse geçersizdir:
        # dayanak kanıtı alıntının kendisidir.
        self.assertIsNone(self._ask(
            "whatsapp'tan ahmet'e mesaj at",
            _send_zarf("ahmet", "hmet'e", "mesaj", "mesaj")))

    def test_joining_separate_words_cannot_invent_a_name(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan demir ay'a mesaj at",
            _send_zarf("nay", "demir ay'a", "mesaj", "mesaj")))

    def test_a_whole_spoken_word_inside_a_longer_span_is_still_grounded(self):
        # Reddedilen şey kelime içi kesimdir; bitişik TAM kelimeler meşrudur.
        proposal = self._ask("whatsapp'tan demir ay'a mesaj at",
                             _send_zarf("demir", "demir ay'a", "mesaj", "mesaj"))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, _MESSAGE)


class TurkishSurfaceParityTests(b3._ZarfHarness):
    """§2.B: gerçek Türkçe ifadeler yeni sınırda bozulmamalı (harf kasımı + ek ayracı)."""

    def test_a_dative_recipient_with_an_apostrophe_still_grounds(self):
        self.assertIsNotNone(self._ask(
            "whatsapp'tan ahmet'e mesaj at",
            _send_zarf("ahmet", "ahmet'e", "mesaj", "mesaj")))

    def test_a_turkish_dative_recipient_still_grounds(self):
        proposal = self._ask(
            "whatsapp'tan Ayşe'ye selam gönder", _envelope(
                _MESSAGE, {"recipient": "ayşe", "body": "selam"},
                {"recipient": "Ayşe'ye", "body": "selam"}))
        self.assertIsNotNone(proposal)

    def test_the_recipient_of_an_inverted_sentence_still_grounds(self):
        proposal = self._ask(
            "ahmet'e yarın geleceğim diye yaz", _envelope(
                _MESSAGE, {"recipient": "ahmet", "body": "yarın geleceğim"},
                {"recipient": "ahmet'e", "body": "yarın geleceğim diye"}))
        self.assertIsNotNone(proposal)

    def test_a_multi_word_recipient_still_grounds(self):
        proposal = self._ask(
            "whatsapp'tan ahmet yılmaz'a selam gönder", _envelope(
                _MESSAGE, {"recipient": "ahmet yılmaz", "body": "selam"},
                {"recipient": "ahmet yılmaz'a", "body": "selam"}))
        self.assertIsNotNone(proposal)

    def test_the_existing_grounded_examples_do_not_regress(self):
        # Bu turun amacı hiçbir zarfı gevşetmemek: önceki turda geçen her sabit satır geçmeli.
        for text, (capability, arguments, sources) in b3.MODEL_STUB_REPLIES.items():
            with self.subTest(text=text):
                self.assertIsNotNone(self._ask(text, _envelope(capability, arguments, sources)))


class BodyAndPhoneSpanTests(b3._ZarfHarness):
    """§2.C: gövde ve numara da kelime/sayı sınırıyla doğrulanır."""

    def test_a_body_cut_out_of_one_word_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan ahmet'e geliyorum yaz", _envelope(
                _MESSAGE, {"recipient": "ahmet", "body": "gel"},
                {"recipient": "ahmet'e", "body": "geliyorum"})))

    def test_a_body_may_not_be_glued_from_several_words_it_did_not_say(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan ahmet'e yarın geleceğim diye mesaj at", _envelope(
                _MESSAGE, {"recipient": "ahmet", "body": "yarıngelecegim"},
                {"recipient": "ahmet'e", "body": "yarın geleceğim"})))

    def test_a_phone_inside_a_longer_number_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "kişi ekle ahmet 10532123456789", _envelope(
                _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "05321234567"},
                {"name": "ahmet", "phone": "05321234567"})))

    def test_a_prefix_of_a_spoken_number_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "kişi ekle ahmet 10532123456789", _envelope(
                _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "1053212345"},
                {"name": "ahmet", "phone": "1053212345"})))

    def test_a_phone_spent_with_separators_still_grounds(self):
        # Ayraç farkı güvenli desteklenmeye devam eder: rakam dizisinin TAMAMI eşittir.
        proposal = self._ask(
            "kişi ekle ahmet 0532 123 45 67", _envelope(
                _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "05321234567"},
                {"name": "ahmet", "phone": "0532 123 45 67"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(dict(proposal.actions[0].arguments)["phone"], "05321234567")

    def test_a_phone_spent_in_groups_equals_its_spoken_digits(self):
        proposal = self._ask(
            "kişi ekle ahmet 0532 123 45 67", _envelope(
                _CONTACTS, {"operation": "add", "name": "ahmet", "phone": "0532 123 45 67"},
                {"name": "ahmet", "phone": "0532 123 45 67"}))
        self.assertIsNotNone(proposal)


class InventedRecipientSideEffectTests(b3._MessageTurnHarness):
    """§2.D: uydurma alıcı Core'a/oturuma/yürütücüye ulaşmamalı — yan etki ölçülür."""

    # Ada birebir kayıtlı ve tekil bir kişi: açık kapalı olsaydı GERÇEKTEN Ali'ye gönderirdi.
    REGISTERED = {"Ali": "905321234567"}

    def _assert_no_send_side_effect(self, out, entry):
        self.assertNotEqual(entry.understanding.capability_hint, _MESSAGE)
        self.assertIsNone(self.ctx._session().pending_msg)
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()

    def test_a_word_internal_recipient_proposal_is_rejected_wholly(self):
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "mesaj"},
            {"recipient": "kaligrafiye", "body": "mesaj"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan kaligrafiye mesaj at")
        self._assert_no_send_side_effect(out, entry)

    def test_the_registered_namesake_never_receives_the_message(self):
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "mesaj"},
            {"recipient": "kaligrafiye", "body": "mesaj"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan kaligrafiye mesaj at")
        self._assert_no_send_side_effect(out, entry)
        self._threaded_turn("evet gönder")
        self.send.assert_not_called()

    def test_approval_off_does_not_open_the_gate_for_a_word_internal_recipient(self):
        self.ctx.load_approve.return_value = False
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "mesaj"},
            {"recipient": "kaligrafiye", "body": "mesaj"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan kaligrafiye mesaj at")
        self._assert_no_send_side_effect(out, entry)

    def test_a_word_internal_recipient_never_reaches_the_contact_writer(self):
        # Rehber yazması kalıcı profil verisidir. Numara meşru, tek uydurma parça kelimenin
        # içinden kesilen ad: `rafi` dizisi `kaligrafiye`nin içindedir ama kimse onu demedi.
        self._start_model_stub(run=_reply(
            _CONTACTS, {"operation": "add", "name": "rafi", "phone": "05321234567"},
            {"name": "kaligrafiye", "phone": "0532 123 45 67"}))
        self._threaded_turn("kişi ekle kaligrafiye 0532 123 45 67")
        self.assertNotIn("Rafi", self.ctx.profile.data.get("contacts") or {})
        self.assertEqual(self.ctx.profile.data.get("contacts"), dict(self.REGISTERED))

    def test_a_spoken_contact_name_is_still_saved(self):
        # Olumsuzun ölçülebilir olması için kontrol: tam söylenen ad + bitişik rakam dizisi
        # yazmaya geçer; sınır meşru rehber kaydını bozmaz.
        self._start_model_stub(run=_reply(
            _CONTACTS, {"operation": "add", "name": "ayşe", "phone": "05321234567"},
            {"name": "ayşe", "phone": "0532 123 45 67"}))
        self._threaded_turn("kişi ekle ayşe 0532 123 45 67")
        self.assertEqual(self.ctx.profile.data.get("contacts"),
                         {"Ali": "905321234567", "Ayşe": "905321234567"})

    def test_a_spoken_recipient_still_sends_after_the_users_own_approval(self):
        # Genel sınır meşru gönderimi bozmamalı: kullanıcı "ali'ye" dediyse gönderim yürür.
        self._start_model_stub(run=_keyed_run({
            "whatsapp'tan ali'ye selam gönder": (
                _MESSAGE, {"recipient": "ali", "body": "selam"},
                {"recipient": "ali'ye", "body": "selam"})}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ali'ye selam gönder")
        self.assertEqual(entry.understanding.capability_hint, _MESSAGE)
        self.assertEqual(self.ctx._session().pending_msg["to"], "Ali")
        self.send.assert_not_called()
        self._threaded_turn("evet gönder")
        self.assertEqual(self.send.call_args.args, ("Ali", "selam", "905321234567"))


if __name__ == "__main__":
    unittest.main()
