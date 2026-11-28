import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from modules import mascot_audio_meter, mascot_face_runtime as face


class HybridFaceTests(unittest.TestCase):
    def test_mouth_changes_only_mapped_face_pixels(self):
        x, y, w, h = face.CROP
        uv = np.full((h, w, 2), 65535, dtype="<u2")
        # Map a rectangle covering the authored mouth.
        uu, vv = np.meshgrid(np.arange(240, 390), np.arange(260, 350))
        uv[:90, :150, 0] = uu * 16
        uv[:90, :150, 1] = vv * 16
        encoded = io.BytesIO()
        Image.new("RGBA", face.SIZE, (25, 25, 25, 255)).save(encoded, format="WEBP", lossless=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.jclip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", json.dumps({
                    "size": list(face.SIZE), "crop": list(face.CROP), "fps": 30, "frames": 1}))
                archive.writestr("body/0000.webp", encoded.getvalue())
                archive.writestr("map/0000.bin", uv.tobytes())
            stream = face.HybridFrameStream(path, size=face.SIZE)
            try:
                with patch.object(mascot_audio_meter, "aperture", return_value=0.0):
                    quiet = np.asarray(stream[0])
                with patch.object(mascot_audio_meter, "aperture", return_value=1.0):
                    speaking = np.asarray(stream[0])
                changed = np.any(quiet != speaking, axis=2)
                self.assertTrue(changed.any())
                changed[y:y + h, x:x + w] = False
                self.assertFalse(changed.any())
            finally:
                stream.close()
            self.assertEqual(len(stream), 0)
