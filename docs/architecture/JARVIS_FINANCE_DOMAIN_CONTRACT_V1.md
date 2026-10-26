# Jarvis Finance Domain sözleşmesi v1

**Durum:** Sözleşme (Faz 3-A)
**Tarih:** 26 Ekim 2026
**Dayanak:** [Finance Domain kararı](JARVIS_FINANCE_DOMAIN_DECISION.md)
**Kod karşılığı:** `modules/finance_domain.py`, test: `tests/test_finance_domain.py`

Bu belge karar kaydını uygulanabilir bir sözleşmeye çevirir: Finance'in dört dalı, her dalın izin/etki sınıfı ve kuralları, Communication ile sınır ve bugün Finance dışında duran kodun göç planı. Yeni yetenek açmaz; salt okuma kapsamı aynen kalır, para hareketi yoktur. `money_credential` Permission Gate'te `deny` kalır.

## 1. Dallar

| Dal | Kapsam | İzin / etki | Sahip modüller | Giriş noktaları |
|---|---|---|---|---|
| `data` | Kur, piyasa, kripto, gram altın, BIST | `read` / `read_only` | `finance.py`, `tool_finance.py` | `finance.answer`, `parse`, `rates`, `is_conversion` |
| `alarm` | Fiyat alarmı ve takip listesi | `local_reversible` / `local_reversible` | `finance_alerts.py`, `finance_alert_store.py`, `finance_alert_schedule.py`, `finance_alert_runner.py`, `finance_alert_commands.py`, `finance_watchlist.py` | `finance_alerts.evaluate`, `finance_alert_runner.run_once`, `finance_alert_commands.handle`, `finance_alert_schedule.notification_text` |
| `analysis` | Hesaplama, karşılaştırma, CSV gelir/gider özeti | `read` / `read_only` | (henüz yok, bkz. 3-F) | `domain_tools.csv_analysis` (`kind='finance'`) |
| `source_verification` | Kaynak, tarih ve evidence doğrulaması | `read` / `read_only` | (henüz yok, bkz. 3-E) | `domain_tools.exchange`, `finance._safe_xml` |

Alarm dalı `local_reversible`'dır çünkü yalnız kullanıcının kendi `DATA_DIR` kaydını (kural, durum, takip listesi) yazar; silme ve değiştirme kullanıcı komutuyla geri alınabilir. Dış kayıt değişmez.

### Dal kuralları

**Veri**
- Yalnız kamuya açık, anahtarsız ve ücretsiz kaynak okunur (TCMB, Frankfurter, CoinGecko, BtcTurk, Yahoo). Okuma `public_sources.fetch` üzerinden yapılır.
- Kaynak yanıtından yalnız sayı ve tarih alınır; kaynak metni modele gitmez.
- Her cevapta kaynak adı ve veri zamanı/gecikmesi yazılır.

**Alarm**
- Eşik değerlendirmesi modelsizdir; emir, alım-satım veya transfer başlatmaz.
- Finance yalnız bildirim metnini üretir (`notification_text`). Kime ve hangi kanaldan iletileceği Communication sınırındadır.

**Analiz**
- Girdi yalnız kullanıcının izinli alanındaki dosya veya veri dalının çıktısıdır.
- Sonuç öneri, kişisel yatırım/ödeme kararı ya da kesin getiri iddiası değildir.
- Kaynak dosyası analiz boyunca değişmez (sha256 ile doğrulanır).

**Kaynak doğrulama**
- Yanıt istenen varlık/para birimi ve tarihle eşleşmezse sonuç reddedilir.
- Kanıt en az kaynak adresi, veri tarihi, okuma zamanı ve gövde özeti (sha256) taşır.
- Kaynak içeriği izin, hedef ya da yürütme yetkisi vermez.

## 2. Domain sınırı

`finance_domain.route(kind)` aşağıdaki tabloyu uygular; bilinmeyen tür `ValueError`, kapalı tür `PermissionError` ile reddedilir.

| Tür | Sahip | İzin sınıfı | Durum |
|---|---|---|---|
| `market_data` | Finance | `read` | açık |
| `analysis` | Finance | `read` | açık |
| `alarm_rule` | Finance | `local_reversible` | açık |
| `alarm_delivery` | Communication | `local_reversible` (kendi ekranı ve ntfy konusu) | açık |
| `send_to_person` | Communication | `message_out` | açık, kesin alıcı ve JIT onay |
| `publish` | Communication | `publish` | açık, ayrı yayın onayı |
| `account_read` | Finance (gelecek) | `money_credential` | **kapalı** |
| `money_effect` | Finance (gelecek) | `money_credential` | **kapalı** |

## 3. Statik denetim (`finance_domain.check`)

