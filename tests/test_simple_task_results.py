import unittest
from unittest.mock import patch
from modules import task_agents as agents


class SimpleResultsTests(unittest.TestCase):
    def job(self, tasks, outputs, state='done'):
        return {'id':'testjob','state':state,'tasks':tasks,'outputs':outputs}

    def task(self, name, agent, depends=(), state='done', **data):
        return {'id':name,'agent':agent,'state':state,'depends':list(depends),'input':data}

    def test_mail_body_visible_without_ids_hashes_or_intermediate_list(self):
        tasks=[self.task('list','account'),self.task('mail','account',('list',))]
        outputs={'list':{'text':'INTERNAL LIST'},'mail':{'text':'Mail kimliği: SECRET_ID',
            'sha256':'secret_hash','snapshot':{'operation':'read_message','message':{
                'subject':'Test konusu','from':'Test gönderen','body':'İyi çalışmalar','truncated':False}}}}
        job=self.job(tasks,outputs)
        result=agents.render_summary(job)
        self.assertIn('Test konusu',result);self.assertIn('İyi çalışmalar',result)
        for private in ('SECRET_ID','secret_hash','INTERNAL LIST',' · account · '):self.assertNotIn(private,result)
        self.assertIn('secret_hash',agents.render(job))

    def test_mail_draft_only_reports_file_and_no_send(self):
        tasks=[self.task('mail','account',operation='read_message'),self.task('reply','writer',('mail',)),self.task('check','verify',('reply',))]
        result=agents.render_summary(self.job(tasks,{'reply':{'text':'INTERNAL METADATA','file':'reply.md','sha256':'digest'}}))
        self.assertIn('Mail gönderilmedi',result);self.assertIn('reply.md',result)
        self.assertNotIn('INTERNAL METADATA',result);self.assertNotIn('digest',result)

    def test_video_hides_journal_and_keeps_file(self):
        result=agents.render_summary(self.job([self.task('video','media')],{'video':{'text':'raw render log','file':'video.mp4'}}))
        self.assertIn('video.mp4',result);self.assertIn('Yayınlanmadı',result);self.assertNotIn('raw render log',result)

    def test_failed_final_check_is_not_hidden(self):
        tasks=[self.task('report','writer'),self.task('check','verify',('report',),state='failed')]
        result=agents.render_summary(self.job(tasks,{'report':{'text':'Rapor metni','file':'report.md'},'check':{'text':'Dosya değişmiş.'}},'incomplete'))
        self.assertIn('henüz tamamlanmadı',result);self.assertIn('Dosya değişmiş',result)
        self.assertIn('görev devam testjob',result)

    def test_long_body_preview_discloses_limit(self):
        result=agents.render_summary(self.job([self.task('mail','account')],{'mail':{'snapshot':{
            'operation':'read_message','message':{'subject':'Test','from':'Test','body':'x'*3000,'truncated':False}}}}))
        self.assertNotIn('x'*2001,result);self.assertIn('devamı',result)

    def test_command_summary_is_opt_in_and_explicit_status_keeps_journal(self):
        job=self.job([self.task('mail','account')],{'mail':{'text':'Mail kimliği: INTERNAL_ID','sha256':'internal_hash',
            'snapshot':{'operation':'read_message','message':{'subject':'Test','from':'Test','body':'Merhaba','truncated':False}}}})
        with patch.object(agents,'execute',return_value=job):
            simple=agents.handle('alice','görev ilk mail oku',summary=True)
            technical=agents.handle('alice','görev ilk mail oku')
        self.assertIn('Merhaba',simple);self.assertNotIn('INTERNAL_ID',simple)
        self.assertIn('INTERNAL_ID',technical)
        with patch.object(agents,'recent',return_value=job):
            self.assertIn('internal_hash',agents.handle('alice','görev durumu',summary=True))
