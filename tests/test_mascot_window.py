"""T5 masaüstü maskot penceresinin Tk'siz saf mantık testleri (pencere açılmaz)."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from modules import mascot_window


class _Config:
    def __init__(self, settings):
        self.settings = dict(settings)

    def load_settings(self):
        return dict(self.settings)

    def save_settings(self, **values):
        self.settings.update(values)


class _Runtime:
    """Pencere açmadan `start()` kapılarını sınamak için en küçük çalışma zamanı."""

    def __init__(self, settings=None):
        self.config = _Config(settings or {})
        self.hub = type("Hub", (), {"state": "idle"})()
        self.engine = type("Engine", (), {"flags": {}})()


class MascotLogicTests(unittest.TestCase):
    def setUp(self):
        mascot_window._THREAD = None
        mascot_window._STOP.clear()

    def test_each_web_state_maps_to_the_same_clip_as_webui(self):
        # webui/mascot.js CLIPS: idle bosta, listening dinleme, thinking dusunme, working calisma, speaking mutlu
        self.assertEqual(mascot_window.clip_name("idle"), "bosta")
        self.assertEqual(mascot_window.clip_name("listening"), "dinleme")
        self.assertEqual(mascot_window.clip_name("thinking"), "dusunme")
        self.assertEqual(mascot_window.clip_name("working"), "calisma")
        self.assertEqual(mascot_window.clip_name("speaking"), "mutlu")
        self.assertEqual(mascot_window.clip_name("greeting"), "selamlama")

    def test_unknown_state_falls_back_to_idle_case_insensitively(self):
        self.assertEqual(mascot_window.clip_name("LISTENING"), "dinleme")
        self.assertEqual(mascot_window.clip_name("bilinmeyen"), "bosta")
        self.assertEqual(mascot_window.clip_name(""), "bosta")

    def test_display_state_uses_engine_flags_without_a_second_source(self):
        self.assertEqual(mascot_window.display_state("thinking", {}), "thinking")
        self.assertEqual(mascot_window.display_state("speaking", {"mic": False}), "speaking")
        self.assertEqual(mascot_window.display_state("speaking", {"sleep": True}), "idle")
        self.assertEqual(mascot_window.display_state("olmayan", {}), "idle")

    def test_dpi_scale_standard_values(self):
        self.assertEqual(mascot_window.dpi_scale(96), 1.0)
        self.assertEqual(mascot_window.dpi_scale(120), 1.25)
        self.assertEqual(mascot_window.dpi_scale(144), 1.5)
        self.assertEqual(mascot_window.dpi_scale(192), 2.0)

    def test_dpi_scale_is_clamped_and_bad_input_is_safe(self):
        self.assertEqual(mascot_window.dpi_scale(48), 1.0)
        self.assertEqual(mascot_window.dpi_scale(480), 3.0)
        self.assertEqual(mascot_window.dpi_scale(None), 1.0)

    def test_window_size_at_200_percent_matches_the_asset_target(self):
        self.assertEqual(mascot_window.window_size(2.0), (320, 412))
        self.assertEqual(mascot_window.window_size(1.0), (160, 206))

    def test_clamp_keeps_the_window_inside_the_monitor_it_overlaps(self):
        monitors = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
        self.assertEqual(mascot_window.clamp_position(-100, -50, 320, 412, monitors), (0, 0))
        # Sağ kenardan taşan pencere tamamen birinci monitöre çekilir.
        self.assertEqual(mascot_window.clamp_position(1700, 1000, 320, 412, monitors), (1600, 668))
        # İkinci monitördeki pencere yerinde kalır.
        self.assertEqual(mascot_window.clamp_position(2000, 300, 320, 412, monitors), (2000, 300))

    def test_clamp_moves_a_fully_offscreen_window_to_the_nearest_monitor(self):
        monitors = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
        self.assertEqual(mascot_window.clamp_position(5000, 5000, 320, 412, monitors), (3520, 668))
        self.assertEqual(mascot_window.clamp_position(320, 412, 320, 412, []), (320, 412))

    def test_oversized_window_is_pinned_to_the_monitor_origin(self):
        monitors = [(0, 0, 1920, 1080)]
        self.assertEqual(mascot_window.clamp_position(100, 100, 2500, 2000, monitors), (0, 0))

    def test_reset_position_is_bottom_right_of_the_primary_with_margin(self):
        monitors = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
        self.assertEqual(mascot_window.reset_position(320, 412, monitors), (1576, 644))
        self.assertEqual(mascot_window.reset_position(320, 412, []), (0, 0))

    def test_restore_size_accepts_the_matching_size_and_rejects_junk(self):
        self.assertEqual(mascot_window.restore_size([320, 412], 2.0), (320, 412))
        self.assertEqual(mascot_window.restore_size([100, 100], 2.0), (320, 412))
        self.assertEqual(mascot_window.restore_size(["x"], 2.0), (320, 412))
        self.assertEqual(mascot_window.restore_size([9000, 9000], 2.0), (320, 412))
        self.assertEqual(mascot_window.restore_size(None, 1.0), (160, 206))

    def test_click_style_toggles_only_the_transparent_bit(self):
        base = mascot_window.WS_EX_LAYERED
        on = mascot_window.click_style(base, True)
        self.assertTrue(on & mascot_window.WS_EX_TRANSPARENT)
        self.assertTrue(on & mascot_window.WS_EX_LAYERED)
        self.assertFalse(mascot_window.click_style(on, False) & mascot_window.WS_EX_TRANSPARENT)
        self.assertTrue(mascot_window.click_style(on, False) & mascot_window.WS_EX_LAYERED)

    def test_key_flat_keys_only_zero_alpha_and_keeps_source_rgb(self):
        from PIL import Image

        source = Image.new("RGBA", (4, 1))
        source.putdata([
            (10, 20, 30, 0),        # tam saydam -> KEY
            (10, 20, 30, 1),        # yarı saydam kenar -> kaynak RGB aynen
            (200, 100, 50, 128),
            (0, 0, 0, 255),
        ])
        flat = mascot_window.key_flat(source, (4, 1))
        self.assertEqual(flat.mode, "RGB")
        self.assertEqual(flat.getpixel((0, 0)), mascot_window.KEY_RGB)
        self.assertEqual(flat.getpixel((1, 0)), (10, 20, 30))
        self.assertEqual(flat.getpixel((2, 0)), (200, 100, 50))
        self.assertEqual(flat.getpixel((3, 0)), (0, 0, 0))

    def test_key_flat_does_not_blend_semi_transparent_pixels_into_key(self):
        from PIL import Image

        source = Image.new("RGBA", (1, 1), (100, 150, 200, 128))
        background = Image.new("RGBA", (1, 1), mascot_window.KEY_RGB + (255,))
        old = Image.alpha_composite(background, source).convert("RGB")
        self.assertNotEqual(old.getpixel((0, 0)), (100, 150, 200))
        self.assertEqual(mascot_window.key_flat(source, (1, 1)).getpixel((0, 0)), (100, 150, 200))

    def test_key_flat_matches_every_pixel_of_a_real_frame(self):
        source = mascot_window.preload()["idle"][0]
        flat = mascot_window.key_flat(source, source.size)
        for y in range(source.height):
            for x in range(source.width):
                red, green, blue, alpha = source.getpixel((x, y))
                expected = mascot_window.KEY_RGB if alpha == 0 else (red, green, blue)
                self.assertEqual(flat.getpixel((x, y)), expected)

    def test_key_flat_resizes_uniform_colors_without_contamination(self):
        from PIL import Image

        opaque = Image.new("RGBA", (2, 2), (123, 45, 67, 255))
        transparent = Image.new("RGBA", (2, 2), (123, 45, 67, 0))
        self.assertEqual(mascot_window.key_flat(opaque, (7, 9)).getcolors(100), [(63, (123, 45, 67))])
        self.assertEqual(mascot_window.key_flat(transparent, (7, 9)).getcolors(100), [(63, mascot_window.KEY_RGB)])

    def test_monitor_normalization_drops_invalid_rectangles(self):
        self.assertEqual(mascot_window.normalize_monitors([(0, 0, 10, 10), (5, 5, 5, 9), "x"]),
                         [(0, 0, 10, 10)])

    def test_real_clips_preload_once_per_distinct_clip(self):
        frames = mascot_window.preload()
        self.assertEqual(set(frames), set(mascot_window.STATES))
        for state in mascot_window.STATES:
            self.assertTrue(frames[state], state)
            self.assertGreater(len(frames[state]), 1)
            self.assertEqual(frames[state][0].mode, "RGBA")
            self.assertEqual(frames[state][0].size, mascot_window.BASE_SIZE)
        # Her durum kendi klibini gösterir; aynı dosyayı paylaşan durum kare çoğaltmaz.
        self.assertEqual(mascot_window.clip_name("thinking"), "dusunme")
        self.assertEqual(mascot_window.clip_name("working"), "calisma")
        self.assertIsNot(frames["thinking"], frames["working"])
        self.assertEqual(len(frames["working"]), 36)

    def test_click_through_wanted_requires_the_setting_and_idle(self):
        self.assertFalse(mascot_window.click_through_wanted(False, "idle"))
        self.assertFalse(mascot_window.click_through_wanted(False, "listening"))
        self.assertTrue(mascot_window.click_through_wanted(True, "idle"))
        self.assertFalse(mascot_window.click_through_wanted(True, "speaking"))

    def test_default_click_through_is_off_and_never_enabled(self):
        window = mascot_window.MascotWindow(_Runtime())
        self.assertFalse(window._click_through_setting)
        window.window = object()
        with patch.object(mascot_window, "set_click_through", return_value=True) as fake:
            window._apply_click_through()
            fake.assert_called_once_with(window.window, False)
            self.assertFalse(window._click_through)
            fake.reset_mock()
            window._apply_click_through()
            fake.assert_not_called()       # kapalıyken tekrar denenmez

    def test_setting_on_enables_idle_and_clears_in_other_states(self):
        window = mascot_window.MascotWindow(_Runtime({"mascot_click_through": True}))
        self.assertTrue(window._click_through_setting)
        window.window = object()
        with patch.object(mascot_window, "set_click_through", return_value=True) as fake:
            window._apply_click_through()
            self.assertEqual(fake.call_args.args, (window.window, True))
            self.assertTrue(window._click_through)
            window._state = "listening"
            window._apply_click_through()
            self.assertEqual(fake.call_args.args, (window.window, False))
            self.assertFalse(window._click_through)

    def test_preload_memory_stays_under_the_desktop_budget(self):
        frames = mascot_window.preload()
        unique = {id(items): items for items in frames.values()}
        raw = sum(mascot_window.frame_memory(items) for items in unique.values())
        photos = mascot_window.photo_memory(len(frames["idle"]), mascot_window.window_size(2.0))
        self.assertLessEqual(raw + photos, 60 * 1024 * 1024)

    def test_missing_asset_directory_returns_empty_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = mascot_window.preload(folder)
        self.assertFalse(any(frames.values()))

    def test_start_is_off_by_default_and_opens_no_thread(self):
        with patch.object(mascot_window.threading, "Thread") as thread:
            self.assertFalse(mascot_window.start(_Runtime()))
        thread.assert_not_called()
        self.assertIsNone(mascot_window._THREAD)

    def test_start_refuses_other_platform_with_a_warning(self):
        runtime = _Runtime({"mascot_window": True})
        output = io.StringIO()
        with patch.object(mascot_window.sys, "platform", "linux"), redirect_stdout(output):
            self.assertFalse(mascot_window.start(runtime))
        self.assertIn("yalnız Windows", output.getvalue())

    def test_tk_root_can_be_created_or_the_test_is_skipped(self):
        # CI'da görünür pencere açılmaz; yalnız Tk ortamının varlığı sınanır.
        if not mascot_window.available():
            self.skipTest("tkinter/Pillow yok")
        import tkinter as tk
        try:
            root = tk.Tk()
        except Exception as exc:       # noqa: BLE001
            self.skipTest(f"Tk kökü açılamadı: {type(exc).__name__}")
        try:
            root.withdraw()
            root.update_idletasks()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
