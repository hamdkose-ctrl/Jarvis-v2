import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image

from modules import pc_guide as guide


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.profile=SimpleNamespace(slug='alice',name='Alice',data={},save=Mock())
        self.runtime=SimpleNamespace(_p=lambda:self.profile,sys=SimpleNamespace(platform='win32'),
            _win_action=Mock(return_value=True),engine=SimpleNamespace(submit=Mock(),_cur_source=''),voice=SimpleNamespace(stop_speaking=Mock()))
        self.session=guide.Session(self.profile,'Fotoğrafı telefona gönder',self.runtime)
        self.session.ui=Mock();self.session.hidden=True
        self.reply=json.dumps({'instruction':'Fotoğraflar klasörüne çift tıkla.','expected':'Klasör açılmış olmalı.',
             'progress':'waiting','target':{'label':'Fotoğraflar','confidence':.95,'box':[.1,.2,.2,.3]}})
        guide.configure(self.runtime)
        self.patches=[patch.object(guide.privacy,'blocked',return_value=None),patch.object(guide.llm,'set_user_context')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        guide._ACTIVE=None;guide.configure(None)

    def test_marker_requires_confidence_bounds_and_visible_label(self):
        self.assertEqual(guide.marker({'label':'Düğme','confidence':.95,'box':[.1,.2,.3,.4]}),[.1,.2,.3,.4])
        for target in [{'label':'x','confidence':.5,'box':[.1,.2,.3,.4]},
                       {'label':'x','confidence':1,'box':[.1,.2,1.1,.4]},
                       {'label':'x','confidence':1,'box':[.3,.2,.1,.4]},
                       {'label':'','confidence':1,'box':[.1,.2,.3,.4]},
                       {'label':'x','confidence':1,'box':[0,0,1,1]}]:
            self.assertIsNone(guide.marker(target))

    def test_check_uses_screen_and_prior_step_then_marks_one_step(self):
        self.session.step='Dosya Gezgini aç';self.session.expected='Gezgin açık'
        with patch.object(self.session,'snapshot',return_value=Image.new('RGB',(300,200))),patch.object(guide.llm,'ask_image',return_value=self.reply) as ask:
            result=self.session.check('yaptım')
            data=json.loads(ask.call_args.args[1]);self.assertEqual(data['previous_step'],'Dosya Gezgini aç')
            self.assertEqual(data['request'],'yaptım')
        self.assertEqual(result,'Fotoğraflar klasörüne çift tıkla.')
        self.session.ui.show.assert_called_with(result,[.1,.2,.2,.3])
        self.profile.save.assert_called_once()

    def test_screen_change_during_answer_does_not_show_old_marker_or_save(self):
        with patch.object(self.session,'snapshot',side_effect=[Image.new('RGB',(100,100),'black'),Image.new('RGB',(100,100),'white')]),patch.object(guide.llm,'ask_image',return_value=self.reply):
            result=self.session.check()
        self.assertIn('eski hedefi işaretlemedim',result);self.profile.save.assert_not_called()
        self.assertEqual(self.session.step,'')

    def test_cancel_while_model_runs_rejects_late_answer(self):
        def respond(*args,**kwargs):self.session.close();return self.reply
        with patch.object(self.session,'snapshot',return_value=Image.new('RGB',(100,100))),patch.object(guide.llm,'ask_image',side_effect=respond):
            self.assertEqual(self.session.check(),'PC rehberliği kapandı.')
        self.profile.save.assert_not_called();self.runtime._win_action.assert_called_once_with('show')

    def test_user_change_rejects_late_answer(self):
        def respond(*args,**kwargs):self.runtime._p=lambda:SimpleNamespace(slug='bob');return self.reply
        with patch.object(self.session,'snapshot',return_value=Image.new('RGB',(100,100))),patch.object(guide.llm,'ask_image',side_effect=respond):
            self.assertEqual(self.session.check(),'PC rehberliği kapandı.')
        self.profile.save.assert_not_called()

    def test_automatic_unchanged_frame_does_not_call_model(self):
        image=Image.new('RGB',(100,100));self.session.last_image=image.resize((320,180))
        with patch.object(self.session,'snapshot',return_value=image),patch.object(guide.llm,'ask_image') as ask:
            self.assertEqual(self.session.check(automatic=True),'');ask.assert_not_called()

    def test_simpler_request_keeps_goal_and_context(self):
        with patch.object(self.session,'snapshot',return_value=Image.new('RGB',(100,100))),patch.object(guide.llm,'ask_image',return_value=self.reply) as ask:
            self.session.check('anlamadım');data=json.loads(ask.call_args.args[1])
            self.assertEqual(data['request'],'anlamadım');self.assertEqual(data['goal'],self.session.goal)

    def test_snapshot_excludes_overlay_and_honors_privacy(self):
        from modules import vision
        with patch.object(vision,'_screen_image',return_value=Image.new('RGB',(20,20))) as shot:
            self.session.snapshot();self.session.ui.hide.assert_called_once();shot.assert_called_once()
        with patch.object(guide.privacy,'blocked',return_value='Gizli modda ekran kapalı'),patch.object(vision,'_screen_image') as shot,self.assertRaises(ValueError):
            self.session.snapshot()
        shot.assert_not_called();self.assertTrue(self.session.closed.is_set())

    def test_overlay_close_failure_still_restores_main_window(self):
        self.session.ui.close.side_effect=OSError('closed')
        with self.assertRaises(OSError):self.session.close()
        self.runtime._win_action.assert_called_once_with('show')

    def test_late_automatic_command_is_inert_after_stop(self):
        self.assertEqual(guide.handle(self.profile,'PC rehberliği: otomatik kontrol'),'PC rehberliği kapalı.')
        self.assertIsNone(guide.handle(self.profile,'Hava nasıl?'))

    def test_phone_cannot_start_desktop_coaching(self):
        self.runtime.engine._cur_source='telefon'
        self.assertIn('yalnız bilgisayardaki',guide.handle(self.profile,'PC yardımı: fotoğraf gönderme'))
        self.runtime._win_action.assert_not_called()

    def test_stop_is_immediate_and_idempotent(self):
        guide._ACTIVE=self.session
        self.session.action('stop');self.session.action('stop')
        self.assertFalse(guide.active('alice'));self.runtime._win_action.assert_called_once_with('show')

    def test_automatic_checks_are_debounced_and_bounded(self):
        self.assertTrue(self.session.queue_automatic_check(20))
        self.session.queued=False
        self.assertFalse(self.session.queue_automatic_check(25))
        for i in range(1,20):
            self.assertTrue(self.session.queue_automatic_check(20+i*10));self.session.queued=False
        self.assertFalse(self.session.queue_automatic_check(300))
        self.assertEqual(self.runtime.engine.submit.call_count,20)

    def test_voice_error_during_stop_still_closes(self):
        self.runtime.voice.stop_speaking.side_effect=OSError('audio')
        with self.assertRaises(OSError):self.session.action('stop')
        self.assertTrue(self.session.closed.is_set());self.runtime._win_action.assert_called_with('show')

    def test_resume_requires_explicit_request_and_rechecks_saved_step(self):
        self.profile.data['pc_guide_last']={'goal':'Fotoğraf gönderme','step':'Klasörü aç','expected':'Klasör içeriği'}
        with patch.object(guide.Session,'open'),patch.object(guide.Session,'check',return_value='Yeni ekranla kontrol edildi.') as check:
            reply=guide.handle(self.profile,'PC yardımı: devam')
        self.assertEqual(guide._ACTIVE.goal,'Fotoğraf gönderme');self.assertEqual(guide._ACTIVE.step,'Klasörü aç')
        self.assertIsNone(guide._ACTIVE.box);check.assert_called_once_with('başla')
        self.assertIn('Yeni ekranla',reply)

    def test_gui_python_uses_console_worker_with_piped_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/'pythonw.exe';console=Path(folder)/'python.exe';console.touch()
            with patch.object(guide.sys,'executable',str(executable)):
                self.assertEqual(guide.worker_python(),str(console))

    def test_i_cannot_find_it_stays_in_coaching_instead_of_switching_users(self):
        guide._ACTIVE=self.session
        with patch.object(self.session,'check',return_value='Sarı kutuya bak.') as check:
            self.assertEqual(guide.handle(self.profile,'Ben bu düğmeyi bulamadım'),'Sarı kutuya bak.')
        check.assert_called_once();self.assertFalse(self.session.closed.is_set())
