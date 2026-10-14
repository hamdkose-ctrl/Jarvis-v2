"""Telefon erişimi: aynı Wi-Fi'deki telefondan Jarvis'e komut ver, yanıtları gör.

Güvenlik: sunucu varsayılan olarak kapalıdır, yalnızca elle açılır. QR adresinin '#' kısmında
90 saniyelik, tek kullanımlık eşleştirme kodu taşınır. Telefon bu kodu kişisel erişim belirtecine
çevirir; korumalı API istekleri X-Token başlığı kullanır. Kalıcı anahtarlar URL ile alınmaz.
Varsayılan HTTPS arkasında yalnız loopback dinlenir; düz HTTP LAN erişimi açık seçim gerektirir.
"""
from modules.diagnostics import record_failure as _record_failure
import queue
import json
import ipaddress
import logging

log = logging.getLogger("jarvis.phone")
import re
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import DATA_DIR, load_settings
from modules import mobile
from modules.phone_pages import PAGE, SIRI_PAGE

PORT = 8765
TOKEN_FILE = DATA_DIR / "phone_token.txt"

def _harden_token_file() -> None:
    _harden(TOKEN_FILE)


def _harden(path) -> None:
    """Anahtar dosyasını mümkün olduğunca yalnız mevcut kullanıcıya sınırlar.

    Düz metin biçimini korur; mevcut mobil/PC köprüleri bozulmaz. Windows'ta ACL,
    diğer sistemlerde 0600 izni uygulanır. Başarısız olursa telefon özelliği yine çalışır.
    """
    TOKEN_FILE_ = path
    try:
        os.chmod(TOKEN_FILE_, 0o600)
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            user = os.environ.get("USERNAME", "").strip()
            if user:
                subprocess.run(
                    ["icacls", str(TOKEN_FILE_), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except (OSError, subprocess.SubprocessError):
            pass


def _aname() -> str:
    """Asistanın Ayarlar'daki adı (telefon sayfası da aynı adı göstersin)."""
    return (str(load_settings().get("assistant_name") or "").strip() or "Jarvis")[:20]


def _named(html: str) -> str:
    """Sayfadaki "Jarvis" yazılarını asistanın güncel adıyla değiştirir (logo dahil)."""
    name = _aname()
    if name == "Jarvis":
        return html
    import html as _h
    esc = _h.escape(name)
    logo = "<i>.</i>".join(_h.escape(ch) for ch in name.upper())
    return (html.replace("J<i>.</i>A<i>.</i>R<i>.</i>V<i>.</i>I<i>.</i>S", logo)
                .replace("JARVIS", esc.upper()).replace("Jarvis", esc))






def get_token() -> str:
    try:
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok and len(tok) >= 24:
            _harden_token_file()
            return tok
        # v5.12 güvenlik geçişi: eski kısa telefon anahtarını bir kez otomatik yenile.
        # Eski QR/Siri kestirmesi bilinçli olarak geçersiz olur; yeni QR telefon ekranında gösterilir.
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(tok, encoding="utf-8")
    _harden_token_file()
    return tok


USER_TOKENS_FILE = DATA_DIR / "phone_tokens.json"     # kişiye özel telefon anahtarları: {kullanıcı_kısa_adı: anahtar}
_tok_lock = threading.RLock()
_token_cache = {}


def _slug(name: str | None) -> str:
    try:
        from modules.personalization import slugify
        return slugify(name or "")
    except Exception:   # noqa: BLE001
        _record_failure('modules/phone.py:_slug')
        return (name or "").strip().lower()


def _owner_slug() -> str:
    """Eski ortak anahtarın (phone_token.txt) sahibi. İlk kez gerektiğinde bilgisayardaki kullanıcı sahip yapılır
    ve kaydedilir; böylece ortak anahtarla başka kullanıcı adına konuşulamaz."""
    from config import save_settings
    own = str(load_settings().get("phone_owner") or "")
    if own:
        return own
    try:
        from modules.personalization import get_active
        own = _slug(get_active())
    except Exception:   # noqa: BLE001
        _record_failure('modules/phone.py:_owner_slug')
        own = ""
    if own:
        save_settings(phone_owner=own)
    return own


def _read_user_tokens() -> dict:
    """Validate file identity each time; reuse parsing without delaying key revocation."""
    with _tok_lock:
        try:
            st=USER_TOKENS_FILE.stat()
            identity=(str(USER_TOKENS_FILE), st.st_ino, st.st_mtime_ns, st.st_size)
            hit=_token_cache.get(identity)
            if hit is not None:return dict(hit)
            d=json.loads(USER_TOKENS_FILE.read_text(encoding='utf-8'))
            out={str(k):str(v) for k,v in d.items() if isinstance(v,str) and len(v)>=24} if isinstance(d,dict) else {}
            _token_cache.clear()
            _token_cache[identity]=out
            return dict(out)
        except (OSError,ValueError):
            _token_cache.clear()
            return {}


def user_token(name: str | None) -> str:
    """Bu kullanıcının telefon anahtarı (yoksa üretir). Sahip için eski ortak anahtar kullanılır (mevcut telefonlar bozulmasın)."""
    slug = _slug(name) or _owner_slug()
    if slug == _owner_slug():
        return get_token()
    with _tok_lock:
        toks = _read_user_tokens()
        if slug not in toks:
            toks[slug] = secrets.token_urlsafe(24)
            USER_TOKENS_FILE.write_text(json.dumps(toks, ensure_ascii=False), encoding="utf-8")
            try:
                _harden(USER_TOKENS_FILE)
            except Exception:   # noqa: BLE001
                _record_failure('modules/phone.py:user_token')
                pass
        return toks[slug]


def token_user(given: str) -> str | None:
    """Anahtarın sahibi olan kullanıcının kısa adı; geçersizse None. Kimin konuştuğunu telefonun gönderdiği ad değil,
    anahtar belirler (bir anahtarla başka kullanıcı adına komut verilemez, onun konuşmaları okunamaz)."""
    given = given or ""
    if not given or not given.isascii() or len(given) > 256:
        return None
    if secrets.compare_digest(given, get_token()):
        return _owner_slug() or None
    for slug, tok in _read_user_tokens().items():
        if tok.isascii() and secrets.compare_digest(given, tok):
            return slug
    return None


def qr_matrix(text: str):
    """Metni QR kodu karelerine çevirir (satırlar listesi, 1 = siyah). segno kurulu değilse None."""
    try:
        import segno
    except ImportError:
        return None
    return [[bool(cell) for cell in row] for row in segno.make(text, error="m", micro=False).matrix]


def tailscale_ip() -> str | None:
    """Tailscale kuruluysa bilgisayarın Tailscale adresi (100.64.0.0/10 aralığı), yoksa None."""
    try:
        import psutil
    except ImportError:
        return None
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family == socket.AF_INET:
                parts = a.address.split(".")
                if len(parts) == 4 and parts[0] == "100" and 64 <= int(parts[1]) <= 127:
                    return a.address
    return None


def tailscale_exe() -> str | None:
    """tailscale.exe yolu (PATH'te ya da Windows kurulum klasöründe), yoksa None."""
    found = shutil.which("tailscale")
    if found:
        return found
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(var)
        if base:
            p = os.path.join(base, "Tailscale", "tailscale.exe")
            if os.path.exists(p):
                return p
    return None


def tailscale_status() -> dict:
    """Tailscale'in durumu: kurulu mu, oturum açık mı, adres ve makine adı.
    state: 'missing' (kurulu değil) | 'stopped' | 'login' (oturum gerekli) | 'running'."""
    exe = tailscale_exe()
    ip = tailscale_ip()
    out = {"installed": bool(exe or ip), "state": "running" if ip else ("missing" if not exe else "stopped"),
           "ip": ip or "", "name": "", "user": ""}
    if not exe:
        return out
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5, creationflags=flags)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    backend = str(data.get("BackendState") or "")
    me = data.get("Self") or {}
    ips = me.get("TailscaleIPs") or []
    v4 = next((a for a in ips if "." in a), "")
    if backend == "Running" or v4:
        out.update(state="running", ip=v4 or out["ip"])
    elif backend in ("NeedsLogin", "NeedsMachineAuth"):
        out["state"] = "login"
    elif backend:
        out["state"] = "stopped"
    out["name"] = str(me.get("DNSName") or "").rstrip(".")
    users = data.get("User") or {}
    uid = str(me.get("UserID") or "")
    if uid in users:
        out["user"] = str(users[uid].get("LoginName") or "")
    return out


def _ts_run(args: list[str], timeout: int = 20) -> tuple[bool, str]:
    """Tailscale komutunu çalıştırır; takılırsa (örn. sertifika onayı bekliyorsa) o ana kadarki çıktıyı döndürür."""
    exe = tailscale_exe()
    if not exe:
        return False, "Tailscale kurulu değil."
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=flags)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired as e:
        def _t(x):
            return x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
        return False, "ZAMAN AŞIMI " + (_t(e.stdout) + _t(e.stderr)).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _serve_urls(text: str) -> list[str]:
    import re
    return re.findall(r"https://[A-Za-z0-9._-]+\.ts\.net(?::\d+)?", text or "")


