"""Existing news receipts can serve read-only research and chat delivery goals."""
import copy
import unittest
from unittest.mock import patch
import test_news_chat_writer as fixture
from modules import goal_executor as goals, news_recovery


class NewsMultigoalDeliveryTests(unittest.TestCase):
    def prepared(self,extra='Başlık, kısa özet ve bağlantıları sohbette sun'):
        scenario=fixture.NewsChatWriterTests();self.addCleanup(scenario.doCleanups)
        case,job,reply,fetch=scenario.run_case()
        evidence=list(job['goals'][0]['evidence'])
        job['goals']=[{'text':'Haber kaynaklarını belirle','state':'done','evidence':evidence},
                      {'text':'Haberleri araştır ve tarihlerini doğrula','state':'pending','evidence':[]},
                      {'text':extra,'state':'pending','evidence':[]}]
        job['state']='paused';goals._save(job)
        return case,job

    def test_saved_two_publishers_finish_three_news_goals_without_model_or_network(self):
        case,job=self.prepared();before=copy.deepcopy(job)
        case.ask.reset_mock();case.ask.side_effect=AssertionError('No new model for saved news delivery')
        with patch('modules.public_sources.fetch',side_effect=AssertionError('No repeat read')):
            reply=goals.run(case.runtime,'devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['state'],'done',reply)
        self.assertTrue(all(g['state']=='done' for g in after['goals']))
        self.assertEqual(after['id'],before['id'])
        self.assertEqual(after['steps'],before['steps'])
        self.assertEqual(after['outputs'],before['outputs'])
        self.assertEqual(after['goals'][0],before['goals'][0])
        case.ask.assert_not_called()

    def test_saved_receipts_finish_plain_planner_delivery_wording(self):
        case,job=self.prepared('Haberleri önem sırasıyla kullanıcıya aktar')
        case.ask.reset_mock();case.ask.side_effect=AssertionError('No new model for saved news delivery')
        with patch('modules.public_sources.fetch',side_effect=AssertionError('No repeat read')):
            reply=goals.run(case.runtime,'devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['state'],'done',reply)
        self.assertTrue(all(goal['state']=='done' for goal in after['goals']))
        case.ask.assert_not_called()

    def test_news_evidence_does_not_complete_other_deliverables(self):
        for text in ('Haber özetini Gmail ile gönder','Haberlerden video üret',
                     'Haber raporunu dosyaya kaydet','Haberler hakkında not ekle',
                     'Habere göre hisse satın al','Haberlerle ilgili kod yaz',
                     'Haberler için görsel çiz','Haber takvim kaydı oluştur',
                     'Spor haberlerini araştır','Haberleri İngilizceye çevir',
                     'Haberleri analiz edip değerlendir','Haberleri sürekli takip et',
                     'Haberleri sosyal medyada yayınla'):
            with self.subTest(text=text):
                case,job=self.prepared(text)
                with patch('modules.public_sources.fetch',side_effect=AssertionError('No extra reads')):
                    news_recovery.deliver(case.runtime,job,existing_only=True)
                    news_recovery.deliver(case.runtime,job,existing_only=True)
                self.assertEqual(job['goals'][2]['state'],'pending')
                self.assertEqual(job['goals'][2]['evidence'],[])

    def test_changed_receipt_cannot_complete_pending_goals(self):
        case,job=self.prepared()
        job['outputs']['s1']['source_quotes']=['Bu alıntı kaynaktan alınmadı.']
        with self.assertRaises((ValueError,PermissionError)):
            news_recovery.deliver(case.runtime,job,existing_only=True)
        self.assertEqual([g['state'] for g in job['goals']],['done','pending','pending'])

    def test_one_publisher_cannot_complete_followup_goals(self):
        case,job=self.prepared()
        job['steps']=job['steps'][:1];job['outputs']={'s1':job['outputs']['s1']}
        job['goals'][0]['evidence']=['s1']
        news_recovery.deliver(case.runtime,job,existing_only=True)
        self.assertEqual([g['state'] for g in job['goals']],['done','pending','pending'])
