import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.widget import Widget


class WidgetMicHitTests(unittest.TestCase):
    def test_rendered_controls_keep_separate_hit_targets_at_windows_dpi(self):
        widget = Widget(lambda: ('idle', {}), {})
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                widget.scale = scale
                idle = widget._render('idle', {'mic': True})
                muted = widget._render('muted', {'mic': False})
                self.assertEqual(idle.size, (int(widget.W * scale), int(widget.H * scale)))
                self.assertNotEqual(idle.tobytes(), muted.tobytes())
                self.assertEqual(widget._hit_test(127 * scale, 161 * scale), 'mic')
                self.assertEqual(widget._hit_test(25 * scale, 161 * scale), 'home')
                self.assertEqual(widget._hit_test(76 * scale, 65 * scale), 'orb')
                self.assertIsNone(widget._hit_test(2 * scale, 65 * scale))

    def test_mic_rect_wins_over_talk_area(self):
        called=[]
        w=Widget(lambda:('idle',{'mic':True}), {'mic':lambda:called.append('mic'),'talk':lambda:called.append('talk')})
        w.scale = 1
        w._render('idle', {'mic': True})
        w.root=SimpleNamespace(winfo_x=lambda:0,winfo_y=lambda:0)
        w._drag=(100,100,0,0); w._moved=False
        w._release(SimpleNamespace(x=127,y=161,x_root=100,y_root=100))
        self.assertEqual(called,['mic'])

    def test_robot_talks_when_clicked_and_ignores_transparent_margin(self):
        called=[]
        w=Widget(lambda:('idle',{'mic':True}), {'mic':lambda:called.append('mic'),'talk':lambda:called.append('talk')})
        w.scale = 1
        w._render('idle', {'mic': True})
        w.root=SimpleNamespace(winfo_x=lambda:0,winfo_y=lambda:0)
        w._drag=(100,100,0,0); w._moved=False
        w._release(SimpleNamespace(x=2,y=65,x_root=100,y_root=100))
        w._release(SimpleNamespace(x=76,y=65,x_root=100,y_root=100))
        self.assertEqual(called,['talk'])

    def test_animation_changes_face_and_keeps_idle_frames_stable_between_blinks(self):
        widget = Widget(lambda: ('idle', {}), {})
        widget.scale = 1
        for state in ('listening', 'thinking', 'speaking'):
            with self.subTest(state=state):
                first = widget._render(state, {}, widget._phase(state, 1.0))
                later = widget._render(state, {}, widget._phase(state, 1.25))
                self.assertNotEqual(first.tobytes(), later.tobytes())
        self.assertEqual(widget._phase('idle', 1.0), widget._phase('idle', 4.5))
        self.assertEqual(widget._phase('idle', 5.0), -1)

    def test_active_animation_reuses_frames_in_the_next_cycle(self):
        widget = Widget(lambda: ('speaking', {}), {})
        widget.scale = 1
        widget._shown = True
        widget.root = SimpleNamespace(after=Mock())
        widget.label = SimpleNamespace(image=None, configure=Mock())
        with patch.object(widget, '_phase', side_effect=list(range(8)) * 2), \
             patch('PIL.ImageTk.PhotoImage') as photo:
            for _ in range(16):
                widget._tick()
        self.assertEqual(photo.call_count, 8)
        self.assertEqual(widget.label.configure.call_count, 16)


if __name__=='__main__':
    unittest.main()
