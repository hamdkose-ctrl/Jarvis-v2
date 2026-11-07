"""PR #530 altıncı güvenlik turu: bitişik HARF+RAKAM dizisi bölünemez.

Beşinci tur dayanak kıyaslamasını alt dizeden kelime/sayı **token sınırına** taşıdı. Ancak
tokenlaştırıcı `[0-9]+|[^\W\d_]+` harflerle rakamları AYRI token sayıyor, dolayısıyla tek bir
bitişik alfasayısal sözcük parçalanabiliyor: `whatsapp'tan ali123 mesaj at` cümlesinde
`ali123` → `("ali", "123")` oluyor ve modelin uydurduğu `ali` alıntının "bitişik token dizisi"
gibi geçiyor. Bu, `ali` → `kaligrafiye` açığıyla aynı sınıfın yeni varyantıdır: kullanıcı
`ali` demedi, `ali123` dedi. Rehberde kayıtlı+tekil `Ali` varsa yanlış kişiye gerçek gönderim
riski yeniden doğuyor.

Bu dosya açığı önce RED olarak ölçer, sonra kapatılacak kuralı ister: **yan yana gelen harf
ve rakamlar TEK alfasayısal tokendır**; onun içinden isim/alıcı/gövde kesilemez. Gerçek kelime
sınırları (boşluk/noktalama/kesme işareti) ve telefondaki TAM rakam dizisi eşitliği korunur.
Yeni fiil/isim/eş anlamlı listesi veya doğal dil regex havuzu yoktur; denetim biçimseldir.

Testler iki düzeyde: zarf düzeyi (`_ZarfHarness._ask` → gerçek `_build` + dayanak denetimi) ve
**üretim zinciri** düzeyi (`prepare → handoff → EngineContext.handle → messaging`; yanıt metni
değil, `send_whatsapp` çağrısının hiç başlamaması ve profil/oturum durumu ölçülür). Zarflar
BAĞLANTI kanıtıdır, modelin doğal dili anladığının kanıtı değildir (§16).
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
    CONFIRM_QUESTION, _envelope, _reply, _utterance_of,
)

_MESSAGE = b3._MESSAGE
_CONTACTS = b3._CONTACTS


def _keyed_run(rows):
    """Cümleye göre zarf döndüren sahte sağlayıcı (ağ yok)."""
    def run(owner, payload, send, *, route, exclude_providers):
        reply = rows.get(_utterance_of(payload))
        return b3._chat_envelope() if reply is None else _envelope(*reply)
    return run


class LetterDigitRunEnvelopeTests(b3._ZarfHarness):
    """§2 negatifleri: tek bitişik alfasayısal sözcükten isim/gövde kesilemez."""

    def test_a_recipient_cut_from_a_letter_digit_word_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan ali123 mesaj at",
            _envelope(_MESSAGE, {"recipient": "ali", "body": "mesaj"},
                      {"recipient": "ali123", "body": "mesaj"})))

    def test_a_turkish_named_recipient_cut_from_digits_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "whatsapp'tan ayşe42 mesaj at",
            _envelope(_MESSAGE, {"recipient": "ayşe", "body": "mesaj"},
                      {"recipient": "ayşe42", "body": "mesaj"})))

    def test_a_body_cut_from_a_letter_digit_word_is_not_grounded(self):
        # Boş alıcı oturumun kendi sorusudur; burada tek ihlal gövdenin kesilmiş olmasıdır.
        self.assertIsNone(self._ask(
            "whatsapp'tan gel123iyorum yaz",
            _envelope(_MESSAGE, {"recipient": "", "body": "gel"},
                      {"body": "gel123iyorum"})))

    def test_a_contact_name_cut_from_a_letter_digit_word_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "kişi ekle rafi123 0532 123 45 67",
            _envelope(_CONTACTS, {"operation": "add", "name": "rafi", "phone": "05321234567"},
                      {"name": "rafi123", "phone": "0532 123 45 67"})))

    def test_a_contact_name_cut_before_its_digits_is_not_grounded(self):
        self.assertIsNone(self._ask(
            "kişi ekle ahmet42 0532 123 45 67",
            _envelope(_CONTACTS, {"operation": "add", "name": "ahmet", "phone": "05321234567"},
                      {"name": "ahmet42", "phone": "0532 123 45 67"})))

    def test_the_whole_spoken_letter_digit_word_is_still_grounded(self):
        # Yasak olan kesimdir; kullanıcının söylediği TAM alfasayısal sözcük meşrudur (gövde
        # biçimce serbesttir, alıcıyı Core biçim hükmü süzer).
        proposal = self._ask("whatsapp'tan ahmet'e ali123 yaz",
                             _envelope(_MESSAGE, {"recipient": "ahmet", "body": "ali123"},
                                       {"recipient": "ahmet'e", "body": "ali123"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.actions[0].capability_id, _MESSAGE)

    def test_the_digits_of_a_spoken_number_still_ground_as_one_whole_run(self):
        # Sayısal yuvanın tam dizi eşitliği bu turda da yaşamalı: ayraç farkı serbest, kesim yok.
        proposal = self._ask("kişi ekle ahmet 0532 123 45 67",
                             _envelope(_CONTACTS, {"operation": "add", "name": "ahmet",
                                                   "phone": "05321234567"},
                                       {"name": "ahmet", "phone": "0532 123 45 67"}))
        self.assertIsNotNone(proposal)
        self.assertEqual(dict(proposal.actions[0].arguments)["phone"], "05321234567")

    def test_the_repaired_boundaries_do_not_let_the_old_substring_attacks_back(self):
        # §4 geri gelme denetimi: kelime içi kesim ve kelime yapıştırma yine reddedilir.
        for text, arguments, sources in (
            ("whatsapp'tan kaligrafiye mesaj at", {"recipient": "ali", "body": "mesaj"},
             {"recipient": "kaligrafiye", "body": "mesaj"}),
            ("whatsapp'tan malik'e mesaj at", {"recipient": "ali", "body": "mesaj"},
             {"recipient": "malik'e", "body": "mesaj"}),
            ("whatsapp'tan salih'e mesaj at", {"recipient": "alih", "body": "mesaj"},
             {"recipient": "salih'e", "body": "mesaj"}),
            ("whatsapp'tan rahmetli'ye mesaj at", {"recipient": "ahmet", "body": "mesaj"},
             {"recipient": "rahmetli'ye", "body": "mesaj"}),
            ("whatsapp'tan demir ay'a mesaj at", {"recipient": "nay", "body": "mesaj"},
             {"recipient": "demir ay'a", "body": "mesaj"}),
            ("whatsapp'tan ahmet'e geliyorum yaz", {"recipient": "ahmet", "body": "gel"},
             {"recipient": "ahmet'e", "body": "geliyorum"}),
            ("kişi ekle ahmet 10532123456789",
             {"operation": "add", "name": "ahmet", "phone": "05321234567"},
             {"name": "ahmet", "phone": "10532123456789"}),
        ):
            with self.subTest(text=text):
                self.assertIsNone(self._ask(text, _envelope(
                    _CONTACTS if text.startswith("kişi") else _MESSAGE, arguments, sources)))


class LetterDigitRunSideEffectTests(b3._MessageTurnHarness):
    """§2 üretim zinciri: kesilmiş alıcı Core'a/oturuma/yürütücüye ulaşmamalı."""

    # Kesilen ad defterde kayıtlı ve tekil: açık olsaydı GERÇEKTEN Ali'ye gönderirdi.
    REGISTERED = {"Ali": "905321234567"}

    def _assert_no_send_side_effect(self, out, entry):
        self.assertNotEqual(entry.understanding.capability_hint, _MESSAGE)
        self.assertIsNone(self.ctx._session().pending_msg)
        self.assertNotIn(CONFIRM_QUESTION, str(out))
        self.send.assert_not_called()

    def test_a_letter_digit_recipient_proposal_is_rejected_wholly(self):
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "selam"},
            {"recipient": "ali123", "body": "selam"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ali123 selam gönder")
        self._assert_no_send_side_effect(out, entry)

    def test_the_registered_namesake_never_receives_the_message(self):
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "selam"},
            {"recipient": "ali123", "body": "selam"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ali123 selam gönder")
        self._assert_no_send_side_effect(out, entry)
        self._threaded_turn("evet gönder")
        self.send.assert_not_called()

    def test_approval_off_does_not_open_the_gate_for_a_letter_digit_recipient(self):
        # `approve_sensitive=False` yalnız kullanıcının kendi onay sorusunu kaldırır.
        self.ctx.load_approve.return_value = False
        self._start_model_stub(run=_reply(
            _MESSAGE, {"recipient": "ali", "body": "selam"},
            {"recipient": "ali123", "body": "selam"}))
        entry, out, _handle, _ = self._threaded_turn("whatsapp'tan ali123 selam gönder")
        self._assert_no_send_side_effect(out, entry)

    def test_a_letter_digit_contact_name_is_never_saved(self):
        self._start_model_stub(run=_reply(
            _CONTACTS, {"operation": "add", "name": "rafi", "phone": "05321234567"},
            {"name": "rafi123", "phone": "0532 123 45 67"}))
        self._threaded_turn("kişi ekle rafi123 0532 123 45 67")
        self.assertNotIn("Rafi", self.ctx.profile.data.get("contacts") or {})
        self.assertEqual(self.ctx.profile.data.get("contacts"), dict(self.REGISTERED))

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
