"""Smart Turn modelini gerçek sesle dene: cümle bitti mi?

Kullanım (mikrofonu olan makinede, Jarvis kapalıyken):

    python -X utf8 scripts/turn_model_probe.py

Betik üç kayıt ister:
  1. TAM cümle      → "Yarın saat üçte buluşalım, sonra kahve içeriz." gibi bitmiş cümle
  2. YARIM cümle    → "Yarın saat üçte ..." deyip sus (cümleyi bitirme)
  3. KISA cevap     → "Evet."

Her kayıttan sonra modelin "konuşmacı bitirdi" olasılığını yazar. Beklenen:
TAM ve KISA yüksek (≥ 0,5), YARIM düşük (< 0,5).

Hiçbir ses diske yazılmaz, hiçbir yere gönderilmez; kayıt yalnız bellekte kalır.
Bu betik Jarvis'in ses hattını değiştirmez; ölçüm yapar.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np          # noqa: E402  (yol kurulduktan sonra)

from modules import voice_smart_turn as turn   # noqa: E402

SECONDS = 5
RATE = 16_000
PROMPTS = [
    ("TAM cümle", "Tam bir cümle söyle: \"Yarın saat üçte buluşalım, sonra kahve içeriz.\""),
    ("YARIM cümle", "Cümleyi YARIM bırak: \"Yarın saat üçte...\" de ve sus."),
    ("KISA cevap", "Kısa cevap ver: \"Evet.\""),
]


def record(seconds: int = SECONDS) -> np.ndarray:
    import sounddevice as sd
    print(f"   {seconds} saniye dinliyorum...", flush=True)
    frames = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="float32")
    sd.wait()
    return frames.reshape(-1)


def main() -> int:
    if not turn.available():
        print("Model bulunamadı: ~/.jarvis/turn_models/smart-turn-v3.0.onnx")
        print("İndirme: https://huggingface.co/pipecat-ai/smart-turn-v3 (BSD-2-Clause)")
        return 2
    print(f"Özellik çıkarımı: {turn.feature_source()}")
    print("Sessizlik tabanı ölçülüyor (3 saniye sus)...")
    silence = record(3)
    base = turn.complete(silence)
    print(f"   sessizlik olasılığı: {base if base is None else round(base, 3)}")
    rows = []
    for label, instruction in PROMPTS:
        print(f"\n{label}: {instruction}")
        audio = record(SECONDS)
        probability = turn.complete(audio)
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        print(f"   ses seviyesi (tepe): {peak:.3f}")
        if probability is None:
            print("   model yanıt vermedi (None) — özellik/çıkarım sorunu")
            continue
        verdict = "BİTTİ" if probability >= 0.5 else "YARIM"
        print(f"   olasılık: {probability:.3f} → {verdict}")
        rows.append((label, probability))
    print("\nÖzet:")
    for label, probability in rows:
        print(f"   {label:12s} {probability:.3f}")
    if len(rows) == 3:
        complete_ok = rows[0][1] >= 0.5 and rows[2][1] >= 0.5
        half_ok = rows[1][1] < 0.5
        print("\nSonuç:", "AYRIŞIYOR (model kullanılabilir)" if complete_ok and half_ok
              else "AYRIŞMIYOR (modeli açma; noktalama kuralı kalsın)")
        return 0 if complete_ok and half_ok else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
