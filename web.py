"""Jarvis Komut Merkezi (web arayüzü).

Çalıştır:  python gui.py  (komut satırı: python main.py)

Python motoru aynen çalışır; arayüz yalnızca bu bilgisayardaki (127.0.0.1) küçük bir sunucudan HTML olarak sunulur
ve Edge/Chrome'un "uygulama penceresi" kipinde açılır. Sunucu rastgele bir anahtar ister, dışarıdan erişilemez.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import json
from contextvars import ContextVar
_bridge_profile = ContextVar("jarvis_bridge_profile", default=None)
import mimetypes
import os
import queue
import re
import secrets
import shutil
import tempfile
import subprocess
import sys
if __name__ == "__main__":
    import instance
    instance.take_over()
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "webui"
import psutil                                                    # noqa: E402

import config                                                    # noqa: E402
import main as engine                                            # noqa: E402
from modules import (agents, browser, google_api, history, kb, llm, media, notify, plugins, privacy, richtext, study, tasks,   # noqa: E402
                     vision, voice, weather)
from modules import when as whenmod                              # noqa: E402
from modules.personalization import list_users                   # noqa: E402
from modules import phone as phonemod                            # noqa: E402
from modules.phone import PhoneServer, qr_matrix                 # noqa: E402

DATA_DIR = config.DATA_DIR
FONT_DIR = DATA_DIR / "fonts"
UPLOAD_DIR = DATA_DIR / "uploads"


# ======================================================================= olay dağıtıcı
class Hub:
    """Motorun gönderdiği olayları bağlı tarayıcı sekmelerine (SSE) dağıtır."""

    def __init__(self) -> None:
        self.clients: set[queue.Queue] = set()
        self.lock = threading.Lock()
        self.ever = False
        self.empty_since = time.time()
        self.state = "idle"
        self.feed: deque = deque(maxlen=60)       # son olaylar (Son hareketler)
        self.activity: deque = deque(maxlen=240)   # kullanıcıya anlaşılır gerçek işlem akışı
        self.activity_seq = 0

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=512)
        with self.lock:
            self.clients.add(q)
            self.ever = True
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(q)
            if not self.clients:
                self.empty_since = time.time()

    def publish(self, kind: str, text: str = "", extra: str = "", metadata=None) -> None:
        owner = engine.pc_profile()
        # IDs come with the original event; identical message text is never used as an identity.
        msg = {"k": kind, "t": text, "x": extra, "ts": time.time(), "user": owner.slug}
        if metadata:
            msg.update({k: metadata[k] for k in ('user', 'mid', 'rid') if k in metadata})
        with self.lock:
            if kind == "state":
                self.state = text
            if kind in ("user", "assistant", "system"):
                self.feed.append({"k": kind, "t": text[:300], "ts": time.time()})
            if kind == "activity":
                self.activity_seq += 1
                parts = (extra or "info||").split("|", 2)
                status = parts[0] if parts else "info"
                area = parts[1] if len(parts) > 1 else ""
                detail = parts[2] if len(parts) > 2 else ""
                self.activity.append({"id": self.activity_seq, "text": text[:500], "status": status,
                                      "area": area[:80], "detail": detail[:900], "ts": time.time()})
            for q in list(self.clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    while not q.empty():
                        try: q.get_nowait()
                        except queue.Empty: break
                    q.put_nowait({"k": "reconcile", "user": msg['user']})


hub = Hub()
_engine_running = False
from modules.deferred import start as _defer


def on_engine(kind: str, text: str = "", extra: str = "", *, metadata=None) -> None:
    if kind == "quit":
        hub.publish("quit")
        _defer(0.5, lambda: _shutdown(reason="kapat komutu"))
        return
    if kind in ("nav", "widget", "win", "restart"):   # Jarvis'in kendi işlemleri (sesle sayfa aç, ayar, yeniden başlat)
        threading.Thread(target=_self_action, args=(kind, text), daemon=True).start()
        return
    # Konuşma olaylarından anlaşılır aktivite kaydı üret. Araçların gerçek başlangıç/sonuçları
    # ayrıca motor tarafından doğrudan activity olayı olarak gelir.
    if kind == "user":
        hub.publish("activity", f"Komut alındı: {text[:180]}", f"start|Komut|Kaynak: {extra or 'bilgisayar'}")
    elif kind == "assistant":
        hub.publish("activity", "Yanıt kullanıcıya iletildi", f"done|Yanıt|{text[:260]}")
    elif kind == "system" and text:
        low = text.casefold()
        st = "error" if any(w in low for w in ("hata", "başarısız", "ulaşılam", "koptu")) else "warn"
        hub.publish("activity", text[:220], f"{st}|Sistem|")
    hub.publish(kind, text, extra, metadata=metadata)


on_engine.event_metadata = True


def _self_action(kind: str, text: str) -> None:
    """Motorun istediği arayüz işleri: sayfa açma, küçük Jarvis göster/gizle, tam ekran, yeniden başlatma."""
    try:
        if kind == "nav":
            top, _, sub = (text or "cc").partition("|")
            with hub.lock:
                has = bool(hub.clients)
            if has:
                _win_action("show")
                hub.publish("nav", text)
            else:                                   # pencere kapalı: istenen sayfayla yeniden aç
                open_window(_url + "#" + top + (f"/{sub}" if sub else ""))
        elif kind == "widget":
            bridge.widget_set(text == "show")
        elif kind == "win":
            want = text == "full"
            if bool(config.load_settings().get("fullscreen", False)) != want:
                if not _win_action("full"):          # pencere yoksa yalnızca ayarı kaydet
                    config.save_settings(fullscreen=want)
        elif kind == "restart":
            time.sleep(3.5)                         # "yeniden başlatıyorum" cevabı söylensin
            bridge.restart()
    except Exception:       # noqa: BLE001
        _record_failure('web.py:_self_action')


# ======================================================================= arka plan ölçümleri
class Sampler:
    """CPU / bellek / ağ örneklerini saniyede bir toplar; hava durumunu ve internet durumunu arada yeniler."""

    def __init__(self) -> None:
        self.cpu: deque = deque(maxlen=120)
        self.mem: deque = deque(maxlen=120)
        self.down: deque = deque(maxlen=120)
        self.up: deque = deque(maxlen=120)
        self.disk = 0.0
        self.disk_total = 0
        self.battery: dict | None = None
        self.online = True
        self.latency_ms: int | None = None
        self.weather: dict | None = None
        self._wx_time = 0.0
        self._wx_city = None
        self._net_time = 0.0
        self._disk_time = 0.0

    def invalidate_weather(self) -> None:
        """Refresh weather after a preference change."""
        self._wx_time = 0.0

    def start(self) -> None:
        psutil.cpu_percent(None)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        last = psutil.net_io_counters()
        last_t = time.time()
        while not engine.stop_event.wait(1.0):
            try:
                now = time.time()
                io = psutil.net_io_counters()
                dt = max(now - last_t, 0.1)
                self.down.append(max(0, (io.bytes_recv - last.bytes_recv) / dt / 1024))
                self.up.append(max(0, (io.bytes_sent - last.bytes_sent) / dt / 1024))
                last, last_t = io, now
                self.cpu.append(psutil.cpu_percent(None))
                self.mem.append(psutil.virtual_memory().percent)
                if now - self._disk_time > 30:
                    self._disk_time = now
                    du = psutil.disk_usage(os.path.abspath(os.sep))
                    self.disk, self.disk_total = du.percent, du.total
                    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
                    self.battery = {"pct": round(bat.percent), "plugged": bool(bat.power_plugged)} if bat else None
                if now - self._net_time > 20:
                    self._net_time = now
                    threading.Thread(target=self._ping, daemon=True).start()
                city = _p().data["prefs"].get("city") or None
                if now - self._wx_time > 1200 or city != self._wx_city:
                    self._wx_time, self._wx_city = now, city
                    threading.Thread(target=self._weather, args=(city,), daemon=True).start()
            except Exception:       # ölçüm hatası arayüzü bozmasın
                _record_failure('web.py:_loop')
                pass

    def _ping(self) -> None:
        import socket
        t0 = time.time()
        # Şirket ağları 1.1.1.1:53'ü (DNS) çoğu zaman engeller; yalnız ona bakınca "İnternet Yok" yanlış çıkıyordu.
        for host in (("1.1.1.1", 53), ("www.google.com", 443), ("generativelanguage.googleapis.com", 443)):
            try:
                socket.create_connection(host, 3).close()
                self.online, self.latency_ms = True, int((time.time() - t0) * 1000)
                return
            except OSError:
                continue
        self.online, self.latency_ms = False, None

    def _weather(self, city) -> None:
        wx = weather_struct(city)
        if not wx and not city:
            wx = weather_struct("İstanbul")      # IP'den konum bulunamazsa (şirket ağı vb.) varsayılan şehir
        if wx:
            self.weather = wx
        else:
            self._wx_time = time.time() - 1200 + 60   # alınamadı: 20 dk değil 1 dk sonra yeniden dene


def weather_struct(city: str | None) -> dict | None:
    try:
        place = weather.geocode(city) if city else weather.locate_me()
        if not place:
            return None
        name, lat, lon = place
        data = weather.forecast(lat, lon)
        cur, day = data["current"], data["daily"]
        return {"city": name, "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
                "desc": weather.WMO.get(int(cur["weather_code"]), "değişken"), "code": int(cur["weather_code"]),
                "min": round(day["temperature_2m_min"][0]), "max": round(day["temperature_2m_max"][0]),
                "rain": (day.get("precipitation_probability_max") or [None])[0],
                "hum": round(cur["relative_humidity_2m"]), "wind": round(cur["wind_speed_10m"])}
    except Exception:
        _record_failure('web.py:weather_struct')
        return None


sampler = Sampler()
phone = PhoneServer(engine)
try:
    from modules import diagnose as _diag
    _diag.PHONE = phone              # arıza tespiti telefon bağlantısını da kontrol etsin
except Exception:       # noqa: BLE001
    _record_failure('web.py:<module>')
    pass
_started = time.time()


# ======================================================================= köprü (arayüzün çağırdığı işlevler)
def _yt_state() -> dict:
    try:
        from modules import studymedia
        return studymedia.state()
    except Exception:   # noqa: BLE001
        _record_failure('web.py:_yt_state')
        return {"key": False, "ok": None, "msg": ""}


def _p():
    """Bilgisayar ekranının kullanıcısı (telefondan başka biri soru sorarken bile)."""
    captured = _bridge_profile.get()
    if captured is not None:
        return captured
    fn = getattr(engine, "pc_profile", None)
    return fn() if fn else engine.profile


_CACHE: dict = {}


def cached(key: str, ttl: float, fn):
    """Sık değişmeyen (ve biraz pahalı) değerleri kısa süre önbellekler."""
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


_OLLAMA_UP = {"t": 0.0, "up": False, "busy": False}


def _ollama_up() -> bool:
    """Ollama çalışıyor mu? Anlık görüntü hiç beklemez: son bilinen değer döner, kontrol arka planda yenilenir
    (eskiden her dakika anlık görüntüyü ve açılıştaki diğer istekleri 2 sn bekletiyordu)."""
    if time.time() - _OLLAMA_UP["t"] > 60 and not _OLLAMA_UP["busy"]:
        _OLLAMA_UP["busy"] = True

        def work() -> None:
            try:
                _OLLAMA_UP["up"] = bool(llm.ollama_models())
            except Exception:       # noqa: BLE001
                _record_failure('web.py:_ollama_up')
                _OLLAMA_UP["up"] = False
            finally:
                _OLLAMA_UP["t"] = time.time()
                _OLLAMA_UP["busy"] = False
        threading.Thread(target=work, daemon=True).start()
    return bool(_OLLAMA_UP["up"])


def _color_ok(c: str) -> str:
    return c if c in ("good", "cyan", "warn", "muted") else "cyan"


def _live():
    from modules import live
    return live


def _wakeword():
    from modules import wakeword
    return wakeword


def _wake_note() -> str:
    """Ayarlar sayfasında uyandırma yönteminin altında gösterilen durum yazısı."""
    ww = _wakeword()
    if not ww.wanted(config.WAKE_WORD):
        return "Google yöntemi: söylenen her şey yazıya çevrilip ad aranıyor (internet gerekir)."
    st = ww.status()
    return {"ready": "✓ İnternetsiz dinleyici çalışıyor. “Hey Jarvis” de; ortam sesi dışarı gitmez.",
            "loading": "İnternetsiz dinleyici hazırlanıyor… (ilk seferde biraz sürer, bu arada Google yöntemi çalışır)",
            "failed": "✗ İnternetsiz dinleyici çalışmıyor, Google yöntemi kullanılıyor. " + st["error"],
            }.get(st["state"], "İnternetsiz dinleyici mikrofon açılınca hazırlanacak.")


from web_study import WebStudy
from web_memory import WebMemory
from web_phone import WebPhone
from web_files import WebFiles
from web_chat import WebChat

from web_models import WebModels
from web_integrations import WebIntegrations

from web_tasks import WebTasks
from web_voice import WebVoice

class Bridge(WebStudy, WebMemory, WebPhone, WebFiles, WebChat, WebModels, WebIntegrations, WebTasks, WebVoice):
    _runtime = sys.modules[__name__]
    """Arayüzden gelen /api/<ad> çağrıları buradaki yöntemlere gider. Dönüş değeri JSON olarak iletilir."""

    # ------------------------------------------------------------ genel durum
    def _snapshot_impl(self) -> dict:
        p = _p()
        d = p.data
        done, total = tasks.counts(p)
        counts = d.get("agent_counts") or {}
        last = d.get("agent_last") or {}
        ag = []
        for key, icon, name, desc, example in agents.AGENTS:
            try:
                st, col = agents.state(key, p)
            except Exception:
                _record_failure('web.py:_snapshot_impl')
                st, col = "Hazır", "cyan"
            ag.append({"key": key, "name": name, "desc": desc, "example": example, "count": counts.get(key, 0),
                       "last": last.get(key, ""), "state": st, "color": _color_ok(col)})
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        evs = sorted(d.get("events") or [], key=lambda e: e["when"])
        up = [e for e in evs if e["when"][:10] >= today][:30]
        # UI daima aktif profilin Gemini anahtarını göstermeli; global/legacy anahtar kullanıcı durumu değildir.
        key = (llm.user_key(p.slug) if llm.key_state(p.slug)["configured"] else "")
        topic = d["prefs"].get("ntfy_topic")
        try:
            import updater as _updater
            github_state = _updater.status()
        except Exception:       # yerel durum okunamazsa arayüz çalışmaya devam etsin
            _record_failure('web.py:_snapshot_impl')
            github_state = {}
        return {
            "now": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "user": {"name": p.name, "slug": p.slug}, "users": cached("users", 3, lambda: list_users()) or [p.name],
            "orb": hub.state, "flags": dict(engine.flags), "wake": config.WAKE_WORD, "winctl": sys.platform.startswith("win"), "aname": _aname(), "fullscreen": bool(config.load_settings().get("fullscreen", False)),
            "mode": vision.mode(), "development": self.development_status(),
            "sys": {"cpu": round(sampler.cpu[-1]) if sampler.cpu else 0, "mem": round(sampler.mem[-1]) if sampler.mem else 0,
                    "disk": round(sampler.disk), "down": round(sampler.down[-1], 1) if sampler.down else 0,
                    "up": round(sampler.up[-1], 1) if sampler.up else 0, "battery": sampler.battery,
                    "uptime": int(time.time() - psutil.boot_time()), "session": int(time.time() - _started),
                    "online": sampler.online, "ping": sampler.latency_ms, "cores": psutil.cpu_count() or 0,
                    "ram_total": psutil.virtual_memory().total, "disk_total": sampler.disk_total,
                    "os": sys.platform},
            "weather": sampler.weather,
            "agents": ag,
            "tasks": [dict(t) for t in (d.get("tasks") or [])], "task_counts": [done, total],
            "events": up, "all_events": evs[-200:],
            "notes": d.get("items") or [], "goals": d.get("goals") or [], "facts": d.get("facts") or [],
            "rules": d.get("rules") or [], "pending_facts": d.get("pending_facts") or [],
            "learn_on": __import__("modules.learning", fromlist=["enabled"]).enabled(p),
            "learning_status": d.get("learning_status") or {},
            "model_validation": __import__("modules.model_health", fromlist=["cached"]).cached(p.slug, key, llm.model_names(p.slug)),
            "kb": [dict(x) for x in (d.get("kb") or [])],
            "study": study.status(p), "youtube_key": bool(config.get_youtube_key()), "youtube": _yt_state(),
            "macros": [{"key": k, "title": v.get("title", k), "actions": v.get("actions", [])}
                       for k, v in (d.get("macros") or {}).items()],
            "contacts": d.get("contacts") or {},
            "counts": d.get("command_counts") or {}, "last_used": d.get("last_used") or {},
            "feedback": d.get("feedback") or {"+": 0, "-": 0},
            "prefs": {k: v for k, v in d["prefs"].items() if k != "ntfy_topic"},
            "ntfy": bool(topic),
            "llm": {"models": llm.model_names(p.slug), "active": llm.model_names(p.slug).index(llm.active_model(p.slug)), "key": bool(key),
                    "key_tail": key[-4:] if len(key) > 8 else "", "provider": llm.provider(),
                    "sec": dict(getattr(llm, "LAST_SEC", {})),
                    "ollama_up": _ollama_up(),
                    "paid": llm.paid_status(),
                    "groq": {"key": bool(llm.user_groq_key(p.slug)), "model": llm.groq_model(),
                             "tail": llm.user_groq_key(p.slug)[-4:]}},
            "google": {"cred": google_api.CRED.exists(), "token": google_api.token_path().exists()},
            "phone": {"running": phone.running, "connected": phone.connected(p.name)},
            "github": github_state,
            "spotify": bool(cached("spotify", 120, media.spotify_installed)),
            "feed": list(hub.feed)[-20:],
            "activity": list(hub.activity)[-120:],
        }

    def snapshot(self) -> dict:
        """UI anlık görüntüsü. Geçici bir alt-modül hatası tüm arayüz yenilemesini düşürmesin."""
        try:
            out = self._snapshot_impl()
            out["engine_running"] = _engine_running
            return out
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:snapshot')
            p = _p()
            return {
                "now": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "user": {"name": p.name, "slug": p.slug},
                "users": list_users() or [p.name],
                "orb": getattr(hub, "state", "idle"),
                "flags": dict(engine.flags),
                "wake": config.WAKE_WORD,
                "mode": vision.mode(),
                "degraded": True,
                "snapshot_error": type(exc).__name__,
            }



    # ------------------------------------------------------------ komut ve ses

    def listen_once(self) -> bool:
        local = bool(config.load_settings().get('local_stt_enabled', False))
        if local != bool(getattr(engine, '_manual_local_stt', False)):
            raise ValueError('Ses tanıma seçimi değişti. Önce Jarvis’i yeniden başlat.')
        if not engine.flags.get("mic", True):
            hub.publish("state", "idle")
            return False
        engine.events.put(("listen",))
        return True

    def set_flag(self, name: str, value: bool) -> dict:
        if name in ("mic", "speak"):
            if name == "mic":
                _set_mic(bool(value))
            else:
                engine.flags[name] = bool(value)
                if not value:
                    voice.stop_speaking()
                hub.publish("state", hub.state)
        return dict(engine.flags)

    def stop_speaking(self) -> bool:
        voice.stop_speaking()
        return True

    def win(self, action: str) -> bool:
        return _win_action(str(action)) if action in ("min", "hide", "full") else False

    def sleep(self, on: bool) -> dict:
        """Hazırda bekle düğmesi: açık kalır, yalnızca '<ad> uyan' dinlenir."""
        engine.set_sleep(bool(on))
        hub.publish("state", hub.state)
        return dict(engine.flags)

    def emergency(self) -> str:
        from modules import pc_guide
        pc_guide.stop()
        engine.requests_state.cancel(_p().slug)
        """Acil durdur: konuşmayı keser, mikrofonu ve paylaşımı kapatır, bekleyen kapatma/onayları iptal eder."""
        voice.stop_speaking()
        _set_mic(False)
        try:
            vision.stop()
            hub.publish("share", "")
        except Exception:
            _record_failure('web.py:emergency')
            pass
        state = engine._sessions.for_owner(_p().slug)
        state.pending_confirm = None
        state.pending_action = None
        state.pending_msg = None
        state.pending_organize = None
        try:
            from modules import system_control
            system_control.cancel_shutdown()
        except Exception:
            _record_failure('web.py:emergency')
            pass
        hub.publish("state", "idle")
        return "Her şey durduruldu: konuşma, mikrofon, paylaşım ve bekleyen işlemler."

    def share(self, which: str | None) -> str:
        target = None if vision.mode() == which else which
        return engine.set_share(target)

    def preview(self) -> str | None:
        if not vision.mode() or privacy.blocked(vision.mode()):
            return None
        try:
            return vision.preview_multi((480, 270))[0]
        except Exception:
            _record_failure('web.py:preview')
            return None

    # ------------------------------------------------------------ kullanıcılar
    def user_switch(self, name: str) -> bool:
        engine.submit(f"ben {name}")
        return True

    def user_new(self, name: str) -> bool:
        engine.submit(f"yeni kullanıcı ekle {name}")
        return True

    def user_rename(self, old: str, new: str) -> bool:
        engine.submit(f"kullanıcıyı yeniden adlandır {old} > {new}")
        return True

    def user_delete(self, name: str) -> bool:
        engine.submit(f"kullanıcıyı sil {name}")
        return True



    def actions_catalog(self) -> list:
        from modules import app_actions
        return app_actions.catalog()

    def action_run(self, action: str, args: dict, confirmed: bool = False) -> dict:
        from modules import app_actions
        result = app_actions.run(self, _p(), action, args, confirmed=confirmed)
        if result.get("ok"):
            engine.emit("action", action)
        return result

    # ------------------------------------------------------------ görevler / notlar / takvim














    # ---- öğrenme: kurallar, onay bekleyen bilgiler, gelişim raporu









    def whatsapp_send(self, name: str, text: str) -> bool:
        """Kayıtlı kişiye WhatsApp mesajı (kullanıcı arayüzde Gönder'e bastığında)."""
        if not (text or "").strip():
            raise ValueError("Mesaj boş.")
        return engine.submit(f"{name}'e {text.strip()} diye whatsapp mesajı at", "yazı", _p().name) is not False




    # ------------------------------------------------------------ geçmiş ve bilgi tabanı






    # ------------------------------------------------------------ Çalışma Modu (her kullanıcıya özel)








    # ---- Çalışma: dersler, soru çözme, program, görsel/video


















    def open_link(self, url: str) -> bool:
        """Görsel/video bağlantısını varsayılan tarayıcıda açar (yalnız bilinen eğitim kaynakları)."""
        u = str(url or "")
        if not re.match(r"^https://([a-z0-9-]+\.)*(wikipedia\.org|wikimedia\.org|youtube\.com|youtu\.be)/", u):
            raise ValueError("Bu bağlantı açılamaz.")
        import webbrowser
        webbrowser.open(u)
        return True

    # ------------------------------------------------------------ ayarlar
    def settings(self) -> dict:
        from modules import local_stt
        s = config.load_settings()
        public_saved = {key: value for key, value in s.items()
                        if key not in ('youtube_key', 'youtube_key_protected')}
        return {"model": llm.model_names(_p().slug)[0], "fallback": llm.model_names(_p().slug)[1:], "wake_word": config.WAKE_WORD,
                "wake_aliases": list(config.WAKE_ALIASES), "wake_is_name": bool(s.get("wake_is_name")), "assistant_name": _aname(), "session_seconds": config.SESSION_SECONDS,
                "input_device": "" if config.INPUT_DEVICE is None else str(config.INPUT_DEVICE),
                "announce_unknown": bool(config.ANNOUNCE_UNKNOWN), "camera_index": config.CAMERA_INDEX,
                "wake_engine": _wakeword().mode(), "wake_status": _wake_note(),
                "wake_sensitivity": int(s.get("wake_sensitivity") or 3), "stt_engine": s.get("stt_engine") or "gemini",
                "local_stt_enabled": bool(s.get('local_stt_enabled', False)), "local_stt_model": s.get('local_stt_model') or 'small', "local_stt_beam": local_stt.beam_size(),
                "stt_words": s.get("stt_words") or "", "followup_no_wake": bool(s.get("followup_no_wake")),
                "live_mode": bool(s.get("live_mode", True)), "live_headphones": bool(s.get("live_headphones")), "live_beep": bool(s.get("live_beep", True)),
                "live_idle_seconds": int(s.get("live_idle_seconds") or 90), "stt_fixes": s.get("stt_fixes") if s.get("stt_fixes") is not None else _live().DEFAULT_FIXES, "live_silence_ms": (lambda v: 1100 if v in (0, 700) else v)(int(s.get("live_silence_ms") or 0)),
                "saved": public_saved, "data_dir": str(DATA_DIR)}

    def settings_save(self, data: dict) -> str:
        ch: dict = {}
        if "assistant_name" in data:
            ch["assistant_name"] = str(data["assistant_name"]).strip()[:20] or "Jarvis"
        if data.get("wake_is_name"):                     # uyandırma kelimesi = asistanın adı
            data["wake_word"] = ch.get("assistant_name") or _aname()
        if "wake_is_name" in data:
            ch["wake_is_name"] = bool(data["wake_is_name"])
        if "wake_word" in data:
            ch["wake_word"] = (str(data["wake_word"]).strip() or "Jarvis")
        if "wake_aliases" in data:
            al = data["wake_aliases"]
            al = [a.strip() for a in (al.split(",") if isinstance(al, str) else al) if str(a).strip()]
            ch["wake_aliases"] = al or None
        if "wake_word" in ch and ch["wake_word"].lower() != config.WAKE_WORD.lower() \
                and list(ch.get("wake_aliases") or []) == list(config.WAKE_ALIASES):
            ch["wake_aliases"] = [ch["wake_word"].lower()]      # eski adın benzer söylenişleri yeni adda yanlış tetiklemesin
        if "session_seconds" in data:
            ch["session_seconds"] = max(5, min(300, int(data["session_seconds"] or 30)))
        if "input_device" in data:
            ch["input_device"] = str(data["input_device"]).strip() or None
        if "announce_unknown" in data:
            ch["announce_unknown"] = bool(data["announce_unknown"])
        if "camera_index" in data:
            ch["camera_index"] = max(0, int(data["camera_index"] or 0))
        if data.get("wake_engine") in ("auto", "offline", "google"):
            ch["wake_engine"] = data["wake_engine"]
        if "wake_sensitivity" in data:
            ch["wake_sensitivity"] = max(1, min(5, int(data["wake_sensitivity"] or 3)))
        if data.get("stt_engine") in ("gemini", "google"):
            ch["stt_engine"] = data["stt_engine"]
        if 'local_stt_enabled' in data:
            ch['local_stt_enabled'] = bool(data['local_stt_enabled'])
        if 'local_stt_model' in data:
            if data['local_stt_model'] not in ('small', 'base'):
                raise ValueError('Yerel ses modeli small veya base olmalı.')
            ch['local_stt_model'] = data['local_stt_model']
        if 'local_stt_beam' in data:
            beam = data['local_stt_beam']
            if isinstance(beam, bool) or not isinstance(beam, int) or not 1 <= beam <= 5:
                raise ValueError('Yerel ses hız/doğruluk değeri 1 ile 5 arasında olmalı.')
            ch['local_stt_beam'] = beam
        if "followup_no_wake" in data:
            ch["followup_no_wake"] = bool(data["followup_no_wake"]) or None
        if "stt_words" in data:
            ch["stt_words"] = ", ".join(w.strip() for w in str(data["stt_words"]).split(",") if w.strip())[:600] or None
        if "live_mode" in data:
            ch["live_mode"] = bool(data["live_mode"])
        if data.get("live_voice") in _live().VOICES:
            ch["live_voice"] = data["live_voice"]
        if "live_headphones" in data:
            ch["live_headphones"] = bool(data["live_headphones"]) or None
        if "stt_fixes" in data:
            ch["stt_fixes"] = ", ".join(f"{a}={b}" for a, b in _live().parse_fixes(str(data["stt_fixes"]))) or ""
        if "live_beep" in data:
            ch["live_beep"] = bool(data["live_beep"])      # kapalı da kaydedilir: varsayılan artık açık
        if "live_silence_ms" in data:
            ch["live_silence_ms"] = max(300, min(2500, int(data["live_silence_ms"] or 1100)))
        if "live_idle_seconds" in data:
            ch["live_idle_seconds"] = max(15, min(600, int(data["live_idle_seconds"] or 90)))
        config.save_settings(**ch)
        _aname_cache["t"] = 0.0
        # Uyandırma ayarlarını hemen uygula (yeniden başlatmaya gerek yok; mikrofon seçimi hariç)
        if "wake_word" in ch:
            engine.WAKE_WORD = config.WAKE_WORD = ch["wake_word"]
            if _widget is not None:
                _widget.wake = ch["wake_word"]
        if "wake_aliases" in ch:
            engine.WAKE_ALIASES = config.WAKE_ALIASES = tuple(ch["wake_aliases"] or ())
        if "session_seconds" in ch:
            engine.SESSION_SECONDS = config.SESSION_SECONDS = ch["session_seconds"]
        if "announce_unknown" in ch:
            engine.ANNOUNCE_UNKNOWN = config.ANNOUNCE_UNKNOWN = ch["announce_unknown"]
        if "assistant_name" in ch:
            engine.ASSISTANT_NAME = config.ASSISTANT_NAME = ch["assistant_name"]
        ww = _wakeword()
        if config.load_settings().get('local_stt_enabled', False):
            msg = 'Kaydedildi. Yerel deneme yalnız Konuş düğmesinde çalışır; ses tanıma seçimi değiştiyse Jarvis’i yeniden başlat.'
        elif ww.wanted(config.WAKE_WORD):
            ww.ready()                                     # gerekirse arka planda hazırlanmaya başlasın
            msg = "Kaydedildi. Artık “Hey Jarvis” diyerek seslenebilirsin (internetsiz uyandırma)."
            if ww.status()["state"] == "failed":
                msg += " Ama internetsiz dinleyici şu an çalışmıyor, Google yöntemi kullanılıyor: " + ww.status()["error"]
        else:
            msg = f"Kaydedildi. Artık “{config.WAKE_WORD}” diyerek seslenebilirsin."
        return msg + (" Mikrofon değişikliği için Jarvis'i yeniden başlat." if "input_device" in ch else "")


    # ------------------------------------------------------------ gizlilik, yerel model, yetenekler, eklentiler
    def privacy_get(self) -> dict:
        s = config.load_settings()
        return {"mode": privacy.mode(), "modes": privacy.MODES, "redact": privacy.redact_enabled(),
                "approve": bool(s.get("approve_sensitive", True)), "tray": bool(s.get("tray", True)),
                "key_protected": config.legacy_key_protected()}

    def privacy_set(self, data: dict) -> dict:
        ch: dict = {}
        if data.get("mode") in privacy.MODES:
            ch["privacy_mode"] = data["mode"]
        for k, name in (("redact", "redact"), ("approve", "approve_sensitive"), ("tray", "tray")):
            if k in data:
                ch[name] = bool(data[k])
        config.save_settings(**ch)
        if ch.get("privacy_mode") in ("gizli", "yerel"):
            engine.set_share(None)
            voice.stop_speaking()
        privacy.audit("gizlilik ayarı", ", ".join(f"{k}={v}" for k, v in ch.items()))
        return self.privacy_get()

    def audit(self, limit: int = 100) -> list:
        return privacy.read_audit(int(limit))

    def audit_clear(self) -> bool:
        privacy.clear_audit()
        return True




    # ------------------------------------------------------------ ev/iş devir listesi (Google Görevler)



    # ------------------------------------------------------------ GitHub ana sürüm / güncelleme
    def update_status(self) -> dict:
        import updater
        return updater.status()

    def github_verify(self) -> dict:
        """Kayıtlı etikete değil gerçek GitHub main ağacına bakarak bu bilgisayarın durumunu doğrular."""
        import updater
        try:
            st = updater.verify_sync()
            return {"ok": bool(st.get("verified")), "msg": st.get("sync_msg") or "Durum doğrulandı.", **st}
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:github_verify')
            return {"ok": False, "msg": f"GitHub doğrulanamadı: {exc}"}

    def dependency_lock_status(self) -> dict:
        from modules import dependencies
        return dependencies.status()

    def dependency_lock_create(self) -> dict:
        from modules import dependencies
        try:
            out = dependencies.create_lock()
            return {"ok": True, "msg": f"Çalışan ortamın {out['count']} paket sürümü requirements.lock.txt dosyasına sabitlendi.", **out}
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:dependency_lock_create')
            return {"ok": False, "msg": str(exc)}

    def update_token_save(self, token: str = "") -> dict:
        """GitHub ana deposuna erişim anahtarını kaydeder ve erişimi doğrular."""
        import updater
        token = (token or "").strip()
        if not token:
            return {"ok": False, "msg": "Önce anahtarı yapıştır."}
        had = updater.TOKEN_FILE.read_text(encoding="utf-8") if updater.TOKEN_FILE.exists() else None
        updater.save_token(token)
        if updater.latest() is None:
            if had is None:
                updater.TOKEN_FILE.unlink(missing_ok=True)
            else:
                updater.TOKEN_FILE.write_text(had, encoding="utf-8")
            return {"ok": False, "msg": "Bu anahtarla Jarvis deposuna ulaşılamadı. Token erişimini kontrol et; yayın için Contents read/write gerekir."}
        return {"ok": True, "msg": "GitHub ana deposuna bağlandı. JARVIS açılışta yalnız kontrol eder; testten geçen yerel değişiklikler ancak “git yükle” komutuyla yayınlanır. Ev/İş PC aynı yetkiye sahiptir."}

    def update_now(self) -> dict:
        """Yalnız güncelleme kontrolü yapar; dosya indirmez."""
        import updater
        note = updater.check(apply_now=False, force=True)
        st = updater.status()
        if note:
            return {"ok": True, "msg": note + " İndirmek için ‘GitHub'dan Al’ düğmesini kullan."}
        if st["error"] and not st["token"]:
            return {"ok": False, "msg": "Depoya erişim yok: önce okuma anahtarını ekle."}
        return {"ok": True, "msg": "Zaten en güncel sürümdesin."}

    def github_pull(self) -> dict:
        """GitHub main'i bu PC'ye güvenli biçimde alır; yerel değişiklik varsa asla ezmez."""
        import updater
        try:
            st = updater.verify_sync()
            state = st.get("sync_state")
            if state == "synced":
                return {"ok": True, "msg": "Bu bilgisayar zaten GitHub main ile aynı sürümde."}
            if state != "remote_ahead":
                return {"ok": False, "msg": st.get("sync_msg") or "GitHub'dan güvenli güncelleme yapılamadı."}
            note = updater.install_latest(force=True)
            if not note:
                err = updater.status().get("error") or "Güncelleme indirilemedi; mevcut dosyalar değiştirilmedi."
                return {"ok": False, "msg": err}
            return {"ok": True, "msg": note + " Değişikliklerin tamamı için JARVIS'i yeniden başlat."}
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:github_pull')
            return {"ok": False, "msg": f"GitHub'dan alınamadı: {exc}"}

    def github_backup_pull(self) -> dict:
        """Çakışma (diverged) durumunda: farklı yerel dosyaları yedekle, sonra GitHub main'i kur. Açık onayla çağrılır."""
        import updater
        try:
            st = updater.verify_sync()
            if st.get("sync_state") != "diverged":
                return {"ok": False, "msg": "Bu işlem yalnız çakışma durumunda gerekir. " + (st.get("sync_msg") or "")}
            out = updater.backup_and_pull()
            where = f" Farklı olan {len(out['saved'])} dosyanın yedeği: {out['backup']}" if out["backup"] else ""
            return {"ok": True, "msg": out["note"] + where, **out}
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:github_backup_pull')
            return {"ok": False, "msg": f"Yedekleyip GitHub'dan alamadım; kaynak dosyalar değiştirilmedi: {exc}"}

    def github_publish(self) -> dict:
        """Açık kullanıcı onayıyla: gerçek GitHub durumunu doğrula, test et, paketleri kilitle ve ayrı dala yükleyip main için PR aç."""
        try:
            import updater
            verified = updater.verify_sync()
            if verified.get("sync_state") in ("diverged", "unknown", "offline"):
                return {"ok": False, "msg": verified.get("sync_msg") or "GitHub durumu güvenli yayın için uygun değil."}
            from modules import git_publish as sc_publish
            msg = sc_publish.publish_worktree("Ayarlar > GitHub'a Yükle ile kullanıcı onaylı yayın")
            return {"ok": True, "msg": msg}
        except Exception as exc:  # noqa: BLE001
            _record_failure('web.py:github_publish')
            return {"ok": False, "msg": f"GitHub'a yüklenemedi: {exc}"}

    def system_doctor(self) -> dict:
        from modules import system_doctor
        return system_doctor.save(_p().slug)








    def plugins_list(self) -> list:
        return plugins.listing()

    def capabilities(self) -> list:
        return _capabilities()





















    # ------------------------------------------------------------ sistem
    def sys_series(self) -> dict:
        return {"cpu": list(sampler.cpu), "mem": list(sampler.mem), "down": list(sampler.down), "up": list(sampler.up)}

    def processes(self) -> list:
        rows = []
        for pr in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                i = pr.info
                rows.append({"pid": i["pid"], "name": i["name"] or "?", "cpu": round(i["cpu_percent"] or 0, 1),
                             "mem": round(i["memory_percent"] or 0, 1)})
            except Exception:
                _record_failure('web.py:processes')
                continue
        rows.sort(key=lambda r: (r["mem"], r["cpu"]), reverse=True)
        return rows[:14]

    def scan(self) -> list:
        """Sistem taraması: her parçayı gerçekten dener; sorun varsa ne yapılacağını da döndürür."""
        from modules import diagnose
        p = _p()
        llm.set_user_context(p.slug)
        items = diagnose.run(speak_flag=engine.flags.get("speak"), user_slug=p.slug)
        return [{"name": x["name"], "ok": x["status"] != "bad", "warn": x["status"] == "warn",
                 "detail": x["detail"], "fix": x["fix"]} for x in items]

    def reflection(self) -> dict:
        """Son 7 günün gerçek verisinden özet (kullanım, saat dağılımı, ajanlar)."""
        rows = history.read(_p().slug, "", 2000)
        cut = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        week = [r for r in rows if r.get("ts", "")[:10] >= cut]
        users = [r for r in week if r.get("role") == "user"]
        hours = [0] * 24
        days: dict[str, int] = {}
        for r in users:
            try:
                hours[int(r["ts"][11:13])] += 1
                days[r["ts"][:10]] = days.get(r["ts"][:10], 0) + 1
            except (ValueError, KeyError):
                pass
        d = _p().data
        ac = d.get("agent_counts") or {}
        names = {a[0]: a[2] for a in agents.AGENTS}
        top = sorted(ac.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"week_commands": len(users), "week_replies": len(week) - len(users), "hours": hours, "days": days,
                "top_agents": [{"key": k, "name": names.get(k, k), "count": v} for k, v in top],
                "open_tasks": sum(1 for t in (d.get("tasks") or []) if not t["done"]),
                "done_tasks": sum(1 for t in (d.get("tasks") or []) if t["done"]),
                "feedback": d.get("feedback") or {}}

    def reflection_generate(self) -> str:
        r = self.reflection()
        rows = history.read(_p().slug, "", 60)
        sample = "\n".join(f"{x['role']}: {x['text'][:160]}" for x in rows[-40:] if x.get("role") == "user")
        prompt = ("Aşağıda bir kullanıcının Jarvis asistanıyla son komutları ve haftalık özeti var. Türkçe, samimi ve kısa: "
                  "1) 3 gelişim önerisi, 2) 3 davranış gözlemi yaz. Madde madde, her madde bir cümle.\n"
                  f"Özet: komut sayısı {r['week_commands']}, en çok kullanılan alanlar {r['top_agents']}, "
                  f"saat dağılımı {r['hours']}, açık görev {r['open_tasks']}.\nKomutlar:\n{sample}")
        text = llm.ask(prompt, "Kısa ve net yaz.", 600)
        _p().set_pref("last_reflection", {"text": text, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
        return text

    def open_folder(self, which: str = "data") -> bool:
        path = {"data": DATA_DIR, "log": DATA_DIR / "jarvis.log", "plugins": plugins.DIR}.get(which, DATA_DIR)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))          # type: ignore[attr-defined]  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            return False
        return True

    def widget_set(self, on: bool | None = None) -> bool:
        """Küçük Jarvis açık/kapalı (kalıcı). Açıkken yalnızca ana pencere küçültülünce görünür."""
        if on is not None:
            config.save_settings(widget_on=bool(on))
            if _widget is not None and _widget.is_visible() != bool(on):
                _widget.toggle()
        return config.load_settings().get("widget_on", True) is not False

    def restart(self) -> bool:
        engine.log.info("Jarvis yeniden başlatılıyor (pid %d)", os.getpid())
        # Keep the current window/engine alive until process creation succeeds.
        # The replacement waits for this process to release its instance lock.
        try:
            restart_env = os.environ.copy()
            restart_env.pop('JARVIS_BOOT_MARKERS', None)
            restart_env.pop('JARVIS_BOOT_ID', None)
            restart_env['JARVIS_RESTART_WAIT'] = '1'
            subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / 'launcher.py')],
                             cwd=str(Path(__file__).resolve().parent), env=restart_env)
        except OSError:
            return False
        hub.publish("quit")
        _defer(0.6, lambda: _shutdown(close_windows=False, reason="yeniden başlatma"))
        return True

    def shutdown(self) -> bool:
        _defer(0.3, lambda: _shutdown(reason="Kapat düğmesi"))
        return True

    def daily(self) -> bool:
        return engine.submit("günlük özet", "yazı", _p().name) is not False

    # ------------------------------------------------------------ yeni arayüz (nx)






    def nx_settings(self) -> dict:
        from modules import nxapi
        return nxapi.ui_settings()

    def nx_set(self, key: str, value) -> dict:
        from modules import nxapi
        if str(key) == "learn_from_chat":
            self.learn_toggle(bool(value))
            return nxapi.ui_settings()
        result=nxapi.ui_set(str(key), value)
        if str(key)=='ai_mode' and not llm.gemini_aux_allowed() and _live().get() is not None:
            _live().get().close()
        return result


