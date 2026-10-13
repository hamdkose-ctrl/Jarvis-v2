from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import sys
import tempfile
import wave
from modules import local_narration, llm


class NarrationSetupTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)

    def test_real_wav_validation_and_temporary_cleanup(self):
        seen=[]
        def voice(owner,text,path):
            seen.append(path)
            with wave.open(str(path),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000)
                out.writeframes(b'\x01\x00'*800)
            return 'test'
        with patch.object(local_narration,'render',side_effect=voice):
            self.assertTrue(local_narration.check('alice')['ok'])
        self.assertFalse(seen[0].exists());self.assertFalse(seen[0].parent.exists())

    def test_missing_voice_is_not_success(self):
        with patch.object(local_narration,'render',side_effect=local_narration.Unavailable('SECRET')):
            result=local_narration.check('alice')
        self.assertFalse(result['ok']);self.assertNotIn('SECRET',result['text'])

    def test_silent_and_truncated_wavs_are_rejected(self):
        for contents in (b'\0'*1600,b'broken'):
            def voice(owner,text,path):
                if contents==b'broken':Path(path).write_bytes(contents)
                else:
                    with wave.open(str(path),'wb') as out:
                        out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(contents)
                return 'test'
            with patch.object(local_narration,'render',side_effect=voice):
                self.assertFalse(local_narration.check('alice')['ok'])

    def test_other_owner_cannot_probe_voice_configuration(self):
        with patch.object(local_narration,'render') as render:
            with self.assertRaises(PermissionError):local_narration.check('bob')
            render.assert_not_called()

    def test_unsigned_eight_bit_silence_is_rejected(self):
        def voice(owner,text,path):
            with wave.open(str(path),'wb') as out:
                out.setnchannels(1);out.setsampwidth(1);out.setframerate(8000);out.writeframes(b'\x80'*800)
            return 'test'
        with patch.object(local_narration,'render',side_effect=voice):
            self.assertFalse(local_narration.check('alice')['ok'])

    def test_sapi_close_error_still_releases_com(self):
        stream=MagicMock();stream.Close.side_effect=OSError('PRIVATE_PATH')
        com=SimpleNamespace(CoInitialize=MagicMock(),CoUninitialize=MagicMock())
        client=SimpleNamespace(CreateObject=MagicMock(side_effect=[stream,MagicMock()]))
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'comtypes':com,'comtypes.client':client}), \
             patch.object(local_narration.sys,'platform','win32'),patch.object(local_narration.shutil,'which',return_value=None), \
             patch.object(local_narration.publish_services,'configuration',return_value={}),patch.object(local_narration,'_record_failure'):
            with self.assertRaises(local_narration.Unavailable):local_narration.render('alice','test',Path(folder)/'audio.wav')
        com.CoUninitialize.assert_called_once()
