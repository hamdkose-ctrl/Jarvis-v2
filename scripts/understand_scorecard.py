"""Anlam karnesi: gercek cumleler hangi kademede cozuluyor?

Uc kademe: kalip (fast_commands) -> katalog (capability_brain) -> model (capability_llm).

Hicbir eylem calistirilmaz; yalniz anlama olculur.
Kullanim: python -X utf8 scripts/understand_scorecard.py [--with-model]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import capability_brain, fast_commands  # noqa: E402

POSITIVE = [
    "chrome da adres alanina youtube yaz",
    "chrome a youtube yaz",
    "adres cubuguna hava durumu yaz",
    "not defterine merhaba yaz",
    "youtube sonucuna tikla",
    "ilk sonuca bas",
    "ekrandaki haberler yazisina tikla",
    "not defterinde kaydet dugmesine bas",
    "onayliyorum",
    "evet onayla",
    "ekranda ne var",
    "hangi program acik",
    "chromeda ne var",
    "not defterinde hangi dugmeler var",
    "indirilenler klasorunde ne var",
    "masaustundeki dosyalari listele",
    "gece plani dosyasini oku",
    "yarin 09:00da not defterinde kaydet dugmesine bas",
    "5 dakika sonra chromeda enter",
    "otonomi durumu",
    "kuyrukta ne var",
    "chrome da enter",
]

SHORT = [
    ("youtube ac", "pc_open_site"),
    ("maili ac", "pc_open_site"),
    ("muzik ac", "pc_open_site"),
    ("ilk mail ne", "screen_read_text"),
    ("hava durumu", "weather"),
    ("saat kac", "fast_time"),
    ("ekranda ne var", "screen_summary"),
    ("indirilenler ne var", "file_list"),
    ("bunu kaydet sonra bakariz", "?"),
    ("yarin 9 da bunu yap", "?"),
    ("kapat", "?"),
]

NEGATIVE = [
    "dun aksam ne yedigimi hatirlamiyorum",
    "bana bir siir yaz",
    "bugun moralim bozuk",
    "yarinki toplantiyi hatirlat",
]


def layer_of(text):
    if fast_commands.resolve(text):
        return "kalip"
    result = capability_brain.resolve(text)
    if result["status"] == "ok":
        return "katalog"
    if result["status"] == "need":
        return "katalog-soru"
    return "belirsiz"


def model_layer(text):
    from modules import capability_llm
    result = capability_llm.resolve(text)
    return {"ok": "model", "need": "model-soru"}.get(result["status"], "-")


def short_scorecard():
    rows = []
    for text, _expected in SHORT:
        fast = fast_commands.resolve(text)
        if fast:
            rows.append((text, "kalip", fast[0]))
            continue
        result = capability_brain.resolve(text)
        rows.append((text, result["status"], result.get("capability") or "-"))
    return rows


def main(argv):
    with_model = "--with-model" in argv
    rows = []
    for text in POSITIVE:
        row = {"cumle": text, "katman": layer_of(text)}
        if row["katman"] == "belirsiz" and with_model:
            row["model"] = model_layer(text)
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row["katman"]] = counts.get(row["katman"], 0) + 1
    print("\n=== OLUMLU CUMMELELER ===")
    for row in rows:
        extra = " -> model: " + row["model"] if "model" in row else ""
        print(" - [{0:13}] {1}{2}".format(row["katman"], row["cumle"], extra))
    print("\nDagilim:", counts, "toplam", len(rows))

    print("\n=== KISA KOMUTLAR ===")
    expected_map = dict(SHORT)
    wrong = 0
    for text, layer, got in short_scorecard():
        expected = expected_map[text]
        ok = expected in ("?", got)
        wrong += 0 if ok else 1
        print(" - [{0:9}] {1:28} -> {2:18} {3}".format(
            layer, text, got, "ok" if ok else "BEKLENEN " + expected))
    print("\nKisa komut isabeti: {0}/{1}".format(len(SHORT) - wrong, len(SHORT)))

    print("\n=== YANLIS IS YAPMAMASI GEREKENLER ===")
    bad = 0
    for text in NEGATIVE:
        layer = layer_of(text)
        result = capability_brain.resolve(text)
        bad += 1 if layer == "katalog" else 0
        print(" - [{0:13}] {1} -> {2}".format(layer, text, result.get("capability")))
    print("\nYanlis eylem: {0}/{1} (0 olmali)".format(bad, len(NEGATIVE)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