from modules import studyexam, studymedia
from modules.study_services import StudyServices
bridge = Bridge(StudyServices(current_profile=lambda: _p(), study=study, exams=studyexam,
                             media=studymedia, llm=llm, privacy=privacy,
                             config=config, events=engine.events))


# ======================================================================= yazı tipleri (ilk açılışta indirilip saklanır)
_FONT_URL = ("https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Inter:wght@400;500;600;700"
             "&family=JetBrains+Mono:wght@400;500;700&display=swap")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_fonts_ready = threading.Event()


def _fetch_fonts() -> None:
    """Google Fonts'tan yalnızca latin ve latin-ext parçalarını indirip yerelde saklar (internet yoksa varsayılan fontlar kullanılır)."""
    try:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        out = FONT_DIR / "fonts.css"
        if out.exists():
            return
        import requests
        css = requests.get(_FONT_URL, headers={"User-Agent": _UA}, timeout=8).text
        blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S)
        keep = []
        got: dict[str, str] = {}
        for subset, block in blocks:
            if subset not in ("latin", "latin-ext"):
                continue
            m = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if not m:
                continue
            url = m.group(1)
            if url not in got:
                fn = f"f{len(got):02d}-{subset}.woff2"
                fp = FONT_DIR / fn
                if not fp.exists():
                    fp.write_bytes(requests.get(url, headers={"User-Agent": _UA}, timeout=10).content)
                got[url] = fn
            keep.append(block.replace(url, f"/fonts/{got[url]}"))
        if keep:
            out.write_text("\n".join(keep), encoding="utf-8")
    except Exception:
        _record_failure('web.py:_fetch_fonts')
        pass
    finally:
        _fonts_ready.set()


