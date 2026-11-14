"""Report regressions: deterministic disk/network/thread tests; no real devices or AI calls."""
import ast
import collections
import concurrent.futures
import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.request
from urllib.parse import parse_qs, urlparse
import os
import shutil
import test_engine_modular as fixtures
from modules import llm, requests_state as requests, study, studyexam, nxapi
from modules import engine_output
ROOT = Path(__file__).resolve().parents[1]


def web_class(name, namespace):
    tree = ast.parse((ROOT/'web.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    exec('from __future__ import annotations\n' + ast.unparse(node), namespace)
    return namespace[name]


class HistoryTests(unittest.TestCase):
    def test_reset_rejects_inflight_reply_then_accepts_fresh_draft(self):
        entered, release = threading.Event(), threading.Event()
        def send(*args):
            entered.set(); self.assertTrue(release.wait(3)); return 'OLD RESPONSE'
        with patch.object(llm, '_histories', {}), patch.object(llm, '_history_epochs', {}), \
             patch.object(llm, '_history_seed', lambda user: []), patch.object(llm, '_send', side_effect=send):
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                pending = pool.submit(llm.chat, 'old question', user='alice')
                self.assertTrue(entered.wait(2))
                llm.reset_history('alice'); release.set()
                with self.assertRaises(requests.Cancelled): pending.result(3)
            self.assertEqual(llm._histories['alice'], [])
            with patch.object(llm, '_send', return_value='NEW RESPONSE'):
                self.assertEqual(llm.chat('new question', user='alice'), 'NEW RESPONSE')
            self.assertEqual(len(llm._histories['alice']), 2)
            self.assertNotIn('OLD RESPONSE', str(llm._histories))

    def test_reset_is_scoped_to_owner(self):
        with patch.object(llm, '_histories', {'a': ['old'], 'b': ['keep']}), patch.object(llm, '_history_epochs', {}):
            llm.reset_history('a')
            self.assertEqual(llm._histories['b'], ['keep'])
            self.assertEqual(llm._history_epochs, {'a': 1})

    def test_cancelled_assistant_is_not_appended_or_emitted(self):
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='a', name='A'), _event_lock=threading.RLock(),
            history=Mock(), _ui=Mock(), _cur_rid='id')
        with patch.object(requests, '_records', {('a','id'): {'state':'cancelled','deadline':time.monotonic()+90}}), \
             patch.object(requests, '_journal', Path(tempfile.gettempdir())/'unused-review-journal'), patch.object(requests, '_save'):
            token = requests._current.set(('a','id'))
            try:
                with self.assertRaises(requests.Cancelled): engine_output.emit(runtime, 'assistant', 'late')
            finally: requests._current.reset(token)
        runtime.history.append.assert_not_called(); runtime._ui.assert_not_called()


class ClientTests(unittest.TestCase):
    def test_simultaneous_same_owner_creates_one_client(self):
        barrier = threading.Barrier(6)
        def worker():
            llm.set_user_context('alice'); barrier.wait(); return llm._cli()
        with patch.object(llm, '_user_clients', {}), patch.object(llm, 'user_key', return_value='fake-key'), \
             patch.object(llm.genai, 'Client', return_value=object()) as create:
            with concurrent.futures.ThreadPoolExecutor(6) as pool:
                results = list(pool.map(lambda _: worker(), range(6)))
            self.assertEqual(create.call_count, 1)
            self.assertTrue(all(x is results[0] for x in results))

    def test_key_change_invalidates_client_created_during_overlap(self):
        entered, release, setting = threading.Event(), threading.Event(), threading.Event()
        def create(**kw):
            if kw['api_key'] == 'old':
                entered.set(); self.assertTrue(release.wait(3))
            return SimpleNamespace(key=kw['api_key'])
        with tempfile.TemporaryDirectory() as td:
            keyfile = Path(td)/'key.txt'; keyfile.write_text('old')
            with patch.object(llm, '_user_clients', {}), patch.object(llm, '_key_file', return_value=keyfile), \
                 patch.object(llm.privacy, 'protect', side_effect=lambda s:s), patch.object(llm.privacy, 'unprotect', side_effect=lambda s:s), \
                 patch.object(llm.genai, 'Client', side_effect=create):
                def get(): llm.set_user_context('alice'); return llm._cli()
                def set_key(): setting.set(); llm.set_user_key('alice', 'new')
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    old = pool.submit(get); self.assertTrue(entered.wait(2))
                    updated = pool.submit(set_key); self.assertTrue(setting.wait(2)); release.set()
                    self.assertEqual(old.result(3).key, 'old'); updated.result(3)
                self.assertEqual(get().key, 'new')
                self.assertEqual(keyfile.read_text(), 'new')


