r"""Canlı kabul ölçümü (B4-5 / B4-6 / B5): kodun gerçek hesaplarla konuşup konuşmadığını
ölçer ve kanıt satırı basar.

Neden ayrı betik: bu maddeler yalnız kullanıcının kendi makinesinde ve kendi hesaplarıyla
ölçülebilir. CI bunları ölçemez, bu yüzden burada "ölçüldü / ölçülemedi" ayrımı açıkça
yazılır — uydurma kabul yok.

Kullanım:
    py -3.13 -X utf8 scripts\canli_kabul.py
    py -3.13 -X utf8 scripts\canli_kabul.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _sonuc(ad: str, durum: str, kanit: str) -> dict:
    return {"ad": ad, "durum": durum, "kanit": kanit}


def kontrol_gmail() -> dict:
    try:
        from modules import google_api
        if not google_api.connected():
            return _sonuc("Gmail", "skip", "hesap bağlı değil (Bağla ile yetki ver)")
        sayi = google_api.unread_count()
        if not isinstance(sayi, int):
            return _sonuc("Gmail", "fail", f"okunmamış sayısı sayı değil: {type(sayi).__name__}")
        return _sonuc("Gmail", "pass", f"okunmamış: {sayi}")
    except Exception as e:       # noqa: BLE001
        return _sonuc("Gmail", "fail", f"{type(e).__name__}: {e}")


def kontrol_drive() -> dict:
    try:
        from modules import drive_readonly
        drive, _docs = drive_readonly.services()
        dosyalar = drive_readonly.list_files(drive, limit=3)
        return _sonuc("Drive", "pass", f"{len(dosyalar)} dosya okundu")
    except PermissionError as e:
        # Drive'ın kendi salt-okunur jetonu ayrı; yoksa "bozuk" değil "henüz izin yok".
        return _sonuc("Drive", "skip", f"izin yok ({e}); Drive'a bir kez Bağla ile izin ver")
    except Exception as e:       # noqa: BLE001
        return _sonuc("Drive", "fail", f"{type(e).__name__}: {e}")


def kontrol_owa() -> dict:
    try:
        from modules import outlook
        metin = outlook.unread_mail(limit=1)
        if not isinstance(metin, str) or not metin.strip():
            return _sonuc("Outlook (OWA)", "fail", "boş cevap")
        return _sonuc("Outlook (OWA)", "pass", metin.strip().splitlines()[0][:60])
    except Exception as e:       # noqa: BLE001
        return _sonuc("Outlook (OWA)", "fail", f"{type(e).__name__}: {e}")


def kontrol_cdp(port: int = 9222) -> dict:
    adres = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(adres, timeout=3) as cevap:
            veri = json.loads(cevap.read().decode("utf-8", "replace"))
        return _sonuc("Chrome CDP", "pass", _cdp_kanit(veri))
    except Exception as e:       # noqa: BLE001
        neden = f"debug portu {port} kapalı ({type(e).__name__})"
        return _sonuc("Chrome CDP", "skip",
                      neden + f"; Chrome'u --remote-debugging-port={port} ile aç")


def _cdp_kanit(veri: dict) -> str:
    tarayici = str(veri.get("Browser", "?"))
    return f"bağlantı açık: {tarayici[:60]}"


def topla() -> list[dict]:
    return [kontrol_gmail(), kontrol_drive(), kontrol_owa(), kontrol_cdp()]


def rapor(satirlar: list[dict]) -> str:
    genislik = max(len(s["ad"]) for s in satirlar)
    return "\n".join(f"{s['ad']:<{genislik}}  {s['durum']:<4}  {s['kanit']}" for s in satirlar)


def main(argv: list[str] | None = None) -> int:
    ayar = argparse.ArgumentParser(description="Canlı kabul ölçümü")
    ayar.add_argument("--json", action="store_true", help="makine okunur çıktı")
    secim = ayar.parse_args(argv)
    satirlar = topla()
    if secim.json:
        print(json.dumps(satirlar, ensure_ascii=False, indent=2))
    else:
        print(rapor(satirlar))
        print()
        print("pass = gerçek hesaptan ölçüldü · skip = bu makinede ölçülemedi · fail = ölçüldü ve bozuk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
