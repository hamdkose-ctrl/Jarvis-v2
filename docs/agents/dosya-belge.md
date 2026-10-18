# Dosya, belge ve klasör (AGENTS.md alan notları)

Bu dosya AGENTS.md'den taşındı; bölümler olduğu gibi, sırası korunarak buradadır. Tarihli bölümler geçmiş kararı anlatır; bir bölüm başka bir bölümle çelişirse tarihi daha yeni ve "son karar" yazan geçerlidir. Kod değişince ilgili bölüm burada güncellenir.

## Klasör analizi — 17 Ekim 2026
- `modules/folder_analysis.py`: "İndirilenler klasörünü incele", "masaüstümde ne var", "belgeler klasörü ne hakkında", "indirilenlerdeki Proje klasörünü incele" (ASCII yazım dahil) ve tırnaklı klasör yolu (`main_documents._file_command`). Bağlantı `engine_tools._extra_commands` içinde tek satırdır, model yönlendirmesinden önce çalışır. Düzenle/aç/sil/taşı/izle, tek dosya ("… dosyasını özetle") ve "… geçiyor mu" aramaları bu yola girmez.
- Yalnız `nxapi.allowed` klasörleri; en çok 2 alt klasör seviyesi, 60 belge / 50 MB okuma, 90 sn, 2000 dosya sayımı. Sembolik bağ ve kısayol izlenmez. Fazlası raporda "Sınırlar" satırında söylenir.
- Modelsiz rapor: tür dağılımı, okunamayanlar ve `docs` hata nedeni, SHA-256 ile birebir aynı dosyalar, en az iki dosyada ortak geçen kelimelerle konu grupları. Model en çok bir kez ("ne hakkında", en çok 6000 karakter) çağrılır; hata/kota olursa rapor yine verilir.
- Adında şifre/kimlik/banka/ekstre/bordro… geçen, anahtar uzantılı (.pem/.kdbx…) veya içinde IBAN/"şifre:" olan dosyalar okunmaz, modele gitmez, dizine eklenmez; raporda adıyla "açmadığım" denir. Okunan belgeler `kb.add` ile aramaya eklenir (açık kullanıcı isteğiyle).
- Düzeltmeler (18 Ekim 2026, GPT incelemesi): adı geçen alt klasör (çok sözcüklü dahil) yoksa üst klasöre genişlenmez, "bulamadım" denir (`folder_analysis.resolve`); "masaüstündeki belgeler klasörü" gibi iki klasörlü söz sondaki klasöre gider; birden çok aday klasörde (`Desktop`, `OneDrive/Desktop`…) en dolu olan seçilir, boş kalıntı değil. Her alt klasör `nxapi.allowed` ile yeniden denetlenir (Windows junction izinli ağaçtan çıkamaz). Adıyla gizli sayılan dosya hiç açılmaz, özet değeri hesabına da girmez; içeriğinde gizli bilgi bulunan dosya kontrol için okunur ve raporda ayrı söylenir. Rapor yolları `/` ile yazılır. Tarama sırasında kaybolan dosya raporu düşürmez. Süre dolunca özet ve aramaya ekleme atlanır ve söylenir; tek belge okumasının kendi 300 sn sınırı (`docs`) bu sınırın içine alınmadı. `kb.add`: yeni metin okunamazsa eski aranabilir kayıt silinmez. Windows'ta OneDrive "Şirket" adlı klasörler ve başka diske taşınmış Known Folder yolları hâlâ aday listesinde yok (denenmedi).
- Windows Known Folder (18 Ekim 2026): `nxapi.known_folder(ad)` Windows'ta `SHGetKnownFolderPath` (ctypes) ile Masaüstü/Belgeler/İndirilenler/Resimler'in gerçek yolunu alır (OneDrive yönlendirmesi, başka diske taşınmış, Türkçe ad); Windows dışında `None`. `nxapi._roots` (izinli kökler) ve `folder_analysis._home_folder` aynı kaynağı kullanır, adlarla tahmin yedek kalır. Yalnız çevrimiçi OneDrive belgesi (`st_file_attributes` RECALL bayrakları) açılmaz/özetlenmez/hash'lenmez, raporda adıyla söylenir (açmak indirmeyi başlatırdı). Linux'ta Windows API'si taklit edildi; gerçek Windows'ta denenmedi. `watcher` ve `main_documents` (18 Ekim 2026) aynı kaynağı `nxapi.home_folder` ile kullanır (Known Folder, yoksa Home/OneDrive adı); gerçek Windows'ta denenmedi.
- Test: `tests/test_folder_analysis.py` gerçek dosyalarla (model taklit). Komut zinciri gerçek `main.handle` ile denendi (cihaz/model taklit). Windows'ta OneDrive yönlendirmeli Masaüstü/Belgeler, bulutta duran dosyalar ve büyük gerçek klasör denenmedi.

