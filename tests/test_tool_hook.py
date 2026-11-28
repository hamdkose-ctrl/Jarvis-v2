"""Araç olayı canonical hook hattından geçiyor mu (Faz 2, T20)."""
import unittest

from modules import hooks, permission_gate


class ToolHookTests(unittest.TestCase):
    def setUp(self):
        self.olaylar = []
        hooks.clear()
        hooks.register("tool", self.olaylar.append)
        self.addCleanup(hooks.clear)

    def test_izin_karari_arac_olayi_yayinliyor(self):
        permission_gate.decide({'class': 'read', 'target': 'C:/gizli/yol.txt', 'via': 'file'})
        self.assertEqual(len(self.olaylar), 1)
        yuk = self.olaylar[0]["payload"]
        self.assertEqual(yuk['class'], 'read')
        self.assertEqual(yuk['via'], 'file')
        self.assertEqual(yuk['decision'], 'allow')
        self.assertNotIn('target', yuk)

    def test_sahipsiz_olay_tek_kez_teslim_ediliyor(self):
        hooks.emit('tool', {'x': 1})
        self.assertEqual(len(self.olaylar), 1)

    def test_bozuk_eylemde_de_olay_dusuyor(self):
        sonuc = permission_gate.decide({"class": "bilinmeyen", "target": "x", "via": "file"})
        self.assertEqual(sonuc['decision'], 'ask')
        self.assertEqual(self.olaylar[0]["payload"]["decision"], "ask")

    def test_gozlemci_hatasi_karari_degistirmiyor(self):
        def patla(event):
            raise RuntimeError("gozlemci bozuk")
        hooks.register("tool", patla)
        sonuc = permission_gate.decide({'class': 'read', 'target': 'x', 'via': 'file'})
        self.assertEqual(sonuc['decision'], 'allow')


if __name__ == "__main__":
    unittest.main()