class DirectToolTests(unittest.TestCase):
    """Domain sahipleri işlem ortasında iptal/deadline duyulunca effect üretmez.

    Eski Live araç çiti (prepare_live_tool/live_tool_runner) emekli oldu; aynı iptal
    garantisi yaşayan yüzeyde test_conversation_request_safety.py'de `_live_command`
    üzerinden, burada ise domain araçlarının kendisinde doğrulanır.
    """

    def test_music_cancelled_during_search_never_opens_browser(self):
        from modules import media
        with tempfile.TemporaryDirectory() as td, patch.object(requests, '_records', {}), patch.object(requests, '_journal', Path(td)/'requests.json'):
            requests.register('a','music')
            def search(*a,**k): requests.cancel('a'); return SimpleNamespace(text='"videoId":"12345678901"')
            with requests.activate('a','music'), patch.object(media.requests,'get',side_effect=search), patch.object(media.webbrowser,'open') as browser:
                with self.assertRaises(requests.Cancelled): media.youtube('test')
                browser.assert_not_called()

    def test_handoff_cancelled_during_list_lookup_never_inserts(self):
        from modules import handoff
        svc=Mock()
        with tempfile.TemporaryDirectory() as td, patch.object(requests, '_records', {}), patch.object(requests, '_journal', Path(td)/'requests.json'):
            requests.register('a','task')
            def lid(s): requests.cancel('a'); return 'list'
            with requests.activate('a','task'), patch.object(handoff,'_svc',return_value=svc), patch.object(handoff,'_lid',side_effect=lid), patch.object(handoff,'place',return_value='ev'):
                with self.assertRaises(requests.Cancelled): handoff.add('test','ev')
                svc.tasks.assert_not_called()


class VisionTests(unittest.TestCase):
    def test_local_vision_uses_real_image_bytes_and_never_calls_gemini(self):
        from PIL import Image
        from provider_fixture import routed_plan
        for fmt in ['PNG','JPEG','WEBP']:
            with self.subTest(fmt=fmt),tempfile.TemporaryDirectory() as td:
                path=Path(td)/'image.any';Image.new('RGB',(4,4)).save(path,fmt)
                with routed_plan(provider='ollama',model='vision-fixture'),patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli') as cloud,patch.object(llm,'_ollama',return_value='yerel') as local,patch.object(llm.privacy,'mode',return_value='normal'):
                    self.assertEqual(llm.ask_image(str(path),'prompt','system',strict=True),'yerel')
                    self.assertEqual(local.call_args.kwargs['images'][0],__import__('base64').b64encode(path.read_bytes()).decode())
                    self.assertEqual(local.call_args.kwargs['model'],'vision-fixture')
                    cloud.assert_not_called()
        self.assertFalse(hasattr(llm,'_ask_image'))

    def test_local_vision_failure_has_no_gemini_fallback(self):
        from provider_fixture import routed_plan
        with routed_plan(provider='ollama',model='vision-fixture'),patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli') as cloud,patch.object(llm,'_ollama',side_effect=llm.LocalModelError('no vision')),patch.object(llm.privacy,'mode',return_value='normal'),patch('builtins.open',__import__('unittest').mock.mock_open(read_data=b'x')):
            with self.assertRaises(RuntimeError):llm.ask_image('x.png','p',strict=True)
        cloud.assert_not_called()