## Dosya okuma ve aramada kodlama, aynı ad ve çeviri sınırı — 17 Ekim 2026
- `docs.decode_text`: TXT/MD/CSV/HTML baytları BOM'lu UTF-16, UTF-8, yoksa cp1254 olarak çözülür; Türkçe Windows metninde harfler artık sessizce silinmez. CSV MarkItDown'a gitmez (cp1254 ve ';' ayracını bozuyordu), kendi okuyucusuyla sütunlu okunur.
- `kb.file_hits` sonucu dosya adına değil belge kimliğine bağlar; farklı klasörlerde aynı adlı dosyalar karışmaz. "hangi dosyadaydi", "hangi pdf'teydi", "dosyalarimda … geciyor mu" (ASCII) arama yoluna girer (`kb._FILE_QUESTION`); "hangi dosyadan/dosyayı" girmez.
- Metinsiz PDF mesajı (`docs.no_text_message`) mevcut açık yerel OCR komutunu önerir; OCR kendiliğinden çalışmaz.
- Çeviri: belge en çok `translate.MAX_TEXT_PARTS`=20 model çağrısı (~40-70 bin karakter); fazlası çevrilmez ve sonuçta açıkça yazılır. Excel `MAX_EXCEL_BATCHES`=30 çağrıyı aşarsa model/kayıt penceresi açılmadan durur (yarım çevrilmiş Excel üretilmez).
- Test: `tests/test_file_reading_fixes.py` gerçek dosyalarla (model taklit). Windows'ta gerçek Not Defteri/Excel dosyası ve canlı model çevirisi denenmedi.

## Uyarı incelemesi, yerel OCR ve kabul ayrımı — 16 Ekim 2026
- Harici dört sekmeli HUD taslağı uygulanmaz; onaylı hologram/18 düğümlü menü/dock, mevcut SSE ve son Selçuklu arka planı korunur. Eski kabul raporu güncel PC önkoşulu sayılmaz; docs/BEKLEYEN_ISLER.md başı güncel durum ile tarihî kayıtları ayırır.
- `local_ocr` yalnız izinli tek PDF için açık tırnaklı dosya komutuyla (`"tam yol.pdf" yerel OCR ile oku`) çalışır. Tesseract tur+eng dosyaları kurulu değilse indirme/model/bulut geri düşüşü yoktur. PDF/görüntü kalıcı kopyalanmaz, metin otomatik indekslenmez; Gmail'in varsayılan ek okuyucusu değişmez. 4 MiB/10 sayfa/20.000 karakter/30 saniye ve sınırlı render korunur. OCR metninin doğruluğu kullanıcı tarafından kontrol edilir; şifre çözülmez. İptal sonrası sonuç son belge bağlamına yazılmaz.
- Kabulde `--video` mevcut gerçek yerel H.264/FFprobe testini çalıştırır; NaN veya beklenen kısa süreden farklı süre başarılı değildir. Varsayılan kabul bu yeni işlemi yapmaz.
- `--confirm-manual` yalnız beş elle kabul alanını kullanıcı+bilgisayar özelinde tarihli kaydeder; rapor durumu `reported_passed`, otomatik test sonucu `passed` değildir. `--reset-manual` beyanı kaldırır. Windows MachineGuid/Linux machine-id (yoksa MAC) ve bilgisayar adı özetlenir; ham kimlik yazılmaz. Farklı PC veya kullanıcı ayrılır; klonlanmış OS kimliği ve ilgili kod/ayar/cihaz değişikliği yeniden kabul gerektirir. Kimlik/istek sınırı, sembolik bağ reddi ve işlemli kayıt korunur.
- Ağır PDF/Office/Whisper/kamera bağımlılıkları ihtiyaç anında kalır; yeni OCR de başlangıçta PDFium/Pillow veya Tesseract açmaz. Büyük eklenti dönüşümü, kilit paketi, ses motoru ve sosyal hesap izinleri değiştirilmedi. `test_warning_acceptance.py` gerçek taranmış PDF OCR (kurulu İngilizce motor), model çağrısı yapmayan açık dosya yolu, eksik Türkçe dili, süre/çıktı sınırı, kabul ayrımı/sahiplik ve ağır okuyucu yüklenmemesini sınar. Windows Türkçe OCR ve canlı hesap kabulü ayrı kalır.
- Güncel main #44 üzerinde son kontrol: 1331 Python testi (1 Windows DPAPI atlaması), 25 Node grubu ve 6 smoke grubu başarılı. 14 odaklı kontrol ve gerçek yerel H.264/FFprobe testi geçti. Salt okunur kural incelemesi geçti; aynı adlı Windows PC'lerin farklı MachineGuid ile ayrıldığı test edildi. Canlı kullanıcı modeli/hesabı ve Windows Türkçe OCR denenmedi.

