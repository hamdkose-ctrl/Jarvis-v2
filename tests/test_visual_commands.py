"""visual_commands: tür tespiti (kalıp + model fallback), istem kurma ve
üretim+kayıt orkestrasyonu. Hiçbir test gerçek ağa/modele çıkmaz."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import visual_commands as vc
from modules import image_gen


class DetectTypeByKeywordTests(unittest.TestCase):
    def test_mindmap_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("bana bir zihin haritası çizer misin"), "mindmap")

    def test_flowchart_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("bu sürecin akış şemasını istiyorum"), "flowchart")

    def test_timeline_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("olayların zaman çizelgesini göster"), "timeline")

    def test_infographic_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("bir infografik hazırla"), "infographic")

    def test_handwritten_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("el yazısıyla not çiz"), "handwritten")

    def test_blueprint_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("bunun teknik çizimini yap"), "blueprint")

    def test_generic_visualize_detected(self):
        self.assertEqual(vc.detect_type_by_keyword("süreç özeti görseli istiyorum"), "visualize")

    def test_unrelated_sentence_returns_none(self):
        self.assertIsNone(vc.detect_type_by_keyword("yarın hava nasıl olacak"))

    def test_case_and_turkish_chars_ignored(self):
        self.assertEqual(vc.detect_type_by_keyword("ZİHİN HARİTASI LÜTFEN"), "mindmap")


class DetectTypeViaModelTests(unittest.TestCase):
    def test_model_answer_mapped_to_type(self):
        result = vc.detect_type_via_model("şunu bana resimle anlat", _ask=lambda *a, **k: "flowchart")
        self.assertEqual(result, "flowchart")

    def test_model_says_none_returns_none(self):
        result = vc.detect_type_via_model("bugün ne yapalım", _ask=lambda *a, **k: "hicbiri")
        self.assertIsNone(result)

    def test_model_error_returns_none_not_raises(self):
        def boom(*a, **k):
            raise RuntimeError("kota hatası")
        self.assertIsNone(vc.detect_type_via_model("x", _ask=boom))


class DetectTypeHybridTests(unittest.TestCase):
    def test_keyword_match_skips_model_call(self):
        calls = []
        def ask(*a, **k):
            calls.append(1)
            return "mindmap"
        result = vc.detect_type("zihin haritası istiyorum", _ask=ask)
        self.assertEqual(result, "mindmap")
        self.assertEqual(calls, [])  # model hiç çağrılmadı

    def test_no_keyword_match_falls_back_to_model(self):
        result = vc.detect_type("bunu resimle anlatır mısın", _ask=lambda *a, **k: "blueprint")
        self.assertEqual(result, "blueprint")


class BuildPromptTests(unittest.TestCase):
    def test_includes_content_and_style_hint(self):
        prompt = vc.build_prompt("mindmap", "A, B, C adımları")
        self.assertIn("A, B, C adımları", prompt)
        self.assertIn("mind map", prompt.lower())

    def test_empty_content_rejected(self):
        with self.assertRaises(ValueError):
            vc.build_prompt("mindmap", "   ")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            vc.build_prompt("nope", "x")


class CreateVisualTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.files_dir = Path(self._tmp.name) / "Jarvis Dosyaları"
        self._patch_files = patch("modules.nxapi.FILES_DIR", self.files_dir)
        self._patch_files.start()
        data_dir = Path(self._tmp.name) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)  # gerçek uygulamada config.py bunu açılışta oluşturur
        self._patch_keys = patch("config.DATA_DIR", data_dir)
        self._patch_keys.start()
        image_gen.set_user_cloudflare("hamdi", "acc1", "tok1")

    def tearDown(self):
        self._patch_files.stop()
        self._patch_keys.stop()
        self._tmp.cleanup()

    def _fake_generate(self, png_bytes=b"\x89PNGfake"):
        return patch("modules.image_gen.generate_image", return_value=png_bytes)

    def test_creates_png_under_gorseller_subfolder(self):
        with self._fake_generate():
            result = vc.create_visual("zihin haritası istiyorum", "A, B, C", slug="hamdi")
        self.assertEqual(result.kind, "mindmap")
        p = Path(result.path)
        self.assertTrue(p.exists())
        self.assertEqual(p.read_bytes(), b"\x89PNGfake")
        self.assertEqual(p.parent, self.files_dir / "Görseller")

    def test_explicit_kind_skips_detection(self):
        with self._fake_generate():
            result = vc.create_visual("bu metin tür içermiyor", "x, y, z", slug="hamdi", kind="timeline")
        self.assertEqual(result.kind, "timeline")

    def test_no_detectable_type_raises_without_network_call(self):
        with patch("modules.image_gen.generate_image") as gen:
            with self.assertRaises(ValueError):
                vc.create_visual("yarın hava nasıl olacak", "x", slug="hamdi", _ask=lambda *a, **k: "hicbiri")
            gen.assert_not_called()

    def test_existing_visual_filename_can_never_be_overwritten(self):
        destination = self.files_dir / 'Görseller' / 'occupied.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b'foreign content')
        with self._fake_generate(), patch.object(vc, '_destination',
                                                 return_value=destination):
            with self.assertRaises(FileExistsError):
                vc.create_visual('görselleştir', 'x', slug='hamdi',
                                 kind='visualize')
        self.assertEqual(destination.read_bytes(), b'foreign content')
        self.assertFalse(list(destination.parent.glob('.jarvis-visual-*')))

    def test_visual_publish_failure_leaves_no_partial_public_file(self):
        destination = self.files_dir / 'Görseller' / 'fresh.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._fake_generate(), patch.object(vc, '_destination',
                                                 return_value=destination), \
             patch.object(vc.os, 'link', side_effect=OSError('no link')):
            with self.assertRaises(OSError):
                vc.create_visual('görselleştir', 'x', slug='hamdi',
                                 kind='visualize')
        self.assertFalse(destination.exists())
        self.assertFalse(list(destination.parent.glob('.jarvis-visual-*')))

    def test_filename_never_collides(self):
        with self._fake_generate():
            r1 = vc.create_visual("zihin haritası", "x", slug="hamdi")
            r2 = vc.create_visual("zihin haritası", "x", slug="hamdi")
        self.assertNotEqual(r1.path, r2.path)
        self.assertTrue(Path(r1.path).exists())
        self.assertTrue(Path(r2.path).exists())


if __name__ == "__main__":
    unittest.main()