def https_url(port: int = PORT, target_host: str = "127.0.0.1", strict: bool = False) -> str:
    """Tailscale Serve bu makine için 443'te açıksa https adresi, değilse ''."""
    ok, out = _ts_run(["serve", "status", "--json"], 8)
    if ok:
        try:
            data = json.loads(out or "{}")
            if not isinstance(data, dict): return ""
            if strict:
                web = data.get("Web") or {}
                tcp = data.get("TCP") or {}
                funnels = data.get("AllowFunnel") or {}
                if not all(isinstance(x, dict) for x in (web, tcp, funnels)): return ""
                tls = tcp.get("443") or {}
                if not isinstance(tls, dict) or tls.get("HTTPS") is not True: return ""
                expected = f"http://{target_host}:{port}"
                for host, cfg in web.items():
                    if not isinstance(host,str) or not host.endswith(":443") or funnels.get(host): continue
                    if not isinstance(cfg,dict): continue
                    handlers = cfg.get("Handlers") or {}
                    if not isinstance(handlers,dict): continue
                    handler = handlers.get("/") or {}
                    if isinstance(handler,dict) and str(handler.get("Proxy") or "").rstrip("/") == expected:
                        return "https://" + host[:-4]
                return ""
            for host in (data.get("Web") or {}):
                if host.endswith(":443"):
                    return "https://" + host[:-4]
            if (data.get("TCP") or {}).get("443"):
                st = tailscale_status()
                if st.get("name"):
                    return "https://" + st["name"]
        except ValueError:
            pass
    if strict: return ""  # Older text output cannot prove the target and Funnel policy.
    ok, out = _ts_run(["serve", "status"], 8)     # eski sürümlerde JSON çıktısı yok
    if ok:
        urls = _serve_urls(out)
        if urls and "proxy" in out.lower():
            return urls[0]
    return ""


