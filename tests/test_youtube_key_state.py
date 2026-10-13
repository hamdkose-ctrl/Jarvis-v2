import unittest
from unittest.mock import MagicMock, patch


class YoutubeKeyStateTests(unittest.TestCase):
    def _http_error(self, reason):
        import requests
        resp = MagicMock()
        resp.json.return_value = {"error": {"message": "x", "errors": [{"reason": reason}]}}
        return requests.HTTPError(response=resp)

    def test_check_key_reports_working_and_errors(self):
        from modules import studymedia as sm
        with patch.object(sm, "_get", return_value={"items": []}):
            self.assertTrue(sm.check_key("AIza" + "x" * 35)["ok"])
        with patch.object(sm, "_get", side_effect=self._http_error("keyInvalid")):
            r = sm.check_key("AIza" + "y" * 35)
            self.assertFalse(r["ok"])
            self.assertEqual(r["msg"], "Anahtar geçersiz")
        with patch.object(sm, "_get", side_effect=self._http_error("accessNotConfigured")):
            self.assertIn("etkin değil", sm.check_key("AIza" + "z" * 35)["msg"])

    def test_state_without_key(self):
        from modules import studymedia as sm
        with patch.object(sm, "get_youtube_key", return_value=""):
            self.assertEqual(sm.state()["key"], False)


if __name__ == "__main__":
    unittest.main()