class UploadTests(unittest.TestCase):
    def handler(self, root, stream, target='files'):
        ns={'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'parse_qs':parse_qs,'urlparse':urlparse,'Path':Path,
            'UPLOAD_DIR':root/'uploads','DATA_DIR':root,'tempfile':tempfile,'os':os,'shutil':shutil,
            '_record_failure':Mock(),'kb':Mock(),'_p':lambda:'profile','threading':Mock(),'_index_upload':Mock()}
        Handler=web_class('Handler',ns)
        obj=Handler.__new__(Handler);obj.path='/upload?to='+target+'&name=test.png';obj.rfile=stream;obj._json=Mock();obj.close_connection=False
        return obj,ns

    def test_stream_is_bounded_and_complete_for_every_target(self):
        class Limited(io.BytesIO):
            def read(self,n=-1):
                if not 0 < n <= 1<<20: raise AssertionError(n)
                return super().read(n)
        for target in ['files','bg','phone','kb']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as td:
                root=Path(td);data=b'\x89PNG\r\n\x1a\n'+b'x'*(2*(1<<20))
                obj,ns=self.handler(root,Limited(data),target)
                def send(p): self.assertEqual(p.read_bytes(),data);return {'ok':True}
                with patch.object(nxapi,'FILES_DIR',root/'files'), patch('modules.filesend.send',side_effect=send):
                    obj._upload(len(data))
                self.assertTrue(obj._json.call_args.args[0]['ok'])
                self.assertFalse(list((root/'uploads').glob('upload_*')))
                if target=='bg':self.assertEqual((root/'arka_plan.img').read_bytes(),data)

    def test_truncated_input_is_rejected_and_staging_cleaned_for_every_target(self):
        for target in ['files','bg','phone','kb']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as td:
                root=Path(td);obj,ns=self.handler(root,io.BytesIO(b'partial'),target)
                with patch.object(nxapi,'save_upload_stream') as accept,patch('modules.filesend.send') as send:
                    obj._upload(100)
                self.assertFalse(obj._json.call_args.args[0]['ok']);accept.assert_not_called();send.assert_not_called()
                self.assertEqual(list((root/'uploads').iterdir()),[]);self.assertTrue(obj.close_connection)

    def test_disk_failure_cleans_phone_staging(self):
        from modules import upload_stream
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);obj,ns=self.handler(root,io.BytesIO(b'x'),'phone')
            with patch.object(upload_stream,'receive',side_effect=OSError('disk failed')):
                obj._upload(1)
            self.assertFalse(obj._json.call_args.args[0]['ok']);self.assertEqual(list((root/'uploads').iterdir()),[])

    def test_existing_kb_file_is_preserved_on_reservation_permission_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);obj,ns=self.handler(root,io.BytesIO(b'new'),'kb');folder=root/'uploads';folder.mkdir()
            existing=folder/'test.png';existing.write_bytes(b'keep')
            original=Path.open
            def opened(path, mode='r', *args, **kwargs):
                if path==existing and mode=='xb': raise PermissionError('denied')
                return original(path,mode,*args,**kwargs)
            with patch.object(Path,'open',opened):obj._upload(3)
            self.assertEqual(existing.read_bytes(),b'keep')


