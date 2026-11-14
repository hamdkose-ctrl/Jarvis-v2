import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from modules import task_agents as agents
from modules import task_results,account_tools


class SimpleResultsTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)

    def mail(self,body='İyi çalışmalar',subject='Test konusu',sender='Test gönderen'):
        snapshot={'owner':'alice','service':'gmail','operation':'read_message','fetched_at':1.,
            'message':{'id':'SECRET_ID','subject':subject,'from':sender,'body':body,'truncated':False,'format':'plain'}}
        return task_results.seal('account',{'state':'done','snapshot':snapshot,
            'text':account_tools.render_snapshot(snapshot),'sha256':account_tools.digest(snapshot)})

    def writer(self,name='report.md',text='Rapor metni'):
        path=self.root/name;path.write_text(text,encoding='utf-8')
        return task_results.seal('writer',{'state':'done','text':text,'file':str(path),'sha256':task_results.file_digest(path)})

    def job(self, tasks, outputs, state='done'):
        return {'owner':'alice','id':'testjob','state':state,'tasks':tasks,'outputs':outputs}

    def task(self, name, agent, depends=(), state='done', **data):
        return {'id':name,'agent':agent,'state':state,'depends':list(depends),'input':data}

    def test_mail_body_visible_without_ids_hashes_or_intermediate_list(self):
        tasks=[self.task('list','account'),self.task('mail','account',('list',))]
        outputs={'list':self.mail('INTERNAL LIST'),'mail':self.mail()}
        job=self.job(tasks,outputs)
        result=agents.render_summary(job)
        self.assertIn('Test konusu',result);self.assertIn('İyi çalışmalar',result)
        for private in ('SECRET_ID','secret_hash','INTERNAL LIST',' · account · '):self.assertNotIn(private,result)
        self.assertIn(outputs['mail']['sha256'],agents.render(job))

    def test_mail_draft_only_reports_file_and_no_send(self):
        tasks=[self.task('mail','account',operation='read_message'),self.task('reply','writer',('mail',)),self.task('check','verify',('reply',))]
        result=agents.render_summary(self.job(tasks,{'mail':self.mail(),'reply':self.writer('reply.md','INTERNAL METADATA'),
            'check':task_results.seal('verify',{'state':'done','checks':{'reply':True}})}))
        self.assertIn('Mail gönderilmedi',result);self.assertIn('reply.md',result)
        self.assertNotIn('INTERNAL METADATA',result);self.assertNotIn('digest',result)

    def test_video_hides_journal_and_keeps_file(self):
        from modules import media_tools
        path=self.root/'video.mp4';path.write_bytes(b'video fixture')
        with patch.object(media_tools,'probe',return_value={'streams':'verified fixture'}):
            output=task_results.seal('media',{'state':'done','text':'raw render log','file':str(path),
                'sha256':task_results.file_digest(path),'media':{'streams':'verified fixture'}})
            result=agents.render_summary(self.job([self.task('video','media')],{'video':output}))
        self.assertIn('video.mp4',result);self.assertIn('Yayınlanmadı',result);self.assertNotIn('raw render log',result)

    def test_failed_final_check_is_not_hidden(self):
        tasks=[self.task('report','writer'),self.task('check','verify',('report',),state='failed')]
        result=agents.render_summary(self.job(tasks,{'report':self.writer(),'check':{'state':'failed','text':'Dosya değişmiş.'}},'incomplete'))
        self.assertIn('henüz tamamlanmadı',result);self.assertIn('Dosya değişmiş',result)
        self.assertIn('görev devam testjob',result)

    def test_long_body_preview_discloses_limit(self):
        result=agents.render_summary(self.job([self.task('mail','account')],{'mail':self.mail('x'*3000,'Test','Test')}))
        self.assertNotIn('x'*2001,result);self.assertIn('devamı',result)

    def test_command_summary_is_opt_in_and_explicit_status_keeps_journal(self):
        job=self.job([self.task('mail','account')],{'mail':self.mail('Merhaba','Test','Test')})
        with patch.object(agents,'execute',return_value=job):
            simple=agents.handle('alice','görev ilk mail oku',summary=True)
            technical=agents.handle('alice','görev ilk mail oku')
        self.assertIn('Merhaba',simple);self.assertNotIn('INTERNAL_ID',simple)
        self.assertIn('SECRET_ID',technical)
        with patch.object(agents,'recent',return_value=job):
            self.assertIn(job['outputs']['mail']['sha256'],agents.handle('alice','görev durumu',summary=True))
