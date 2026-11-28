import unittest

from modules import awareness_watch


class TakvimTekrarEtmez(unittest.TestCase):
    """Aynı toplantı her tikte değil, olay başına en fazla iki kez söylenir."""

    SESSIZ_YOK = (0, 0)

    def _tik(self, minutes, kimlik, seen):
        state = {"next_event_minutes": minutes}
        if kimlik:
            state["next_event_id"] = kimlik
        adaylar = awareness_watch.candidates(state, seen=seen, hour=12, quiet=self.SESSIZ_YOK)
        awareness_watch.mark_seen(adaylar, seen)
        return adaylar

    def test_ayni_olay_uzak_dilimde_tek_kez(self):
        seen: set[str] = set()
        self.assertEqual(len(self._tik(30, "toplanti@10:00", seen)), 1)
        self.assertEqual(self._tik(28, "toplanti@10:00", seen), [])
        self.assertEqual(self._tik(12, "toplanti@10:00", seen), [])

    def test_yakin_dilimde_bir_kez_daha(self):
        seen: set[str] = set()
        self._tik(30, "toplanti@10:00", seen)
        self.assertEqual(len(self._tik(10, "toplanti@10:00", seen)), 1)
        self.assertEqual(self._tik(6, "toplanti@10:00", seen), [])

    def test_baska_olay_yeniden_bildirilir(self):
        seen: set[str] = set()
        self._tik(25, "a@10:00", seen)
        self.assertEqual(len(self._tik(25, "b@11:00", seen)), 1)

    def test_kimlik_yoksa_dakika_parmak_izi_korunur(self):
        seen: set[str] = set()
        self.assertEqual(len(self._tik(30, None, seen)), 1)
        self.assertEqual(self._tik(30, None, seen), [])


if __name__ == '__main__':
    unittest.main()
