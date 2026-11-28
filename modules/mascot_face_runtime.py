"""Runtime face compositor for the approved geometry-mapped body clip."""
import io
import json
import math
import time
import zipfile

import numpy as np
from PIL import Image, ImageDraw

from modules import mascot_audio_meter

SIZE = (480, 618)
CROP = (110, 125, 250, 165)
COLOR = (53, 220, 244, 255)


def artwork(aperture, blink):
    """Approved fixed eye anchors and minimal cyan mouth."""
    image = Image.new("RGBA", (650, 440))
    draw = ImageDraw.Draw(image)

    def xy(x, y):
        return (x - 170) * 5, (y - 183) * 5

    half_height = max(1.5, 16 * (1 - blink))
    for sign in (-1, 1):
        x, y = 233.1 + sign * 32.9, 220.3
        draw.ellipse((*xy(x - 10, y - half_height), *xy(x + 10, y + half_height)), fill=COLOR)
    x, y = 233.1, 246.
    if aperture > .06:
        rw, rh = 8 - 3.5 * aperture, 1.35 + 4.7 * aperture
        draw.ellipse((*xy(x - rw, y - rh), *xy(x + rw, y + rh)), fill=COLOR)
        if rh > 2:
            iw, ih = max(.3, rw - 1.8), rh - 1.8
            draw.ellipse((*xy(x - iw, y - ih), *xy(x + iw, y + ih)), fill=(0, 0, 0, 0))
    else:
        left, right = xy(x - 8, y), xy(x + 8, y)
        draw.line([left, right], fill=COLOR, width=13)
        for xx, yy in (left, right):
            draw.ellipse((xx - 6.5, yy - 6.5, xx + 6.5, yy + 6.5), fill=COLOR)
    return np.asarray(image)[:, :, 3]


class HybridFrameStream:
    """Read only the current body and geometry map; compose face in real time."""
    def __init__(self, path, *, size, first_only=False):
        self.archive = zipfile.ZipFile(path)
        try:
            manifest = json.loads(self.archive.read("manifest.json"))
            if manifest["size"] != list(SIZE) or manifest["crop"] != list(CROP):
                raise ValueError("mascot asset geometry mismatch")
            self.count = int(manifest["frames"])
            self.fps = int(manifest["fps"])
            if not 0 < self.count <= 3600 or not 1 <= self.fps <= 60:
                raise ValueError("mascot asset timing outside limits")
            if first_only:
                self.count = 1
        except Exception:
            self.archive.close()
            raise
        self.size = tuple(size)
        self.first_only = first_only
        self.started = time.monotonic()
        mascot_audio_meter.enable(not first_only)

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        x, y, w, h = CROP
        with Image.open(io.BytesIO(self.archive.read(f"body/{index:04d}.webp"))) as image:
            body = image.convert("RGBA")
        if body.size != SIZE:
            raise ValueError("mascot body size mismatch")
        uv = np.frombuffer(self.archive.read(f"map/{index:04d}.bin"), dtype="<u2").reshape(h, w, 2)
        now = time.monotonic()
        phase = abs(((now - self.started) % 3.6) - 2.6) / .12
        blink = .5 * (1 + math.cos(math.pi * phase)) if phase < 1 and not self.first_only else 0.0
        aperture = mascot_audio_meter.aperture(now) if not self.first_only else 0.0
        u, v = uv[:, :, 0].astype(np.float32) / 16, uv[:, :, 1].astype(np.float32) / 16
        valid = (u < 649) & (v < 439)
        u, v = np.where(valid, u, 0), np.where(valid, v, 0)
        i, j = u.astype(np.int32), v.astype(np.int32)
        du, dv = u - i, v - j
        a = artwork(aperture, blink)
        alpha = ((1 - dv) * ((1 - du) * a[j, i] + du * a[j, i + 1])
                 + dv * ((1 - du) * a[j + 1, i] + du * a[j + 1, i + 1]))
        overlay = np.zeros((h, w, 4), np.uint8)
        overlay[:, :, :3] = COLOR[:3]
        overlay[:, :, 3] = np.where(valid, alpha, 0).astype(np.uint8)
        body.alpha_composite(Image.fromarray(overlay), (x, y))
        if body.size != self.size:
            body = body.resize(self.size, Image.Resampling.LANCZOS)
        body.info["duration"] = round((index + 1) * 1000 / self.fps) - round(index * 1000 / self.fps)
        return body

    def close(self):
        mascot_audio_meter.enable(False)
        self.archive.close()
        self.count = 0
