"""Sağlayıcı eşzamanlılığı: hesap başına 2 slot, arka plan 1 slotu ayırır.

Madde 1 (paralel iş) için kanıt: darboğaz sağlayıcı katmanı DEĞİL. Bu test
hiçbir ağ çağrısı yapmaz; yalnız kira/claim defterini sınar.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import router_quota


def _istek(call_id='c1', work_class='foreground'):
    return SimpleNamespace(owner='hamdi', call_id=call_id, work_class=work_class)


def _spec(provider='gemini'):
    return SimpleNamespace(provider=provider, connection_id=None,
                           connection_revision=None)


class ProviderSlotConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self._gecici = tempfile.TemporaryDirectory()
        self.klasor = self._gecici.name
        # Hesap parmak izi gerçek anahtarı okumasın: sabit kapsam.
        self._yama = patch.object(router_quota, 'account_scope', lambda r, s: 'key:sabit')
        self._yama.start()

    def tearDown(self):
        self._yama.stop()
        self._gecici.cleanup()

    def test_two_foreground_calls_share_one_account(self):
        c1 = router_quota.admission(_istek('a1'), _spec(), directory=self.klasor)
        c2 = router_quota.admission(_istek('a2'), _spec(), directory=self.klasor)
        with c1, c2:
            pass

    def test_third_call_is_refused_with_capacity_reason(self):
        with router_quota.admission(_istek('b1'), _spec(), directory=self.klasor), \
             router_quota.admission(_istek('b2'), _spec(), directory=self.klasor):
            with self.assertRaises(router_quota.ReservationUnavailable) as ctx:
                with router_quota.admission(_istek('b3'), _spec(), directory=self.klasor):
                    pass
        self.assertEqual(ctx.exception.reason_code, 'PROVIDER_CAPACITY_BUSY')

    def test_background_never_takes_the_reserved_foreground_slot(self):
        # Slot 0 ön plan tarafından tutulurken arka plan slot 1'e düşer.
        with router_quota.admission(_istek('c1'), _spec(), directory=self.klasor):
            with router_quota.admission(_istek('c2', 'background'), _spec(), directory=self.klasor):
                pass
        # İki arka plan aynı anda: yalnız 1 slot var.
        with router_quota.admission(_istek('d1', 'background'), _spec(), directory=self.klasor):
            with self.assertRaises(router_quota.ReservationUnavailable):
                with router_quota.admission(_istek('d2', 'background'), _spec(), directory=self.klasor):
                    pass

    def test_local_provider_has_exactly_one_slot(self):
        with patch.object(router_quota, 'account_scope', lambda r, s: 'local:loopback'):
            with router_quota.admission(_istek('e1'), _spec('ollama'), directory=self.klasor):
                with self.assertRaises(router_quota.ReservationUnavailable):
                    with router_quota.admission(_istek('e2'), _spec('ollama'), directory=self.klasor):
                        pass

    def test_released_slot_is_reusable(self):
        with router_quota.admission(_istek('f1'), _spec(), directory=self.klasor):
            pass
        with router_quota.admission(_istek('f2'), _spec(), directory=self.klasor):
            pass

    def test_capacity_belongs_to_the_account_not_the_owner(self):
        # Ölçüldü: slotlar sahip başına değil HESAP kapsamında. İki ayrı sahip
        # aynı anahtarı kullanıyorsa üçüncü çağrı yine kapasiteye takılır.
        diger = SimpleNamespace(owner='baska', call_id='g3', work_class='foreground')
        with router_quota.admission(_istek('g1'), _spec(), directory=self.klasor), \
             router_quota.admission(_istek('g2'), _spec(), directory=self.klasor):
            with self.assertRaises(router_quota.ReservationUnavailable):
                with router_quota.admission(diger, _spec(), directory=self.klasor):
                    pass


if __name__ == '__main__':
    unittest.main()
