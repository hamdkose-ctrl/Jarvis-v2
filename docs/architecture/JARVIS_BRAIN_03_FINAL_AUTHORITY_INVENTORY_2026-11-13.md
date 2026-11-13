# JARVIS-v2 — BRAIN-03 semantic authority cutover

13 Kasım 2026 · Issue #545 · **yalnız PR #613**

## Kabul kararı: AÇIK — merge edilmez

Bu belge, ilk 32 kalemli *başlangıç envanteri* yerine PR #613'ün mevcut
üretim bağlantılarını kaydeder. Buradaki "kod bağlı" ifadesi **PASS** değildir.
Kapanış için SON DEĞİŞİKLİK SHA'sında Windows CI completed/success,
aynı SHA'da gerçek PC watcher Genel+Validation PASS ve canlı birincil model
Full holdout ölçümü ayrı ayrı gerekir. Hiçbiri tahminle doldurulmaz.

## Tek semantik karar, tek yürütme

- Normal bağımsız dil: `engine_loop/engine_live_brain → brain_entry.prepare
  (model_understanding=True) → model proposal → brain_core_map.core_plan →
  engine_intents.dispatch / tek mevcut domain worker`.
- Core, modelin önerdiği kapalı enum, şekil, referans, kullanıcıya ait alan dayanağı,
  sahip ve etki iznini yeniden doğrular. İptal, pending/State/Fast ve açık onaylar
  ayrı bounded protokollerdir.
- Model yok veya zarf geçersizse ham `_extra_commands`, `_planner_command`,
  `_user_controls`, `_study_intent` yorumlayıcılarına geri düşülmez:
  açık kullanıcı cevabı olmadan yürütme yapılmaz. Exact ve kayıtlı
  makine protokolleri (UI dosya yolu + işlem, kayıtlı tam makro, PC/workflow,
  Fast/State, yayın/güncelleme) genel doğal dil intent seçimi değildir.
- `modules/brain_precedence.py` yalnız sınırlı UI dosya eylemi ve tam makro
  tetikleyicisini taşıyor; genel cascade sırası ve `claim_tail` kaldırıldı.
  UI dosya eylemi artık tam-cümle grameridir; olumsuz, alıntı ve soru
  içerisindeki alt dizeler izin/etki yaratamaz.

## Domain → tek Core/effect sahibi

| Domain | Model/Core intent → tek effect sahibi | Fiziksel sınır |
|---|---|---|
| Not ekle/oku/düzelt/sil/tümünü temizle | `notes.add/read/write/manage` → mevcut Profile/not worker'ı | Eski planner not mutasyon seçicileri kaldırıldı; tek not kimliği owner/referans ve SHA-256 sürüm mühürüyle bound; toplu silme State onayı ister |
| Hatırlatıcı/takvim | `reminder.propose`, `reminders.manage`, `calendar.read` → `main_planner` | Eski planner niyet seçicisi kaldırıldı; pending tarih/çakışma sorusu belirsiz cevapla kaybolmaz |
| Hoca/çalışma | `hoca.lesson.start`, `study.read` ve State `hoca_control` → mevcut Hoca/study worker | Eski `_study_intent` çağıranı kaldırıldı; tam ses tercihi ve açık `hoca modu: araştır KONU` için güvenli public kaynak yürütmesi korundu |
| Cihaz/ses/ekran | `device.share`, `voice.rate/select`, `screen.text` → mevcut privacy, VoiceCoordinator ve OCR işçisi | İkinci capture/voice/note etkisi yok; kapatma/uyku sadece tam Fast protokolü |
| Workbench | `workbench.followup` → `workbench.followup_typed` → aynı `handle` | Kullanıcıya ait süreli digest, izinli kaynak tekrar denetimi; serbest raw followup emekli |
| Finans alarmı | `finance.alert.manage` → `finance_alert_commands.execute_typed` → mevcut `finance_alert_store` | Ham finans alarmı `matches/handle` grameri fiziksel kaldırıldı; dayanaklı asset/eşik/sıra; kullanıcı listesi atomik çözüm |
| Gmail/Outlook okuma | `mail.read` → `engine_tools.mail_read_typed` → aynı `google_api`/`outlook` worker'ı | Ham `_mail_handle` kaldırıldı; salt-okuma, taslak/gönderim yeni yetki kazanmaz |
| Diğer mevcut tipli domainler | Dosya, tarayıcı, mesaj/kişi, görev, KB, iştakip, media, handoff, notify, model-goal | Eski genel cascade'in effect seçimi yok; mevcut worker'lar korunur |

## Gerçek test/kanıt kapıları

- Core, owner, id, digest, yanlış hedef, negatif/soru/metin-içi komut ve onay testleri
  PR #613'te genişletildi. Özellikle tam motor event-loop testinin artık canlı model
  sağlayıcıya yanlışlıkla takılmaması için bağımlılık sınırı izole edildi.
- Repo testleri ve envanter guard'ları kaldırılmış sembolleri çağırmayacak
  şekilde güncellendi. **Test eklendi ≠ test PASS.**
- Kalan kabul: güncel exact-HEAD Windows CI sonuçları; aynı HEAD gerçek
  PC watcher; gerçek ücretsiz/birincil modelde pozitif, negatif, pending,
  dosya ve çoklu görev Full holdout. Canlı sağlayıcı kullanılamıyorsa
  **UNMEASURED** yazılır, sahte PASS kullanılmaz.
- BRAIN-04 action_batch/Scheduler, BRAIN-05 Goal/CAS, BRAIN-07 worker
  yürütme sahipliği ve diğer Brain PR'larına bu PR'de müdahale edilmez.

**Son karar:** CI/PC/Full holdout doğrulanana ve regresyonlar kapatılana
kadar #613 Draft, #545 açık, merge yok.
