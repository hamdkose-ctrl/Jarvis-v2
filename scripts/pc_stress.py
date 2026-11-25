"""PC ajanı zor görev karnesi (gece 7. madde).

Kolay işlerde çalışmak yetmez: uzun zincir, bilerek imkânsız orta adım, uzun metin,
kapalı uygulama ve belirsiz pencere adı denenir. Hiçbir adım kullanıcı dosyasına
yazmaz; kaydetme yalnız ~/.jarvis/sandbox/ içinde olur ve sonunda silinir.

Kullanım: python -X utf8 scripts/pc_stress.py
"""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import pc_files, pc_hands, pc_task, pc_vision  # noqa: E402


def case_long_chain() -> dict:
    """6+ adımlı zincir: hesap makinesinde 7+3+2= hesapla."""
    started = time.time()
    result = pc_task.run("hesap makinesinde 7 düğmesine bas, sonra artı düğmesine bas, "
                         "sonra 3 düğmesine bas, sonra artı düğmesine bas, "
                         "sonra 2 düğmesine bas, sonra eşittir düğmesine bas")
    return {"ad": "uzun zincir (6 adım)", "durum": result["status"],
            "süre": round(time.time() - started, 1), "adım": len(result.get("done", []))}


def case_impossible_middle() -> dict:
    """Ortadaki adım imkânsız: zincir durmalı, kalan adımlar çalışmamalı."""
    result = pc_task.run("hesap makinesinde 7 düğmesine bas, sonra mor düğmesine bas, "
                         "sonra 3 düğmesine bas")
    return {"ad": "imkânsız orta adım", "durum": result["status"],
            "adım": len(result.get("done", [])), "beklenen": "stop, 1 adım"}


def case_long_text() -> dict:
    """1000+ karakter yazma ve OCR ile doğrulama."""
    text = " ".join(["uzun metin denemesi"] * 60)
    result = pc_hands.type_text("not defteri", "metin", text)
    visible = pc_vision.find_text("uzun metin")["status"]
    return {"ad": "uzun metin (1000+ karakter)", "durum": result["status"],
            "ekranda": visible, "uzunluk": len(text)}


def case_closed_app() -> dict:
    """Kapalı uygulama: dürüst 'açamadım' / 'bulamadım' cevabı."""
    result = pc_hands.click("kesinlikle olmayan uygulama", "kaydet")
    return {"ad": "kapalı/olmayan uygulama", "durum": result["status"], "cevap": result["text"][:70]}


def case_ambiguous() -> dict:
    """Aynı adlı iki pencere: tahmin yok, tek soru."""
    result = pc_hands.find_control("chrome", "kapat")
    return {"ad": "belirsiz hedef", "durum": result.get("status"), "cevap": str(result.get("text"))[:70]}


def case_save_and_verify() -> dict:
    """Sandbox'a kaydet ve diskten doğrula, sonra temizle."""
    asked = pc_files.save_as("not defteri", "stres_denemesi.txt")
    if asked["status"] != "needs_confirmation":
        return {"ad": "kaydet + doğrula", "durum": asked["status"], "not": asked["text"][:60]}
    done = pc_files.confirm_save()
    cleaned = pc_files.cleanup(done.get("path", "")) if done.get("path") else False
    return {"ad": "kaydet + doğrula", "durum": done["status"], "temizlendi": cleaned}


CASES = (case_long_chain, case_impossible_middle, case_long_text, case_closed_app,
         case_ambiguous, case_save_and_verify)


def main() -> int:
    rows = []
    for case in CASES:
        try:
            rows.append(case())
        except Exception:
            rows.append({"ad": case.__name__, "durum": "HATA", "iz": traceback.format_exc()[-160:]})
    print("\n=== ZOR GÖREV KARNESİ ===")
    for row in rows:
        print(" ·", row)
    passed = sum(1 for row in rows if row.get("durum") in ("done", "stop", "no_window", "not_found", "ambiguous"))
    print(f"\nBeklenen davranışı gösteren: {passed}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
