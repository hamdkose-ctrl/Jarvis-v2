import importlib
import sys
import tempfile
import threading
import unittest
import numpy  # noqa: F401 - patch.dict(sys.modules) çıkışta silerdi; numpy ikinci kez yüklenemez
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_privacy_voice_and_pending  # Existing hardware adapters when unavailable.
from modules import local_stt, voice
from modules.engine_voice import VoiceSession
import web
from web_voice import WebVoice


class LocalSttTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = patch.object(local_stt.config, 'DATA_DIR', Path(self.tmp.name))
        self.data.start(); self.addCleanup(self.data.stop)
        self.settings = {'local_stt_model': 'small'}
        self.cfg = patch.object(local_stt.config, 'load_settings', side_effect=lambda:self.settings.copy())
        self.cfg.start(); self.addCleanup(self.cfg.stop)
        local_stt._model = local_stt._model_path = None
        local_stt._preparing.clear(); local_stt._errors.clear()
        self.addCleanup(self.clear_cache)

    def clear_cache(self):
        local_stt._model = local_stt._model_path = None

    def ready(self, name='small'):
        path = local_stt.model_dir(name);path.mkdir(parents=True)
        for filename in ('model.bin', 'config.json', 'tokenizer.json'):
            (path/filename).write_bytes(b'data')
        return path

    def test_missing_model_does_not_download_or_import_whisper(self):
        downloader = Mock(side_effect=AssertionError('network'))
        with patch.dict(sys.modules, {'faster_whisper':SimpleNamespace(download_model=downloader)}):
            with self.assertRaisesRegex(ValueError, 'hazır değil'):
                local_stt.transcribe(b'\0\0'*1600)
        downloader.assert_not_called()

    def test_missing_tokenizer_is_rejected_before_whisper_can_download_one(self):
        path=self.ready();(path/'tokenizer.json').unlink()
        factory=Mock(side_effect=AssertionError('must not load'))
        with patch.dict(sys.modules, {'faster_whisper':SimpleNamespace(WhisperModel=factory)}):
            with self.assertRaises(ValueError):local_stt.transcribe(b'\0\0'*1600)
        factory.assert_not_called()

    def test_turkish_cpu_int8_cache_and_model_switch(self):
        path=self.ready();base=self.ready('base')
        model=Mock();model.transcribe.side_effect=lambda *a,**k:(iter([SimpleNamespace(text=' Şartname '),SimpleNamespace(text='özetle')]),None)
        factory=Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper':SimpleNamespace(WhisperModel=factory)}):
            raw=b'\xff\x7f'*1600
            self.assertEqual(local_stt.transcribe(raw),'Şartname özetle')
            self.assertEqual(local_stt.transcribe(raw),'Şartname özetle')
            factory.assert_called_once_with(str(path),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
            audio=model.transcribe.call_args.args[0]
            self.assertEqual(audio.shape,(1600,));self.assertLess(float(audio[0]),1)
            self.assertEqual(model.transcribe.call_args.kwargs['language'],'tr')
            self.assertTrue(model.transcribe.call_args.kwargs['vad_filter'])
            self.settings['local_stt_model']='base';local_stt.transcribe(raw)
            self.assertEqual(factory.call_count,2);self.assertEqual(factory.call_args.args[0],str(base))

    def test_no_speech_returns_no_command(self):
        self.ready();model=Mock();model.transcribe.return_value=(iter([]),None)
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}):
            self.assertIsNone(local_stt.transcribe(b'\0\0'*1600))

    def test_private_and_normal_local_recognition_never_calls_cloud_even_on_error(self):
        for mode in ('normal','gizli','yerel'):
            with self.subTest(mode=mode), patch.object(voice.privacy,'mode',return_value=mode), \
                 patch.object(voice,'_engine',side_effect=AssertionError('cloud route')), \
                 patch.object(voice._rec,'recognize_google',side_effect=AssertionError('Google')), \
                 patch.object(local_stt,'transcribe',return_value='not al') as transcribe:
                self.assertEqual(voice.recognize(b'\0\0',local=True),'not al')
                transcribe.side_effect=ValueError('yerel hata')
                with self.assertRaisesRegex(ValueError,'yerel hata'):voice.recognize(b'\0\0',local=True)

    def segments(self, *segs):
        import numpy  # noqa: F401 - patch.dict(sys.modules) çıkışta silerdi; numpy ikinci kez yüklenemez
        if not local_stt._complete(local_stt.model_dir('small')):self.ready()
        local_stt._model=local_stt._model_path=None
        model=Mock();model.transcribe.return_value=(iter(segs),None)
        return patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))})

    def test_fabricated_phrases_are_dropped_but_real_commands_stay(self):
        raw=b'\xff\x7f'*1600
        for fake in ('Altyazı M.K.','İzlediğiniz için teşekkürler.','İZLEDİĞİNİZ İÇİN TEŞEKKÜR EDERİM','Abone olun!'):
            with self.subTest(fake=fake),self.segments(SimpleNamespace(text=fake)):
                self.assertIsNone(local_stt.transcribe(raw))
        with self.segments(SimpleNamespace(text='Altyazı ekle'),SimpleNamespace(text='teşekkürler')):
            self.assertEqual(local_stt.transcribe(raw),'Altyazı ekle teşekkürler')

    def test_low_confidence_silence_and_repetition_are_dropped(self):
        raw=b'\xff\x7f'*1600
        silent=SimpleNamespace(text='Bir şey söyledi',no_speech_prob=0.9,avg_logprob=-1.4,compression_ratio=1.0)
        loop=SimpleNamespace(text='evet evet evet evet',no_speech_prob=0.1,avg_logprob=-0.3,compression_ratio=3.1)
        good=SimpleNamespace(text='Şartnameyi özetle',no_speech_prob=0.1,avg_logprob=-0.3,compression_ratio=1.2)
        unsure_but_speech=SimpleNamespace(text='Dosyayı aç',no_speech_prob=0.2,avg_logprob=-1.4,compression_ratio=1.0)
        with self.segments(silent,loop,good,unsure_but_speech):
            self.assertEqual(local_stt.transcribe(raw),'Şartnameyi özetle Dosyayı aç')

    def test_unrecognized_local_speech_is_announced_and_never_uses_cloud(self):
        for text,spoken in ((None,1),('aç',0)):
            with self.subTest(text=text),patch.object(voice,'_engine',side_effect=AssertionError('cloud')), \
                 patch.object(local_stt,'transcribe',return_value=text),patch.object(voice,'speak') as speak:
                self.assertEqual(voice.recognize(b'\0\0',announce_fail=True,local=True),text)
                self.assertEqual(speak.call_count,spoken)
        with patch.object(local_stt,'transcribe',return_value=None),patch.object(voice,'speak') as speak:
            voice.recognize(b'\0\0',announce_fail=False,local=True);speak.assert_not_called()

    def test_listen_reports_capture_before_transcription(self):
        order=[]
        loud,quiet=b'\x00\x10',b'\0\0'
        class Stream:
            def __enter__(s):return s
            def __exit__(s,*a):return False
            def __init__(s):s.n=0
            def read(s,n):
                s.n+=1;return ((loud if 3<s.n<8 else quiet)*n,False)
        with patch.object(voice.sd,'RawInputStream',return_value=Stream()),patch.object(voice,'_level',side_effect=lambda d:1000 if d[:2]==loud else 0), \
             patch.object(voice,'recognize',side_effect=lambda *a,**k:order.append('recognize') or 'x'):
            self.assertEqual(voice.listen(local=True,on_captured=lambda:order.append('captured')),'x')
        self.assertEqual(order,['captured','recognize'])

    def test_beam_defaults_to_five_and_is_passed_to_whisper(self):
        for stored,expected in ((None,5),(2,2),(1,1),(0,5),(9,5),('x',5),(True,1)):
            with self.subTest(stored=stored):
                self.settings.pop('local_stt_beam',None)
                if stored is not None:self.settings['local_stt_beam']=stored
                self.assertEqual(local_stt.beam_size(),expected)
        self.settings['local_stt_beam']=2
        model=Mock();model.transcribe.return_value=(iter([SimpleNamespace(text='aç')]),None)
        self.ready()
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}):
            local_stt.transcribe(b'\xff\x7f'*1600)
        self.assertEqual(model.transcribe.call_args.kwargs['beam_size'],2)

    def test_custom_words_become_a_short_whole_word_prompt(self):
        self.assertIsNone(local_stt.hint_prompt())
        self.settings['stt_words']=' , '
        self.assertIsNone(local_stt.hint_prompt())
        self.settings['stt_words']='Nevzat Bey, EAE'
        self.assertEqual(local_stt.hint_prompt(),'Nevzat Bey, EAE')
        self.settings['stt_words']=', '.join(f'Kelime{i:02d}' for i in range(60))
        prompt=local_stt.hint_prompt()
        self.assertLessEqual(len(prompt),200);self.assertTrue(prompt.endswith(tuple(f'Kelime{i:02d}' for i in range(60))))
        model=Mock();model.transcribe.return_value=(iter([SimpleNamespace(text='aç')]),None)
        self.settings['stt_words']='Nevzat Bey, EAE'
        self.ready()
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}):
            local_stt.transcribe(b'\xff\x7f'*1600)
        self.assertEqual(model.transcribe.call_args.kwargs['initial_prompt'],'Nevzat Bey, EAE')

    def test_prompt_echo_is_dropped_but_a_spoken_custom_word_stays(self):
        raw=b'\xff\x7f'*1600
        self.settings['stt_words']='Nevzat Bey, EAE, Şartname'
        for echo in ('Nevzat Bey, EAE, Şartname','nevzat bey eae'):
            with self.subTest(echo=echo),self.segments(SimpleNamespace(text=echo)):
                self.assertIsNone(local_stt.transcribe(raw))
        with self.segments(SimpleNamespace(text='EAE')):
            self.assertEqual(local_stt.transcribe(raw),'EAE')

    def test_preload_only_loads_an_installed_model_when_enabled_and_never_downloads(self):
        started=[]
        def thread(**kw):started.append(kw);return Mock()
        downloader=Mock(side_effect=AssertionError('network'))
        modules={'faster_whisper':SimpleNamespace(WhisperModel=Mock(),download_model=downloader)}
        with patch.dict(sys.modules,modules),patch.object(local_stt.threading,'Thread',side_effect=thread), \
             patch.object(local_stt.importlib.util,'find_spec',return_value=object()):
            self.assertFalse(local_stt.preload())                      # ayar kapalı
            self.settings['local_stt_enabled']=True
            self.assertFalse(local_stt.preload())                      # model inmemiş
            self.assertEqual(started,[])
        downloader.assert_not_called()

    def test_preload_warms_model_in_background_and_failures_are_silent(self):
        self.settings['local_stt_enabled']=True;path=self.ready()
        targets=[]
        def thread(**kw):targets.append(kw['target']);return Mock()
        factory=Mock(return_value=Mock())
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=factory)}), \
             patch.object(local_stt.threading,'Thread',side_effect=thread), \
             patch.object(local_stt.importlib.util,'find_spec',return_value=object()):
            self.assertTrue(local_stt.preload())
            factory.assert_not_called()
            targets[0]()
            factory.assert_called_once_with(str(path),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
            targets[0]()                                               # zaten yüklü: ikinci yükleme yok
            factory.assert_called_once()
            local_stt._model=local_stt._model_path=None
            factory.side_effect=OSError('bozuk')
            targets[0]()                                               # hata dışarı sızmaz
        self.assertIsNone(local_stt._model)

    def test_bridge_validates_and_saves_beam(self):
        bridge=web.Bridge.__new__(web.Bridge)
        with patch.object(web.config,'save_settings') as save,patch.object(web,'_wakeword'):
            bridge.settings_save({'local_stt_beam':2})
            save.assert_called_once_with(local_stt_beam=2)
            for bad in (0,6,True,'2',None):
                with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'1 ile 5'):
                    bridge.settings_save({'local_stt_beam':bad})
            self.assertEqual(save.call_count,1)

    def test_empty_odd_and_oversize_audio(self):
        self.assertIsNone(local_stt.transcribe(b''))
        for raw in (b'x',b'\0'*960002):
            with self.assertRaises(ValueError):local_stt.transcribe(raw)

    def test_download_only_normal_and_explicit(self):
        for mode in ('gizli','yerel'):
            with patch.object(local_stt.privacy,'mode',return_value=mode),patch.object(local_stt.threading,'Thread') as thread:
                with self.assertRaisesRegex(ValueError,'Normal'):local_stt.prepare('small')
                thread.assert_not_called()
        with patch.object(local_stt.privacy,'mode',return_value='normal'),patch.object(local_stt.importlib.util,'find_spec',return_value=None),patch.object(local_stt.threading,'Thread') as thread:
            with self.assertRaisesRegex(ValueError,'kurulu değil'):local_stt.prepare('small')
            thread.assert_not_called()

    def test_download_deduplicates_and_failure_can_retry(self):
        targets=[]
        def thread(**kw):targets.append(kw['target']);return Mock()
        with patch.object(local_stt.privacy,'mode',return_value='normal'),patch.object(local_stt.importlib.util,'find_spec',return_value=object()),patch.object(local_stt.threading,'Thread',side_effect=thread):
            self.assertTrue(local_stt.prepare('small')['started'])
            self.assertFalse(local_stt.prepare('small')['started'])
            with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(download_model=Mock(side_effect=OSError('offline')))}):targets[0]()
            self.assertIn('indirilemedi',local_stt.status()['error'])
            self.assertTrue(local_stt.prepare('small')['started'])
            def download(name,output_dir,use_auth_token):
                self.assertFalse(use_auth_token)
                path=Path(output_dir);path.mkdir(parents=True)
                for f in ('model.bin','config.json','tokenizer.json'):(path/f).write_bytes(b'x')
            with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(download_model=download)}):targets[-1]()
            self.assertTrue(local_stt.status()['ready']);self.assertFalse(local_stt.status()['preparing'])
            self.assertEqual(local_stt.status()['error'],'')

    def test_model_path_cannot_escape_allowed_names(self):
        for name in ('../escape','small.en','large',''):
            with self.assertRaises(ValueError):local_stt.model_dir(name)

    def test_manual_local_session_does_not_enable_live_or_barge_listener(self):
        self.settings['local_stt_enabled']=True
        runtime=SimpleNamespace(sys=SimpleNamespace(argv=['main.py']),live=SimpleNamespace(enabled=Mock(side_effect=AssertionError('Live'))))
        session=VoiceSession(runtime)
        self.assertTrue(session.manual_local_stt);self.assertFalse(session.live_on)
        session._barge_watch(threading.Event())

    def test_web_adapter_requires_explicit_prepare_call(self):
        with patch.object(local_stt,'status',return_value={'ready':False}) as status,patch.object(local_stt,'prepare',return_value={'started':True}) as prepare:
            self.assertEqual(WebVoice().local_stt_status(),{'ready':False});prepare.assert_not_called()
            self.assertEqual(WebVoice().local_stt_prepare('base'),{'started':True})
            prepare.assert_called_once_with('base')

    def test_manual_mode_voice_picker_uses_regular_tts_not_live(self):
        bridge=WebVoice()
        profile=SimpleNamespace(data={'prefs':{}},set_pref=Mock())
        live=SimpleNamespace(enabled=Mock(side_effect=AssertionError('Live voice picker')))
        bridge._runtime=SimpleNamespace(config=SimpleNamespace(load_settings=lambda:{'local_stt_enabled':True}),
            _p=lambda:profile,_live=lambda:live,voice=SimpleNamespace(VOICES={'tr_erkek':('Kerem','tr-TR-AhmetNeural')}),engine=SimpleNamespace(events=Mock()))
        self.assertNotIn('live',bridge.voice_options())
        self.assertTrue(bridge.voice_set('tr_erkek'))
        profile.set_pref.assert_called_once_with('voice','tr_erkek')


if __name__=='__main__':unittest.main()
