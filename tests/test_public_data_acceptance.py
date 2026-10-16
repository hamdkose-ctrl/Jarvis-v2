import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from datetime import datetime,timezone,timedelta
from modules import public_data_acceptance as acceptance,llm,public_data,domain_tools,nxapi,public_sources,requests_state


class PublicDataAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        p=patch.object(nxapi,'FILES_DIR',self.root);p.start();self.addCleanup(p.stop)
        p=patch.object(domain_tools,'headlines',return_value={'items':[]});self.headlines=p.start();self.addCleanup(p.stop)

    def test_real_partial_file_verified_without_model_goal_or_account_calls(self):
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        body=('<article><h1>Yeni araştırma</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Üniversite yapay zekâ projesini yeni bilimsel sonuçlarla birlikte duyurdu. Araştırmanın ayrıntıları açıklandı.</p></article>').encode()
        with patch.object(public_data,'news_search',return_value={'items':[{'url':'https://example.edu.tr/news/ai'}]}),patch.object(domain_tools,'exchange',return_value={'data':{'date':day}}),patch.object(public_sources,'fetch',side_effect=lambda url:{'url':url,'body':body}),patch('modules.privacy.blocked',return_value=None),patch.object(llm,'ask',side_effect=AssertionError('No model')):
            checks=acceptance.run('alice')
        report=next(c for c in checks if c['check']=='public_news_report')
        self.assertEqual(report['state'],'passed');self.assertIn('Partial',report['detail'])
        files=list(self.root.rglob('*.md'));self.assertEqual(len(files),1)
        text=files[0].read_text(encoding='utf-8');self.assertIn(day,text);self.assertIn('example.edu.tr',text)

    def test_rate_error_does_not_block_news_and_empty_news_is_not_a_report(self):
        with patch.object(domain_tools,'exchange',side_effect=OSError('offline')),patch.object(public_data,'news_search',return_value={'items':[]}):
            checks=acceptance.run('alice')
        states={c['check']:c['state'] for c in checks}
        self.assertEqual(states['public_exchange'],'pending');self.assertEqual(states['public_news_search'],'passed')
        self.assertEqual(states['public_news_report'],'pending');self.assertFalse(list(self.root.rglob('*.md')))

    def test_failed_search_never_reads_or_writes_an_article(self):
        with patch.object(domain_tools,'exchange',return_value={'data':{'date':'2026-10-16'}}),patch.object(public_data,'news_search',side_effect=ValueError('429')),patch.object(acceptance.task_agents,'worker') as worker:
            checks=acceptance.run('alice')
        worker.assert_not_called();self.assertEqual(checks[-1]['state'],'pending')

    def test_search_timeout_falls_back_to_real_publisher_and_verifies_file(self):
        from urllib3.exceptions import ReadTimeoutError
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        article='https://tubitak.gov.tr/tr/haber/yapay-zeka'
        body=('<article><h1>Yapay zekâ projesi</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Yeni yapay zekâ araştırması bilimsel sonuçlarıyla birlikte kamuoyuna açıklandı. Projenin ayrıntıları paylaşıldı.</p></article>').encode()
        self.headlines.return_value={'items':[{'title':'Yapay zekâ projesi','url':article}]}
        with patch.object(domain_tools,'exchange',return_value={'data':{'date':day}}),patch.object(public_data,'news_search',side_effect=ReadTimeoutError(None,'https://api.gdeltproject.org/','timeout')) as search,patch.object(public_sources,'fetch',return_value={'url':article,'body':body}),patch('modules.privacy.blocked',return_value=None),patch.object(llm,'ask',side_effect=AssertionError('No model')):
            checks=acceptance.run('alice')
        states={r['check']:r['state'] for r in checks}
        self.assertEqual(states['public_news_search'],'pending');self.assertEqual(states['public_news_report'],'passed')
        search.assert_called_once();self.assertEqual(self.headlines.call_count,2)
        self.assertEqual(len(list(self.root.rglob('*.md'))),1)

    def test_publisher_permission_denial_is_not_bypassed(self):
        self.headlines.side_effect=PermissionError('privacy')
        with patch.object(domain_tools,'exchange',return_value={'data':{'date':'2026-10-16'}}),patch.object(public_data,'news_search',return_value={'items':[]}):
            with self.assertRaises(PermissionError):acceptance.run('alice')

    def test_cancellation_and_owner_mismatch_propagate(self):
        with self.assertRaises(PermissionError):acceptance.run('bob')
        with patch.object(domain_tools,'exchange',side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):acceptance.run('alice')
        with patch.object(domain_tools,'exchange',side_effect=PermissionError('owner changed')):
            with self.assertRaises(PermissionError):acceptance.run('alice')

    def test_flag_is_opt_in_and_owner_context_is_restored(self):
        from modules import acceptance_checks,service_health
        import updater
        with patch.object(updater,'verify_sync',return_value={'sync_state':'synced'}),patch.object(service_health,'report',return_value='safe'),patch.object(acceptance,'run',return_value=[{'check':'public_data_probe','state':'passed','detail':'safe'}]) as run:
            acceptance_checks.run(suite=False);run.assert_not_called()
            checks=acceptance_checks.run(suite=False,public_data=True)['checks']
            run.assert_called_once();self.assertIn('public_data_probe',[c['check'] for c in checks])
        self.assertEqual(llm._key_context.get(),'alice')


if __name__=='__main__':unittest.main()
