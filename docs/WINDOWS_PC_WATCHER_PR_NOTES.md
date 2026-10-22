# Temiz watcher PR kapsamı

Bu dal gerçek Windows PC test/watcher altyapısını ve haber final kabul kapısını içerir: `scripts/pc_test_watcher.py`, kurulum betikleri, `modules/acceptance_checks.py --news` kapısı ve bunların testleri. Otomatik Terra düzeltme döngüsü (`pc_test_loop.py`, `codex_followup.py`) 22 Ekim 2026'da bu daldan kaldırıldı; watcher yalnız ölçer ve raporlar, PR yorumu yalnız kapı durumu taşır.

Haber HTML kurtarma yamaları ve #225'teki haber modülü değişiklikleri bu dala taşınmamıştır. Bunun dışında dalda iki küçük kapsam daha vardır: dosyasız genel haber hedefinin sınırlı yayıncı kurtarmasıyla kanıt yoksa duraklaması (`modules/goal_executor.py`, `modules/publisher_news.py`; haber kabul kapısının ölçtüğü davranış) ve `modules/docs.py`/`service_store.py`/`study.py` hafif import.

Final gerçek-PC kabulü yerel watcher tarafından yapılmalıdır. Haber kabulü normal desktop turundan ayrıdır ve yalnız final kapısında çalışır. Aynı `goal_executor.py` bölgesinde #227'de farklı duraklama/planlayıcı kararı vardır; birleşme sırası netleştikten sonra ikinci dal uyarlanır.