# ======================================================================= HTTP sunucusu
TOKEN = secrets.token_urlsafe(18)
SESSION_COOKIE = secrets.token_urlsafe(32)

PUBLIC = {"/", "/index.html", "/nx.html"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Jarvis"

    def log_message(self, *a):
        pass

    # --- yardımcılar
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _token(self) -> str:
        header = self.headers.get("X-Jarvis-Token") or ""
        if header:
            return header
        # Cookie is only for GET resources that cannot attach a custom header.
        if self.command != "GET":
            return ""
        from http.cookies import SimpleCookie, CookieError
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except CookieError:
            return ""
        item = cookie.get(self._cookie_name())
        return TOKEN if item and secrets.compare_digest(item.value, SESSION_COOKIE) else ""

    def _cookie_name(self) -> str:
        return "jarvis_session_" + str(self.server.server_address[1])

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # The UI builds inline event handlers/styles and displays remote image
        # thumbnails. Keep those existing features, but restrict scripts and
        # connections to this server and frames to the existing YouTube player.
        self.send_header("Content-Security-Policy", (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
            "font-src 'self'; connect-src 'self'; media-src 'self' data: blob:; "
            "frame-src https://www.youtube-nocookie.com; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        ))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    # --- GET
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, b"yasak", "text/plain")
        path = urlparse(self.path).path
        if path == "/events":
            return self._events()
        if path == "/arka_plan":                              # kullanıcının seçtiği arka plan resmi
            f = DATA_DIR / "arka_plan.img"
            if not secrets.compare_digest(self._token(), TOKEN) or not f.exists():
                return self._send(404, b"", "text/plain")
            d = f.read_bytes()
            ct = ("image/png" if d[:4] == b"\x89PNG" else "image/webp" if d[8:12] == b"WEBP" else "video/mp4"
                  if d[4:8] == b"ftyp" else "video/webm" if d[:4] == b"\x1aE\xdf\xa3" else "image/jpeg")
            return self._send(200, d, ct)
        if path == "/fonts.css":
            _fonts_ready.wait(5)
            f = FONT_DIR / "fonts.css"
            return self._send(200, f.read_bytes() if f.exists() else b"", "text/css; charset=utf-8")
        if path.startswith("/fonts/"):
            f = FONT_DIR / Path(path[7:]).name
            if f.exists():
                return self._send(200, f.read_bytes(), "font/woff2", {"Cache-Control": "max-age=31536000"})
            return self._send(404, b"", "text/plain")
        rel = "nx.html" if path in PUBLIC else path.lstrip("/")
        f = (WEB / rel).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            return self._send(404, b"yok", "text/plain")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    def _events(self) -> None:
        if not secrets.compare_digest(self._token(), TOKEN):
            return self._send(403, b"anahtar", "text/plain")
        q = hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=5)
                    self.wfile.write(b"data: " + json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            hub.unsubscribe(q)
            self.close_connection = True

    # --- POST
    def _reject_post(self) -> None:
        # Do not parse an unauthenticated body as the next HTTP request.
        # Drain only a small, bounded body so Windows can deliver the 403
        # before closing; oversized/incomplete input never holds a worker.
        self.close_connection = True
        previous_timeout = self.connection.gettimeout()
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if 0 < size <= 65536 and not self.headers.get("Transfer-Encoding"):
                deadline = time.monotonic() + 1.0
                while size:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(min(size, 8192))
                    if not chunk:
                        break
                    size -= len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self.connection.settimeout(previous_timeout)
        self._send(403, b"yasak", "text/plain", {"Connection": "close"})

    def do_POST(self) -> None:
        if not self._host_ok() or not secrets.compare_digest(self._token(), TOKEN):
            return self._reject_post()
        path = urlparse(self.path).path
        if path == "/session":
            return self._send(200, b"{}", "application/json", {
                "Set-Cookie": f"{self._cookie_name()}={SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict"
            })
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if path == "/upload":
            return self._upload(size)
        if size < 0 or size > 2_000_000:
            return self._json({"ok": False, "error": "İstek gövdesi 2 MB sınırını aşıyor."}, 413)
        body = self.rfile.read(size) if size else b""
        if not path.startswith("/api/"):
            return self._send(404, b"yok", "text/plain")
        name = path[5:]
        fn = getattr(bridge, name, None) if re.fullmatch(r"[a-z][a-z0-9_]*", name) else None
        if not callable(fn):
            return self._json({"ok": False, "error": f"Bilinmeyen çağrı: {name}"}, 404)
        try:
            args = json.loads(body or b"[]")
            if not isinstance(args, list):
                args = [args]
            owner = engine.pc_profile()
            token = _bridge_profile.set(owner)
            try:
                llm.set_user_context(owner.slug)
                self._json({"ok": True, "data": fn(*args)})
            finally:
                _bridge_profile.reset(token)
        except Exception as e:      # noqa: BLE001
            _record_failure('web.py:do_POST')
            self._json({"ok": False, "error": str(e) if isinstance(e, ValueError) else "İşlem tamamlanamadı; ayrıntı tanı günlüğüne kaydedildi."})

    def _upload(self, size: int) -> None:
        from modules.upload_stream import receive
        q = parse_qs(urlparse(self.path).query)
        name = Path((q.get("name") or ["belge"])[0]).name or "belge"
        if name in {".", ".."}:
            name = "belge"
        target = (q.get("to") or [""])[0]
        limit = {"files": 200_000_000, "bg": 80_000_000, "phone": 500_000_000}.get(target, 40_000_000)
        if size <= 0 or size > limit:
            self.close_connection = True
            return self._json({"ok": False, "error": f"Dosya boş ya da {limit//1_000_000} MB'tan büyük."}, 413)
        folder = None
        dest = None
        reserved = False
        try:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="upload_", dir=UPLOAD_DIR))
            temporary = folder / name
            receive(self.rfile, temporary, size)
            if target == "files":
                from modules import nxapi
                with temporary.open('rb') as source:
                    dest = nxapi.save_upload_stream(name, source)
                threading.Thread(target=_index_upload, args=(dest,), daemon=True, name="belge-dizin").start()
                return self._json({"ok": True, "data": {"path": str(dest), "name": dest.name}})
            if target == "bg":
                with temporary.open('rb') as source:
                    head = source.read(16)
                if not (head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or head[8:12] == b"WEBP"
                        or head[4:8] == b"ftyp" or head[:4] == b"\x1aE\xdf\xa3"):
                    raise ValueError("Yalnızca JPG, PNG, WEBP resim ya da MP4/WEBM video.")
                os.replace(temporary, DATA_DIR / "arka_plan.img")
                return self._json({"ok": True, "data": True})
            if target == "phone":
                from modules import filesend
                return self._json({"ok": True, "data": filesend.send(temporary)})
            # Reserve the KB name without overwriting another simultaneous upload.
            n = 0
            while True:
                dest = UPLOAD_DIR / (name if not n else f"{Path(name).stem}_{n}{Path(name).suffix}")
                try:
                    output = dest.open('xb')
                    reserved = True
                    break
                except FileExistsError:
                    n += 1
            with output, temporary.open('rb') as source:
                shutil.copyfileobj(source, output, length=1 << 20)
            try:
                entry = kb.add(_p(), str(dest))
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
            return self._json({"ok": True, "data": entry})
        except Exception as exc:
            _record_failure('web.py:_upload')
            self.close_connection = True
            # Failed KB copies must not leave a partial accepted file.
            if reserved and dest is not None and target not in {"files", "bg", "phone"}:
                dest.unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, ValueError) else "Dosya yüklenemedi; ayrıntı tanı günlüğüne kaydedildi."
            return self._json({"ok": False, "error": message})
        finally:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)