Kod çalıştırmadan, ağa çıkmadan AST üzerinden:

- **FIN-001:** Finance modülü Communication (`notify`, `outbox`, `message_inbox`, `publish_*`, `tool_mail`, `mail_*`, `social_reads`, `git_publish`) veya izin yazan modülleri (`permission_grants`, `permission_policy`) içe aktaramaz.
- **FIN-002:** `tool_finance.CONTRACT` eylemleri yalnız `read` veya `local_reversible` sınıfında olabilir.
- **FIN-003:** Göç planındaki her "dosya:sembol" hâlâ tanımlı olmalıdır. Bir parça taşındığında aynı PR plan satırını günceller; bayat plan test hatası verir.
- **FIN-004:** Her dalın giriş noktası tanımlı olmalıdır.

`validate()` ayrıca sözleşmenin kendi tutarlılığını denetler: dal izin/etki sınıfı izinli kümede, bir modül tek dala bağlı, para ve hesap yolu kapalı.

## 4. Bugünkü dağınıklık

Finance kodu tek yerde değil. Taşınması gereken parçalar:

- **`watcher.py` (klasör izleme):** Alarm turu (`finance_tick`), kurtarma kaydı (`_finance_recover`), durum dosyası (`_finance_save`, `_finance_path`) ve fiyat okuma (`_finance_price`) klasör izleme modülünde duruyor. `_finance_price`, `finance._yahoo` ve `finance._market` özel fonksiyonlarını çağırıyor.
- **Bildirim teslimi:** `watcher.loop` içindeki `emit` alarm metnini ekrana ve ntfy telefon bildirimine "Jarvis klasör izleme" başlığıyla gönderiyor. Teslim Communication'da kalmalı ama finans alarmı olarak ayrışmalı.
- **`domain_tools.py`:** Tarihli kur (`exchange`) ve CSV gelir/gider özeti (`csv_analysis` içindeki `kind='finance'` kolu) mağaza/haber/sosyal araçlarıyla aynı dosyada.

Komut yönlendirme noktaları (`engine_commands.handle` → `finance.answer`, `engine_tools._extra_commands` → `finance_alert_commands`, `chat_translation` → `finance.is_conversion`, `goal_executor` → `finance.parse`) taşınmaz; motor yalnız Finance girişini çağırır.

## 5. Kod göçü planı

Her adım ayrı, küçük ve davranışı değiştirmeyen bir PR'dır. Sıra kesindir; bir adım önceki merge edilmeden başlamaz. Her PR `finance_domain.MIGRATION` satırını günceller (FIN-003 bunu zorlar).

| Adım | Dal | Bugünkü konum | Hedef | Not |
|---|---|---|---|---|
| 3-B | data | `watcher._finance_price` | `finance.quote(kind, symbol)` | Tek açık fiyat girişi; watcher özel fonksiyon çağırmaz. |
| 3-C | alarm | `watcher.finance_tick`, `_finance_recover`, `_finance_save`, `_finance_path` | `finance_alert_tick.py` | Alarm turu Finance'e taşınır; `watcher.finance_tick` geçici olarak yeni modüle yönlenir. Durum dosyası yolu (`finance_alert_ticks`) değişmez. |
| 3-D | alarm | `watcher.loop` (emit) | `watcher.loop` | Teslim Communication'da kalır; ntfy başlığı finans alarmı olarak ayrılır. |
| 3-E | source_verification | `domain_tools.exchange` | `finance.dated_rate` | `domain_tools.exchange` ince sarmalayıcı kalır; kanıt alanları aynı. |
| 3-F | analysis | `domain_tools.csv_analysis` (finance kolu) | `finance_analysis.csv_summary` | Mağaza CSV'si `domain_tools`'ta kalır. |

Her adımın kabul ölçütü: mevcut `test_finance*`, `test_news_finance_contracts` ve `test_finance_domain` geçer; kullanıcıya giden metin değişmez; yeni ağ kaynağı, model çağrısı ya da izin sınıfı eklenmez.

## 6. Kapsam dışı

Bu sözleşme şunları açmaz ve açılmalarına izin vermez: hesap bağlama, token/parola saklama, emir/alım-satım/transfer, dış portföy kaydı yazma, kullanıcı yerine yatırım/ödeme kararı. Bunlar için karar kaydındaki "gelecek işin giriş ölçütü" geçerlidir: yeni capability manifest kaydı, kesin owner/hedef, JIT izin, idempotency, receipt/reconciliation ve canlı kabul.

Faz 4E (Finans salt okuma worker'ı) bu sözleşmeyi okur; worker yalnız `data`, `analysis` ve `source_verification` dallarının giriş noktalarını kullanır.
