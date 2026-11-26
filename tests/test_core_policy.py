"""Core güvenlik şeması: serbest / onay / yasak tek karar noktası."""
import unittest

from modules import core_policy


class Verdicts(unittest.TestCase):
    def test_read_is_free(self):
        self.assertEqual(core_policy.decide({"kind": "read", "label": "pencere"})["verdict"], "free")

    def test_delete_asks(self):
        self.assertEqual(core_policy.decide({"kind": "click", "label": "Sil"})["verdict"], "ask")

    def test_payment_asks(self):
        self.assertEqual(core_policy.decide({"kind": "click", "label": "Ödeme yap"})["verdict"], "ask")

    def test_password_is_forbidden(self):
        self.assertEqual(core_policy.decide({"kind": "type", "label": "şifre alanı"})["verdict"], "forbid")

    def test_banking_is_forbidden(self):
        self.assertEqual(core_policy.decide({"kind": "open", "label": "banka hesabı"})["verdict"], "forbid")

    def test_write_outside_sandbox_is_forbidden(self):
        self.assertEqual(core_policy.decide({"kind": "save", "path": "C:/Windows/a.txt"})["verdict"], "forbid")

    def test_write_inside_sandbox_is_free(self):
        path = core_policy.SANDBOX / "test.txt"
        self.assertEqual(core_policy.decide({"kind": "save", "path": str(path)})["verdict"], "free")
        self.assertTrue(core_policy.allow_write(str(path)))


if __name__ == "__main__":
    unittest.main()
