import engine_source
"""Behavior regressions for the general review; no provider or device calls."""
import ast
import concurrent.futures
import contextlib
import io
import json
import queue
import re
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]

def functions(file, names, ns):
    tree=engine_source.tree() if file == 'main.py' else ast.parse((ROOT/file).read_text(encoding='utf-8'))
    picked=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=picked,type_ignores=[])),file,'exec'),ns)
    return ns

class IdentityTests(unittest.TestCase):
    def test_concurrent_clients_do_not_cross_users(self):
        from modules import llm
        barrier=threading.Barrier(2)
        def worker(user):
            llm.set_user_context(user);barrier.wait()
            return llm._cli()
        with patch.object(llm,'_user_clients',{'a':('key','client-a'),'b':('key','client-b')}):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                a=pool.submit(worker,'a');b=pool.submit(worker,'b')
                self.assertEqual(a.result(),'client-a');self.assertEqual(b.result(),'client-b')
    def test_google_tokens_are_separate_and_legacy_not_given_to_guest(self):
        from modules import google_api as g,llm
        from config import load_settings,save_settings
        with tempfile.TemporaryDirectory() as td, patch.object(g,'DATA_DIR',Path(td)), patch.object(g,'TOKEN',Path(td)/'google_token.json'), \
             patch('config.load_settings', return_value={'google_legacy_owner': 'owner'}), patch('config.save_settings'):
            g.TOKEN.write_text('owner-secret')
            with patch('modules.personalization.get_active',return_value='Owner'),patch.object(llm,'current_user',return_value='guest'):
                self.assertFalse(g.token_path().exists())
            with patch.object(llm,'current_user',return_value='owner'):
                owner=g.token_path();self.assertEqual(owner.read_text(encoding='utf-8'),'owner-secret')
            with patch.object(llm,'current_user',return_value='guest'):
                self.assertNotEqual(owner,g.token_path());self.assertFalse(g.token_path().exists())
    def test_gizli_image_never_reads_or_sends_file(self):
        from modules import llm
        with patch.object(llm.privacy,'mode',return_value='gizli'),patch.object(llm,'_cli',side_effect=AssertionError('cloud')):
            self.assertIn('Gizli',llm.ask_image('/missing-file','test'))
    def test_capture_gate_blocks_existing_camera(self):
        from modules import vision
        cam=Mock()
        with patch.object(vision,'_mode','camera'),patch.object(vision,'_camera',cam),patch('modules.privacy.blocked',return_value='kapalı'):
            self.assertIsNone(vision.current_image());cam.image.assert_not_called()
    def test_privacy_transition_stops_share(self):
        tree=ast.parse((ROOT/'web.py').read_text(encoding='utf-8'));bridge=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Bridge')
        fn=next(n for n in bridge.body if isinstance(n,ast.FunctionDef) and n.name=='privacy_set')
        engine=Mock();privacy=Mock(MODES={'gizli':'Gizli'})
        ns={'engine':engine,'privacy':privacy,'voice':Mock(),'config':Mock()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'privacy','exec'),ns)
        ns['privacy_set'](SimpleNamespace(privacy_get=lambda:{}),{'mode':'gizli'})
        engine.set_share.assert_called_once_with(None)

