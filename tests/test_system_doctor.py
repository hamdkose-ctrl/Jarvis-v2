import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from modules import system_doctor as doctor, nxapi


class DoctorTests(unittest.TestCase):
    def test_import_availability_never_claims_hardware_verified(self):
        with patch.object(doctor,'_installed',return_value=False):report=doctor.check()
        self.assertFalse(report['hardware_verified'])
        voice=next(c for c in report['checks'] if c['name']=='Canlı mikrofon, uyandırma, TTS')
        self.assertEqual(voice['state'],'unverified')
        self.assertIn('unverified',doctor.render(report))

    def test_report_is_saved_and_separate_for_users(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(nxapi,'FILES_DIR',Path(folder)),patch.object(doctor,'_installed',return_value=False):
            doctor.save('alice')
            self.assertTrue((Path(folder)/'Jarvis Tanılama/alice/pc-ses-kontrol.json').is_file())
            self.assertFalse((Path(folder)/'Jarvis Tanılama/bob').exists())
            with self.assertRaises(ValueError):doctor.save('../escape')


if __name__=='__main__':unittest.main()
