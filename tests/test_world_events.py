"""Dünya olay akışı: ağ yoksa uydurmaz, tekrarları atar, ilgiye göre sıralar."""
import io
import json
import unittest

from modules import world_events


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener(payload):
    def call(url, timeout=None):
        call.url = url
        return FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return call


PAYLOAD = {"articles": [
    {"title": "Ekonomi: faiz kararı", "url": "https://a/1", "domain": "a.com"},
    {"title": "EKONOMİ: faiz kararı", "url": "https://a/2", "domain": "a.com"},
    {"title": "Spor: maç sonucu", "url": "https://b/1", "domain": "b.com"},
]}


class Fetch(unittest.TestCase):
    def test_url_is_public_and_keyless(self):
        url = world_events.build_url()
        self.assertIn("gdeltproject.org", url)
        self.assertIn("format=json", url)

    def test_duplicates_are_removed(self):
        result = world_events.fetch(opener=opener(PAYLOAD))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["items"]), 2)

    def test_offline_is_honest(self):
        def boom(url, timeout=None):
            raise OSError("ağ yok")
        result = world_events.fetch(opener=boom)
        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["items"], [])

    def test_rank_prefers_interests_without_hiding_rest(self):
        result = world_events.fetch(opener=opener(PAYLOAD))
        ranked = world_events.rank(result["items"], ["ekonomi"])
        self.assertIn("Ekonomi", ranked[0]["title"])
        self.assertEqual(len(ranked), 2)

    def test_text_lists_headlines(self):
        result = world_events.fetch(opener=opener(PAYLOAD))
        self.assertIn("Dünya olayları", result["text"])


if __name__ == "__main__":
    unittest.main()