class ContextTests(unittest.TestCase):
    def setUp(self):
        from modules import history, conversation_reset
        self.h=history;self.cr=conversation_reset;self.td=tempfile.TemporaryDirectory();self.addCleanup(self.td.cleanup)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(history,'DIR',Path(self.td.name)/'history'))
        self.stack.enter_context(patch.object(conversation_reset,'_resets',{}));self.stack.enter_context(patch.object(conversation_reset,'_reset_file',Path(self.td.name)/'sessions.json'))

    def source(self, command, rows):
        """Kaynak seçimi tek sözdizim kuralındadır: translation_request (ikinci oturum cache'i yok)."""
        from modules import translation_request as tr
        request = tr.parse(command)
        self.assertIsNotNone(request, command)
        return tr.pick_source(request, command, rows)[0]

    def test_short_source_translation_and_explicit_summary(self):
        text='This is a short sample text.'
        self.h.append('a','user',text);self.h.append('a','assistant','Kısa özet')
        rows=self.h.read('a')
        self.assertEqual(self.source('çevir',rows),text)
        self.assertEqual(self.source('özeti İngilizceye çevir',rows),'Kısa özet')
    def test_long_text_survives_storage(self):
        text='Çevirilecek metin '+('Şğİ🙂'*3000)
        self.h.append('a','user',text)
        self.assertEqual(self.h.read('a')[0]['text'],text)
    def test_reset_excludes_old_source_but_same_second_new_source_works(self):
        self.h.append('a','user','Eski kaynak metin uzun.')
        self.cr.mark('a')
        self.assertEqual(self.source('çevir',self.cr.recent('a',self.h.read('a'))),'')
        self.h.append('a','user','Yeni kaynak metin uzun.')
        self.assertEqual(self.source('çevir',self.cr.recent('a',self.h.read('a'))),'Yeni kaynak metin uzun.')
    def test_users_cannot_share_source(self):
        self.h.append('a','user','Original source text for A')
        self.assertEqual(self.source('çevir',self.h.read('b')),'')
    def test_tool_results_refresh_model_context(self):
        from modules import llm
        self.h.append('a','user','Original input')
        self.h.append('a','assistant','First answer')
        with patch.object(llm,'_history_seed',lambda user:[(r['role'],r['text']) for r in self.h.read(user)]),patch.object(llm,'_histories',{}),patch.object(llm,'_send',return_value='draft') as send:
            llm.chat_draft('question',user='a')
            self.h.append('a','assistant','NEW TOOL TABLE RESULT')
            llm.chat_draft('explain it',user='a')
            self.assertIn('NEW TOOL TABLE RESULT',str(send.call_args.args[3]))
    def test_table_routes_before_translate_and_updates_export(self):
        ns={'emit':Mock(),'re':re,'profile':SimpleNamespace(slug='a'),'_llm':Mock(),'_tr_lower':str.lower,
            '_cur_source':'yazı','flags':{'sleep':False},'_close_jarvis':Mock(),'set_sleep':Mock(),
            '_record_failure':Mock(),'output':Mock(),'pending_weather_location':False,
            'pending_confirm':None,'pending_level':None,
            'pending_msg':None,'pending_organize':None,'pending_voice':None,'pending_event_title':None,
            'last_doc':None,'speech_override':None}
        from modules.session_state import SessionState
        state=SessionState();ns['_session']=lambda:state
        tree=engine_source.tree();fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='handle')
        prefix=[]
        for stmt in fn.body:
            if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_st' for t in stmt.targets):break
            prefix.append(stmt)
        fn.body=prefix;exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'main-prefix','exec'),ns)
        self.h.append('a','assistant','A=1 B=2')
        ns.update(history=self.h,ask=Mock(return_value='| A | B |\n|1|2|'))
        functions('main.py',['_table_chat','_conversation_summary'],ns)
        for command in ['bunu tabloya çevir','bunu tabloya dönüştür','yazıları toplo yap']:
            result=ns['handle'](command);self.assertIn('| A |',result);self.assertEqual(state.last_doc[0],result)
        self.assertEqual(ns['handle']('tamam'),'Tamam.')
    def test_tail_read_and_size_pruning(self):
        with patch.object(self.h,'_MAX_BYTES',3000):
            for i in range(30):self.h.append('a','user',str(i)+'x'*200)
            rows=self.h.read('a',limit=2)
            self.assertTrue(rows[-1]['text'].startswith('29'))
            self.assertLess(self.h._path('a').stat().st_size,3000)

class RequestTests(unittest.TestCase):
    def setUp(self):
        from modules import requests_state as r
        self.r=r;self.td=tempfile.TemporaryDirectory();self.addCleanup(self.td.cleanup)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(r,'_records',{}));self.stack.enter_context(patch.object(r,'_journal',Path(self.td.name)/'requests.json'))
    def test_duplicate_cancelled_and_completed_do_not_register_again(self):
        self.assertTrue(self.r.register('a','id'))
        self.r.cancel('a','id');self.assertFalse(self.r.register('a','id'))
        self.r.register('b','id')
        with self.r.activate('b','id'):self.r.check()
        self.assertFalse(self.r.register('b','id'))
        self.assertEqual(json.loads(self.r._journal.read_text(encoding='utf-8'))[-1]['state'],'done')
    def test_cancel_during_model_call_discards_response(self):
        from modules import llm
        self.r.register('a','id')
        with self.r.activate('a','id'):
            def result():self.r.cancel('a','id');return 'DO NOT APPLY'
            with self.assertRaises(self.r.Cancelled):llm._timed('mock',result)
    def test_deadline_and_owner_scoping(self):
        self.r.register('a','id',seconds=-1);self.r.register('b','id')
        self.assertTrue(self.r.is_cancelled('a','id'));self.assertFalse(self.r.is_cancelled('b','id'))
        with self.assertRaises(self.r.Cancelled):
            with self.r.activate('a','id'):pass