class PerformanceTests(unittest.TestCase):
    def test_bank_is_built_once_per_mock_or_stats_operation_and_refreshes_next_time(self):
        from test_study_exam_bank import SAMPLE,_Profile
        with tempfile.TemporaryDirectory() as td,patch.object(study,'ROOT',Path(td)):
            p=_Profile([{'id':1,'title':'exam','kind':'exam','year':2025}])
            folder=study._dir(p);(folder/'1.txt').write_text(SAMPLE)
            p.data['study']['courses']=[next(iter(studyexam.bank(p)))]
            with patch.object(studyexam,'_exam_bank',wraps=studyexam._exam_bank) as parse:
                result=studyexam.mock_start(p,2);self.assertEqual(result['total'],2);self.assertEqual(parse.call_count,1)
                studyexam.stats(p);self.assertEqual(parse.call_count,2)
            p.data['study']['docs']=[]
            self.assertEqual(studyexam.bank(p),{})
            self.assertIsNone(studyexam._bank_snapshot.get())

    def test_ollama_tags_cache_returns_copies_and_isolates_url_and_force(self):
        response=Mock();response.json.return_value={'models':[{'name':'test'}]}
        config={'url':'http://one'}
        with patch.object(llm,'_ollama_tags_cache',{}),patch.object(llm,'_cfg',side_effect=lambda:config),patch.object(llm.requests,'get',return_value=response) as get:
            first=llm.ollama_models();first.append('changed');self.assertEqual(llm.ollama_models(),['test']);self.assertEqual(get.call_count,1)
            llm.ollama_models(force=True);self.assertEqual(get.call_count,2)
            config['url']='http://two';llm.ollama_models();self.assertEqual(get.call_count,3)

    def test_query_vector_cache_is_scoped_to_user_key_model_and_privacy(self):
        p=SimpleNamespace(slug='a');settings={};owner=['a'];key=['one'];mode=['normal']
        with patch.object(study,'_QUERY_VECTORS',{}),patch('config.load_settings',side_effect=lambda:settings), \
             patch.object(llm,'current_user',side_effect=lambda:owner[0]),patch.object(llm,'user_key',side_effect=lambda u:key[0]), \
             patch.object(llm,'provider',return_value='ollama'),patch.object(llm.privacy,'mode',side_effect=lambda:mode[0]), \
             patch.object(llm,'gemini_aux_allowed',return_value=True),patch.object(llm,'embed',return_value=[[1,2]]) as embed:
            study._question_vector(p,'question');study._question_vector(p,'question');self.assertEqual(embed.call_count,1)
            key[0]='two';study._question_vector(p,'question');self.assertEqual(embed.call_count,2)
            settings['ollama_embed_model']='new';study._question_vector(p,'question');self.assertEqual(embed.call_count,3)
            owner[0]='b';study._question_vector(p,'question');self.assertEqual(embed.call_count,4)
            mode[0]='yerel';study._question_vector(p,'question');self.assertEqual(embed.call_count,5)


class EventTests(unittest.TestCase):
    def test_same_text_events_keep_their_original_message_and_request_ids(self):
        engine=SimpleNamespace(pc_profile=lambda:SimpleNamespace(slug='a'))
        Hub=web_class('Hub',{'engine':engine,'threading':threading,'queue':queue,'deque':collections.deque,'time':time})
        hub=Hub();q=hub.subscribe()
        hub.publish('assistant','same',metadata={'user':'a','mid':'first','rid':'one'})
        hub.publish('assistant','same',metadata={'user':'a','mid':'second','rid':'two'})
        self.assertEqual((q.get()['mid'],q.get()['rid']),('first','two'))
        # No event_log lookup exists: the fake engine intentionally has none.

    def test_concurrent_activity_ids_are_unique(self):
        Hub=web_class('Hub',{'engine':SimpleNamespace(pc_profile=lambda:SimpleNamespace(slug='a')),'threading':threading,'queue':queue,'deque':collections.deque,'time':time})
        hub=Hub()
        with concurrent.futures.ThreadPoolExecutor(8) as pool:list(pool.map(lambda i:hub.publish('activity',str(i)),range(200)))
        self.assertEqual(len({x['id'] for x in hub.activity}),200);self.assertEqual(hub.activity_seq,200)


