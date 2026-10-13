"""Android/iOS ortak telefon uygulamasının herkese açık, kişisel veri içermeyen kaynakları."""
import json
import math
import struct
import zlib
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "webui" / "mobile"


def manifest(name: str) -> bytes:
    return json.dumps({
        "id": "/", "name": name, "short_name": name, "lang": "tr",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#e8f0fb", "theme_color": "#e8f0fb",
        "description": "Bilgisayarındaki kişisel asistana güvenli telefon bağlantısı",
        "icons": [{"src": f"/icon-{s}.png", "sizes": f"{s}x{s}",
                   "type": "image/png", "purpose": "any maskable"} for s in (192, 512)],
    }, ensure_ascii=False).encode("utf-8")


@lru_cache(maxsize=3)
def icon(size: int) -> bytes:
    """Harici paket gerektirmeyen, maskelenebilir reaktör simgesi (PNG)."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG satır filtresi
        for x in range(size):
            r = math.hypot(x + .5 - size / 2, y + .5 - size / 2) / size
            glow = max(0., 1 - abs(r - .25) / .055)
            if r < .067 or abs(r - .25) < .009 or abs(r - .32) < .004:
                rows.extend((51, 214, 255))
            else:
                rows.extend((5 + int(9 * glow), 13 + int(43 * glow), 28 + int(60 * glow)))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def resource(path: str, name: str):
    """Yalnız sabit izin listesindeki kaynaklar; kullanıcı yolu/dosyası açılmaz."""
    if path == "/manifest.json":
        return "application/manifest+json; charset=utf-8", manifest(name)
    if path in ("/icon-180.png", "/icon-192.png", "/icon-512.png"):
        return "image/png", icon(int(path[6:-4]))
    files = {"/sw.js": ("text/javascript; charset=utf-8", "sw.js"),
             "/mobile-install.js": ("text/javascript; charset=utf-8", "install.js"),
             "/offline.html": ("text/html; charset=utf-8", "offline.html"),
             "/notes.html": ("text/html; charset=utf-8", "notes.html"),
             "/notes.js": ("text/javascript; charset=utf-8", "notes.js")}
    if path in files:
        mime, filename = files[path]
        return mime, (ASSETS / filename).read_bytes()
    return None