class UpdateTests(unittest.TestCase):
    def test_pending_development_blocks_update_before_download_or_source_checks(self):
        import updater as u
        import release_guard as guard
        for status in ('applying', 'rolling_back', 'awaiting_start', 'confirmed'):
            with self.subTest(status=status), patch.object(guard, 'pending', return_value={'status': status}), patch.object(u, '_protected_local_changes') as local, patch.object(u, '_get') as get:
                with self.assertRaisesRegex(RuntimeError, 'geliştirmeyi tamamla'):
                    u.apply({'sha': 'candidate'})
                local.assert_not_called();get.assert_not_called()

    def test_unknown_base_stops_before_download(self):
        import updater as u
        with patch.object(u,'_protected_local_changes',return_value={}),patch.object(u,'_state',return_value={}),patch.object(u,'_get') as get:
            with self.assertRaisesRegex(RuntimeError,'taban'):u.apply({'sha':'x'})
            get.assert_not_called()
    def test_failed_second_replace_rolls_back_all_files(self):
        import updater as u
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';root.mkdir();data=Path(td)/'data';data.mkdir()
            (root/'main.py').write_text('OLD MAIN');(root/'web.py').write_text('OLD WEB');(root/'old.py').write_text('OLD DELETED')
            raw=io.BytesIO()
            with zipfile.ZipFile(raw,'w') as z:
                z.writestr('repo/main.py','a=1');z.writestr('repo/web.py','b=2')
            original=u.os.replace;n=[0]
            def fail(src,dest):
                if Path(dest).parent == root:
                    n[0]+=1
                    if n[0]==2:raise OSError('disk failure')
                original(src,dest)
            with patch.object(u,'ROOT',root),patch.object(u,'DATA',data),patch.object(u,'_protected_local_changes',return_value={}),patch.object(u,'_local_source_changes',return_value=[]),patch.object(u,'_compare_commits',return_value='ahead'),patch.object(u,'_get',return_value=raw.getvalue()),patch.object(u.os,'replace',side_effect=fail),patch('modules.release_workspace.validate',return_value=(True,'checks passed')):
                with self.assertRaisesRegex(OSError,'disk failure'):u.apply({'sha':'x','msg':'test','date':'today'})
            self.assertEqual((root/'main.py').read_text(encoding='utf-8'),'OLD MAIN');self.assertEqual((root/'web.py').read_text(encoding='utf-8'),'OLD WEB');self.assertTrue((root/'old.py').exists())
    def test_offline_clears_stale_sync_state(self):
        import updater as u
        with patch.object(u,'status',return_value={'sync_state':'synced'}),patch.object(u,'latest',return_value=None),patch.object(u,'_save_state') as save:
            self.assertEqual(u.verify_sync()['sync_state'],'offline');self.assertEqual(save.call_args.kwargs['sync_state'],'offline')
    def test_asset_android_and_secret_scope(self):
        import updater as u
        from modules import git_publish as publish
        for name in ['android/Jarvis3/app/src/main/java/jarvis/MainActivity.java','webui/logo.png','webui/icon.svg']:
            self.assertTrue(u._publishable_path(name))
        for name in ['.env','android/Jarvis3/local.properties','android/Jarvis3/app/build/output.json']:
            self.assertFalse(u._publishable_path(name))

