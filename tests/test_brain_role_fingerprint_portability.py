"""Brain-role fingerprint portability: line endings must not revoke an acceptance.

Evidence (2026-11-17): a GitHub ZIP install (LF) and a local git checkout (CRLF)
of the identical commit produced different role fingerprints, so every
``role_qualifications`` row failed and the live app fail-closed with
"canlı kabul bekliyor" on every free-form turn. The fingerprint now normalizes
CRLF to LF per hashed file; any real content change still moves it.
"""
import tempfile
import unittest
from pathlib import Path

from modules import smart_router

REPO = Path(smart_router.__file__).resolve().parents[1]


class RoleFingerprintPortabilityTests(unittest.TestCase):
    def _copy_inputs(self, dest: Path, *, crlf: bool) -> None:
        for name in smart_router._ROLE_FINGERPRINT_PATHS:
            data = (REPO / name).read_bytes().replace(b'\r\n', b'\n')
            if crlf:
                data = data.replace(b'\n', b'\r\n')
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def test_every_declared_fingerprint_input_exists_in_the_checkout(self):
        for name in smart_router._ROLE_FINGERPRINT_PATHS:
            self.assertTrue((REPO / name).exists(), f'fingerprint input missing: {name}')

    def test_lf_and_crlf_checkouts_of_the_same_bytes_share_one_fingerprint(self):
        reference = smart_router._role_fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            lf = Path(tmp) / 'lf'
            cr = Path(tmp) / 'crlf'
            lf.mkdir()
            cr.mkdir()
            self._copy_inputs(lf, crlf=False)
            self._copy_inputs(cr, crlf=True)
            self.assertEqual(smart_router._role_fingerprint(lf), reference)
            self.assertEqual(smart_router._role_fingerprint(cr), reference)

    def test_mixed_line_endings_also_share_the_fingerprint(self):
        reference = smart_router._role_fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            mixed = Path(tmp) / 'mixed'
            self._copy_inputs(mixed, crlf=False)
            for index, name in enumerate(smart_router._ROLE_FINGERPRINT_PATHS):
                if index % 2:
                    target = mixed / name
                    target.write_bytes(target.read_bytes().replace(b'\n', b'\r\n'))
            self.assertEqual(smart_router._role_fingerprint(mixed), reference)

    def test_a_real_content_change_still_moves_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'edit'
            self._copy_inputs(root, crlf=True)
            target = root / 'modules' / 'router_quota.py'
            data = target.read_bytes().replace(b'\r\n', b'\n') + b'# one line change\n'
            target.write_bytes(data.replace(b'\n', b'\r\n'))
            self.assertNotEqual(smart_router._role_fingerprint(root),
                                smart_router._role_fingerprint())


if __name__ == '__main__':
    unittest.main()