class MiscTests(unittest.TestCase):
    def test_number_line_rejects_non_lists_and_keeps_valid_values(self):
        from modules import math_tutor
        for values in ['12',{},None,1]:
            with self.subTest(values=values),self.assertRaises(ValueError):math_tutor.visual_svg({'kind':'number_line','min':0,'max':20,'values':values})
        self.assertIn('12</text>',math_tutor.visual_svg({'kind':'number_line','min':0,'max':20,'values':[12]}))

    def test_empty_goal_does_not_save_or_mutate(self):
        from modules.personalization import Profile
        p=Profile.__new__(Profile);p.data={'goals':['keep']};p.save=Mock()
        for text in ['', '   ', None]:p.add_goal(text)
        self.assertEqual(p.data['goals'],['keep']);p.save.assert_not_called()

    def test_turkish_mishearing_is_normalized_and_deduplicated(self):
        from modules import learning, stt_fixes
        settings={'stt_fixes':''}
        with patch.object(learning,'load_settings',side_effect=lambda:settings),patch.object(learning,'save_settings',side_effect=lambda **kw:settings.update(kw)):
            learning.learn_mishearing('IŞIK','ışık aç');learning.learn_mishearing('ışık','ışık kapat')
            pairs=stt_fixes.parse_fixes(settings['stt_fixes']);self.assertEqual(pairs,[('ışık','ışık kapat')])
            self.assertEqual(stt_fixes.format_fixes(pairs),'ışık=ışık kapat')

    def test_background_settings_follow_data_dir(self):
        with tempfile.TemporaryDirectory() as td,patch.object(nxapi,'DATA_DIR',Path(td)),patch.object(nxapi,'load_settings',return_value={}),patch.object(nxapi,'autostart_get',return_value=False),patch('modules.learning.enabled',return_value=False),patch('modules.personalization.Profile'),patch('modules.personalization.get_active',return_value='a'):
            image=Path(td)/'arka_plan.img';image.write_bytes(b'image')
            self.assertTrue(nxapi.ui_settings()['bg'])
            nxapi.ui_set('bg',False)
            self.assertFalse(image.exists())

    def test_scope_change_restarts_running_phone(self):
        from web_phone import WebPhone
        runtime=SimpleNamespace(phone=Mock(running=True),config=Mock(),privacy=Mock())
        bridge=WebPhone();bridge._runtime=runtime;bridge.phone_info=lambda:{'ok':True}
        bridge.phone_set({'scope':'both'});runtime.phone.stop.assert_called_once();runtime.phone.start.assert_called_once()
        runtime.config.save_settings.assert_called_once_with(phone_scope='both',phone_allow_http=True)

    def test_unknown_phone_post_returns_404(self):
        from modules import phone
        from test_phone_user_tokens import _FakeEngine
        with tempfile.TemporaryDirectory() as td,patch.object(phone,'TOKEN_FILE',Path(td)/'token'),patch.object(phone,'USER_TOKENS_FILE',Path(td)/'tokens.json'),patch.object(phone,'_harden'),patch.object(phone,'load_settings',return_value={'phone_scope':'both','phone_allow_http':True}),patch.object(phone,'https_url',return_value=''),patch.object(phone,'tailscale_ip',return_value=None),patch.object(phone,'lan_ip',return_value='127.0.0.1'),patch('modules.personalization.get_active',return_value='Hamdi'):
            server=phone.PhoneServer(_FakeEngine(),port=0);server.start()
            try:
                req=urllib.request.Request('http://127.0.0.1:'+str(server._httpd.server_address[1])+'/unknown',data=b'')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req,timeout=3)
                self.assertEqual(error.exception.code,404);error.exception.close()
            finally:server.stop()

    def test_stale_background_scan_cannot_overwrite_forced_refresh(self):
        old_started, release_old = threading.Event(), threading.Event()
        old=[{'mtime':1,'cat':'pdf','name':'old'}]; new=[{'mtime':2,'cat':'pdf','name':'new'}]
        def scan():
            if threading.current_thread().name=='old-scan':
                old_started.set();self.assertTrue(release_old.wait(3));return old
            return new
        with tempfile.TemporaryDirectory() as td, patch.object(nxapi,'FILES_DIR',Path(td)), \
             patch.object(nxapi,'_FILE_CACHE',{'rows':old,'ts':0}),patch.object(nxapi,'_file_generation',0), \
             patch.object(nxapi,'_scan_files',side_effect=scan):
            thread=threading.Thread(target=nxapi._background_refresh,args=(0,),name='old-scan');thread.start()
            try:
                self.assertTrue(old_started.wait(2))
                result=nxapi.list_files(force=True);self.assertEqual(result['files'][0]['name'],'new')
            finally:release_old.set();thread.join(3)
            self.assertFalse(thread.is_alive());self.assertEqual(nxapi._FILE_CACHE['rows'],new)

    def test_invalid_audio_path_does_not_escape_cleanup_and_next_audio_is_handed_off(self):
        from modules import engine_loop
        runtime=SimpleNamespace(pc_profile=lambda:SimpleNamespace(name='A'),slugify=lambda x:x,
            requests_state=SimpleNamespace(cancel=Mock(),Cancelled=requests.Cancelled,check=Mock(),activate=lambda *a,**k:contextlib.nullcontext()),
            _record_failure=Mock(),_reject_queued_input=Mock(),os=os,emit=Mock(),
            as_user=lambda x:contextlib.nullcontext(),llm_transcribe=Mock(return_value='merhaba'),
            _tr_lower=str.lower,privacy=Mock(),events=queue.Queue())
        engine_loop._queued_audio(runtime,('audio',None,'telefon','A',None))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'audio.wav';path.write_bytes(b'fake')
            engine_loop._queued_audio(runtime,('audio',str(path),'telefon','A','valid'))
            self.assertFalse(path.exists())
        self.assertEqual(runtime.events.get_nowait(),('command','merhaba','telefon','A','valid'))