## Sohbette dosyalar

- Üst menüde "Dosyalar" düğmesi yoktur (`NAV` içinde durur; `go('files')` ve sesle açılış çalışır, sayfa silinmedi). Dosya işleri sohbetten yapılır: "dosyalarımı göster" / "son yüklediklerim" ya da alttaki "Dosyalarım" düğmesi son 5 dosyayı kartlarla sohbete koyar; her kartta türüne uygun ilk 3 işlem (`FACTS`) bulunur ve `fdo` → `doFile` ile normal sohbet komutu olarak gider. Kart isteği tarayıcıda cevaplanır (`showFileCards`), modele/Gemini'ye gitmez; yalnız ekli dosya yokken yakalanır. Kart mesajı geçmişe yazılmaz (`role:'files'`), kopyalanan konuşmaya girmez.
- Sohbet altındaki kısayol satırı sadedir (`chatShortcuts`): Dosyalarım, Özetle, Tabloya Dönüştür, Dosya Olarak Al, Türkçeye Çevir. Taslak/Uygula/Geri Al/Normal Sohbet yalnız geliştirme modu açıkken görünür; geliştirme modunu açma, İngilizceye çevir, model yetenekleri, görev durumu ve PC/Ses kontrolü sohbet başlığındaki "•••" menüsündedir. Sol sohbet listesi değişmedi.

## Sohbet ekleri

- Dosya ekleme, yapıştırma ve pencereye sürükle-bırak aynı yolu kullanır: `attachChatFile` → `/upload?to=files`. Dosya `Belgeler › Jarvis Dosyaları` klasörüne kopyalanır.
- `S.att` bir dizidir. En fazla 10 dosya eklenebilir, her biri en fazla 200 MB olabilir. Klasör ve boş dosya reddedilir.
- Gönderimde tüm ekler tek istekte `"yol1" "yol2" talimat` biçiminde gider (`main_documents._file_command`, `_FILE_CMD`). Belge masası işi değilse sunucu her dosyayı ayrı işler ve cevapları dosya adı başlığıyla birleştirir.
- Kendi bırakma alanı olan kutular (ör. Matematik) olayı `preventDefault` ile işler. Genel bırakma dinleyicisi bu durumda dosyayı tekrar yüklemez.

## Belge okuma

- Tüm belge okuma `docs.read_document` üzerinden geçer (sohbet ekleri, bilgi tabanı, çeviri, özet).
- Word, Excel (.xlsx/.xlsm), PowerPoint ve HTML önce MarkItDown ile ayrı süreçte ve süre sınırıyla Markdown'a çevrilir (`read_markitdown_isolated`). MarkItDown kurulu değilse ya da çeviremezse mevcut okuyuculara düşülür.
- PDF bilerek mevcut `read_pdf_isolated` yolunda kalır.
- MarkItDown kilit dosyasında değildir; kilit yalnız Hamdi'nin çalışan `.venv` ortamından üretilir (`modules/dependencies.py`). `kurulum.bat` onu `requirements-bundle.txt` ile kurar ve [7/8] doğrulamasında içe aktarır; elle kurmak gerekirse `.venv\Scripts\pip install "markitdown[docx,xlsx,pptx]"`. Ardından Ayarlar'dan paket sürümlerini sabitleme.
- Office dosyaları okunmadan önce `check_office_file` ile denetlenir: şifreli (OLE) dosya, bozuk zip ve açılınca 500 MB'ı aşan içerik reddedilir. Eski .doc/.xls/.ppt için ".docx olarak kaydet" mesajı verilir. Makrolar asla çalıştırılmaz.

## Yüklenen dosyalarda arama

