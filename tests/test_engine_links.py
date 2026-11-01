"""Cross-component state transfer with actual runtime and handlers."""
import ast
import concurrent.futures
import inspect
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import test_engine_modular as fixtures
from modules import engine_runtime


class EngineLinkTests(unittest.TestCase):
    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def test_pc_context_uses_active_profile_when_disk_user_list_is_empty(self):
        context = self.context()
        profile = context.profile
        context.list_users = lambda: []
        context._get_profile = Mock(side_effect=AssertionError('must reuse active profile'))
        self.assertIsNone(context.match_user(profile.name))
        with context.as_user(profile.name):
            self.assertIs(context.profile, profile)
            self.assertIsNone(context._guest)
        context._get_profile.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Telefon kullanıcısı bulunamadı'):
            with context.as_user('missing-user'):
                self.fail('unknown user accepted')

    def test_live_prompt_and_command_work_without_saved_pc_profile(self):
        from modules.engine_voice import _pc_context
        context = self.context()
        context.list_users = lambda: []
        context.emit = Mock()
        context.handle = Mock(return_value='Tamam.')
        prompt = _pc_context(context, lambda: context.profile.name)
        self.assertEqual(prompt(), context.pc_profile().name)
        self.assertEqual(context._live_command('merhaba'), 'Tamam.')
        context.handle.assert_called_once_with('merhaba')

    def test_pc_scope_reuses_home_profile_during_phone_session(self):
        context = self.context()
        home = context.profile
        guest = SimpleNamespace(name='Guest', slug='guest', data={})
        context.profile = guest
        context._guest = guest.name
        context._home = home
        context.list_users = lambda: []
        with context.as_user(home.name):
            self.assertIs(context.profile, home)
        self.assertIs(context.profile, guest)
        self.assertEqual(context._guest, guest.name)
        self.assertIs(context._home, home)

    def test_registered_components_bind_every_handler_to_one_runtime(self):
        context=self.context()
        for component,names in engine_runtime._HANDLERS.items():
            for name in names:
                with self.subTest(component=component,handler=name):
                    handler=getattr(context,name)
                    if name in ('_live_prompt','_live_command'):handler=handler.__wrapped__
                    self.assertIs(handler.args[0],context)
                    self.assertEqual(handler.func.__module__,'modules.'+component)
                    self.assertEqual(next(iter(inspect.signature(handler.func).parameters)),'runtime')

    def test_every_direct_runtime_dependency_is_declared(self):
        context=self.context()
        known=set(vars(context))|set(context._exported)
        for path in (fixtures.ROOT/'modules').glob('engine_*.py'):
            for node in ast.walk(ast.parse(path.read_bytes())):
                if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='runtime':
                    self.assertIn(node.attr,known,f'{path.name}:{node.lineno}')

    def test_concurrent_command_metadata_does_not_cross_between_threads(self):
        context=self.context();barrier=threading.Barrier(2)
        def work(source,rid,typo):
            context._cur_source=source;context._cur_rid=rid
            context._typo_pass=typo;context._typo_orig=rid
            barrier.wait(timeout=5)
            return context._cur_source,context._cur_rid,context._typo_pass,context._typo_orig
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(work,'telefon','phone-rid',True)
            second=pool.submit(work,'ses','voice-rid',False)
            self.assertEqual(first.result(),('telefon','phone-rid',True,'phone-rid'))
            self.assertEqual(second.result(),('ses','voice-rid',False,'voice-rid'))
        self.assertEqual((context._cur_source,context._cur_rid,context._typo_pass),('',None,False))

    def test_output_keeps_each_threads_request_identity(self):
        context=self.context();barrier=threading.Barrier(2)
        context.history=SimpleNamespace(append=Mock(return_value={}))
        def work(rid):
            context._cur_rid=rid;barrier.wait(timeout=5)
            context.emit('assistant',rid)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(work,'one');second=pool.submit(work,'two')
            first.result();second.result()
        self.assertEqual({row['text']:row['rid'] for row in context.event_log},{'one':'one','two':'two'})

    def test_live_handler_does_not_inherit_previous_request_and_restores_context(self):
        context=self.context();context.emit=Mock()
        context.match_user=lambda name:context.profile.name
        context._get_profile=lambda name:context.profile
        context._cur_source='telefon';context._cur_rid='outer-rid'
        context._typo_pass=False;context._typo_orig='outer text'
        observed=[]
        def handle(text):
            observed.append((context._cur_source,context._cur_rid,context._typo_pass,context._typo_orig))
            context._session().speech_override='Sesli kısa sonuç'
            return 'Tam sonuç'
        context.handle=handle
        self.assertEqual(context._live_command('istek'),'Sesli kısa sonuç')
        self.assertEqual(len(observed),1)
        source,rid,typo,original=observed[0]
        self.assertEqual((source,typo,original),('ses',True,''))
        self.assertTrue(rid)
        self.assertNotEqual(rid,'outer-rid')
        self.assertEqual((context._cur_source,context._cur_rid,context._typo_pass,context._typo_orig),('telefon','outer-rid',False,'outer text'))

    def test_live_preparation_failure_restores_context(self):
        context=self.context();context._cur_source='web';context._cur_rid='outer'
        context.match_user=lambda name:context.profile.name
        context._get_profile=lambda name:context.profile
        context.emit=Mock(side_effect=RuntimeError('output unavailable'))
        with self.assertRaises(RuntimeError):context._live_command('istek')
        self.assertEqual((context._cur_source,context._cur_rid,context._typo_pass),('web','outer',False))

    def test_facade_temporary_metadata_patch_restores_the_outer_values(self):
        import main
        outer=('telefon','outer',True,'outer text')
        for name,value in zip(('_cur_source','_cur_rid','_typo_pass','_typo_orig'),outer):
            previous=getattr(main,name)
            setattr(main,name,value)
            try:
                with patch.object(main,name,'temporary'):
                    self.assertEqual(getattr(main._runtime,name),'temporary')
                self.assertEqual(getattr(main,name),value)
                self.assertNotIn(name,vars(main))
            finally:setattr(main,name,previous)

    def test_multi_step_reply_never_reinterprets_its_steps(self):
        context=self.context();session=context._session()
        context.handle=Mock(side_effect=AssertionError('adım metni ikinci kez yorumlanamaz'))
        out=context._run_steps(['bir','iki'])
        self.assertIn('bir',out);self.assertIn('iki',out)
        context.handle.assert_not_called()
        self.assertFalse(session._in_multi)

    def test_closing_sequence_does_not_execute_even_its_first_step(self):
        context=self.context();context.flags['closing']=True;context.handle=Mock()
        self.assertIn('tek tek',context._run_steps(['bir','iki']))
        context.handle.assert_not_called()

    def test_macro_never_runs_an_action_through_the_interpreter(self):
        context=self.context();session=context._session()
        context.profile.data['macros']={'başla':{'title':'başla','actions':['bir','iki']}}
        context.requests_state=SimpleNamespace(check=Mock())
        context.time=SimpleNamespace(sleep=Mock())
        context.system_control=SimpleNamespace(find_app=Mock(return_value=None),open_application=Mock())
        context.handle=Mock(side_effect=AssertionError('kısayol adımı yeniden yorumlanamaz'))
        out=context._macro_run('başla')
        self.assertIn('bir, iki',out)
        context.handle.assert_not_called()
        context.system_control.open_application.assert_not_called()
        self.assertIsNone(session.speech_override)
        self.assertFalse(session._in_macro)
