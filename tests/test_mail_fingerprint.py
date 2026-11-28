import unittest

from modules import awareness_watch


class MailParmakIzi(unittest.TestCase):
    """Sayı sabit kalsa da yeni mail bildirilmeli (canlı kusur sınıfı)."""

    SESSIZ_YOK = (0, 0)

    def _adaylar(self, state, seen):
        return awareness_watch.candidates(state, seen=seen, hour=12,
                                          quiet=self.SESSIZ_YOK)

    def test_ayni_sayi_farkli_kimlik_yeni_bildirim(self):
        seen: set[str] = set()
        ilk = self._adaylar({"unread_mail": 67, "mail_head": "m1"}, seen)
        awareness_watch.mark_seen(ilk, seen)
        ikinci = self._adaylar({"unread_mail": 67, "mail_head": "m2"}, seen)
        self.assertEqual(len(ikinci), 1)
        self.assertEqual(ikinci[0]["kind"], "mail")

    def test_ayni_kimlik_tekrar_bildirilmez(self):
        seen: set[str] = set()
        ilk = self._adaylar({"unread_mail": 67, "mail_head": "m1"}, seen)
        awareness_watch.mark_seen(ilk, seen)
        self.assertEqual(self._adaylar({"unread_mail": 67, "mail_head": "m1"}, seen), [])

    def test_kimlik_yoksa_sayi_parmak_izi_korunur(self):
        seen: set[str] = set()
        ilk = self._adaylar({"unread_mail": 3}, seen)
        awareness_watch.mark_seen(ilk, seen)
        self.assertEqual(self._adaylar({"unread_mail": 3}, seen), [])
        self.assertEqual(len(self._adaylar({"unread_mail": 4}, seen)), 1)


if __name__ == '__main__':
    unittest.main()
