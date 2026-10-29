"""Acceptance evidence must survive watcher worktree cleanup and another PR run."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import acceptance_checks

spec=importlib.util.spec_from_file_location('watcher_persistence',Path(__file__).resolve().parents[1]/'scripts/pc_test_watcher.py')
watcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(watcher)

class NewsAcceptancePersistence(unittest.TestCase):
    def test_news_cli_archives_only_news_checks_before_temp_worktree_disappears(self):
        report={'checks':[{'check':'news_chat_resume','state':'failed','detail':'ikinci yayıncı yok'},
                          {'check':'gmail_attachment','state':'passed','detail':'private account detail'}]}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict('os.environ',{'LOCALAPPDATA':tmp}):
                path=acceptance_checks.archive_news_result(report)
            data=path.read_text(encoding='utf-8')
            self.assertIn('ikinci yayıncı yok',data)
            self.assertNotIn('private account detail',data)
            self.assertTrue((path.parent/'news_acceptance_last.json').is_file())
    def test_new_pr_report_does_not_overwrite_another_commit_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for sha in ['a'*40,'b'*40]:
                watcher.archive_report(root/'last.json',{'sha':sha,'status':'failed'})
            self.assertTrue((root/'reports'/('a'*40+'.json')).is_file())
            self.assertTrue((root/'reports'/('b'*40+'.json')).is_file())
    def test_comment_keeps_second_scenario_diagnostic_after_first_300_chars(self):
        detail='genel sohbet: passed; '+('x'*310)+' | Türkiye AI sohbet: failed; ikinci yayıncı eksik'
        body=watcher.pr_comment_body({'sha':'a'*40,'status':'failed','news_acceptance':{
            'exit_code':1,'checks':[{'check':'news_chat_resume','state':'failed','detail':detail}]}})
        self.assertIn('ikinci yayıncı eksik',body)

    def test_archive_failure_preserves_worktree_and_does_not_mark_seen(self):
        item={'ref':'refs/remotes/origin/gpt/news','sha':'a'*40,'time':2}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(watcher,'load_state',return_value={'seen':{}}), \
                 patch.object(watcher,'remote_heads',return_value=[item]), \
                 patch.object(watcher,'open_pr_refs',return_value={item['ref']}), \
                 patch.object(watcher,'changed_paths',return_value=[]), \
                 patch.object(watcher,'add_worktree'), \
                 patch.object(watcher,'remove_worktree') as remove, \
                 patch.object(watcher,'run_suite',return_value={'status':'failed'}), \
                 patch.object(watcher,'archive_report',side_effect=OSError('disk full')), \
                 patch.object(watcher,'publish_pr_comment') as publish, \
                 patch.object(watcher,'save_json') as save:
                with self.assertRaises(OSError):
                    watcher.once(Path(tmp),Path(tmp)/'state.json',Path(tmp)/'last.json','refs/remotes/origin',desktop=False,news=True)
            remove.assert_not_called();publish.assert_not_called();save.assert_not_called()

    def test_external_failure_not_hidden_by_passed_chat(self):
        body=watcher.pr_comment_body({'sha':'a'*40,'status':'failed','news_acceptance':{
            'exit_code':1,'checks':[{'check':'news_chat_resume','state':'passed','detail':'chat good'},
                                   {'check':'news_external_discovery','state':'failed','detail':'external blocked'}]}})
        self.assertIn('external blocked',body)
        self.assertNotIn('chat good',body)