def _index_upload(path) -> None:
    """Dosyalar'a yüklenen belge aranabilir olsun (arka planda; başarısızlık yüklemeyi bozmaz)."""
    try:
        kb.index_files(_p(), [path])
    except Exception:
        _record_failure('web.py:_index_upload')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_server: Server | None = None


def _jarvis_hwnds() -> list[int]:
    from modules import web_window
    return web_window._jarvis_hwnds(sys.modules[__name__])


def _win_action(action: str) -> bool:
    from modules import web_window
    return web_window._win_action(sys.modules[__name__], action)


def _reopen_window() -> None:
    from modules import web_window
    return web_window._reopen_window(sys.modules[__name__])


def _close_windows() -> None:
    from modules import web_window
    return web_window._close_windows(sys.modules[__name__])


def _shutdown(close_windows: bool = True, reason: str = "kapatıldı") -> None:
    from modules import pc_guide
    pc_guide.stop()
    try:                                # normal kapanış loga yazılsın (çökmeyle karışmasın); os._exit beklemez
        import logging
        engine.log.info("Jarvis kapatıldı (%s, pid %d)", reason, os.getpid())
        for h in logging.getLogger().handlers:
            h.flush()
    except Exception:       # noqa: BLE001
        _record_failure('web.py:_shutdown')
        pass
    # Arka plan iş parçacıkları (sabah özeti, Google izin uyarısı...) süreç kilidi bırakılmadan önce dursun:
    # yeniden başlatmada yeni süreç kilidi alınca eski süreç artık ileti üretmemeli.
    engine.stop_event.set()
    try:
        import instance
        instance.release()
    except Exception:       # noqa: BLE001
        _record_failure('web.py:_shutdown')
        pass
    if close_windows:
        try:
            hub.publish("quit")         # açık sayfalar "Jarvis kapandı" göstersin
            time.sleep(0.3)
            _close_windows()
        except Exception:       # noqa: BLE001
            _record_failure('web.py:_shutdown')
            pass
    try:
        if _tray is not None:
            _tray.stop()            # tepsi simgesi hayalet olarak kalmasın
    except Exception:       # noqa: BLE001
        _record_failure('web.py:_shutdown')
        pass
    try:
        vision.stop()
        phone.stop()
        engine.stop_event.set()
        voice.stop_speaking()
    finally:
        os._exit(0)


