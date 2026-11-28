"""Uyandırma modelleri: kullanıcı klasörüne inen ONNX seti (Faz 1, T18)."""
import io
import tempfile
import unittest
from pathlib import Path

from modules import wakeword_models


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _entries():
    return {
        "melspectrogram": {"model_path": r"C:\pkg\resources\melspectrogram.tflite",
                           "download_url": "https://example.test/melspectrogram.tflite"},
        "embedding": {"model_path": r"C:\pkg\resources\embedding_model.tflite",
                      "download_url": "https://example.test/embedding_model.tflite"},
        "hey_jarvis": {"model_path": r"C:\pkg\resources\hey_jarvis_v0.1.tflite",
                       "download_url": "https://example.test/hey_jarvis_v0.1.tflite"},
    }


class EnsureModelsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "wake_models"
        self.urls = []

    def opener(self, url, timeout=None):
        self.urls.append(url)
        return _Response(b"onnx-bytes")

    def test_missing_models_are_downloaded_into_the_given_folder(self):
        paths = wakeword_models.ensure_models(self.root, self.opener,
                                              validator=lambda p: True, entries=_entries())
        self.assertEqual(sorted(paths), ["embedding", "hey_jarvis", "melspectrogram"])
        self.assertEqual(Path(paths["hey_jarvis"]).name, "hey_jarvis_v0.1.onnx")
        for path in paths.values():
            self.assertEqual(Path(path).read_bytes(), b"onnx-bytes")
        self.assertTrue(all(url.endswith(".onnx") for url in self.urls))

    def test_existing_models_are_not_downloaded_again(self):
        self.root.mkdir(parents=True)
        (self.root / "hey_jarvis_v0.1.onnx").write_bytes(b"eski")
        wakeword_models.ensure_models(self.root, self.opener,
                                      validator=lambda p: True, entries=_entries())
        self.assertNotIn("https://example.test/hey_jarvis_v0.1.onnx", self.urls)
        self.assertEqual((self.root / "hey_jarvis_v0.1.onnx").read_bytes(), b"eski")

    def test_a_broken_model_is_not_kept(self):
        def bozuk(path):
            raise ValueError("onnx yüklenemedi")
        with self.assertRaises(ValueError):
            wakeword_models.ensure_models(self.root, self.opener, validator=bozuk, entries=_entries())
        self.assertFalse((self.root / "hey_jarvis_v0.1.onnx").exists())
        self.assertEqual(list(self.root.glob("*.download")), [])

    def test_a_failed_download_leaves_no_partial_file(self):
        def kopuk(url, timeout=None):
            raise OSError("ağ yok")
        with self.assertRaises(OSError):
            wakeword_models.ensure_models(self.root, kopuk, validator=lambda p: True, entries=_entries())
        self.assertEqual(list(self.root.glob("*")), [])

    def test_default_folder_is_the_writable_user_data_folder(self):
        default = wakeword_models.MODEL_DIR
        self.assertEqual(default.name, "wake_models")
        self.assertNotIn("site-packages", str(default))


if __name__ == "__main__":
    unittest.main()
