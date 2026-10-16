import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from modules import local_ocr


class LocalOcrTests(unittest.TestCase):
    def test_missing_engine_never_starts_a_process(self):
        with patch.object(local_ocr.shutil, 'which', return_value=None), patch.object(local_ocr.subprocess, 'run') as run:
            self.assertFalse(local_ocr.check()['ok'])
            run.assert_not_called()

    def test_missing_turkish_does_not_silently_use_english(self):
        with patch.object(local_ocr.shutil, 'which', return_value='tesseract'), patch.object(
                local_ocr.subprocess, 'run', return_value=SimpleNamespace(stdout=b'eng\nosd\n')):
            self.assertFalse(local_ocr.check()['ok'])
            self.assertTrue(local_ocr.check('eng')['ok'])

    def test_limits_are_checked_before_starting_worker(self):
        with patch.object(local_ocr.subprocess, 'run') as run:
            for raw in (b'', b'x' * (local_ocr.MAX_BYTES + 1), 'not bytes'):
                with self.assertRaises(local_ocr.OcrError):
                    local_ocr.read(raw)
            run.assert_not_called()

    def test_timeout_and_corrupt_worker_output_are_not_success(self):
        with patch.object(local_ocr.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 30)):
            with self.assertRaisesRegex(local_ocr.OcrError, 'süre sınırına'):
                local_ocr.read(b'pdf')
        for output in (b'bad json', b'{"body":"","truncated":false}', b'{"body":"x","truncated":1}'):
            with patch.object(local_ocr.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
                with self.assertRaises(local_ocr.OcrError):
                    local_ocr.read(b'pdf')

    def test_worker_error_contains_no_document_or_tool_output(self):
        with patch.object(local_ocr, '_extract', side_effect=RuntimeError('PRIVATE DOCUMENT')):
            self.assertEqual(local_ocr._worker(b'pdf', 'eng'), {'error': 'document'})

    def test_real_scanned_pdf_uses_local_engine(self):
        if not local_ocr.check('eng')['ok']:
            self.skipTest('Optional Tesseract English engine not installed')
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (1400, 300), 'white')
        try:
            font = ImageFont.load_default(size=54)
            ImageDraw.Draw(image).text((50, 100), 'JARVIS ACCEPTANCE 12345', fill='black', font=font)
            data = io.BytesIO()
            image.save(data, format='PDF')
        finally:
            image.close()
        from modules.attachment_documents import extract, Rejected
        with self.assertRaises(Rejected):
            extract(data.getvalue(), '.pdf')
        result = local_ocr.read(data.getvalue(), language='eng')
        self.assertIn('JARVIS ACCEPTANCE 12345', result['body'])
        self.assertFalse(result['truncated'])

    def test_explicit_file_command_bypasses_models_and_workbench(self):
        from modules import main_documents, nxapi, workbench
        session = SimpleNamespace(last_doc=None)
        runtime = SimpleNamespace(_FILE_CMD=re.compile(r'^((?:"[^"]{4,400}"\s+){1,10})(.+)$'),
            re=re, _tr_lower=str.lower, _session=lambda: session, ask_image=Mock(), profile=SimpleNamespace(slug='alice'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scan.pdf'
            path.write_bytes(b'pdf')
            with patch.object(nxapi, 'allowed', return_value=path), patch.object(workbench, 'handle') as writer, patch.object(
                    local_ocr, 'read', return_value={'body': 'Okunan metin', 'truncated': False}) as read:
                result = main_documents._file_command(runtime, f'"{path}" yerel OCR ile oku')
            self.assertIn('Okunan metin', result)
            self.assertEqual(session.last_doc[0], 'Okunan metin')
            read.assert_called_once_with(b'pdf')
            writer.assert_not_called()
            runtime.ask_image.assert_not_called()


class ManualAcceptanceTests(unittest.TestCase):
    def setUp(self):
        from modules import llm, manual_acceptance
        self.manual = manual_acceptance
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(manual_acceptance, 'ROOT', Path(self.temp.name) / 'acceptance'))
        self.machine = self.stack.enter_context(patch.object(manual_acceptance, '_machine', return_value='pc-one'))
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)

    def test_default_read_does_not_create_storage(self):
        self.assertEqual(self.manual.update('alice'), {})
        self.assertFalse(self.manual.ROOT.exists())

    def test_declarations_are_per_owner_and_computer_and_resettable(self):
        self.manual.update('alice', confirm=['speaker_voice_quality'])
        self.assertIn('speaker_voice_quality', self.manual.update('alice'))
        self.machine.return_value = 'pc-two'
        self.assertEqual(self.manual.update('alice'), {})
        self.machine.return_value = 'pc-one'
        with self.assertRaises(PermissionError):
            self.manual.update('bob', confirm=['screen_camera'])
        self.manual.update('alice', reset=['speaker_voice_quality'])
        self.assertEqual(self.manual.update('alice'), {})

    def test_invalid_or_conflicting_claims_cannot_write(self):
        for confirm, reset in [(['release_suite'], []), (['screen_camera'], ['screen_camera'])]:
            with self.assertRaises(ValueError):
                self.manual.update('alice', confirm=confirm, reset=reset)
        self.assertFalse(self.manual.ROOT.exists())

    def test_same_windows_hostname_does_not_share_machine_guid_acceptance(self):
        import sys
        # Exercise the real registry-derived computer identity with a fixed hostname.
        self.stack.close()
        with patch.object(self.manual, 'ROOT', Path(self.temp.name) / 'same-host'), patch.object(
                self.manual.platform, 'system', return_value='Windows'), patch.object(
                self.manual.platform, 'node', return_value='SAME-NAME'):
            registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, KEY_READ=2, KEY_WOW64_64KEY=4,
                OpenKey=lambda *args: contextlib.nullcontext(object()), QueryValueEx=Mock(return_value=('machine-one', 1)))
            with patch.dict(sys.modules, {'winreg': registry}):
                self.manual.update('alice', confirm=['screen_camera'])
                registry.QueryValueEx.return_value = ('machine-two', 1)
                self.assertEqual(self.manual.update('alice'), {})

    def test_report_separates_real_video_from_user_declaration(self):
        from modules import acceptance_checks, personalization, service_health, media_setup
        import updater
        with patch.object(personalization, 'get_active', return_value='alice'), patch.object(
                updater, 'verify_sync', return_value={'sync_state': 'synced'}), patch.object(
                service_health, 'report', return_value='Local only'), patch.object(
                media_setup, 'check', return_value={'ok': True, 'text': 'Real H264 check'}) as video:
            report = acceptance_checks.run(suite=False, manual_confirm=['speaker_voice_quality'])
            video.assert_not_called()
            second = acceptance_checks.run(suite=False, video=True)
        rows = {row['check']: row for row in second['checks']}
        self.assertEqual(rows['video_runtime']['state'], 'passed')
        self.assertEqual(rows['speaker_voice_quality']['state'], 'reported_passed')
        self.assertEqual(rows['screen_camera']['state'], 'pending')
        self.assertNotIn('release_suite', rows)
        self.assertEqual({r['check']: r['state'] for r in report['checks']}['video_runtime'], 'pending')