def _capabilities() -> list:
    """Yetenek listesi: her madde gerçek duruma bağlı. durum: ready (çalışıyor) | setup (kurulum/ayar gerekli) | off."""
    from modules import tray as traymod
    st = llm.status()
    prof = _p()
    s = config.load_settings()
    mic_ok = True
    try:
        import sounddevice  # noqa: F401
    except Exception:
        _record_failure('web.py:_capabilities')
        mic_ok = False
    google_ok = google_api.token_path().exists()
    ollama = st["ollama_up"]
    out = []

    def add(group, name, en, status, note=""):
        out.append({"group": group, "name": name, "en": en, "status": status, "note": note})

    G = "Güçlü yetenekler"
    add(G, "Kişisel yapay zekâ işletim sistemi", "Personal AI operating system", "ready", "Komut merkezi, ajanlar, hafıza ve araçlar tek çatıda")
    add(G, "Windows yapay zekâ asistanı", "Windows AI assistant", "ready", "Uygulama, ses, parlaklık, kilit, kapatma")
    add(G, "Çoklu model yapay zekâ çalışma alanı", "Multi-model AI workspace", "ready",
        f"Gemini {len(st['gemini_models'])} model (yedekli)" + (" + Groq" if st["groq_key"] else "") + (f" + Ollama {len(st['ollama_models'])} yerel model" if ollama else ""))
    add(G, "Akıllı yapay zekâ ajanı", "Intelligent AI agent", "ready", "12 yetenek alanı, komutları kendisi sınıflandırır")
    add(G, "Yapay zekâ hafızası ve kişisel bağlam", "AI memory and personal context", "ready", f"{len(prof.data.get('facts') or [])} bilgi, hedefler, tercihler")
    add(G, "Bilgi erişimi (RAG)", "RAG knowledge retrieval", "ready", f"{len(prof.data.get('kb') or [])} belgeden yanıt")
    add(G, "Belge ve PDF desteği", "Document and PDF assistance", "ready", "PDF, DOCX, XLSX, TXT özet/çeviri")
    add(G, "Anlamsal arama", "Semantic search", "ready" if (st["gemini_key"] or ollama) else "setup",
        "Vektör araması; gömme alınamazsa anahtar kelime aramasına döner")
    add(G, "Sesli asistan ve eller serbest modu", "Voice assistant and hands-free mode", "ready" if mic_ok else "setup", "Uyandırma kelimesi: " + config.WAKE_WORD)
    add(G, "Windows masaüstü otomasyonu", "Windows desktop automation", "ready", "Uygulama açma, klavye/fare, dosya düzenleme")
    add(G, "Tarayıcı destekli otomasyon", "Browser-assisted automation", "off" if privacy.blocked("web") else "ready",
        "Web arama, site açma, sayfa özetleme (“sayfayı özetle site.com”)")
    add(G, "Araç çağırma ve çok adımlı yürütme", "Tool calling and multi-step execution", "ready", "“Önce X, sonra Y” komutları sırayla çalışır")
    add(G, "İş akışı otomasyonu", "Workflow automation", "ready", f"{len(prof.data.get('macros') or {})} kısayol/rutin")
    add(G, "Takvim ve e-posta desteği", "Calendar and email assistance", "ready" if google_ok else "setup",
        "Gmail ve Google Takvim (salt okuma)" if google_ok else "Menü › Yapay zekâ › Gmail ve Takvim bölümünden Google'ı bağla")
    add(G, "Ollama aracılığıyla yerel yapay zekâ", "Local AI through Ollama", "ready" if ollama else "setup",
        f"Model: {st['ollama_model']}" if ollama else "Ollama kurulu/çalışır değil (ollama.com)")
    cloud_names=(["Gemini"] if st["gemini_key"] else []) + (["Groq ("+st["groq_model"]+")"] if st["groq_key"] else [])
    cloud_names += [label for key,label in (("openai","OpenAI"),("anthropic","Claude")) if st.get("paid",{}).get(key,{}).get("key")]
    add(G, "Bulut yapay zekâ sağlayıcısı desteği", "Cloud AI provider support", "ready" if cloud_names else "setup",
        " · ".join(cloud_names) or "Anahtar ekle")
    add(G, "Gizlilik kontrolleri ve onay iş akışları", "Privacy controls and approval workflows", "ready", "Mod: " + privacy.mode())
    add(G, "Sistem tepsisi erişimi", "System tray access", "ready" if (traymod.available() and s.get("tray", True)) else "setup",
        "Simge sağ altta" if traymod.available() else "pip install pystray pillow gerekli")
    add(G, "Komuta Merkezi paneli", "Command Center dashboard", "ready", "Bu pencere")
    add(G, "Genişletilebilir entegrasyonlar", "Extensible integrations", "ready", f"{len(plugins.listing())} eklenti (~/.jarvis/plugins)")
    P = "Gizlilik ve kontrol"
    add(P, "Yerel yapay zekâ (Ollama)", "Local AI", "ready" if ollama else "setup", "“Yalnızca yerel” modda hiçbir şey buluta gitmez")
    add(P, "Yerel ses tanıma ve ses seçenekleri", "Local speech options", "ready" if mic_ok else "setup",
        "Ses tanıma Google'ın çevrimiçi servisini kullanır; “Yalnızca yerel” modda konuşma sesi çevrimdışı Windows sesiyle okunur")
    add(P, "Gizli kişisel bilgi/hafıza depolama", "Private memory storage", "ready", "Yalnızca bu bilgisayarda ~/.jarvis içinde")
    key_prot = config.legacy_key_protected()
    add(P, "Korumalı sağlayıcı kimlik bilgileri", "Protected provider credentials", "ready" if key_prot else "setup",
        "API anahtarı Windows hesabınla şifreli" if key_prot else "Anahtarı Entegrasyonlar'dan yeniden kaydet (Windows'ta şifrelenir)")
    add(P, "Yapılandırılabilir gizlilik modları", "Configurable privacy modes", "ready", "Normal · Gizli · Yalnızca yerel")
    add(P, "Hassas işlemler için onay", "Approval for sensitive actions", "ready" if s.get("approve_sensitive", True) else "off", "Mesaj gönderme, kapatma, dosya taşıma")
    add(P, "Harici eylem denetimi (geçmiş)", "Audit trail", "ready", f"{len(privacy.read_audit(1000))} kayıt")
    add(P, "Hassas bilgiyi gizleme (redaction)", "Redaction", "ready" if privacy.redact_enabled() else "off", "Anahtar, e-posta, kart, IBAN, telefon, T.C. no buluta gitmeden maskelenir")
    return out


