"""Jarvis başlatıcısı: anahtar ve güncelleme kontrolünden sonra Komut Merkezi (web arayüzü) açılır.

Çalıştır:  python gui.py        (komut satırı sürümü: python main.py)
Eski Tk pencere arayüzü (pages/pages2/panel/chatview/theme) 2026-10-05 kaldırıldı.
"""
from modules.diagnostics import record_failure as _record_failure
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

# Anahtarsız da Komut Merkezi açılır. Anahtar aktif profilin Ayarlar ekranından
# eklenir; global/legacy anahtar sorarak kullanıcıyı boş bir hesaba yönlendirme.

# Tek kopya kilidi güncelleme ve motor yüklenmeden önce alınır.
if __name__ == "__main__":
    try:
        import instance
        instance.take_over()
    except Exception:                     # noqa: BLE001
        _record_failure('gui.py:<module>')
        raise SystemExit(1)

# GitHub ana dalı: açılışta yalnız kontrol edilir; otomatik kurulum/üzerine yazma yoktur.
if __name__ == "__main__" and "--guncellemesiz" not in sys.argv:
    try:
        import updater
        _upd = updater.check(apply_now=False)
        if _upd:
            print("[Güncelleme]", _upd)  # yalnız bildirim; dosya değiştirilmez
    except Exception as _exc:             # noqa: BLE001 - güncelleme olmazsa eski sürümle devam
        _record_failure('gui.py:<module>')
        print(f"[Uyarı] Güncelleme denetlenemedi: {type(_exc).__name__}")

# Komut Merkezi (web arayüzü) tek arayüzdür. Açılamazsa nedeni gösterilir; eski yedek pencere yoktur.
def main() -> None:
    try:
        import web
    except Exception as exc:              # noqa: BLE001
        _record_failure('gui.py:main')
        import traceback
        detail = __import__("modules.diagnostics", fromlist=["failure_detail"]).failure_detail()
        try:
            (Path.home() / ".jarvis" / "baslatma_hatasi.log").write_text(detail, encoding="utf-8")
        except OSError:
            pass
        print(detail)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Jarvis", f"Jarvis açılamadı: {type(exc).__name__}: {exc}\n\n"
                                 f"Ayrıntı: {Path.home() / '.jarvis' / 'baslatma_hatasi.log'}")
            root.destroy()
        except Exception:                 # noqa: BLE001
            _record_failure('gui.py:main')
            pass
        sys.exit(1)
    web.main()


if __name__ == "__main__":
    main()