class OptionalComponentsTests(unittest.TestCase):
    def test_study_and_media_do_not_load_heavy_optional_readers(self):
        import os
        import sys
        with tempfile.TemporaryDirectory() as folder:
            code = ("import sys; from modules import study, media_tools, local_ocr; "
                    "heavy={'faster_whisper','torch','cv2','pypdfium2','markitdown','docx','openpyxl'}; "
                    "assert not heavy.intersection(sys.modules), heavy.intersection(sys.modules)")
            cp = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, 'JARVIS_DATA_DIR': folder}, capture_output=True, timeout=15)
            self.assertEqual(cp.returncode, 0, cp.stderr.decode('utf-8', 'replace'))

    def test_video_probe_rejects_nan_or_wrong_duration(self):
        from modules import media_setup
        for duration in ('NaN', '1000', '0'):
            metadata = {'streams': [{'codec_name': 'h264', 'width': 64, 'height': 64}],
                        'format': {'duration': duration}}
            def run(command, **kwargs):
                if '-show_streams' in command:
                    return SimpleNamespace(stdout=json.dumps(metadata))
                if '-t' in command:
                    Path(command[-1]).write_bytes(b'test video')
                return SimpleNamespace(stdout='')
            with patch.object(media_setup.shutil, 'which', return_value='tool'), patch.object(
                    media_setup.subprocess, 'run', side_effect=run):
                self.assertFalse(media_setup.check()['ok'])
