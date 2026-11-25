"""Anlam karnesi: gerçekçi cümleler hangi kademede çözülüyor?

Üç kademe: kalıp (fast_commands) → katalog (capability_brain) → model (capability_llm, isteğe bağlı).

Ölçüm: her cümle için kademe, yetenek ve alanlar; ayrıca **yanlış iş yapmama**
(negatif) cümleleri. Hiçbir eylem çalıştırılmaz — yalnız anlama ölçülür.

Kullanım: python -X utf8 scripts/understand_scorecard.py [--with-model]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import capability_brain, fast_commands  # noqa: E402

POSITIVE = [
    "chrome da adres alanına youtube yaz",
    "chrome a youtube yaz",
    "adres çubuğuna hava durumu yaz",
    "not defterine merhaba yaz",
    "youtube sonucuna tıkla",
    "ilk sonuca bas",
    "ekrandaki haberler yazısına tıkla",
    "not defterinde kaydet düğmesine bas",
    "chrome'da kapat düğmesine bas",
    "onaylıyorum",
    "evet onayla",
    "ekranda ne var",
    "hangi program açık",
    "chrome'da ne var",
    "not defterinde hangi düğmeler var",
    "indirilenler klasöründe ne var",
    "masaüstündeki dosyaları listele",
    "gece planı dosyasını oku",
    "yarın 09:00'da not defterinde kaydet düğmesine bas",
    "5 dakika sonra chrome da enter",
    "otonomi durumu",
    "kuyrukta ne var",
    "youtube a git",
    "chrome da enter",
]

NEGATIVE = [
    "dün akşam ne yediğimi hatırlamıyorum",
    "bana bir şiir yaz",
    "hava nasıl",
    "bugün moralim bozuk",
    "yarınki toplantıyı hatırlat",
]


def layer_of(text: str) -> str:
    if fast_commands.resolve(text):
        return "kalıp"
    result = capability_brain.resolve(text)
    if result["status"] == "ok":
        return "katalog"
    if result["status"] == "need":
        return "katalog-soru"
    return "belirsiz"


def model_layer(text: str) -> str:
    from modules import capability_llm
    result = capability_llm.resolve(text)
    return {"ok": "model", "need": "model-soru"}.get(result["status"], "-")


def main(argv: list[str]) -> int:
    with_model = "--with-model" in argv
    rows = []
    for text in POSITIVE:
        row = {"cumle": text, "katman": layer_of(text)}
        if row["katman"] == "belirsiz" and with_model:
            row["model"] = model_layer(text)
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["katman"]] = counts.get(row["katman"], 0) + 1
    print("\n=== OLUMLU CÜMLELER ===")
    for row in rows:
        extra = f" → model: {row['model']}" if "model" in row else ""
        print(f" · [{row['katman']:13}] {row['cumle']}{extra}")
    print("\nDağılım:", counts, f"toplam {len(rows)}")
    print("\n=== YANLIŞ İŞ YAPMAMASI GEREKENLER ===")
    bad = 0
    for text in NEGATIVE:
        layer = layer_of(text)
        result = capability_brain.resolve(text)
        acts = layer in ("katalog",)
        bad += 1 if acts else 0
        print(f" · [{layer:13}] {text} → {result.get('capability')}")
    print(f"\nYanlış eylem: {bad}/{len(NEGATIVE)} (0 olmalı)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