class SchedulerTests(unittest.TestCase):
    def test_reminders_delivered_without_processing_command_queue(self):
        from modules import engine_background
        owner=SimpleNamespace(name='A',slug='a',data={'prefs':{}},due_events=Mock(return_value=[{'title':'Reminder'}]))
        emitted=Mock();q=queue.Queue()
        ns={'list_users':lambda:['A'],'_get_profile':lambda name:owner,'datetime':datetime,'_emit_for':emitted,'pc_profile':lambda:owner,'events':q,
            'reminder_speech_id':engine_background.reminder_speech_id,
            'reminder_occurrence_id':engine_background.reminder_occurrence_id,
            'REMINDER_SPEECH_TTL_SECONDS':engine_background.REMINDER_SPEECH_TTL_SECONDS}
        functions('main.py',['_reminder_tick'],ns);ns['_reminder_tick']()
        emitted.assert_called_once_with(owner,'assistant','Hatırlatma: Reminder','hatırlatma')
        event=q.get()
        self.assertEqual(event[0],'say')
        # The spoken notice names the record it announces, so a later correction
        # of that record can drop exactly this queued audio.
        self.assertEqual(event[3]['kind'], 'reminder')
        self.assertTrue(event[3]['event_id'].startswith('reminder:'), event[3])
        self.assertGreater(event[3]['ttl_seconds'], 0)
    def test_bad_plan_date_does_not_mutate_profile(self):
        from modules import studyexam
        prof=SimpleNamespace(data={},save=Mock())
        for cfg in [{'time':'99:99'},{'exam_date':'2026-02-31'}]:
            with self.assertRaises(ValueError):studyexam.set_plan_cfg(prof,cfg)
        self.assertEqual(prof.data,{})
    def test_plan_change_refreshes_existing_reminders(self):
        from modules import studyexam
        prof=SimpleNamespace(data={'events':[{'title':'Çalışma: konu'}]},save=Mock())
        with patch.object(studyexam,'plan_cfg',return_value={}),patch.object(studyexam,'plan',return_value={}),patch.object(studyexam,'set_reminders') as reminders:
            studyexam.set_plan_cfg(prof,{'time':'21:30'});reminders.assert_called_once_with(prof)

class FieldNoteTests(unittest.TestCase):
    def test_duplicate_note_is_saved_once_and_users_remain_separate(self):
        from modules import fieldnotes
        from modules.personalization import Profile
        def prof(name):
            p=Profile.__new__(Profile);p.slug=name;p.data={'items':[]};p._new_id=Mock(side_effect=range(1,20));p.save=Mock();return p
        a,b=prof('a'),prof('b');payload=[{'uid':'note-12345678','text':'Sahada motor ısındı.'}]
        self.assertEqual(fieldnotes.sync(a,payload)['ack'],['note-12345678'])
        fieldnotes.sync(a,payload);self.assertEqual(len(a.data['items']),1);self.assertEqual(b.data['items'],[])
        fieldnotes.sync(b,payload);self.assertEqual(len(b.data['items']),1)
    def test_deleted_note_does_not_return_on_retry(self):
        from modules import fieldnotes
        p=SimpleNamespace(slug='a',data={'items':[]},_new_id=lambda:1,save=Mock())
        payload=[{'uid':'note-12345678','text':'saha notu'}];fieldnotes.sync(p,payload);p.data['items']=[];fieldnotes.sync(p,payload)
        self.assertEqual(p.data['items'],[])
    def test_invalid_batch_does_not_partially_write(self):
        from modules import fieldnotes
        p=SimpleNamespace(data={},save=Mock())
        with self.assertRaises(ValueError):fieldnotes.sync(p,[{'uid':'note-12345678','text':'valid'},{'uid':'bad','text':'invalid'}])
        self.assertEqual(p.data,{});p.save.assert_not_called()
    def test_simultaneous_retries_produce_one_note(self):
        from modules import fieldnotes
        p=SimpleNamespace(slug='a',data={'items':[]},_new_id=lambda:1,save=Mock())
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            futures=[pool.submit(fieldnotes.sync,p,[{'uid':'note-12345678','text':'saha notu'}]) for _ in range(3)]
            for f in futures:f.result()
        self.assertEqual(len(p.data['items']),1)

class CancellationRaceTests(unittest.TestCase):
    def test_cancel_at_activation_keeps_command_loop_alive(self):
        from modules import requests_state as r
        tree=engine_source.tree()
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        branch=next(n for n in ast.walk(main) if isinstance(n,ast.Try) and any(isinstance(x,ast.With) and 'requests_state.activate' in ast.unparse(x.items) for x in n.body))
        loop=ast.For(target=ast.Name(id='_',ctx=ast.Store()),iter=ast.List(elts=[ast.Constant(value=1)],ctx=ast.Load()),body=[branch],orelse=[])
        emit=Mock()
        ns={'requests_state':r,'as_user':lambda user:contextlib.nullcontext(),'slugify':lambda user:user,'pc_profile':lambda:SimpleNamespace(name='a'),'owner':'a','user':'a','_cur_rid':'id','pause_listening':threading.Event(),'emit':emit}
        with tempfile.TemporaryDirectory() as td,patch.object(r,'_records',{}),patch.object(r,'_journal',Path(td)/'requests.json'):
            r.register('a','id');r.cancel('a','id')
            exec(compile(ast.fix_missing_locations(ast.Module(body=[loop],type_ignores=[])),'real-command-loop','exec'),ns)
        emit.assert_called_once_with('state','idle')


