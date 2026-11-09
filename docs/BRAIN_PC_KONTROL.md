# Windows'ta Brain kontrolü

Jarvis'in model hesabının bağlı olduğu Windows kullanıcısında çalıştırılır.
Anahtar veya profil kopyalanmaz. Kullanıcı başlatmadan model çağrısı yapılmaz.

Kurulum dosyası `scripts/Run-BrainCheck.ps1`:

```powershell
powershell -NoProfile -File scripts/Run-BrainCheck.ps1 -Install -RepoRoot (Get-Location).Path -Ref refs/pull/533/head
```

Bu komut scriptin bulunduğu kaynak kopyadan çalıştırılır; `-RepoRoot` gerçek
Jarvis Git klasörünü göstermelidir. Kurucu scripti kalıcı kullanıcı klasörüne
kopyalar ve masaüstüne iki kısayol ekler:

- **Jarvis Brain Quick:** Bir gerçek model isteğiyle bağlantı ve geçerli
  proposal kontrolü. Başarılı olması anlam doğruluğu veya Brain kabulü değildir.
- **Jarvis Brain Full:** Çıktı/teşhis diliminin 20 semantik örneği. İlk yanıt
  alınamazsa veya geçersizse kalan çağrılar yapılmaz. Quick sonrasında istenince
  başlatılır; Quick otomatik Full çalıştırmaz.

Her çalıştırma seçilen ref'in güncel commit'ini alıp geçici kaynak kopyasında
çalışır. Kurulu Jarvis checkout'u değiştirilmez. Kısayol belirli bir PR'ı
izliyorsa PR numarası kendiliğinden değiştirilmez. Birleşmiş sürümü kullanmak
için kurulum `-Ref main` ile yeniden yapılır.

JSON raporları masaüstündeki `Jarvis-Brain-Acceptance` klasöründedir. Her koşu
SHA ve zaman damgasıyla arşivlenir; `brain-connection-latest.json` ve
`brain-holdout-latest.json` son sonuçların ayrı kopyalarıdır.

`scope=connection` raporunda semantik başarı yüzdesi bulunmaz ve
`semantic_acceptance=false` kalır. Full raporundaki kabul yalnız bu 20 örneğin
kapsamıdır; bütün Brain'in veya çoklu iş yeteneğinin kabulü değildir.

Kurulum yalnız script ve kısayol oluşturur; Groq plan beyanını yenilemez,
modeli değiştirmez ve test/CI/watch çağrısı başlatmaz. Kaldırmak için iki
kısayolu ve `%LOCALAPPDATA%\Jarvis\brain-check` klasörünü silmek yeterlidir.

## Windows CI ile bu menünün ayrımı

Yeşil `testler-windows` işi kod doğrulaması kanıtıdır; canlı Brain kabulü
değildir. CI artık canlı semantik ölçümü **hiç denemez**: otomatik `--run`
çağrısı, exit kodu eşlemesi ve rapor artifact adımı zorunlu kod
doğrulamasından çıkarıldı. Bir CI adımının `unmeasured` (exit 2) sonucunu
yeşile çevirmek ayrım üretmiyordu, aynı kanıtı iki kez sayıyordu. Kalan beyin
adımı model çağırmaz; yalnız bu ayrımı ve gereken kapanış kanıtını CI özetine
yazar. `continue-on-error` yoktur.

Canlı ölçüm bu menünün işidir: scriptin kendi sözleşmesi (0 passed, 1 ölçülmüş
başarısızlık, 2 ölçülemedi), 20 örneklik korpus, %95 doğruluk ve sıfır
yanlış-action şartı olduğu gibi durur; koşul yalnız bu PC'de ve kullanıcı
başlattığında olur.

Kabulün kapanış kanıtı bu menüden üretilir: aynı commit'i hedefleyen
`Jarvis Brain Full` kısayolu ve masaüstü `Jarvis-Brain-Acceptance` klasöründeki
`brain-holdout-<SHA>-<tarih>.json` raporunun `state=passed` sonucu (20 örneğin
tümü yanıtlı, doğruluk en az %95, sıfır yanlış işlem önerisi, sıfır efekt
girişimi). CI adım özetinde bu ayrım ve gereken rapor açıkça yazılır.
