Jarvis klasöründe terminal açıp `.venv\Scripts\python.exe -B scripts\pc_duman_testi.py` komutunu çalıştırın (Linux: `python -B scripts/pc_duman_testi.py`).
Türkçe özet ekrana ve varsayılan olarak `%USERPROFILE%\.jarvis\duman_raporlari\duman_raporu_<tarih_saat>.txt` dosyasına yazılır (Linux: `~/.jarvis/duman_raporlari/`); `JARVIS_DATA_DIR` veya `--veri-klasoru` seçilmişse rapor onun altındadır; yardım alırken paylaşabilirsiniz.
Başka rapor konumu için `--rapor-klasoru "C:\Raporlar"`, başka veri/profil için `--veri-klasoru "C:\Veri" --profil hamdi` ekleyin.
Betik rapor klasörü/raporu ve oradaki kendi geçici kodlama dosyası dışında yazmaz; mail, model, mikrofon kaydı veya ayar değişikliği yapmaz.
GEÇTİ ön kontrolü gösterir; UYARI belirsizliği, BAŞARISIZ sorunu, ATLANDI uygun olmayan platform/modülü belirtir; Linux'ta Windows kontrolleri atlanır (çıkış 0: başarısız yok, 1: kontrol başarısız, 2: rapor/başlatma sorunu).