def https_set(on: bool, port: int, target_host: str = "127.0.0.1") -> tuple[bool, str]:
    """Telefon sunucusunu Tailscale'in geçerli sertifikalı https adresine bağlar (mikrofon için gerekir)."""
    if not on:
        ok, out = _ts_run(["serve", "--https=443", "off"], 15)
        if not ok:
            ok, out = _ts_run(["serve", "reset"], 15)
        return ok, out[-400:]
    target = f"http://{target_host}:{port}"
    ok, out = _ts_run(["serve", "--bg", target], 45)
    if not ok and "--bg" in out and ("unknown" in out.lower() or "flag" in out.lower()):
        ok, out = _ts_run(["serve", "https", "/", target], 45)          # eski sürüm sözdizimi
    low = out.lower()
    link = ""
    import re
    m = re.search(r"https://login\.tailscale\.com/\S+", out)
    if m:
        link = m.group(0)
    if not ok and (link or "not enabled" in low or "https" in low and ("enable" in low or "certificate" in low) or out.startswith("ZAMAN AŞIMI")):
        msg = ("Tailscale hesabında HTTPS/Serve henüz etkin değil. Şu sayfada onayla, sonra bu düğmeye tekrar bas: "
               + (link or "login.tailscale.com/admin/dns  (HTTPS Certificates → Enable HTTPS)"))
        return False, msg
    if ok and not https_url(port=port, target_host=target_host, strict=True):
        urls = _serve_urls(out)
        return (True, out[-400:]) if urls else (False, "Komut çalıştı ama https adresi görünmüyor: " + out[-300:])
    return ok, out[-500:]


def reset_token() -> str:
    """Telefon anahtarlarını (sahibinki ve kişiye özel olanlar) yeniler; eski adresler ve kayıtlı telefonlar bir daha giremez."""
    tok = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(tok, encoding="utf-8")
    _harden_token_file()
    with _tok_lock:
        try:
            USER_TOKENS_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    return tok