- Yalnız kullanıcının yüklediği dosyalar aranır: Bilgi tabanı sayfasına eklenenler ve sohbette özetlenen/analiz edilen/soru sorulan dosyalar (`kb.remember`). Masaüstü veya klasör taranmaz (Hamdi'nin kararı); yalnız kullanıcı açıkça "… klasörünü incele" derse o klasörde okunan belgeler eklenir (`folder_analysis`).
- `kb.add` metni `~/.jarvis/kb/<kullanıcı>/<id>.txt` olarak saklar ve `arama.sqlite` (SQLite FTS5) içinde dizinler. Parçalar konum taşır: `sayfa 3` (PDF, `\f`), `slayt 7`, `sayfa "Özet"` (Excel).
- Arama kelime aramasıdır (kota harcamaz). Türkçe ekler için kelimenin ilk 5 harfiyle önek araması yapılır. Anlamsal (gömme) arama yalnız açık "anlamsal ara" komutunda çalışır.
- Aynı dosya değişmeden tekrar eklenmez (yol + boyut + değişiklik zamanı); değişmişse eski kaydın yerine geçer. Eski sürümde eklenen belgeler ilk aramada dizinlenir.
- `docs.read_document(path, cache=True)` aynı dosyanın art arda iki kez okunmasını önler (özetleme + dizinleme).

## Belge masası (tablo işleri)

- Giriş `main_documents._file_command`: ekli dosyalar + istek `workbench.wants` ile tablo işi sayılırsa `workbench.handle` çalışır (görseller ve "dönüştür" hariç). Değilse eski akış (özet, analiz, soru) her dosyada ayrı yürür.
- Belgeden tablo ("önemli yerleri tablo yap", "karşılaştır"): metin `docs.read_document(keep_pages=True, cache=True)` ile okunur, `kb._sections` ile `[sayfa N]` etiketli 12 bin karakterlik parçalara bölünür. Bir işte en fazla 12 model çağrısı yapılır (`MAX_CALLS`); fazlası kullanıcıya not olarak söylenir. Varsayılan sütunlar "Konu, Önemli husus, Değer / süre / tutar"; "sütunlar: A, B" ile değişir. Satırdaki her rakam/tarih kaynak parçada aranır, bulunamayan "Kontrol" sütununda işaretlenir.
- Excel/CSV işlemleri (yalnız tüm dosyalar tablo ise: birleştir, grupla/topla, tekrar edenleri sil, sütun birleştir): model yalnız beyaz listeli bir JSON plan yazar (`merge`, `dedupe`, `group_sum`, `join_columns`); hesabı kod yapar. pandas kuruluysa kullanılır, yoksa aynı sonuç saf Python ile çıkar (testler ikisini de dener). Türkçe sayılar (`1.234,56`) ve birimler (ad/adet, mt/m) normalleşir. Benzer ama aynı olmayan kalemler birleştirilmez, "Kontrol et" sayfasına yazılır.
- Çıktı ilk dosyanın klasöründe yeni bir dosyadır (`<ad>_tablo.xlsx`, `_2` eki); kaynak asla ezilmez. Biçim istekten seçilir (Word/PDF dendiyse o, yoksa Excel). Sohbete ilk 10 satır önizleme düşer. Excel'de metin hücreleri formül olarak yazılmaz.
- 30 dakika içinde "şu sütunu ekle", "tabloyu Word'de ver" gibi istekler son işi ek istekle yeniden çalıştırıp yeni sürüm üretir (`workbench.followup`, kullanıcıya özel).

## Klasör izleme

- Kural sesle/yazıyla verilir: "İndirilenler'i izle, PDF gelince önemli yerleri tablo yap" (ayrıca "… haber ver", "… özetle"). "İzlenen klasörler" listeler, "izlemeyi durdur" / "İndirilenler izlemesini durdur" kapatır. Komut `engine_commands` içinde `_file_command`'dan önce `watcher.handle` ile yakalanır; klasör adı tanınmazsa (ör. "videoyu izle") `None` döner ve diğer komutlara geçer.
- Kurallar kullanıcıya özel `~/.jarvis/izleme/<kullanıcı>.json` dosyasındadır. Yalnız `nxapi.allowed` klasörleri (İndirilenler, Masaüstü, Belgeler, Resimler, Jarvis Dosyaları) izlenir, alt klasörlere inilmez.
- `watcher.loop` (`engine_loop` içinde başlar) 20 saniyede bir yalnız dosya listesine bakar; model yalnız kurala uyan yeni dosya için çağrılır. Yalnız PC'nin aktif kullanıcısının kuralları çalışır ve iş parçacığı `llm.set_user_context` ile o kullanıcının anahtarına bağlanır.
- Kuraldan önce var olan dosyalar, `.crdownload/.tmp` gibi yarım dosyalar ve Jarvis'in ürettiği çıktılar (`watcher.OUTPUTS`) işlenmez. Dosya iki taramada aynı boyutta görülünce işlenir. İşlenen adlar kurala yazılır (`done`), yeniden başlatınca tekrar işlenmez.
- Saatte en fazla 5 dosya kendiliğinden işlenir; fazlası bekletilir, "bekleyen dosyaları işle" ile işlenir. Klasöre erişilemezse kural duraklatılır. Sonuç sohbete (`_emit_for`, kaynak `izleme`) ve telefon bildirimi açıksa ntfy'ye gider.