class GitSyncTests(unittest.TestCase):
    def test_line_endings_match_but_content_and_binary_changes_do_not(self):
        from modules.source_sync import blob_matches,blob_sha
        self.assertTrue(blob_matches('main.py',b'x=1\r\n',blob_sha(b'x=1\n')))
        self.assertTrue(blob_matches('main.py',b'x=1\n',blob_sha(b'x=1\r\n')))
        self.assertFalse(blob_matches('main.py',b'x=2\r\n',blob_sha(b'x=1\n')))
        self.assertFalse(blob_matches('image.png',b'x\r\n',blob_sha(b'x\n')))
        self.assertTrue(blob_matches('modules/desktop_uia.ps1',b'x=1\r\n',blob_sha(b'x=1\n')))   # Windows CRLF kopyası fark sayılmaz

    def test_updater_comparison_does_not_report_newline_only_as_dirty(self):
        import updater
        from modules.source_sync import blob_sha
        with tempfile.TemporaryDirectory() as td,patch.object(updater,'ROOT',Path(td)):
            (Path(td)/'main.py').write_bytes(b'x=1\r\n');(Path(td)/'image.png').write_bytes(b'image')
            tree={'tree':[{'path':'main.py','type':'blob','sha':blob_sha(b'x=1\n')},{'path':'image.png','type':'blob','sha':blob_sha(b'image')}]}
            with patch.object(updater,'_get',return_value=json.dumps(tree).encode()):
                self.assertEqual(updater._source_changes_against('base'),[])
                (Path(td)/'main.py').write_bytes(b'x=2\r\n');self.assertEqual(updater._source_changes_against('base'),['main.py'])

    def test_existing_divergence_guard_is_not_bypassed(self):
        import updater
        with patch.object(updater,'status',return_value={}),patch.object(updater,'latest',return_value={'sha':'remote'}),patch.object(updater,'_state',return_value={'sha':'base'}),patch.object(updater,'_source_changes_against',return_value=['main.py']),patch.object(updater,'_compare_commits',return_value='ahead'),patch.object(updater,'_save_state'):
            self.assertEqual(updater.verify_sync()['sync_state'],'diverged')


if __name__=='__main__':unittest.main()
