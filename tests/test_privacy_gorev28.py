import unittest

from modules import privacy
from modules import permission_gate as gate


class MaskExtraTests(unittest.TestCase):
    def test_new_secret_shapes_are_masked_and_idempotent(self):
        rows = [
            'Authorization: Basic dXNlcjpwYXNzd29yZA==',
            'https://x.example/a?key=abcdef123456&q=1',
            'https://x.example/a?q=1&access_token=abcdef123456',
            'AKIAABCDEFGHIJKLMNOP',
            'ASIAABCDEFGHIJKLMNOP',
        ]
        for row in rows:
            with self.subTest(row=row):
                once = privacy.redact(row, force=True)
                self.assertIn('gizlendi', once)
                for raw in ('dXNlcjpwYXNzd29yZA', 'abcdef123456', 'ABCDEFGHIJKLMNOP'):
                    self.assertNotIn(raw, once)
                self.assertEqual(once, privacy.redact(once, force=True))

    def test_plain_text_is_left_alone(self):
        for row in ['Basic bilgi ver', 'key=1', 'https://x.example/a?q=ev']:
            self.assertEqual(privacy.redact(row, force=True), row)


class AppsNeverTests(unittest.TestCase):
    def test_case_and_exe_do_not_bypass(self):
        for never, target in [(['cmd'], 'CMD.EXE'), (['Putty.exe'], 'putty'), (['REGEDIT'], 'regedit.exe')]:
            with self.subTest(target=target):
                self.assertEqual(gate._never_hit(never, target), True)
        self.assertEqual(gate._never_hit(['cmd'], 'calc.exe'), False)


if __name__ == '__main__':
    unittest.main()
