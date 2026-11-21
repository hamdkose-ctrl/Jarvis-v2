import unittest
from types import SimpleNamespace

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
                self.assertEqual(widget._hit_test(188 * scale, 23 * scale), 'mic')
                self.assertEqual(widget._hit_test(158 * scale, 23 * scale), 'home')
                self.assertEqual(widget._hit_test(80 * scale, 23 * scale), 'orb')

    def test_mic_rect_wins_over_talk_area(self):
        called=[]
        w=Widget(lambda:('idle',{'mic':True}), {'mic':lambda:called.append('mic'),'talk':lambda:called.append('talk')})
        w._hit={'orb':(0,0,210)}
        w._hit_rect={'mic':(170,5,209,44),'home':(135,5,165,44)}
        w.root=SimpleNamespace(winfo_x=lambda:0,winfo_y=lambda:0)
        w._drag=(100,100,0,0); w._moved=False
        w._release(SimpleNamespace(x=195,y=23,x_root=100,y_root=100))
        self.assertEqual(called,['mic'])

    def test_rest_of_bar_still_talks(self):
        called=[]
        w=Widget(lambda:('idle',{'mic':True}), {'mic':lambda:called.append('mic'),'talk':lambda:called.append('talk')})
        w._hit={'orb':(0,0,210)}
        w._hit_rect={'mic':(170,5,209,44),'home':(135,5,165,44)}
        w.root=SimpleNamespace(winfo_x=lambda:0,winfo_y=lambda:0)
        w._drag=(100,100,0,0); w._moved=False
        w._release(SimpleNamespace(x=80,y=23,x_root=100,y_root=100))
        self.assertEqual(called,['talk'])


if __name__=='__main__':
    unittest.main()