class QueuedVoiceCancellationTests(unittest.TestCase):
    def test_cancelled_queue_entry_releases_listen_and_request_context(self):
        from modules import requests_state as r
        tree = engine_source.tree()
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        branch = next(n for n in ast.walk(main) if isinstance(n, ast.If) and ast.unparse(n.test).startswith('requests_state.is_cancelled('))
        loop = ast.For(target=ast.Name(id='_', ctx=ast.Store()), iter=ast.List(elts=[ast.Constant(value=1)], ctx=ast.Load()), body=[branch], orelse=[])
        pause = threading.Event(); pause.set()
        emit = Mock()
        ns = {'requests_state': r, 'slugify': lambda name: name, 'owner': 'a', 'user': 'a', '_cur_rid': 'voice-id', '_cur_source': 'ses', 'pause_listening': pause, 'emit': emit}
        with patch.object(r, '_records', {('a', 'voice-id'): {'state': 'cancelled', 'deadline': 0}}):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), 'queued-cancel-production-branch', 'exec'), ns)
        self.assertFalse(pause.is_set())
        self.assertIsNone(ns['_cur_rid'])
        self.assertEqual(ns['_cur_source'], '')
        emit.assert_called_once_with('state', 'idle')


class DeletedQueuedUserTests(unittest.TestCase):
    def test_deleted_user_does_not_stop_command_audio_or_photo_loop(self):
        from modules import requests_state as r
        tree = engine_source.tree()
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        cleanup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_reject_queued_input')
        def rejected_user(name):
            raise ValueError('Telefon kullanıcısı bulunamadı')
        for kind in ('audio', 'photo', 'command'):
            with self.subTest(kind=kind):
                if kind == 'audio':
                    from modules import engine_loop, engine_queue
                    pause = threading.Event(); pause.set()
                    emit, failure = Mock(), Mock()
                    runtime = SimpleNamespace(as_user=rejected_user, slugify=lambda name:name,
                        requests_state=SimpleNamespace(Cancelled=r.Cancelled,cancel=Mock()),
                        _cur_source='telefon',_cur_rid='rid',pause_listening=pause,
                        emit=emit,_record_failure=failure,os=SimpleNamespace(remove=Mock()))
                    runtime._reject_queued_input=lambda:engine_queue._reject_queued_input(runtime)
                    engine_loop._queued_audio(runtime,('audio','upload','telefon','deleted','rid'))
                    self.assertFalse(pause.is_set())
                    self.assertIsNone(runtime._cur_rid);self.assertEqual(runtime._cur_source,'')
                    runtime.os.remove.assert_called_once_with('upload')
                    failure.assert_called_once()
                    self.assertIn(unittest.mock.call('state','idle'),emit.call_args_list)
                    continue
                if kind == 'command':
                    branch = next(n for n in ast.walk(main) if isinstance(n, ast.Try) and any(isinstance(x, ast.With) and 'requests_state.activate' in ast.unparse(x.items) for x in n.body))
                    event = ('command', 'merhaba', 'telefon', 'deleted', 'rid')
                else:
                    branch = next(n for n in ast.walk(main) if isinstance(n, ast.If) and ast.unparse(n.test) == 'kind == ' + repr(kind))
                    event = (kind, 'upload', 'telefon', 'deleted') if kind == 'audio' else (kind, 'upload', '', 'telefon', 'deleted', 'rid')
                loop = ast.For(target=ast.Name(id='_', ctx=ast.Store()), iter=ast.List(elts=[ast.Constant(value=1)], ctx=ast.Load()), body=[branch], orelse=[])
                pause = threading.Event(); pause.set()
                emit, failure = Mock(), Mock()
                ns = {'kind': kind, 'event': event, 'as_user': rejected_user, 'requests_state': r,
                      'slugify': lambda name: name, 'pc_profile': lambda: SimpleNamespace(name='deleted'), 'owner': 'deleted',
                      'user': 'deleted', '_cur_source': 'telefon', '_cur_rid': 'rid', 'pause_listening': pause,
                      'emit': emit, '_record_failure': failure}
                exec(compile(ast.fix_missing_locations(ast.Module(body=[cleanup, loop], type_ignores=[])), 'deleted-user-production-loop', 'exec'), ns)
                self.assertFalse(pause.is_set())
                self.assertIsNone(ns['_cur_rid'])
                self.assertEqual(ns['_cur_source'], '')
                failure.assert_called_once()
                self.assertIn(unittest.mock.call('state', 'idle'), emit.call_args_list)


