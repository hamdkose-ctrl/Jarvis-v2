import unittest
from modules import browser_readonly as readonly


class FakeElement:
    def __init__(self, role, name, value="", input_type=""):
        self.role = role
        self.name = name
        self.value = value
        self.input_type = input_type


class FakePage:
    def __init__(self, url, title, elements=()):
        self.url = url
        self.title = title
        self.elements = list(elements)


class BrowserReadonlyTests(unittest.TestCase):
    def test_accessibility_snapshot_redacts_secret_controls_and_keeps_tabs(self):
        pages = [
            FakePage("https://example.test/a", "A", [FakeElement("button", "Ara"), FakeElement("textbox", "Şifre", "secret", "password")]),
            FakePage("https://example.test/b", "B", [FakeElement("link", "Kaynak")]),
        ]
        result = readonly.observe_tabs(pages)
        self.assertEqual([tab["title"] for tab in result["tabs"]], ["A", "B"])
        self.assertEqual(result["tabs"][0]["accessibility"][1]["name"], "Şifre")
        self.assertNotIn("value", result["tabs"][0]["accessibility"][1])

    def test_readonly_contract_rejects_upload_but_allows_download_receipt(self):
        with self.assertRaisesRegex(readonly.ReadonlyBrowserError, "yükleme"):
            readonly.assert_readonly_action({"op": "upload", "path": "private.pdf"})
        receipt = readonly.download_receipt("https://example.test/report.pdf", "report.pdf", 123)
        self.assertEqual(receipt["state"], "observed")
        self.assertEqual(receipt["filename"], "report.pdf")

    def test_2fa_handoff_and_vault_never_return_credential_value(self):
        vault = readonly.CredentialVault(encrypt=lambda value: "enc:" + value, decrypt=lambda value: value[4:])
        vault.store("work", "very-secret")
        handoff = readonly.two_factor_handoff("work", "Kod gerekli")
        self.assertEqual(handoff["state"], "human_required")
        self.assertNotIn("very-secret", str(handoff))
        self.assertNotIn("very-secret", str(vault.model_safe_metadata("work")))

    def test_dialog_observation_is_readonly(self):
        dialog = readonly.observe_dialog({"type": "beforeunload", "message": "Kaydedilsin mi?"})
        self.assertEqual(dialog["state"], "human_required")
        self.assertEqual(dialog["kind"], "beforeunload")


if __name__ == "__main__":
    unittest.main()