# ======================================================================= pencere
def _find_browser() -> str | None:
    from modules import web_window
    return web_window._find_browser(sys.modules[__name__])


def _loading_hwnds() -> list[int]:
    from modules import web_window
    return web_window._loading_hwnds(sys.modules[__name__])


def _set_jarvis_icon(hwnd) -> None:
    from modules import web_window
    return web_window._set_jarvis_icon(sys.modules[__name__], hwnd)


def _center_window(wait: float = 15.0) -> None:
    from modules import web_window
    return web_window._center_window(sys.modules[__name__], wait)


def open_window(url: str) -> None:
    from modules import web_window
    return web_window.open_window(sys.modules[__name__], url)


_tray = None
_url = ""
_window_lock = threading.RLock()
_window_open_until = 0.0


def _watchdog() -> None:
    from modules import web_window
    return web_window._watchdog(sys.modules[__name__])


def _main_window_open() -> bool:
    from modules import web_window
    return web_window._main_window_open(sys.modules[__name__])


def _widget_should_hide() -> bool:
    from modules import web_window
    return web_window._widget_should_hide(sys.modules[__name__])


_aname_cache = {"t": 0.0, "v": "Jarvis"}


def _aname() -> str:
    from modules import web_window
    return web_window._aname(sys.modules[__name__])


