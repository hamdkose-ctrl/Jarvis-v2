"""Canlı kabul betiği: ölçülemeyeni "skip" der, uydurma kabul yok."""
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

_YOL = Path(__file__).resolve().parent.parent / "scripts" / "canli_kabul.py"
_SPEC = importlib.util.spec_from_file_location("canli_kabul", _YOL)
canli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(canli)


class Gmail(unittest.TestCase):
    def test_hesap_bagli_degilse_skip(self):
        with patch("modules.google_api.connected", return_value=False):
            self.assertEqual(canli.kontrol_gmail()["durum"], "skip")

    def test_sayi_okunursa_pass(self):
        with patch("modules.google_api.connected", return_value=True), \
             patch("modules.google_api.unread_count", return_value=3):
            sonuc = canli.kontrol_gmail()
        self.assertEqual(sonuc["durum"], "pass")
        self.assertIn("3", sonuc["kanit"])

    def test_sayi_degilse_fail(self):
        with patch("modules.google_api.connected", return_value=True), \
             patch("modules.google_api.unread_count", return_value="3"):
            self.assertEqual(canli.kontrol_gmail()["durum"], "fail")


class Cdp(unittest.TestCase):
    def test_port_kapaliysa_skip_ve_nasil_acilacagi(self):
        with patch("urllib.request.urlopen", side_effect=OSError("kapalı")):
            sonuc = canli.kontrol_cdp()
        self.assertEqual(sonuc["durum"], "skip")
        self.assertIn("--remote-debugging-port", sonuc["kanit"])


class Rapor(unittest.TestCase):
    def test_json_ciktisi_liste(self):
        sahte = [canli._sonuc("Gmail", "pass", "okunmamış: 3")]
        with patch.object(canli, "topla", lambda: sahte):
            akis = io.StringIO()
            with redirect_stdout(akis):
                canli.main(["--json"])
        veri = json.loads(akis.getvalue())
        self.assertEqual(veri[0]["durum"], "pass")

    def test_duz_metin_durum_kelimelerini_icerir(self):
        metin = canli.rapor([canli._sonuc("Gmail", "skip", "bağlı değil")])
        self.assertIn("skip", metin)


class Drive(unittest.TestCase):
    def test_izin_yoksa_skip_ve_nasil_verilecegi(self):
        with patch("modules.drive_readonly.services",
                   side_effect=PermissionError("jeton yok")):
            sonuc = canli.kontrol_drive()
        self.assertEqual(sonuc["durum"], "skip")
        self.assertIn("izin ver", sonuc["kanit"])

    def test_baska_hata_fail(self):
        with patch("modules.drive_readonly.services", side_effect=RuntimeError("bozuk")):
            self.assertEqual(canli.kontrol_drive()["durum"], "fail")


if __name__ == '__main__':
    unittest.main()
