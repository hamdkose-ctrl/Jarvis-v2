# Roadmap tamamlanma kanıtı v2

Bu not, `scripts/roadmap_completion_evidence_check.py` tarafından zorlanan SHA modelini açıklar.

Bir roadmap maddesi yeni `✅` olduğunda `Kanıt:` satırındaki `SHA` ve `Acceptance=watcher-pass@<SHA>` alanı, watcher'ın gerçekten geçtiği **kod commit'ini** gösterir. Bu SHA'nın PR'ın güncel head commit'inin atası olması zorunludur.

Acceptance alındıktan sonra yalnız `docs/` altında kapanış/kanıt belgesi değişebilir. Acceptance SHA ile PR head arasında `modules/`, test, script, workflow, web veya başka herhangi bir kod/yapılandırma değişikliği varsa tamamlanma kapısı FAIL olur ve yeni watcher acceptance gerekir.

`PR=#...` alanı da CI olayındaki gerçek PR numarasıyla aynı olmak zorundadır. Böylece uydurma PR numarası veya başka bir branch/commit acceptance'ı kapanış kanıtı olarak kullanılamaz.

Bu model, roadmap dosyasının kendi güncel head SHA'sını içine yazma çıkmazını önler: acceptance kod SHA'sına bağlanır, sonradan yalnız dokümantasyon kanıtı eklenebilir.