def lan_ip() -> str:
    """Bilgisayarın yerel ağ adresi (telefonun bağlanacağı)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # paket gönderilmez, yalnızca doğru ağ arayüzü seçilir
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def allowed_peer(address, scope="both"):
    """Only local/LAN and encrypted tailnet source addresses are accepted."""
    try:
        peer = ipaddress.ip_address(address)
        if getattr(peer, 'ipv4_mapped', None): peer = peer.ipv4_mapped
    except ValueError:
        return False
    if peer.is_loopback: return True  # Local HTTPS reverse proxy.
    if scope == "secure": return False
    tailnets = (ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48'))
    if any(peer.version == net.version and peer in net for net in tailnets): return True
    if scope != 'both': return False
    lans = (ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'), ipaddress.ip_network('192.168.0.0/16'))
    return any(peer.version == net.version and peer in net for net in lans)


class PhoneServer:
    def __init__(self, engine, port: int = PORT):
        self.engine = engine
        self.port = port
        self.token = get_token()
        self._httpd: ThreadingHTTPServer | None = None
        self._fails = 0
        self._auth_failures: dict[str, tuple[int, float]] = {}
        self._auth_lock = threading.Lock()
        self.https = ""
        self._pairs: dict[str, tuple[str, float]] = {}
        self._pair_lock = threading.Lock()
        self._seen: dict[str, float] = {}
        from modules.android_setup import SetupGrants
        self.android_setup = SetupGrants()

    def connected(self, user: str | None) -> bool:
        with self._pair_lock:
            return self.running and time.monotonic() - self._seen.get(_slug(user), float("-inf")) < 20

    def clear_pairings(self, user: str | None = None) -> None:
        self.android_setup.clear(_slug(user) if user else None)
        with self._pair_lock:
            if user:
                slug = _slug(user)
                self._pairs = {k: v for k, v in self._pairs.items() if v[0] != slug}
            else:
                self._pairs.clear()
                self._seen.clear()

    def pairing_code(self, user: str | None) -> str:
        """QR: 90 saniyelik tek kullanımlık kod; kişisel API anahtarı içermez."""
        slug = _slug(user) or _owner_slug()
        now = time.monotonic()
        with self._pair_lock:
            self._pairs = {k: v for k, v in self._pairs.items() if v[1] > now}
            for code, (owner, _) in self._pairs.items():
                if owner == slug:
                    return code
            if len(self._pairs) >= 200:
                self._pairs.pop(next(iter(self._pairs)))
            code = secrets.token_urlsafe(24)
            self._pairs[code] = (slug, now + 90)
            return code

    def redeem_pairing(self, code: str) -> str | None:
        with self._pair_lock:
            pair = self._pairs.pop(code, None)
        if not pair or pair[1] <= time.monotonic() or self.user_of(pair[0]) is None:
            return None
        return user_token(pair[0])

    @property
    def url(self) -> str:
        urls = self.urls()
        return urls[0][1] if urls else ""

    @staticmethod
    def scope() -> str:
        """HTTPS is the default; LAN HTTP requires a new explicit opt-in."""
        st = load_settings()
        chosen = st.get("phone_scope")
        if chosen == "tailscale": return chosen
        if chosen == "both" and st.get("phone_allow_http") is True: return chosen
        return "secure"

    def urls(self, user: str | None = None) -> list[tuple[str, str]]:
        """Gösterilecek adresler: (etiket, adres). Tailscale varsa ilk sıradadır. user: kimin telefonu
        (her kullanıcının adresinde kendi eşleştirme kodu vardır; boşsa sahibin kodu)."""
        code = self.pairing_code(user)
        out = []
        ts = tailscale_ip()
        hu = getattr(self, "https", "")
        if hu:
            out.append(("Her yerden · HTTPS (mikrofon çalışır)", f"{hu}/#p={code}"))
        if ts and self.scope() != "secure":
            out.append(("Her yerden (Tailscale)", f"http://{ts}:{self.port}/#p={code}"))
        if self.scope() == "both":
            out.append(("Aynı Wi-Fi", f"http://{lan_ip()}:{self.port}/#p={code}"))
        return out

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> str:
        if self._httpd is None:
            outer = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *a):   # konsolu doldurmasın
                    pass

                def _auth_limited(self) -> bool:
                    ip = self.client_address[0] if self.client_address else "?"
                    now = time.time()
                    with outer._auth_lock:
                        count, first = outer._auth_failures.get(ip, (0, now))
                        if now - first > 60:
                            outer._auth_failures[ip] = (0, now)
                            return False
                        return count >= 8

                def _auth_failed(self) -> None:
                    ip = self.client_address[0] if self.client_address else "?"
                    now = time.time()
                    with outer._auth_lock:
                        count, first = outer._auth_failures.get(ip, (0, now))
                        if now - first > 60:
                            count, first = 0, now
                        outer._auth_failures[ip] = (count + 1, first)
                    with outer._auth_lock:
                        outer._fails += 1

                def _ok(self) -> bool:
                    if self._auth_limited():
                        self._json({"error": "çok fazla yetkisiz deneme"}, 429)
                        return False
                    given = self.headers.get("X-Token", "")
                    who = token_user(given)
                    if who:
                        if outer.user_of(who) is None:  # anahtarın sahibi silinmiş: bilgisayardaki kullanıcıya düşme
                            self._json({"error": "bu anahtarın kullanıcısı bulunamadı"}, 403)
                            return False
                        self.who = who                  # bu isteğin kullanıcısı: anahtardan, telefonun söylediği addan değil
                        with outer._pair_lock:
                            outer._seen[who] = time.monotonic()
                        return True
                    self._auth_failed()
                    self._json({"error": "yetkisiz"}, 401)
                    return False

                def _common_headers(self) -> None:
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-Frame-Options", "DENY")
                    self.send_header("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
                    self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

                def _read_body(self, size):
                    data = self.rfile.read(size)
                    self._unread = max(0, getattr(self, "_unread", 0) - len(data))
                    return data

                def _drain_body(self) -> None:
                    # Yanıt gövde okunmadan gidip soket kapanırsa alıcı tamponda veri kalır; Windows FIN yerine RST
                    # gönderir ve istemci 429/400 yanıtını okuyamaz. Yalnız küçük gövde (≤64 KiB) en çok 1 sn
                    # beklenerek tüketilir; büyük/eksik gövde sunucuyu bekletmez. Bağlantı her durumda kapanır.
                    size, self._unread = getattr(self, "_unread", 0), 0
                    self.close_connection = True
                    if not 0 < size <= 65536 or self.headers.get("Transfer-Encoding"):
                        return
                    previous = self.connection.gettimeout()
                    deadline = time.monotonic() + 1.0
                    try:
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
                        self.connection.settimeout(previous)

                def _json(self, obj, code=200, headers=None):
                    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                    unread = getattr(self, "_unread", 0) > 0
                    if unread:
                        self._drain_body()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self._common_headers()
                    for key, value in (headers or {}).items():
                        self.send_header(key, value)
                    if unread:
                        self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)

                def do_GET(self):
                    if not allowed_peer(self.client_address[0], outer.scope()):
                        self._json({"error": "Telefon erişimi yalnız yerel ağ/Tailscale üzerinden kullanılabilir"}, 403)
                        return
                    path, _, query = self.path.partition("?")
                    if path == "/api/web-session":
                        # Custom header blocks cross-site form/navigation recovery; no CORS is granted.
                        if self.headers.get("X-Jarvis-Web-Session") != "1":
                            self._json({"error": "geçersiz oturum isteği"}, 403)
                            return
                        if self._auth_limited():
                            self._json({"error": "çok fazla yetkisiz deneme"}, 429)
                            return
                        try:
                            cookies = SimpleCookie()
                            cookies.load(self.headers.get("Cookie", "")[:4096])
                            item = cookies.get("jarvis_web_session")
                            token = item.value if item else ""
                        except CookieError:
                            token = ""
                        who = token_user(token)
                        if not who or outer.user_of(who) is None:
                            self._auth_failed()
                            self._json({"error": "oturum bulunamadı"}, 401)
                            return
                        self._json({"token": token})
                        return
                    asset = mobile.resource(path, _aname())
                    if asset:
                        mime, body = asset
                        self.send_response(200)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Length", str(len(body)))
                        self._common_headers()
                        self.end_headers()
                        self.wfile.write(body)
                    elif path == "/":
                        body = _named(PAGE).encode("utf-8")   # sayfada gizli bilgi yok; anahtar tarayıcıda
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self._common_headers()
                        self.end_headers()
                        self.wfile.write(body)
                    elif path == "/siri":
                        body = _named(SIRI_PAGE).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self._common_headers()
                        self.end_headers()
                        self.wfile.write(body)
                    elif path == "/api/ask":
                        # URL credentials are deliberately rejected, even if otherwise valid.
                        self._json({"error": "Bu eski kestirme artık desteklenmiyor. /siri ekranından POST ve X-Token başlığıyla yeniden kur."}, 410)
                    elif path == "/api/notes":
                        if not self._ok(): return
                        from modules import fieldnotes
                        profile = outer.engine._get_profile(self.who)
                        self._json({"notes": fieldnotes.list_notes(profile), "user": profile.slug})
                    elif path == "/api/history":
                        if not self._ok(): return
                        from modules import history
                        self._json(history.read(_slug(self.who), limit=300))
                    elif path == "/api/log" and self._ok():
                        try:
                            after = int(dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("after", 0))
                        except ValueError:
                            after = 0
                        mine = outer.user_filter(outer.user_of(self.who))   # yalnız anahtarın sahibinin konuşmaları
                        self._json([e for e in list(outer.engine.event_log) if e["id"] > after and mine(e.get("user"))])
                    elif path == "/api/users" and self._ok():
                        try:
                            from modules.personalization import get_active, list_users
                            names, pc = list_users(), get_active()
                        except Exception:
                            _record_failure('modules/phone.py:do_GET')
                            names, pc = [], ""
                        me = outer.user_of(self.who) or next((n for n in names if _slug(n) == self.who), self.who)
                        # Her anahtar tek bir kişiye ait: telefon yalnız kendi kullanıcısını görür ve seçebilir.
                        self._json({"list": [me], "active": me, "pc": me})
                    elif path not in ("/api/log", "/api/users", "/api/ask", "/siri"):
                        self._json({"error": "yok"}, 404)

                def do_POST(self):
                    try:
                        self._unread = max(0, int(self.headers.get("Content-Length") or 0))
                    except ValueError:
                        self._unread = 0
                    if not allowed_peer(self.client_address[0], outer.scope()):
                        self._json({"error": "Telefon erişimi yalnız yerel ağ/Tailscale üzerinden kullanılabilir"}, 403)
                        return
                    if self.path == "/api/android-setup":
                        # Only a local reverse proxy (Tailscale HTTPS Serve) may
                        # expose this endpoint; never send credentials over LAN HTTP.
                        if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                            return self._json({"error": "HTTPS aktarımı gerekli."}, 403)
                        from urllib.parse import urlparse
                        host = (self.headers.get('Host') or '').split(':')[0].lower()
                        trusted = {'127.0.0.1', 'localhost', urlparse(outer.https).hostname}
                        if host not in trusted or self.headers.get('Origin'):
                            return self._json({"error": "Kurulum kaynağı reddedildi."}, 403)
                        if self._auth_limited():
                            return self._json({"error": "Çok fazla deneme."}, 429)
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 1024:
                                raise ValueError('boyut')
                            body = json.loads(self._read_body(size))
                            if not isinstance(body, dict) or not isinstance(body.get('code'), str):
                                raise ValueError('kod')
                            def key_for(owner):
                                return outer.engine.llm.user_key(owner) if outer.user_of(owner) else ''
                            result = outer.android_setup.redeem(body['code'], key_for)
                        except (ValueError, OSError):
                            return self._json({"error": "Geçersiz kurulum isteği."}, 400)
                        if result is None:
                            self._auth_failed()
                            return self._json({"error": "Kurulum kodu kullanılmış veya süresi dolmuş."}, 401)
                        return self._json(result)
                    if self.path == "/api/web-session":
                        if not self._ok(): return
                        self._json({"ok": True}, headers={"Set-Cookie":
                            "jarvis_web_session=" + self.headers.get("X-Token", "") +
                            "; Path=/api/web-session; Max-Age=31536000; Secure; HttpOnly; SameSite=Strict"})
                        return
                    if self.path == "/api/notes":
                        if not self._ok(): return
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 2_000_000: raise ValueError("boyut")
                            payload = json.loads(self._read_body(size))
                            from modules import fieldnotes
                            owner = outer.engine._get_profile(self.who)
                            result = fieldnotes.sync(owner, payload.get("notes"))
                            self._json(result)
                        except (ValueError, TypeError, AttributeError) as exc:
                            self._json({"error": str(exc)}, 400)
                        return
                    if self.path == "/api/pair":
                        if self._auth_limited():
                            self._json({"error": "Çok fazla deneme. Bir dakika sonra tekrar dene."}, 429)
                            return
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 1024:
                                raise ValueError("boyut")
                            payload = json.loads(self._read_body(size))
                            if not isinstance(payload, dict) or not isinstance(payload.get("code"), str):
                                raise ValueError("kod")
                            token = outer.redeem_pairing(payload["code"])
                        except (ValueError, OSError):
                            self._json({"error": "Geçersiz eşleşme isteği."}, 400)
                            return
                        if not token:
                            self._auth_failed()
                            self._json({"error": "QR kullanılmış veya süresi dolmuş. Bilgisayarda QR’ı yenileyip tekrar okut."}, 401)
                        else:
                            self._json({"token": token})
                        return
                    if self.path == "/api/photo":
                        if not self._ok():
                            return
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 8_000_000:
                                raise ValueError("boyut")
                            data = self._read_body(size)
                            jpeg = data[:2] == b"\xff\xd8"
                            if not jpeg and data[:4] != b"\x89PNG":
                                raise ValueError("tür")
                            q = urllib.parse.unquote(self.headers.get("X-Question", ""))[:300]
                            fn = getattr(outer.engine, "submit_photo", None)
                            if fn is None:
                                raise ValueError("desteklenmiyor")
                            fd, tmp = tempfile.mkstemp(prefix="jarvis_foto_", suffix=".jpg" if jpeg else ".png")
                            with os.fdopen(fd, "wb") as fh:
                                fh.write(data)
                            fn(tmp, q, "telefon", outer.user_of(self.who))
                            self._json({"ok": True})
                        except (ValueError, OSError):
                            self._json({"error": "geçersiz fotoğraf"}, 400)
                        return
                    if self.path == "/api/audio":
                        if not self._ok():
                            return
                        tmp, queued = None, False
                        response, code = {"ok": True}, 200
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 4_000_000:
                                raise ValueError("boyut")
                            data = self._read_body(size)
                            if data[:4] != b"RIFF":
                                raise ValueError("tür")
                            fn = getattr(outer.engine, "submit_audio", None)
                            if fn is None:
                                raise ValueError("desteklenmiyor")
                            fd, tmp = tempfile.mkstemp(prefix="jarvis_ses_", suffix=".wav")
                            with os.fdopen(fd, "wb") as fh:
                                fh.write(data)
                            if fn(tmp, "telefon", outer.user_of(self.who)) is False:
                                raise ValueError("İstek kuyruğa alınmadı")
                            queued = True
                        except (ValueError, OSError):
                            response, code = {"error": "geçersiz ses"}, 400
                        finally:
                            if tmp and not queued:
                                try:
                                    os.remove(tmp)
                                except OSError:
                                    pass
                        # Complete rejection cleanup before acknowledging it;
                        # receiving HTTP 400 must not race the temp-file removal.
                        self._json(response, code)
                        return
                    if self.path == "/api/ask":
                        # Siri Kestirmesi / Android uygulaması: soruyu gönderir, yanıtı bekleyip düz metin olarak döndürür.
                        if not self._ok():
                            return
                        try:
                            size = int(self.headers.get("Content-Length", 0))
                            if not 0 < size <= 4000:
                                raise ValueError("boyut")
                            payload = json.loads(self._read_body(size) or b"{}")
                            if not isinstance(payload, dict):
                                raise ValueError("JSON nesnesi bekleniyordu")
                            text = str(payload.get("text", ""))[:500]
                        except (ValueError, OSError):
                            self._json({"error": "bozuk istek"}, 400)
                            return
                        self._json({"reply": outer.ask(text, self.who)})
                        return
                    if self.path != "/api/send":
                        return self._json({"ok": False, "error": "Bilinmeyen yol."}, 404)
                    if not self._ok():
                        return
                    try:
                        size = int(self.headers.get("Content-Length", 0))
                        if not 0 < size <= 2000:
                            raise ValueError("boyut")
                        payload = json.loads(self._read_body(size) or b"{}")
                        if not isinstance(payload, dict):
                            raise ValueError("JSON nesnesi bekleniyordu")
                        text = str(payload.get("text", ""))[:500]
                    except (ValueError, OSError):
                        self._json({"error": "bozuk istek"}, 400)
                        return
                    rid = str(payload.get("rid") or "")[:80]
                    if rid and re.fullmatch(r"[A-Za-z0-9_-]{8,80}", rid):
                        outer.engine.submit(text, "telefon", outer.user_of(self.who), rid=rid)
                    else:
                        outer.engine.submit(text, "telefon", outer.user_of(self.who))
                    self._json({"ok": True})

            host = "127.0.0.1"
            if self.scope() == "secure":
                self.https = https_url(port=self.port, strict=True)
                if not self.https:
                    raise OSError("Güvenli telefon bağlantısı henüz hazır değil. Telefon ekranından Tailscale HTTPS’i aç; ardından telefon erişimini aç.")
            elif self.scope() == "both":
                host = "0.0.0.0"
            elif self.scope() == "tailscale":
                host = tailscale_ip() or ""
                if not host:
                    raise OSError("“Yalnızca Tailscale” seçili ama Tailscale bağlı değil. Önce Tailscale’i aç ya da kapsamı değiştir.")
            self.token = get_token()

            class _PhoneHTTPServer(ThreadingHTTPServer):
                daemon_threads = True
                request_queue_size = 16
                allow_reuse_address = True

            self._httpd = _PhoneHTTPServer((host, self.port), Handler)
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self.url

    def ask(self, text: str, user: str = "", timeout: float = 90) -> str:
        """Soruyu motora verir ve yanıtı bekler (telefon kestirmeleri için). Yanıt sesli okunmaya uygun düz metindir."""
        eng = self.engine
        text = (text or "").strip()
        if not text:
            return "Seni duyamadım, bir daha söyler misin?"
        low = text.replace("I", "ı").replace("İ", "i").lower().strip(" .!?")
        if low in ("kapat", "çık"):
            return "Telefondan kapatamam, bilgisayardan kapatabilirsin."
        who = self.user_of(user)
        if user and who is None:
            return "Telefon kullanıcısı bulunamadı; yeniden kullanıcı seç."
        if low in ("dur", "sus", "yeter", "stop"):
            eng.submit(text, "telefon", who)
            return "Tamam."
        # Her soruya ayrı bir kimlik (rid) verilir; yanıt metne/kullanıcıya göre değil bu kimliğe göre bulunur.
        # Böylece aynı kişinin aynı anda gönderdiği iki soru ya da aynı cümle tekrarlanınca yanıtlar karışmaz.
        rid = secrets.token_hex(8)
        start = getattr(eng, "_log_id", 0)
        from modules.personalization import slugify
        owner=slugify(who or eng.pc_profile().name) if hasattr(eng,'pc_profile') else _slug(who)
        waiters=getattr(eng,'response_waiters',None)
        import contextlib
        scope=waiters.subscribe(owner,rid) if waiters is not None else contextlib.nullcontext(None)
        with scope as inbox:
            accepted = eng.submit(text, "telefon", who, rid=rid)
            if accepted is False:
                return "İstek kuyruğa alınmadı; yeniden gönder."
            mine = self.user_filter(who)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                stop = getattr(eng, "stop_event", None)
                if stop is not None and stop.is_set():
                    return "Jarvis kapandı; yeniden açtıktan sonra dene."
                if hasattr(eng, "requests_state") and eng.requests_state.is_cancelled(owner,rid):
                    return "İşlem iptal edildi veya süresi doldu."
                if inbox is not None:
                    try:return self._for_speech(inbox.get(timeout=min(.25,max(0,deadline-time.monotonic()))))
                    except queue.Empty:continue
                # Compatibility for older engine adapters without the notification service.
                lock=getattr(eng,'_event_lock',None)
                with lock if lock is not None else contextlib.nullcontext():
                    rows=list(eng.event_log)
                for e in rows:
                    if e["id"] > start and e.get("rid") == rid and e["kind"] == "assistant" and mine(e.get("user")):
                        return self._for_speech(e["text"])
                time.sleep(.25)
            if hasattr(eng, "requests_state"):
                eng.requests_state.cancel(owner,rid)
            return f"{_aname()} şu an yanıt veremedi, biraz sonra tekrar dener misin?"

    def user_of(self, name: str | None) -> str | None:
        """Telefonun bildirdiği adı kayıtlı kullanıcıyla eşleştirir; boş/bilinmiyorsa bilgisayardaki kullanıcı (None)."""
        fn = getattr(self.engine, "match_user", None)
        try:
            return fn(name) if fn else None
        except Exception:
            _record_failure('modules/phone.py:user_of')
            return None

    def user_filter(self, who: str | None):
        """Bu telefonun kullanıcısına ait konuşma satırlarını seçen fonksiyon (who None ise bilgisayardaki kullanıcı)."""
        try:
            from modules.personalization import get_active, slugify
            pc = get_active()
            target = slugify(who or pc)
            return lambda ev_user: slugify(ev_user or pc) == target
        except Exception:
            _record_failure('modules/phone.py:user_filter')
            return lambda ev_user: False

    def _for_speech(self, out: str) -> str:
        eng = self.engine
        try:
            rt = getattr(eng, "richtext", None)
            if rt is not None and hasattr(rt, "speakable"):
                out = rt.speakable(out)
            if hasattr(eng, "_short_for_speech"):
                out = eng._short_for_speech(out, 900)
        except Exception:
            _record_failure('modules/phone.py:_for_speech')
        return out

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self.clear_pairings()
