"""Kullanıcıya verilmiş davranış sözleşmelerinin kalıcı kimlikleri.

Her ID kullanıcı açısından tek bir değişmez davranışı temsil eder. Ayrıntılı testler başka
dosyalarda kalır; release kapısı bu manifestodan isimleri toplar.
"""

CONTRACT_MANIFEST = {
    'NEWS-001': {
        'description': 'Güncel haber isteği sohbet yerine araştırma görevine gider.',
        'tests': ('tests.test_fresh_research_routing.FreshResearchRoutingTests',),
    },
    'NEWS-002': {
        'description': 'Model kotası bitse de doğrulanmış haber modelsiz teslim edilebilir.',
        'tests': ('tests.test_model_free_news_fallback.ModelFreeNewsFallbackTests',),
    },
    'NEWS-003': {
        'description': 'Recovery gerçek kaynakları dener, uydurma URL veya sahte tamamlanma üretmez.',
        'tests': (
            'tests.test_goal_executor.GoalTests.test_resume_question_delivers_saved_news_without_asking_planner_again',
            'tests.test_goal_executor.GoalTests.test_three_guessed_news_urls_are_rejected_without_fetch_or_unbounded_plans',
            'tests.test_goal_executor.GoalTests.test_vague_news_question_recovers_without_asking_user_or_another_model',
            'tests.test_goal_executor.GoalTests.test_vague_question_real_file_recovers_two_publishers_with_no_more_models',
            'tests.test_goal_executor.GoalTests.test_news_preview_never_cuts_a_url_or_marks_old_single_source_complete',
            'tests.test_news_recovery_catalog.NewsRecoveryCatalogTests.test_broad_recovery_scans_registered_catalog_after_two_publishers',
        ),
    },
    'MAIL-001': {
        'description': 'Gmail ek kabulü ilk mesaja takılmaz ve gerçek eki doğrular.',
        'tests': ('tests.test_gmail_acceptance_scan.GmailAcceptanceScanTests',),
    },
    'MAIL-002': {
        'description': 'Google DNS/ağ kesintisi kod hatası gibi sistemi çökertmez.',
        'tests': ('tests.test_google_network_unavailable.GoogleNetworkUnavailableTests',),
    },
    'PC-001': {
        'description': 'Uygulamayı açmak daha büyük PC hedefini tamamlanmış saydırmaz.',
        'tests': ('tests.test_outcome_learning_contracts.OutcomeLearningContracts',),
    },
    'UPDATE-001': {
        'description': 'Kabul raporu ve geçici dosyalar kaynak farkı sayılmaz.',
        'tests': (
            'tests.test_update_blockers.UpdateBlockerTests.test_acceptance_report_and_temp_files_are_not_source',
            'tests.test_update_blockers.UpdateBlockerTests.test_report_alone_now_counts_as_synced',
        ),
    },
    'EXEC-001': {
        'description': 'Yeni tamamlanan çıktılar merkezi outcome contract kimliği taşır.',
        'tests': ('tests.test_execution_policy_stability.ExecutionPolicyTests.test_local_results_carry_outcome_contract',),
    },
    'FAIL-001': {
        'description': 'Aynı ağ/kota/izin hatası bütün katmanlarda aynı sınıfa girer.',
        'tests': ('tests.test_execution_policy_stability.ExecutionPolicyTests.test_failure_policy_classifies_core_failures',),
    },
    'ROUTE-001': {
        'description': 'Eylem varsayılan Do modudur; formal spec yalnız açıkça istenir.',
        'tests': ('tests.test_execution_policy_stability.ExecutionPolicyTests.test_work_modes_are_do_first_without_forcing_spec',),
    },
    'MEM-001': {
        'description': 'Davranış kuralları yalnız ilgili bağlamda prompta yüklenir.',
        'tests': ('tests.test_execution_policy_stability.ExecutionPolicyTests.test_rules_are_scoped_by_query',),
    },
    'STARTUP-001': {
        'description': 'Açılıştaki GitHub kontrolü pencereyi bloklamaz ve pencere zamanı kaydedilir.',
        'tests': ('tests.test_execution_policy_stability.ExecutionPolicyTests.test_startup_update_check_is_non_blocking_and_measured',),
    },
}


def test_names() -> tuple[str, ...]:
    names = []
    for contract in CONTRACT_MANIFEST.values():
        names.extend(contract['tests'])
    return tuple(dict.fromkeys(names))
