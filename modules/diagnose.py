"""Arıza tespiti: Jarvis'in çalışması için gereken her şeyi gerçekten dener ve sorun varsa ne yapılacağını söyler.

run()      -> kontrol listesi (Komut Merkezi'ndeki "Sistem taraması" ve "sistemi kontrol et" komutu)
summary()  -> listeden sesli okunacak kısa özet
explain()  -> bir komut çalışırken çıkan hatayı anlaşılır Türkçe cümleye çevirir
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import concurrent.futures as cf
import socket
import time

PHONE = None          # web.py açılışta telefon sunucusunu buraya bağlar (telefon kontrolü için)

def _item(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


# ------------------------------------------------------------------ tek tek kontroller
def check_internet() -> dict:
    t0 = time.time()
    for host in (("1.1.1.1", 443), ("8.8.8.8", 53), ("www.google.com", 443)):
        try:
            with socket.create_connection(host, timeout=3):
                ms = round((time.time() - t0) * 1000)
                return _item("İnternet", "warn" if ms > 800 else "ok", f"{ms} ms" + (" (yavaş)" if ms > 800 else ""),
                             "Bağlantı yavaş; yanıtlar gecikebilir." if ms > 800 else "")
        except OSError:
            continue
    return _item("İnternet", "bad", "bağlantı yok",
                 "Wi-Fi ya da kabloyu kontrol et. İnternet olmadan yapay zeka, hava durumu ve mail çalışmaz.")


def check_ai(user_slug: str | None = None) -> dict:
    from modules import llm
    if user_slug:
        llm.set_user_context(user_slug)
    try:
        prov = llm.provider()
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_ai')
        prov = "gemini"
    name = {"gemini": "Yapay zeka (Gemini)", "groq": "Yapay zeka (Groq)", "ollama": "Yapay zeka (yerel)", "openai":"Yapay zeka (OpenAI)", "anthropic":"Yapay zeka (Claude)"}.get(prov, "Yapay zeka")
    t0 = time.time()
    try:
        llm.ask("Yalnızca 'tamam' yaz.", "Tek kelime yaz.", 20)
        ms = round((time.time() - t0) * 1000)
        return _item(name, "warn" if ms > 8000 else "ok", f"yanıt {ms / 1000:.1f} sn",
                     "Yanıtlar yavaş geliyor." if ms > 8000 else "")
    except Exception as e:  # noqa: BLE001
        _record_failure('modules/diagnose.py:check_ai')
        return _item(name, "bad", "yanıt vermiyor", explain(e))


def check_microphone() -> dict:
    try:
        import numpy as np
        import sounddevice as sd
        ins = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if not ins:
            return _item("Mikrofon", "bad", "cihaz bulunamadı", "Mikrofonu tak ya da Windows ses ayarlarında etkinleştir.")
        dev = sd.query_devices(kind="input")
        sr = int(dev.get("default_samplerate") or 16000)
        rec = sd.rec(int(0.5 * sr), samplerate=sr, channels=1, dtype="float32")
        sd.wait()
        level = float(np.abs(rec).max())
        name = str(dev.get("name", ""))[:40]
        if level == 0.0:
            return _item("Mikrofon", "bad", f"{name}: ses gelmiyor",
                         "Windows Ayarlar → Gizlilik → Mikrofon'dan uygulamaların mikrofona erişimine izin ver; "
                         "mikrofonun sessize alınmadığını kontrol et.")
        return _item("Mikrofon", "ok", name)
    except Exception as e:  # noqa: BLE001
        _record_failure('modules/diagnose.py:check_microphone')
        return _item("Mikrofon", "warn", "denenemedi", f"Mikrofon şu an kullanımda olabilir ({type(e).__name__}).")


def check_speaker(speak_flag: bool | None = None) -> dict:
    if speak_flag is False:
        return _item("Hoparlör / konuşma", "warn", "Jarvis'in konuşması kapalı", "Komut Merkezi'nde 'Konuşma' düğmesini aç.")
    try:
        from modules import system_control
        ep = system_control._volume_endpoint()
        if ep is not None:
            if ep.GetMute():
                return _item("Hoparlör / konuşma", "warn", "bilgisayarın sesi kapalı (sessiz)", "“Sesi aç” de ya da ses tuşuna bas.")
            vol = round(ep.GetMasterVolumeLevelScalar() * 100)
            if vol < 5:
                return _item("Hoparlör / konuşma", "warn", f"ses çok kısık (%{vol})", "“Sesi yüzde 50 yap” de.")
            return _item("Hoparlör / konuşma", "ok", f"ses %{vol}")
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_speaker')
        pass
    return _item("Hoparlör / konuşma", "ok", "açık")


def check_google() -> dict:
    from modules import google_api as g
    if not g.token_path().exists():
        if g.CRED.exists():
            return _item("Gmail ve Takvim", "warn", "izin bekliyor", "Menü › Yapay zekâ › Gmail ve Takvim bölümünde “Bağlan” düğmesine bas.")
        return _item("Gmail ve Takvim", "warn", "kurulmadı", "İstersen Menü › Yapay zekâ › Gmail ve Takvim bölümünden Google'ı bağlayabilirsin.")
    try:
        problem = g._ready()
        if problem:
            return _item("Gmail ve Takvim", "bad", "bağlantı sorunlu", problem[:160])
        g._service("gmail", "v1").users().getProfile(userId="me").execute()
        return _item("Gmail ve Takvim", "ok", "bağlı")
    except Exception as e:  # noqa: BLE001
        _record_failure('modules/diagnose.py:check_google')
        msg = str(e).lower()
        if "invalid_grant" in msg or "expired" in msg or "revoked" in msg:
            return _item("Gmail ve Takvim", "bad", "izin süresi dolmuş",
                         "Menü › Yapay zekâ › Gmail ve Takvim bölümünde “Bağlan” düğmesiyle yeniden bağlan (Testing modundaki Google uygulamalarında izin bir süre sonra düşebilir).")
        return _item("Gmail ve Takvim", "bad", "ulaşılamıyor", explain(e))


def check_outlook() -> dict | None:
    try:
        from modules import outlook
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_outlook')
        return None
    if not outlook.installed():
        return None                       # bu bilgisayarda Outlook yok: listede gösterme
    if outlook.running():
        return _item("İş maili (Outlook)", "ok", "açık")
    return _item("İş maili (Outlook)", "ok", "kapalı (gerekince Jarvis açar)")


def check_phone() -> dict | None:
    if PHONE is None:
        return None
    try:
        from modules import phone as phonemod
        ts = phonemod.tailscale_status()
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_phone')
        ts = {}
    if not PHONE.running:
        return _item("Telefon bağlantısı", "warn", "kapalı",
                     "Siri ve telefondan kullanım için Daha Fazla → Telefon'dan telefon erişimini aç.")
    state = ts.get("state")
    if state == "running":
        return _item("Telefon bağlantısı", "ok", f"açık · Tailscale {ts.get('ip', '')}")
    if state == "login":
        return _item("Telefon bağlantısı", "warn", "Tailscale oturumu kapalı", "Tailscale'i açıp hesabınla giriş yap.")
    if state == "missing":
        return _item("Telefon bağlantısı", "warn", "yalnızca aynı Wi-Fi", "Dışarıdan bağlanmak için Tailscale kur.")
    return _item("Telefon bağlantısı", "warn", "Tailscale kapalı", "Sağ alttaki Tailscale simgesinden bağlan.")


def check_watch() -> dict | None:
    """Uyanıklık (gözlem) gerçekten açık mı, sessiz saat ne, kaç olay hatırlanıyor?

    Teşhis panelinde bu satır yoktu: kullanıcı "neden hiç haber vermiyor?"
    sorusunun cevabını göremiyordu (varsayılan kapalı).
    """
    try:
        from config import load_settings
        from modules import awareness_watch, pc_autonomy_queue
        settings = load_settings() or {}
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_watch')
        return None
    if not awareness_watch.enabled(settings):
        return _item("Uyanıklık", "warn", "kapalı",
                     "Bir şey olduğunda haber vermesini istersen uyanıklığı aç")
    start, end = awareness_watch.quiet_bounds(settings)
    seen = len(pc_autonomy_queue._SEEN)
    detail = f"açık · sessiz saat {start:02d}:00–{end:02d}:00 · {seen} olay hatırlanıyor"
    last = pc_autonomy_queue.announce_state()
    if last.get("at"):
        stamp = time.strftime("%d.%m %H:%M", time.localtime(float(last["at"])))
        detail += f" · son bildirim {stamp}"
    else:
        detail += " · henüz bildirim yok"
    return _item("Uyanıklık", "ok", detail)


def check_wake() -> dict | None:
    try:
        import config
        from modules import wakeword
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_wake')
        return None
    if not wakeword.wanted(config.WAKE_WORD):
        return None                       # Google yöntemi seçili: ayrı kontrol yok
    st = wakeword.status()
    if st["state"] == "ready":
        return _item("İnternetsiz uyandırma", "ok", "“Hey Jarvis” dinleniyor")
    if st["state"] == "failed":
        return _item("İnternetsiz uyandırma", "warn", "çalışmıyor, Google yöntemi kullanılıyor", st["error"][:200])
    return _item("İnternetsiz uyandırma", "ok", "hazırlanıyor")


def check_resources() -> list[dict]:
    out = []
    try:
        import psutil
        import os
        disk = psutil.disk_usage((os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/").percent
        out.append(_item("Disk", "bad" if disk >= 95 else "warn" if disk >= 85 else "ok", f"%{round(disk)} dolu",
                         "Diskte yer azaldı; gereksiz dosyaları sil." if disk >= 85 else ""))
        mem = psutil.virtual_memory().percent
        out.append(_item("Bellek", "warn" if mem >= 90 else "ok", f"%{round(mem)} kullanımda",
                         "Bellek dolu; kullanmadığın programları kapat (“Chrome'u kapat” gibi)." if mem >= 90 else ""))
    except Exception:       # noqa: BLE001
        _record_failure('modules/diagnose.py:check_resources')
        pass
    return out


# ------------------------------------------------------------------ toplu tarama
def run(speak_flag: bool | None = None, user_slug: str | None = None) -> list[dict]:
    """Bütün kontrolleri aynı anda çalıştırır (en fazla ~15 sn)."""
    jobs = [check_internet, lambda: check_ai(user_slug), check_microphone, lambda: check_speaker(speak_flag), check_google,
            check_outlook, check_phone, check_wake, check_watch]
    results: list[dict | None] = [None] * len(jobs)
    names = ["İnternet", "Yapay zeka", "Mikrofon", "Hoparlör / konuşma", "Gmail ve Takvim", "İş maili (Outlook)",
             "Telefon bağlantısı", "İnternetsiz uyandırma", "Uyanıklık"]
    # 'with' kullanılmıyor: with bloğu çıkarken takılan kontrolü sonuna kadar bekliyordu ve tarama donuyordu.
    ex = cf.ThreadPoolExecutor(max_workers=len(jobs))
    futs = {ex.submit(f): i for i, f in enumerate(jobs)}
    try:
        for fut in cf.as_completed(futs, timeout=12):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                _record_failure('modules/diagnose.py:run')
                results[i] = _item(names[i], "warn", "denenemedi", type(e).__name__)
    except cf.TimeoutError:
        for fut, i in futs.items():
            if results[i] is None and not fut.done():
                results[i] = _item(names[i], "warn", "zaman aşımı", "Kontrol çok uzun sürdü; tekrar dene.")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)   # yavaş kalan kontrol arka planda kendi biter, ekranı bekletmez
    return [r for r in results if r] + check_resources()


def summary(items: list[dict]) -> str:
    bad = [x for x in items if x["status"] == "bad"]
    warn = [x for x in items if x["status"] == "warn"]
    if not bad and not warn:
        return "Her şey yolunda. İnternet, yapay zeka, mikrofon, ses ve bağlantıların hepsi çalışıyor."
    parts = []
    if bad:
        parts.append(f"{len(bad)} sorun buldum. " + " ".join(f"{x['name']}: {x['detail']}. {x['fix']}" for x in bad))
    if warn:
        parts.append(("Ayrıca " if bad else "Ciddi bir sorun yok ama ") + f"{len(warn)} uyarı var: " +
                     "; ".join(f"{x['name']} {x['detail']}" for x in warn) + ".")
    return " ".join(p.strip() for p in parts)


# ------------------------------------------------------------------ hata açıklama
def explain(e: BaseException) -> str:
    """Komut sırasında çıkan hatayı ortak failure policy ile açıklar."""
    from modules import failure_policy
    return failure_policy.explain(e)
