"""CI hızlı yol sınıflandırıcısı (T22)."""
import unittest

from scripts.ci_change_class import classify


class ChangeClassTests(unittest.TestCase):
    def test_yalniz_dokuman_hizli_yol(self):
        self.assertEqual(classify(["docs/Jarvis_Yol_Haritasi.md", "README.md"]), "docs")

    def test_kod_dosyasi_tam_dogrulama(self):
        self.assertEqual(classify(["docs/x.md", "modules/hooks.py"]), "code")

    def test_test_dosyasi_tam_dogrulama(self):
        self.assertEqual(classify(["tests/test_gateway_hook.py"]), "code")

    def test_workflow_degisikligi_tam_dogrulama(self):
        self.assertEqual(classify([".github/workflows/testler-windows.yml"]), "code")

    def test_kok_python_dosyasi_tam_dogrulama(self):
        self.assertEqual(classify(["web.py"]), "code")

    def test_bos_liste_guvenli_tarafa_duser(self):
        self.assertEqual(classify([]), "code")

    def test_markdown_olmayan_dokuman_tam_dogrulama(self):
        self.assertEqual(classify(["docs/sema.json"]), "code")


if __name__ == "__main__":
    unittest.main()
