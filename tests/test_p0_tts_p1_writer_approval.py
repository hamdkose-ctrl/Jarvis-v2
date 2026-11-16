"""P0 audio isolation and P1 direct Writer consent regression."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import engine_loop, runtime_prepare_approval, task_workers


class TTSEngineFaultTests(unittest.TestCase):
    def test_oserror_and_runtimeerror_muted_without_stopping_background(self):
        for error in (OSError('missing speaker'), RuntimeError('tts exploded')):
            with self.subTest(error=type(error).__name__):
                events = []
                stop = threading.Event()
                runtime = SimpleNamespace(
                    flags={'speak': True, 'mic': True}, stop_event=stop,
                    emit=lambda *args: events.append(args),
                    _record_failure=Mock(),
                )
                voice = SimpleNamespace(speak=Mock(side_effect=error), speak_enabled=True)
                with patch('modules.voice_runtime.block_legacy_on_fault') as block, \
                     patch('modules.voice_runtime.interrupt_active') as interrupt:
                    self.assertFalse(engine_loop._speak_isolated(runtime, voice, 'hello', shown=True))
                    block.assert_called_once_with()
                    interrupt.assert_called_once_with()
                self.assertFalse(runtime.flags['speak'])
                self.assertTrue(runtime.flags['mic'])
                self.assertFalse(voice.speak_enabled)
                self.assertFalse(stop.is_set())
                self.assertTrue(any(kind == 'system' for kind, *_ in events))
                self.assertFalse(engine_loop._speak_isolated(runtime, voice, 'again'))
                voice.speak.assert_called_once()


    def test_startup_tts_oserror_leaves_text_engine_alive(self):
        from modules.engine_voice import VoiceSession
        runtime = SimpleNamespace(
            sys=SimpleNamespace(argv=[]), flags={'speak': True, 'mic': True},
            emit=Mock(), _record_failure=Mock(),
        )
        with patch('config.load_settings', return_value={}), \
             patch('modules.voice_runtime.maybe_start', side_effect=OSError('missing device')), \
             patch('modules.voice_runtime.block_legacy_on_fault') as block:
            session = VoiceSession(runtime)
        block.assert_called_once()
        self.assertIsNone(session.voice_lane)
        self.assertFalse(session.speak_enabled)
        self.assertFalse(runtime.flags['speak'])
        self.assertTrue(runtime.flags['mic'])
        self.assertIn('yazılı yanıt', session.voice_core_fault)
        self.assertFalse(getattr(runtime, 'stop_event', threading.Event()).is_set())

    def test_voice_stop_failure_does_not_escape_or_claim_silence(self):
        runtime = SimpleNamespace(
            flags={'speak': True}, stop_event=threading.Event(),
            emit=Mock(), _record_failure=Mock())
        session = SimpleNamespace(speak_enabled=True, speak=Mock(side_effect=OSError('broken')),
                                  speech_blocks_mic=Mock(side_effect=OSError('busy sensor')))
        with patch('modules.voice_runtime.block_legacy_on_fault'), \
             patch('modules.voice_runtime.interrupt_active',side_effect=RuntimeError('no receipt')):
            self.assertFalse(engine_loop._speak_isolated(runtime,session,'test'))
        engine_loop._emit_idle_if_silent(runtime,session)
        runtime.emit.assert_called_once()
        self.assertEqual(runtime.emit.call_args.args[0],'system')
        self.assertFalse(runtime.stop_event.is_set())

    def test_tts_status_probe_failure_does_not_crash_engine_or_open_mic(self):
        runtime=SimpleNamespace(
            flags={'speak': True, 'mic': True}, stop_event=threading.Event(),
            emit=Mock(), _record_failure=Mock())
        session=SimpleNamespace(
            speak_enabled=True, speech_blocks_mic=Mock(side_effect=OSError('device gone')))
        with patch('modules.voice_runtime.block_legacy_on_fault') as block, \
             patch('modules.voice_runtime.interrupt_active') as stop:
            self.assertFalse(engine_loop._prepare_manual_listen(runtime, session))
            block.assert_called_once()
            stop.assert_called_once()
        self.assertFalse(runtime.flags['speak'])
        self.assertTrue(runtime.flags['mic'])
        self.assertFalse(session.speak_enabled)
        self.assertFalse(runtime.stop_event.is_set())
        runtime.emit.assert_called_with('system', unittest.mock.ANY)

    def test_healthy_voice_preserves_foreground_and_identity(self):
        runtime=SimpleNamespace(flags={'speak': True},emit=Mock(),_record_failure=Mock())
        session=SimpleNamespace(speak_enabled=True,speak=Mock())
        self.assertTrue(engine_loop._speak_isolated(runtime,session,'hello',
                                                   shown=True,identity={'goal_id':'one'}))
        session.speak.assert_called_once_with('hello',shown=True,identity={'goal_id':'one'})
        self.assertTrue(runtime.flags['speak'])


class WriterDirectWriteFenceTests(unittest.TestCase):
    def test_native_writer_has_no_unapproved_model_or_filesystem_access(self):
        with patch('modules.model_wait.ask',side_effect=AssertionError('No model')) as model:
            with self.assertRaisesRegex(PermissionError,'onay'):
                task_workers.run('alice',{'id':'write','agent':'writer','input':{
                    'instruction':'Make report','filename':'report.md'}, 'execution':{
                        'owner':'alice','job_id':'job123','task_id':'write',
                    }}, {})
            model.assert_not_called()

    def test_spoofed_writer_approved_flag_is_not_user_consent(self):
        forged = {'id':'write','agent':'writer',
                  'input': {'instruction':'Make report','filename':'report.md'},
                  'execution': {'owner':'alice','job_id':'invented-job',
                                'task_id':'write','_writer_approved':True}}
        with patch('modules.model_wait.ask',
                   side_effect=AssertionError('No model before real Core approval')) as model:
            with self.assertRaisesRegex(PermissionError,'onay'):
                task_workers.run('alice',forged,{})
        model.assert_not_called()

    def test_legacy_writer_accepts_consumed_prepare_on_second_attempt_only(self):
        data={'instruction':'Write summary','filename':'summary.md'}
        identity={'owner':'alice','job_id':'job1','task_id':'write',
                  '_writer_approved':True}
        proposal={'state':'approval','text':'Exact user-approved proposal'}
        approval={'consumed_at':100.0,'execution_started_at':101.0,
                  'binding':{'certificate':'bound'}}
        job={'id':'job1','owner':'alice','state':'running',
             'steps':[{'id':'write','tool':'writer','input':data,
                       'state':'running','attempts':2,'started':True,
                       'approval':approval}],
             'outputs':{'write':proposal}}
        task={'agent':'writer','input':data,'execution':identity}
        with patch('modules.goal_executor.read_job',return_value=job), \
             patch('modules.goal_approval.binding',
                   return_value={'certificate':'bound'}):
            self.assertTrue(runtime_prepare_approval.require_writer_execution('alice',task))
            # The first (prepare-only) attempt is not an authorized write.
            job['steps'][0]['attempts']=1
            with self.assertRaises(PermissionError):
                runtime_prepare_approval.require_writer_execution('alice',task)
            job['steps'][0]['attempts']=2
            # A completed/replaced output cannot be used to replay consent.
            job['outputs']['write']={'state':'done','file':'report.md'}
            with self.assertRaises(PermissionError):
                runtime_prepare_approval.require_writer_execution('alice',task)

    def test_prepare_approval_is_bound_to_owner_job_step_and_input(self):
        identity={'owner':'alice','job_id':'my-job','task_id':'report'}
        data={'instruction':'Write summary','filename':'summary.md'}
        proposal=runtime_prepare_approval.prepare(identity,'writer',data)
        self.assertEqual(proposal['state'],'approval')
        self.assertTrue(runtime_prepare_approval.accept(proposal,identity,'writer',data))
        with self.assertRaises(PermissionError):
            runtime_prepare_approval.accept(proposal,dict(identity,owner='bob'),'writer',data)
        with self.assertRaises(PermissionError):
            runtime_prepare_approval.accept(proposal,identity,'writer',
                                            dict(data,instruction='Write different bytes'))


if __name__=='__main__':
    unittest.main()