def _show_main() -> None:
    from modules import web_window
    return web_window._show_main(sys.modules[__name__])


_widget = None


def _set_mic(on: bool) -> bool:
    from modules import web_window
    return web_window._set_mic(sys.modules[__name__], on)


def _run_widget() -> bool:
    from modules import web_window
    return web_window._run_widget(sys.modules[__name__])


def _start_tray() -> None:
    from modules import web_window
    return web_window._start_tray(sys.modules[__name__])


def serve(port: int = 0) -> tuple[Server, str]:
    from modules import pc_guide
    pc_guide.configure(sys.modules[__name__])
    global _server
    _server = Server(("127.0.0.1", port), Handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server, f"http://127.0.0.1:{_server.server_address[1]}/#key={TOKEN}"


def start_engine() -> None:
    def run() -> None:
        global _engine_running
        _engine_running = True
        try:
            engine.main(ui=on_engine)
        except Exception as exc:    # noqa: BLE001
            _record_failure('web.py:run')
            hub.publish("system", f"Motor durdu: {type(exc).__name__}: {exc}")
        finally:
            _engine_running = False
            marker = os.environ.get('JARVIS_BOOT_MARKERS')
            if marker:
                (Path(marker) / 'engine').unlink(missing_ok=True)
    threading.Thread(target=run, daemon=True).start()


def _github_watch() -> None:
    """Ana sayfadaki GitHub kartı için: açılıştan 40 sn sonra ve 10 dakikada bir yerel kaynakları GitHub main ile
    karşılaştırır (yalnız okur; hiçbir şey göndermez/kurmaz). Anahtar yoksa ya da ağ yoksa sessizce geçer."""
    time.sleep(40)
    while True:
        try:
            import updater as _u
            if _u.status().get("token"):
                _u.verify_sync()
        except Exception:   # noqa: BLE001
            _record_failure('web.py:_github_watch')
            pass
        time.sleep(600)


def main() -> None:
    try:
        import instance
        instance.take_over()                    # gui.py'den gelmediyse (python web.py) burada; ikinci çağrı bir şey yapmaz
    except Exception:       # noqa: BLE001
        _record_failure('web.py:main')
        raise SystemExit(1)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        _record_failure('web.py:main')
        pass
    threading.Thread(target=_fetch_fonts, daemon=True).start()
    sampler.start()
    threading.Thread(target=_github_watch, daemon=True).start()
    try:
        history.trim(_p().slug)
    except Exception:
        _record_failure('web.py:main')
        pass
    global _url
    _, url = serve()
    _url = url
    start_engine()
    llm.model_check_background()
    if config.load_settings().get("phone_auto"):
        try:
            phone.start()           # "Jarvis açılınca telefon erişimini aç" seçiliyse
        except OSError as exc:
            print(f"Telefon erişimi açılamadı: {type(exc).__name__}")
    _start_tray()
    print(f"Jarvis Komut Merkezi: {url}")
    for _old in ("index.html", "core.js", "cc.js", "pages.js", "pages2.js", "pages3.js", "reactor.js", "boot.js",
                 "style.css", "ironman.png", "ring.png"):     # eski arayüzün dosyaları (tek arayüz: nx)
        try:
            (WEB / _old).unlink(missing_ok=True)
        except OSError:
            pass
    if config.load_settings().get("fullscreen"):          # açılış her zaman normal pencere
        config.save_settings(fullscreen=False)
    _close_windows()        # önceki çalışmadan kalan Jarvis penceresi varsa yeni ayarlar uygulanabilsin
    time.sleep(0.5)
    open_window(url)
    from modules import startup_metrics
    startup_metrics.ready('window_open')
    import release_guard
    release_guard.ready("web")
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        _run_widget()               # masaüstü küçük Jarvis (sağ alt köşe)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        _shutdown(reason="Ctrl+C")


if __name__ == "__main__":
    main()

