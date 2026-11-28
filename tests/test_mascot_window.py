"""T5 masaüstü maskot penceresinin Tk'siz saf mantık testleri (pencere açılmaz)."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

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
        # webui/mascot.js CLIPS: idle bosta, listening dinleme, thinking dusunme, working calisma, speaking konusma
        self.assertEqual(mascot_window.clip_name("idle"), "bosta")
        self.assertEqual(mascot_window.clip_name("listening"), "dinleme")
        self.assertEqual(mascot_window.clip_name("thinking"), "dusunme")
        self.assertEqual(mascot_window.clip_name("working"), "calisma")
        self.assertEqual(mascot_window.clip_name("speaking"), "konusma")
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

    def test_key_flat_keys_low_coverage_and_keeps_source_rgb(self):
        from PIL import Image

        source = Image.new("RGBA", (5, 1))
        source.putdata([
            (10, 20, 30, 0),
            (10, 20, 30, 1),
            (10, 20, 30, 127),
            (200, 100, 50, 128),
            (0, 0, 0, 255),
        ])
        flat = mascot_window.key_flat(source, (5, 1))
        self.assertEqual(flat.mode, "RGB")
        for x in range(3):
            self.assertEqual(flat.getpixel((x, 0)), mascot_window.KEY_RGB)
        self.assertEqual(flat.getpixel((3, 0)), (200, 100, 50))
        self.assertEqual(flat.getpixel((4, 0)), (0, 0, 0))

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
                expected = mascot_window.KEY_RGB if alpha < 128 else (red, green, blue)
                self.assertEqual(flat.getpixel((x, y)), expected)

    def test_key_flat_resizes_uniform_colors_without_contamination(self):
        from PIL import Image

        opaque = Image.new("RGBA", (2, 2), (123, 45, 67, 255))
        transparent = Image.new("RGBA", (2, 2), (123, 45, 67, 0))
        self.assertEqual(mascot_window.key_flat(opaque, (7, 9)).getcolors(100), [(63, (123, 45, 67))])
        self.assertEqual(mascot_window.key_flat(transparent, (7, 9)).getcolors(100), [(63, mascot_window.KEY_RGB)])

    def test_key_flat_does_not_make_lanczos_fringe_opaque_at_high_dpi(self):
        from PIL import Image, ImageDraw

        source = Image.new("RGBA", (160, 206))
        ImageDraw.Draw(source).ellipse((35, 40, 125, 166), fill=(240, 240, 240, 255))
        size = (320, 412)
        resized = source.resize(size, Image.LANCZOS)
        flat = mascot_window.key_flat(source, size)
        fringe = 0
        for rgba, rgb in zip(resized.getdata(), flat.getdata()):
            alpha = rgba[3]
            if 0 < alpha < 128:
                fringe += 1
                self.assertEqual(rgb, mascot_window.KEY_RGB)
            elif alpha >= 128:
                self.assertEqual(rgb, rgba[:3])
        self.assertGreater(fringe, 0)

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
            self.assertIn(frames[state][0].size, (mascot_window.BASE_SIZE, (480, 618)))
        # Her durum kendi klibini gösterir; aynı dosyayı paylaşan durum kare çoğaltmaz.
        self.assertEqual(mascot_window.clip_name("thinking"), "dusunme")
        self.assertEqual(mascot_window.clip_name("working"), "calisma")
        self.assertIsNot(frames["thinking"], frames["working"])
        self.assertGreaterEqual(len(frames["working"]), 24)

    def test_greeting_shows_only_while_idle_and_until_the_timer_runs_out(self):
        # Açılışta bir kez selamlama; konuşma sürerken selamlama araya girmez.
        self.assertEqual(mascot_window.greeting_state("idle", 100.0, 99.0), "greeting")
        self.assertEqual(mascot_window.greeting_state("idle", 100.0, 100.0), "idle")
        self.assertEqual(mascot_window.greeting_state("idle", 100.0, 140.0), "idle")
        self.assertEqual(mascot_window.greeting_state("idle", 0.0, 5.0), "idle")
        for state in ("listening", "thinking", "working", "speaking"):
            self.assertEqual(mascot_window.greeting_state(state, 100.0, 5.0), state)
        self.assertIn("greeting", mascot_window.CLIPS)

    def test_every_state_finds_its_frames_in_the_preload_dictionary(self):
        # preload() durum adıyla anahtarlar; _show_clip klip adıyla ararsa pencere hep gizli kalır.
        frames = mascot_window.preload()
        self.assertEqual(len(mascot_window.frames_for(frames, "idle")), len(frames["idle"]))
        self.assertGreaterEqual(len(mascot_window.frames_for(frames, "idle")), 24)
        for state in mascot_window.STATES:
            self.assertTrue(mascot_window.frames_for(frames, state), state)
            self.assertIs(mascot_window.frames_for(frames, state), frames[state], state)
        self.assertIs(mascot_window.frames_for(frames, "bilinmeyen"), frames["idle"])
        self.assertIs(mascot_window.frames_for(frames, ""), frames["idle"])
        self.assertEqual(mascot_window.frames_for({}, "idle"), [])
        self.assertEqual(mascot_window.frames_for(None, "idle"), [])

    def test_show_clip_keeps_one_photo_and_releases_previous_decoder(self):
        window = mascot_window.MascotWindow(_Runtime())
        window._frames = mascot_window.preload(lazy=True)
        window.window = Mock()
        window.label = Mock()
        with patch.object(window, "_photo", side_effect=lambda frame: object()) as photo:
            window._show_clip("thinking")
            previous = window._active_frames
            self.assertGreater(len(previous), 1)
            self.assertEqual(photo.call_count, 1)
            window._show_clip("working")
            self.assertEqual(photo.call_count, 2)
            self.assertEqual(len(previous), 0)
            self.assertIsNone(previous.image)
            self.assertIsNotNone(window._current_photo)
            window._release_clip()

    def test_player_uses_frame_time_and_finishes_greeting(self):
        from PIL import Image

        frame = Image.new("RGBA", (1, 1))
        frame.info["duration"] = 83
        window = mascot_window.MascotWindow(_Runtime(), fps=30)
        window._active_frames = mascot_window.FrameStream([frame, frame], size=(1, 1))
        window._active_clip = window._state = "greeting"
        window._frame_index = 1
        window.window = Mock()
        window.label = Mock()
        with patch.object(window, "_photo", return_value="second"), patch.object(
                mascot_window.time, "monotonic", return_value=1.0):
            window._tick_frame()
            window.window.after.assert_called_once_with(83, window._tick_frame)
            window.label.configure.assert_called_once_with(image="second")
            window.window.after.reset_mock()
            window._tick_frame()
            window.window.after.assert_not_called()

    def test_persistent_speech_restarts_at_clip_end(self):
        from PIL import Image

        window = mascot_window.MascotWindow(_Runtime())
        window._state = "speaking"
        window._active_frames = mascot_window.FrameStream([Image.new("RGBA", (1, 1))], size=(1, 1))
        window._frame_index = 1
        with patch.object(window, "_show_clip") as restart:
            window._tick_frame()
            restart.assert_called_once_with("speaking")

    def test_stream_reads_requested_frames_and_retains_timing(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clip.webp"
            frames = [Image.new("RGBA", (480, 618), (i * 20, 20, 30, 255)) for i in range(6)]
            frames[0].save(path, save_all=True, append_images=frames[1:],
                           duration=[33, 34, 33, 34, 33, 34], loop=0, lossless=True)
            stream = mascot_window.FrameStream(path, size=(160, 206))
            try:
                self.assertEqual(len(stream), 6)
                self.assertEqual(stream[0].size, (160, 206))
                self.assertEqual(mascot_window.frame_delay_ms(stream[1], 30), 34)
                self.assertEqual(mascot_window.frame_delay_ms(stream[0], 30), 33)
            finally:
                stream.close()
            self.assertEqual(len(stream), 0)

    def test_each_new_speech_state_uses_the_other_gesture(self):
        from PIL import Image

        frame = Image.new("RGBA", (1, 1))
        window = mascot_window.MascotWindow(_Runtime())
        window.window = Mock()
        window.label = Mock()
        window._frames = {"speaking": [frame]}
        window._extra_frames = {"speaking_alt": [frame]}
        with tempfile.TemporaryDirectory() as folder, patch.object(
                mascot_window, "ASSET_DIR", Path(folder)), patch.object(
                window, "_photo", side_effect=lambda frame: object()):
            clips = []
            for _ in range(3):
                window._show_clip("speaking")
                clips.append(window._active_clip)
        self.assertEqual(clips, ["speaking", "speaking_alt", "speaking"])

    def test_single_hybrid_clip_does_not_alternate_with_legacy_face(self):
        from PIL import Image

        window = mascot_window.MascotWindow(_Runtime())
        window.window = Mock()
        window.label = Mock()
        window._frames = {"speaking": [Image.new("RGBA", (1, 1))]}
        window._extra_frames = {"speaking_alt": window._frames["speaking"]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "konusma.jclip").touch()
            with patch.object(mascot_window, "ASSET_DIR", root), patch.object(
                    window, "_photo", return_value=object()), patch(
                    "modules.mascot_face_runtime.HybridFrameStream",
                    side_effect=lambda *args, **kwargs: mascot_window.FrameStream(
                        window._frames["speaking"], size=window.size)) as hybrid:
                for _ in range(3):
                    window._show_clip("speaking")
                    self.assertEqual(window._active_clip, "speaking")
                self.assertEqual(hybrid.call_count, 3)
        window._release_clip()

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

    def test_stream_retains_no_decoded_frame_collection(self):
        catalogue = mascot_window.preload(lazy=True)
        stream = mascot_window.FrameStream(catalogue["idle"], size=(320, 412))
        try:
            self.assertIsNone(stream.source)
            self.assertEqual(stream[0].size, (320, 412))
            self.assertEqual(stream[1].size, (320, 412))
            self.assertIsNone(stream.source)
        finally:
            stream.close()

    def test_lazy_catalogue_decodes_no_frames_at_startup(self):
        with patch.object(mascot_window, "load_frames") as decode:
            catalogue = mascot_window.preload(lazy=True)
        decode.assert_not_called()
        self.assertEqual(set(catalogue), set(mascot_window.STATES))
        self.assertTrue(all(isinstance(path, Path) and path.is_file()
                            for path in catalogue.values()))

    def test_high_resolution_decode_uses_display_size_and_preserves_timing(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.webp"
            first = Image.new("RGBA", (480, 618), (240, 220, 200, 255))
            second = Image.new("RGBA", (480, 618), (20, 30, 40, 255))
            first.save(path, save_all=True, append_images=[second],
                       duration=[40, 90], loop=0, lossless=True)
            frames = mascot_window.load_frames(path, size=(160, 206))
            self.assertEqual([frame.size for frame in frames], [(160, 206)] * 2)
            self.assertEqual([mascot_window.frame_delay_ms(frame, 30)
                              for frame in frames], [40, 90])
            self.assertEqual(len(mascot_window.load_frames(path, size=(160, 206),
                                                           first_only=True)), 1)

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
