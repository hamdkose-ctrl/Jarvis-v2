# Mobil Arayüz — 9 Ekim 2026

Mobil web ve Android kaynak arayüzü PC tasarımına yaklaştırıldı: açık mavi zemin, beyaz paneller, üstte kullanıcı alanı, mavi sohbet balonları ve daha geniş sohbet alanı. Büyük merkez animasyonu küçük durum alanına taşındı.

## Mobil Web

Sohbet, Notlar ve Araçlar geçişleri bulunur. Araçlar fotoğraf çekme, kullanıcı seçme, ana ekrana ekleme ve Siri bağlantısını açar. Notlar ve çevrimdışı sayfa aynı açık temayı kullanır. Önbellek sürümü v3 oldu. Telefon erişimi ve mevcut QR eşleştirmesi korunur.

PC tarafındaki bu paketi kullanıp Telefon sayfasından bağlantıyı açın. Eski görünüm sürerse mobil sayfayı yenileyin; kurulu web uygulamasını kapatıp açın.

## Android

Sohbet, Hedefler, Dosyalar ve Ayarlar geçişleri eklendi. Kullanıcı seçimi, ses, wake-word, fotoğraf ve PC bağlantısı mevcut kod üzerinden çalışır; bunların gerçek telefonda çalışması bu paketle doğrulanmadı.

Ana dalda Android uygulama kaynakları bulunmadığı için son silinmeden önceki **3.0.7** kaynakları geri alındı. Kaynak: https://github.com/hamdkose-ctrl/Jarvis/tree/ddbe8848d68bfbd8e367cbfaff9e20c630ea9989/android/Jarvis3

Görsel değişiklikler MainActivity.java, Ui.java ve themes.xml dosyalarındadır. Gradle sürüm numarası değiştirilmedi. Bu bir APK veya otomatik telefon güncellemesi değildir. Daha yeni telefon sürümünün kaynaklarıyla birleştirilmeden eski sürüm olarak kurulması önerilmez.

Derlemek için android/Jarvis3 projesini Android Studio'da açın; JDK 17, Android SDK 35 ve bağımlılıklar gerekir. Gradle wrapper dahildir. Windows: gradlew.bat assembleDebug. Linux: sh gradlew assembleDebug. İlk derleme bağımlılıkları internetten indirir. Derlenmiş APK bu pakette yoktur.

## Kontrol Sınırı

Mobil web davranış testi yeni araç geçişlerini de çalıştırır. Android Java dosyaları sözdizimi ayrıştırmasından, XML dosyaları XML kontrolünden geçirildi. Bu kontroller APK derlemesi veya cihaz testi değildir. Gerçek telefonda dar ekran, klavye açılması, QR eşleştirme, mesaj, fotoğraf ve ses birlikte kontrol edilmelidir.
