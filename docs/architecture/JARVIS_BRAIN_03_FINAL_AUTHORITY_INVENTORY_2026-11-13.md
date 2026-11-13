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
| Şifreli geliştirme | `development.manage` → `developer.execute_typed` → aynı korumalı taslak/test/release işçisi | Request kontrol olarak yeniden yorumlanmaz; apply/undo exact özgün Core cümlesi ve mevcut UI şifresiyle sınırlı; ek yolları modelden gelmez |
| Diğer mevcut tipli domainler | Dosya, tarayıcı, mesaj/kişi, görev, KB, iştakip, media, handoff, notify, model-goal | Eski genel cascade'in effect seçimi yok; mevcut worker'lar korunur |

## Son parite ve model sözleşmesi bağlantıları

- Katalogdaki her Core yeteneği açık argüman şeması taşır; dosya/not slot talimatı ile decoder aynı sözleşmededir. City set/reset için önceki geçiş yasağı kaldırılmıştır; set kullanıcı sözünden dayanak ister, model kimlik/yol veremez.
- Takvim `meeting_prep`, mail `awaiting_*`/ilk mail ekleri, not count/one, konuşma tablosu, dosya çeviri/dönüşüm/mutasyon ve geçmiş cevabın tam metin çevirisi mevcut worker'larına bağlıdır. Prompt yalnız önizleme alır; çeviri Core'un owner/rol/turn ID bağlı tam kaynağını kullanır. Tarihli öneriler gözlenen yerel saatten üretilir. Saat `ActiveContext.current_time` metadata'sıdır; iş/dosya/referans adayı değildir ve artifact/pending bağlanırken korunur.
- Hatırlatma değişikliği Profile kilidi içinde exact snapshot onayıyla yapılır; sıradaki tekrar, base saati ve fired snooze ayrılır, değişen olayın eski ses kuyruğu geçersizleşir.
- Desktop açık soru cevabı exact native job/soru/aktif PC sahibine bağlanır. Goal açık soru cevabı model ilişkisinden aynı hedefin mevcut resolver/control çitine gider; canonical Scheduler yerine ikinci run açılmaz.
- Görev silme tam owner başlığından mevcut State onayına; tema değişimi mevcut UI ayar sahibine bağlıdır. Geliştirme request/control ve owner ek bağlama paritesi ayrı typed sözleşmeyle korunur; hiçbir model alanı özgün onay metnini değiştiremez.
- Eski testler raw fallback yerine açık model önerisiyle gerçek prepare/handoff/Core/domain hattını sürer. Bounded `boşver` hedef yokken `job.empty_cancel` no-op olarak ölçülür; eski baseline sonuçları yeniden yazılmaz.
- Saf eski `understand` fonksiyonu `model_understanding=False` karakterizasyon yüzeyinde kalır. Talimatsız fotoğrafın “ne yapayım?” meta bekleme turu da model çağırmaz; burada kullanıcı komutu yürütülmez. Serbest talimat içeren üretim text/live/photo ve iç adımlar birincil modele gider; kaynak/caller guard'ları bu sınırı denetler.

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
- BRAIN-04/05 mevcut batch ve Goal continuation adaptörleri kullanılır;
  BRAIN-07 worker/Scheduler yürütme sahipliği ve diğer açık PR'lar genişletilmez.

**Son karar:** CI/PC/Full holdout doğrulanana ve regresyonlar kapatılana
kadar #613 Draft, #545 açık, merge yok.
