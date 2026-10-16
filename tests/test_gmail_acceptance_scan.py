import unittest
from unittest.mock import patch
from modules import acceptance_checks,account_tools,task_results


class GmailAcceptanceScanTests(unittest.TestCase):
    def listing(self,count):return {'state':'done','snapshot':{'items':[{'id':'mail-'+str(n)} for n in range(count)]}}
    def attachments(self,*rows):return {'state':'done','snapshot':{'items':list(rows)}}
    def read(self,mid='mail-0',index=1):
        return {'state':'done','snapshot':{'owner':'alice','service':'gmail','operation':'read_attachment',
            'message_id':mid,'attachment':{'index':index,'body':'PRIVATE_CONTENT'}}}

    def test_second_mail_is_read_with_its_own_id_and_attachment_index(self):
        read=self.read('mail-1',3)
        with patch.object(account_tools,'run',side_effect=[self.listing(2),self.attachments(),
                self.attachments({'supported':True,'index':3}),read]) as run,patch.object(
                task_results,'seal',return_value={'sealed':True}) as seal,patch.object(task_results,'verify') as verify:
            state,detail=acceptance_checks._gmail_attachment('alice')
        self.assertEqual(state,'passed');self.assertIn('sayısı: 2',detail)
        self.assertNotIn('PRIVATE',detail);self.assertNotIn('mail-',detail)
        self.assertEqual(run.call_args.args,('alice',{'service':'gmail','operation':'read_attachment','message_id':'mail-1','attachment_index':3}))
        self.assertEqual(run.call_args_list[0].args[1]['limit'],10)
        seal.assert_called_once_with('account',read);verify.assert_called_once_with({'sealed':True},owner='alice')

    def test_scan_is_bounded_even_if_provider_returns_more_than_requested(self):
        with patch.object(account_tools,'run',side_effect=[self.listing(15)]+[self.attachments()]*10) as run:
            state,detail=acceptance_checks._gmail_attachment('alice')
        self.assertEqual(state,'pending');self.assertIn('İlk 10',detail)
        self.assertEqual(run.call_count,11)
        self.assertTrue(all(call.args[1]['operation']!='read_attachment' for call in run.call_args_list))

    def test_supported_but_broken_attachment_is_not_skipped(self):
        with patch.object(account_tools,'run',side_effect=[self.listing(2),self.attachments({'supported':True,'index':1}),
                ValueError('Unreadable')]) as run:
            with self.assertRaises(ValueError):acceptance_checks._gmail_attachment('alice')
        self.assertEqual(run.call_count,3)

    def test_failed_verification_is_not_passed(self):
        with patch.object(account_tools,'run',side_effect=[self.listing(1),self.attachments({'supported':True,'index':1}),
                self.read()]),patch.object(task_results,'seal',return_value={}),patch.object(
                task_results,'verify',side_effect=ValueError('tampered')):
            with self.assertRaises(ValueError):acceptance_checks._gmail_attachment('alice')

    def test_incomplete_list_is_not_silently_skipped(self):
        with patch.object(account_tools,'run',side_effect=[self.listing(2),{'state':'blocked'}]) as run:
            state,detail=acceptance_checks._gmail_attachment('alice')
        self.assertEqual(state,'pending');self.assertIn('kontrol tamamlanmadı',detail);self.assertEqual(run.call_count,2)

    def test_no_unread_mail_or_missing_connection_are_pending(self):
        for response in [self.listing(0),{'state':'blocked'}]:
            with patch.object(account_tools,'run',return_value=response) as run:
                state,_=acceptance_checks._gmail_attachment('alice')
            self.assertEqual(state,'pending');run.assert_called_once()

    def test_disappeared_attachment_empty_list_is_not_a_successful_read(self):
        empty={'state':'done','snapshot':{'operation':'list_attachments','items':[]}}
        with patch.object(account_tools,'run',side_effect=[self.listing(1),self.attachments({'supported':True,'index':1}),empty]),patch.object(task_results,'verify') as verify:
            state,detail=acceptance_checks._gmail_attachment('alice')
        self.assertEqual(state,'pending');self.assertIn('artık yok',detail);verify.assert_not_called()

    def test_mismatched_read_receipt_is_not_passed(self):
        for field,value in [('owner','bob'),('message_id','another-mail'),('attachment',{'index':2,'body':'text'}),
                            ('attachment',{'index':1,'body':''})]:
            result=self.read();result['snapshot'][field]=value
            with patch.object(account_tools,'run',side_effect=[self.listing(1),self.attachments({'supported':True,'index':1}),result]):
                with self.assertRaises(ValueError):acceptance_checks._gmail_attachment('alice')