class MultiStepOwnershipTests(unittest.TestCase):
    def envelope(self, replies=None):
        calls = []
        def step(_runtime, text):
            calls.append(text)
            return (replies.get(text, text + ' bitti') if replies else text + ' bitti',
                    SimpleNamespace(result_status='handled'))
        return calls, patch('modules.brain_entry.run_step', side_effect=step)

    def test_a_step_cannot_consume_an_open_pending_answer(self):
        from modules.session_state import SessionState
        from modules.command_manager import PENDING_INPUT_FIELDS
        session = SessionState()
        for field in PENDING_INPUT_FIELDS:
            with self.subTest(field=field):
                setattr(session, field, True if field == 'pending_weather_location' else 'waiting')
                ns = {'_session': lambda: session, 'profile': SimpleNamespace(slug='hamdi'), 'runtime': object(),
                      'handle': Mock(side_effect=AssertionError('adım yeniden yorumlanamaz')),
                      'privacy': SimpleNamespace(audit=Mock()), 'flags': {}, 'stop_event': threading.Event()}
                functions('main.py', ['_run_steps'], ns)
                calls, envelope = self.envelope()
                with envelope:
                    result = ns['_run_steps'](['ilk adım', 'sonraki adım'])
                ns['handle'].assert_not_called()
                self.assertEqual(calls, ['ilk adım'])
                self.assertIn('yanıt veya onay bekliyor', result)
                self.assertEqual(getattr(session, field), True if field == 'pending_weather_location' else 'waiting')
                self.assertFalse(session._in_multi)
                setattr(session, field, None)

    def test_a_chain_stops_when_the_user_changes_after_a_step(self):
        from modules.session_state import SessionState
        original, target = SessionState(), SessionState()
        ns = {'profile': SimpleNamespace(slug='hamdi'), 'privacy': SimpleNamespace(audit=Mock()), 'flags': {},
              'stop_event': threading.Event(), 'runtime': object(),
              'handle': Mock(side_effect=AssertionError('adım yeniden yorumlanamaz'))}
        ns['_session'] = lambda: original if ns['profile'].slug == 'hamdi' else target
        functions('main.py', ['_run_steps'], ns)
        calls = []
        def step(_runtime, text):
            calls.append(text)
            if text == 'kullanıcı değiştir':
                ns['profile'] = SimpleNamespace(slug='ebru')
            return (text + ' bitti', SimpleNamespace(result_status='handled'))
        with patch('modules.brain_entry.run_step', side_effect=step):
            result = ns['_run_steps'](['kullanıcı değiştir', 'dosyayı sil'])
        ns['handle'].assert_not_called()
        self.assertEqual(calls, ['kullanıcı değiştir'])
        self.assertIn('Kullanıcı değişti', result)
        self.assertNotIn('dosyayı sil', result)
        self.assertFalse(original._in_multi)
        self.assertFalse(target._in_multi)


