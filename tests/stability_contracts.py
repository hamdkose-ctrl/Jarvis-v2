"""Jarvis'te daha önce kabul edilmiş kritik davranışların değişmez regresyon kapısı.

Bu dosya davranışları yeniden test etmez; mevcut ayrıntılı regresyon testlerini isimleriyle
zorunlu bir kabul grubu olarak tekrar çalıştırır. Böylece haber/recovery, Gmail taraması,
PC sonuç sözleşmesi, öğrenme ve güncelleme kaynak koruması birlikte korunur.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACTS = (
    # Haber / recovery / devam / model kotası bağımsızlığı
    'tests.test_goal_executor.GoalTests.test_resume_question_delivers_saved_news_without_asking_planner_again',
    'tests.test_goal_executor.GoalTests.test_three_guessed_news_urls_are_rejected_without_fetch_or_unbounded_plans',
    'tests.test_goal_executor.GoalTests.test_vague_news_question_recovers_without_asking_user_or_another_model',
    'tests.test_goal_executor.GoalTests.test_vague_question_real_file_recovers_two_publishers_with_no_more_models',
    'tests.test_goal_executor.GoalTests.test_news_preview_never_cuts_a_url_or_marks_old_single_source_complete',
    'tests.test_news_recovery_catalog.NewsRecoveryCatalogTests.test_broad_recovery_scans_registered_catalog_after_two_publishers',
    # Gmail: ilk mail sınırına geri dönmesin; bozuk ek başarı sayılmasın; DNS kesintisi kod hatası olmasın.
    'tests.test_gmail_acceptance_scan.GmailAcceptanceScanTests',
    'tests.test_google_network_unavailable.GoogleNetworkUnavailableTests',
    # PC: uygulamayı açmak işi bitirmek sayılmasın; öğrenme ve araştırma teslim sözleşmesi korunsun.
    'tests.test_outcome_learning_contracts.OutcomeLearningContracts',
    # Kabul raporu/geçici çıktılar kaynak farkı üretip güncellemeyi tekrar kilitlemesin.
    'tests.test_update_blockers.UpdateBlockerTests.test_acceptance_report_and_temp_files_are_not_source',
    'tests.test_update_blockers.UpdateBlockerTests.test_report_alone_now_counts_as_synced',
)


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(CONTRACTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
