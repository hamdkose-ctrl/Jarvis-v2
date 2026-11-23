"""Smart Turn modeli (yerel, açık) — özellik çıkarımı ve karar sözleşmesi.

Model: pipecat-ai/smart-turn-v3.0.onnx (BSD-2-Clause, 8,7 MB). Bu modül modeli
KURMAZ; kurulu modeli yükler ve "konuşmacı bitirdi mi" olasılığı verir.

Kilitlenen davranış:
* Model yoksa `complete()` → None (hat noktalama kuralına düşer, kilitlenmez).
* Özellik çıkarımı: referans (transformers Whisper) varsa o, yoksa numpy sürümü.
* Girdi tam 8 saniye: kısa ses **sağa yaslanır** (son saniyeler pencerenin sonunda).
* Model hatası kararı kilitlemez; tanılama kaydı bırakır.
* Sessizlik/boş ses çökme üretmez.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from modules import voice_smart_turn as turn


class Features(unittest.TestCase):
    def test_shape_and_range(self):
        audio = np.zeros(16_000, dtype=np.float32)
        features = turn.log_mel(audio)
        self.assertEqual(features.shape, (turn.N_MELS, turn.FRAMES))
        self.assertTrue(np.isfinite(features).all())
        self.assertGreaterEqual(float(features.min()), -2.0)   # sessizlikte taban -1,5
        self.assertLessEqual(float(features.max()), 4.0)

    def test_short_audio_is_right_aligned(self):
        """Kısa ses pencerenin SONUNA yaslanır: karar anı sağda."""
        audio = np.zeros(16_000, dtype=np.float32)
        audio[-800:] = 0.5 * np.sin(np.linspace(0, 200 * np.pi, 800))
        features = turn.log_mel(audio)
        energy = features.mean(axis=0)
        self.assertGreater(energy[-40:].mean(), energy[:40].mean())

    def test_long_audio_keeps_last_seconds(self):
        audio = np.zeros(turn.AUDIO_SAMPLES * 2, dtype=np.float32)
        features = turn.log_mel(audio)
        self.assertEqual(features.shape[1], turn.FRAMES)

    def test_empty_and_none_do_not_crash(self):
        self.assertEqual(turn.log_mel(None).shape, (turn.N_MELS, turn.FRAMES))
        self.assertEqual(turn.log_mel([]).shape, (turn.N_MELS, turn.FRAMES))

    def test_deterministic(self):
        audio = np.random.default_rng(7).normal(0, 0.1, 16_000).astype(np.float32)
        first = turn.log_mel(audio)
        second = turn.log_mel(audio)
        self.assertTrue(np.array_equal(first, second))

    def test_mel_filterbank_is_stable(self):
        bank = turn.mel_filterbank()
        self.assertEqual(bank.shape, (turn.N_MELS, turn.N_FFT // 2 + 1))
        self.assertGreater((bank > 0).sum(), turn.N_MELS)


class Decision(unittest.TestCase):
    def test_missing_model_returns_none(self):
        with patch.object(turn, "available", return_value=False):
            self.assertIsNone(turn.complete(np.zeros(1600, dtype=np.float32)))
            self.assertIsNone(turn.verdict(np.zeros(1600, dtype=np.float32)))

    def test_threshold_rule(self):
        self.assertTrue(turn.verdict.__doc__)   # sözleşme belgeli
        class _Session:
            def run(self, _outputs, _feed):
                return [np.array([[0.6]], dtype=np.float32)]
            def get_inputs(self):
                class _Input:
                    name = "input_features"
                return [_Input()]
        with patch.object(turn, "available", return_value=True), \
             patch.object(turn, "_session", return_value=_Session()), \
             patch.object(turn, "reference_features", return_value=None):
            probability = turn.complete(np.zeros(1600, dtype=np.float32), prefer_reference=False)
            self.assertAlmostEqual(probability, 1 / (1 + np.exp(-0.6)), places=5)
            self.assertTrue(turn.verdict(np.zeros(1600, dtype=np.float32), prefer_reference=False))

    def test_model_error_is_recorded_and_null(self):
        class _Broken:
            def run(self, *_a, **_k):
                raise RuntimeError("bozuk")
            def get_inputs(self):
                class _Input:
                    name = "x"
                return [_Input()]
        with patch.object(turn, "available", return_value=True), \
             patch.object(turn, "_session", return_value=_Broken()), \
             patch.object(turn, "reference_features", return_value=None), \
             patch.object(turn, "_record_failure") as record:
            self.assertIsNone(turn.complete(np.zeros(1600, dtype=np.float32), prefer_reference=False))
        record.assert_called()

    def test_available_requires_big_file(self):
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat") as stat:
            stat.return_value.st_size = 10
            self.assertFalse(turn.available("/tmp"))
            stat.return_value.st_size = 5_000_000
            self.assertTrue(turn.available("/tmp"))

    def test_feature_source_names_are_known(self):
        self.assertIn(turn.feature_source(), ("reference", "numpy"))


if __name__ == "__main__":
    unittest.main()