class BackgroundNoticeTests(unittest.TestCase):
    def nested(self, name, ns):
        tree = engine_source.tree()
        outer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        fn = next(n for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'real-background-notice', 'exec'), ns)
        return ns[name]

    def test_shutdown_aborts_delayed_startup_notices(self):
        for name in ('_handoff_notice', '_learning_notice'):
            with self.subTest(name=name):
                ns = {'stop_event': SimpleNamespace(wait=Mock(return_value=True))}
                self.nested(name, ns)()  # No model, UI, profile or provider should be needed.
                ns['stop_event'].wait.assert_called_once()

    def test_handoff_is_owned_by_pc_even_while_phone_guest_is_active(self):
        from modules import handoff
        owner = SimpleNamespace(slug='hamdi', data={'prefs': {}})
        sent, events = Mock(), queue.Queue()
        ns = {'stop_event': SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)), 'pc_profile': lambda: owner, 'profile': SimpleNamespace(slug='ebru'), 'datetime': SimpleNamespace(now=lambda: SimpleNamespace(hour=19)), '_emit_for': sent, 'events': events, '_record_failure': Mock()}
        with patch.object(handoff, 'startup_notice', return_value='Devir notu'):
            self.nested('_handoff_notice', ns)()
        sent.assert_called_once_with(owner, 'assistant', 'Devir notu')
        self.assertEqual(events.get_nowait(), ('say', 'Devir notu', 'hamdi'))

    def test_learning_uses_pc_owner_and_does_not_emit_to_a_changed_pc_user(self):
        from modules import learning
        owner, other = SimpleNamespace(slug='hamdi'), SimpleNamespace(slug='can')
        emitted, model = Mock(), Mock()
        ns = {'stop_event': SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)), 'pc_profile': Mock(side_effect=[owner, other]), '_llm': model, 'emit': emitted, '_record_failure': Mock()}
        with patch.object(learning, 'startup_notice', return_value='Rapor') as notice:
            self.nested('_learning_notice', ns)()
        notice.assert_called_once_with(owner)
        model.set_user_context.assert_called_once_with('hamdi')
        emitted.assert_not_called()

    def test_ui_failure_does_not_abort_background_history_and_notifications(self):
        owner = SimpleNamespace(slug='hamdi', name='Hamdi')
        failure, history = Mock(), Mock()
        history.append.return_value = {'id': 42}
        ns = {'_log_id': 0, '_event_lock': threading.RLock(), 'event_log': [], 'history': history, 'pc_profile': lambda: owner, '_ui': Mock(side_effect=RuntimeError('UI closed')), '_record_failure': failure}
        functions('main.py', ['_emit_for'], ns)
        ns['_emit_for'](owner, 'assistant', 'Hatırlatma', 'hatırlatma')
        self.assertEqual(ns['event_log'][0]['hid'], 42)
        failure.assert_called_once()


class MorningBriefOwnershipTests(unittest.TestCase):
    def runtime(self):
        owner = SimpleNamespace(name='Hamdi', slug='hamdi', data={'prefs': {}}, set_pref=Mock())
        now = datetime(2026, 10, 8, 9, 0)
        return SimpleNamespace(profile=SimpleNamespace(name='Ebru', slug='ebru'), pc_profile=Mock(return_value=owner), datetime=SimpleNamespace(now=lambda: now), stop_event=SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)), flags={'sleep': False}, _llm=Mock(), _emit_for=Mock(), events=queue.Queue()), owner

    def test_brief_uses_captured_pc_profile_and_owner_tagged_speech(self):
        from modules import main_planner
        runtime, owner = self.runtime()
        with patch.object(main_planner, '_daily_briefing', return_value='PC özeti') as briefing, patch.object(main_planner, '_brief_facts', return_value=['PC verisi']) as facts:
            main_planner._morning_brief(runtime)
            owned = briefing.call_args.args[0]
            self.assertIs(owned.profile, owner)
            self.assertEqual(owned._brief_facts(), ['PC verisi'])
            facts.assert_called_once_with(owned)
        self.assertEqual(runtime.profile.slug, 'ebru')
        runtime._llm.set_user_context.assert_called_once_with('hamdi')
        runtime._emit_for.assert_called_once_with(owner, 'assistant', 'PC özeti')
        self.assertEqual(runtime.events.get_nowait(),
                         ('say', 'PC özeti', 'hamdi', {'kind': 'notice', 'event_id': 'brief:2026-10-08'}))

    def test_shutdown_before_delay_does_not_fetch_brief_or_mark_seen(self):
        from modules import main_planner
        runtime, owner = self.runtime();runtime.stop_event.wait.return_value = True
        with patch.object(main_planner, '_daily_briefing') as briefing:
            main_planner._morning_brief(runtime)
        briefing.assert_not_called();owner.set_pref.assert_not_called()

    def test_pc_user_change_during_network_call_does_not_emit_or_mark_seen(self):
        from modules import main_planner
        runtime, owner = self.runtime()
        runtime.pc_profile.side_effect = [owner, SimpleNamespace(slug='can')]
        with patch.object(main_planner, '_daily_briefing', return_value='Hamdi özeti'):
            main_planner._morning_brief(runtime)
        runtime._emit_for.assert_not_called();owner.set_pref.assert_not_called()
        self.assertTrue(runtime.events.empty())
