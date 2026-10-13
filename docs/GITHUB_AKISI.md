# GitHub Ana Akış

**Tek kod tabanı:** Ev PC ve İş PC aynı `main` dalını izler; iki bilgisayarın yetkisi aynıdır.

Yerel geliştirme: rollback → açık kullanıcı onayı → hedefli değişiklik → test → yerelde koruma.

Yayın: kullanıcı `git yükle / GitHub'a gönder` der → testler yeniden çalışır → uzak `main` tabanı kontrol edilir → çakışma yoksa tek commit/push.

Diğer bilgisayar: açılış → salt-okunur güncelleme kontrolü → “yeni sürüm var” bildirimi → kullanıcı açıkça kur derse uygulama.

Koruma kuralları:
- Self-Coder otomatik push yapmaz.
- Açılışta otomatik kurulum/pull yok.
- Uzak `main` bu PC'nin tabanından ilerideyse `git yükle` durur; önce güncelleme gerekir.
- Yerel, GitHub'a gönderilmemiş değişiklik varken güncelleme kurulmaz.
- Force-push yok.
- API anahtarları ve `~/.jarvis` kullanıcı verileri GitHub'a gönderilmez.

## v5.12 doğrulama ve bağımlılık kilidi
- Ev/İş ayrımı yoktur; değişiklik hangi PC'de yapıldıysa o PC `git yükle` diyebilir.
- Yayın öncesi uzak `main` gerçek kaynak ağacıyla karşılaştırılır. Kayıtlı SHA etiketi tek başına “senkron” sayılmaz.
- Uzak dal ilerlemiş ve yerel dosyalar da farklıysa yayın durur; force-push yapılmaz.
- Çalışan `.venv` ortamındaki paketler yayın öncesi `requirements.lock.txt` dosyasına sabitlenir.
- Yerelde gerçekten silinen yayınlanabilir kaynak/not dosyaları GitHub commit'inde de silinir.
