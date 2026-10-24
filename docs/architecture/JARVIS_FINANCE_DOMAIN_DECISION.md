# Jarvis Finance Domain kararı

**Durum:** Karar kaydı
**Tarih:** 24 Ekim 2026

## Karar

Finance, Communication'ın alt özelliği değildir; ayrı bir domain'dir. Communication dış alıcıya mesaj/yayın teslimini, Finance ise finansal veri, analiz ve gelecekteki finansal etkiyi sahiplenir. İki domain ortak Core, Decision Authority, Permission Gate, Effect Policy, WorkerResult ve evidence sözleşmesini kullanır; ikinci bir yürütme ya da izin motoru kurulmaz.

## Bugünkü izinli kapsam

Finance'in bugünkü kapsamı yalnız salt-okuma analizdir:

- kur, piyasa, kripto, altın ve BIST verisini okumak,
- kaynak, veri zamanı/gecikmesi ve belirsizliği açıkça göstermek,
- hesaplama, karşılaştırma ve kullanıcıya ait olmayan genel analiz üretmek,
- gelecekteki alarm/izleme isteğini yalnız ayrı capability ve acceptance ile ele almak.

Salt-okuma kaynak içeriği kanıt olabilir; permission, authority, hedef veya para hareketi yetkisi vermez. Model/worker finansal işlem başlatamaz ve öneri, alım-satım talimatı ya da kesin getiri iddiası yürütme yetkisi değildir.

## Açıkça kapsam dışı

Aşağıdakiler için mevcut Finance yolu açılmaz:

- banka, aracı kurum, borsa veya cüzdan hesabı bağlamak,
- token, parola ya da finansal kimlik bilgisi saklamak/kullanmak,
- emir vermek, alım-satım yapmak, para transferi başlatmak,
- dış portföy veya finansal kaydı oluşturmak, değiştirmek ya da silmek,
- kullanıcı yerine yatırım/ödeme kararı vermek.

`money_credential` Permission Gate'te `deny` kalır. Bu karar onu `external_write` veya bir grant ile sessizce açmaz. İleride bir finansal dış kayıt veya hareket düşünülürse yeni capability manifest kaydı, kesin owner ve hedef, JIT izin, idempotency, receipt/reconciliation ve gerçek acceptance ayrı tasarlanır; bu belge tek başına izin vermez.

## Domain sınırı

| Konu | Sahip | Varsayılan effect/izin |
|---|---|---|
| Kur/piyasa verisi, hesaplama ve kaynaklı analiz | Finance | `read_only` / `read` |
| Bir kişiye finans bilgisi göndermek | Communication | `message_out`; kesin alıcı ve JIT onay |
| Finans verisini genel yayın olarak paylaşmak | Communication | `publish`; ayrı yayın onayı |
| Hesap/portföy verisini dış sağlayıcıdan okumak | Gelecek Finance capability | Şimdilik kapalı; provider ve owner tasarımı gerekir |
| Para, emir veya finansal kayıt etkisi | Gelecek Finance capability | Şimdilik `money_credential` nedeniyle kapalı |

Bir kullanıcı "Ahmet'e dolar kurunu gönder" dediğinde Finance yalnız doğrulanabilir veriyi sağlayabilir; gönderim Communication capability'sinin ayrı hedef/onay/receipt hattından geçer. Finance verisi alıcıyı, içeriği veya gönderim iznini belirleyemez.

## Gelecek işin giriş ölçütü

Finance'i salt-okumanın ötesine taşıyan iş, gerçek bir kullanıcı ihtiyacı ve ayrı acceptance ile açılır. Önce domain invariant, capability id/version, permission/effect sınıfı, kesin hedef, failure/reconcile davranışı ve canlı kabul kanıtı yazılır. Bu ölçütler olmadan Finance'te yeni dış etki eklenmez.
