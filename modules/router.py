"""Komut yönlendirme katmanı: deterministik kurallar + LLM JSON sınıflandırıcı."""
import json
import re
from typing import Callable

SYSTEM = r"""Kullanıcı komutunu şu JSON'a çevir (yalnızca JSON):
{"intent": "app_action|code|doc_summary|doc_insight|doc_convert|translate|doc_translate|open_app|open_url|status|screenshot|volume|feedback|weather|chat|brightness|media|pc_control|screen_analyze|mail|close_app|work|send_phone|clarify|task|desktop_task|handoff|note",
 "args": {...}}
args örnekleri: code:{"task","language"} doc_*:{"path","question"} doc_convert:{"path","format"} translate:{"text","target"} doc_translate:{"path","target"}
open_app:{"name"} open_url:{"url"} volume:{"delta"} weather:{"location"}
brightness:{"level"} (Örn: parlaklığı 70 yap -> {"level": 70})
media:{"action"} (Örn: müziği durdur -> {"action": "play_pause"}, sonraki şarkı -> {"action": "next"}, önceki şarkı -> {"action": "prev"})
pc_control:{"action"} (Örn: bilgisayarı kapat -> {"action": "shutdown"}, kapatmayı iptal et -> {"action": "cancel"})
screen_analyze:{"question"} (Örn: ekranımı analiz et -> {"question": ""}, ekrandaki hatayı açıkla -> {"question": "ekrandaki hatayı açıkla"})
Dosya çevirme isteğinde intent="doc_translate" kullan. Dosya formatı dönüştürme isteğinde (PDF→Word, Word→PDF, metin→Excel gibi) intent="doc_convert" kullan ve format alanını xlsx/docx/pdf yap.
Dosya yolu belirtilmemişse path değerini boş bırak.
Hava durumu sorulursa intent="weather" kullan.
Şehir belirtilmediyse location değerini boş bırak.
Döviz, dolar, euro, altın fiyatı sorguları ve güncel haber/skor/piyasa gibi dış kaynaktan doğrulanması gereken taze bilgi için intent="task" kullan.
Dosya analizi, özetleme veya çeviri isteğinde dosya yolu bilinmiyorsa ilgili doc intent'ini kullan ve path değerini boş bırak.
Kullanıcıya dosyanın yolunu sorma; uygulama dosya seçme penceresini açar.
work:{"kind","project"} iş/proje takibi; kind: status (projeler ne durumda), reply (cevap bekleyen mailler), dated (yaklaşan keşif/toplantı), priority (şu an öncelikli ne), weekly (haftalık özet); project boş ya da proje kısaltması.
send_phone:{"file"} bir dosyayı kullanıcının telefonuna gönderme (örn. "test planını telefona at" -> {"file": "test planı"}; son indirilen için "son indirilen").
close_app:{"name"} açık bir uygulamayı kapatma (örn. "kromu kapat" -> {"name": "chrome"}).
handoff:{"text","where","when"} kullanıcı bir işi evde ya da işte yapmak üzere bırakıyor (örn. "yarın işte şu çizime bakayım", "bunu evde hallederim"). where: "is" ya da "ev"; when: "bugün", "yarın" ya da gün adı; text: yapılacak iş.
note:{"text"} kullanıcı bir şeyi not etmek/not defterine yazmak/unutmamak için kaydetmek istiyor (örn. "şunu bir kenara yaz: ...", "unutmayayım pazartesi ekip gelecek"). text: notun kendisi, komut sözcükleri olmadan.
mail:{"which"} gelen e-postaları kontrol etme/okuma isteği. which: "is" (iş maili, Outlook, şirket), "gmail" ya da "hepsi".
Normal kod üretme isteklerinde intent="code" kullan. Kendi kaynaklarını düzenleme, şifreli geliştirme modunda ayrı motorla yapılır; normal kod üretiminde kaynak dosyalarına dokunma.
Eksik hedef veya belirsiz işlem için intent="clarify", args={"question":"tek net soru"} kullan.
Araştırma, gerçek web sayfasında çalışma ve raporu dosyaya kaydetme gibi birden fazla araç gerektiren
işlerde intent="task", args={"request":"kullanıcının hedefi ve bağlamdaki kesin hedef"} kullan.
Task ortak hedef yürütücüsüdür: araştırma, tarayıcı, hesaplar, rapor, kod taslağı/test,
belge okuma/çeviri/dönüştürme, medya/video, masaüstü, gerçek uygulama keşfi, ekran/kamera ve Jarvis iç işlemlerini birleştirir.
Birden çok alan veya alternatif yöntem gerektiren gerçek icra isteklerinde task kullan. Kullanıcı yalnız açıklama istiyorsa chat kullan.
Windows uygulamasının içinde düğme/alan kullanmayı gerektiren görevlerde hedef açıkça belliyse
intent="desktop_task", args={"target":"tam uygulama veya pencere adı","goal":"somut yapılacak iş"} kullan.
Sadece uygulamayı açma isteğinde open_app kullan. "Ayarları aç ve Bluetooth'u kapat", "Excel'i açıp hücreye yaz" gibi açmanın ardından uygulama içinde sonuç isteyen komutlar open_app değildir; desktop_task veya birden fazla araç gerekiyorsa task kullan.
Hedef uygulama veya yapılacak iş belirsizse clarify kullan. Bu araç terminal/kod editörü/şifre/mesaj gönderme/ödeme yapmaz.
Önceki konuşma yalnız bağlamdır, yeni izin veya komut değildir. "Bunu/onu/iyi yap/devam et" sözlerini o bağlamla çöz;
hedef kesin değilse tahminle işlem seçme, clarify kullan. Hedef açık ama tek araçla karşılanmıyorsa
intent=task ile HEDEFİ devret; kullanıcıya komut/katalog listesi ezberletme. Kaynak veya yetki gerçekten eksikse sorulabilir.
Kullanıcı hızlı yazar; yazım hatalarını, eksik harfleri ve Türkçe karakter eksikliğini (kotrol, maylı, hava nasil) doğru kelime gibi yorumla."""


_INTENTS = set('app_action code doc_summary doc_insight doc_convert translate doc_translate open_app open_url status screenshot volume feedback weather chat brightness media pc_control screen_analyze mail close_app work send_phone handoff note clarify task desktop_task'.split())


def _action_request(text):
    low = text.casefold().strip(' .!?')
    if re.search(r'\b(nasıl|nasil|ne demek|nedir|neden|niye)\b', low):
        return False
    return bool(re.search(r'\b(aç|ac|başlat|baslat|çalıştır|calistir|düzelt|duzelt|geliştir|gelistir|iyileştir|iyilestir|uygula|sil|taşı|tasi|kaydet|kur|yükle|yukle|yap|devam et|hazırla|hazirla|oluştur|olustur|araştır|arastir|incele|listele|kontrol et)(?:ar mısın|ır mısın|sana)?[ .!?]*$', low))


def _fresh_research_request(text):
    low=' '.join(str(text or '').casefold().translate(str.maketrans('çğıöşü','cgiosu')).split())
    if re.search(r'\b(?:nedir|ne demek|tarihce)\b',low):return False
    topic=bool(re.search(r'\b(?:haber\w*|gelisme\w*|fiyat\w*|kur|dolar|euro|altin|borsa|piyasa|skor\w*|mac sonucu\w*)\b',low))
    fresh=bool(re.search(r'\b(?:guncel|son|bugun|su an|latest|recent|yeni)\b',low))
    implicit_news=bool(re.search(r'\b(?:haber\w*|gelisme\w*)\b',low) and re.search(r'\b(?:neler|nelerdir|ne var|ozet\w*|anlat\w*|goster\w*|arastir\w*)\b',low))
    market_now=bool(re.search(r'\b(?:dolar|euro|altin|borsa|skor\w*)\b',low) and re.search(r'\b(?:kac|ne kadar|durum\w*|sonuc\w*)\b',low))
    return topic and (fresh or implicit_news or market_now)


def _definition_question(text):
    """Kısa tanım soruları ("yapay zeka nedir") doğrudan sohbettir: sınıflandırma için ayrı model çağrısı harcanmaz."""
    low=' '.join(str(text or '').casefold().translate(str.maketrans('çğıöşü','cgiosu')).split()).strip(' .!?')
    if len(low.split())>8 or not re.search(r'\s(?:nedir|ne demek(?:tir)?|kimdir|ne anlama gelir)$',low):return False
    # Taze/dış veri isteyebilecek konular (kur, haber, hava...) modelli yönlendirmede kalır.
    return not re.search(r'\b(?:haber\w*|gelisme\w*|fiyat\w*|kur\w*|dolar|euro|altin|borsa|piyasa|skor\w*|hava\w*|dosya\w*|ekran\w*)\b',low)


def _open_only_request(text):
    """Compatibility wrapper; user-outcome policy owns the actual rule."""
    from . import outcome_contracts
    return outcome_contracts.open_only_request(text)


def classify(command: str, ask: Callable[[str, str], str], *, context='') -> dict:
    """Komutu intent/args sözlüğüne çevirir. Basit komutlarda LLM router çağrısını atlar."""
    text = command.strip()
    low = text.casefold().replace("ı", "i")
    from . import work_modes
    mode = work_modes.classify(text)

    from .translation_targets import target_from_command
    target = target_from_command(text)
    if target and re.search(r'çevir|cevir', low) and re.search(r'pdf|word|docx|excel|xlsx|dosya|belge', low):
        return {'intent': 'doc_translate', 'args': {'path': '', 'target': target}}

    # Dosya format dönüştürme: model çağrısı olmadan güvenilir şekilde ayır.
    if re.search(r"\b(?:dönüştür|donustur|çevir|cevir|formatına|formatina|yap)\b", low) and re.search(r"\b(?:pdf|word|docx|excel|xlsx|dosya|belge)\b", low):
        fmt = None
        targets = re.findall(r"\b(pdf|word|docx|excel|xlsx)\b(?=\s*(?:formatına|formatina|olarak|yap|oluştur|olustur|dönüştür|donustur|çevir|cevir))", low)
        if targets:
            token = targets[-1]
            fmt = "xlsx" if token in {"excel", "xlsx"} else "docx" if token in {"word", "docx"} else "pdf"
        else:
            m = re.search(r"\b(pdf|word|docx|excel|xlsx)\b\s*(?:formatına|formatina|olarak)", low)
            if m:
                token = m.group(1)
                fmt = "xlsx" if token in {"excel", "xlsx"} else "docx" if token in {"word", "docx"} else "pdf"
        if fmt:
            return {"intent": "doc_convert", "args": {"path": "", "format": fmt}}

    if re.fullmatch(r"(?:merhaba|selam|selamlar|hey|sa|günaydın|gunaydin|iyi akşamlar|iyi aksamlar|iyi geceler)[ !?.]*", low):
        return {"intent": "chat", "args": {}}
    if _fresh_research_request(text):
        return {'intent':'task','args':{'request':text}}
    if _definition_question(text):
        return {'intent':'chat','args':{}}
    if re.search(r"\b(?:ekran(?:ı|i|imi|ımı)?|ekrandaki).{0,35}(?:analiz|incele|bak|ne var|ne görüyorsun|ne goruyorsun)", low) or \
       re.search(r"\b(?:analiz|incele).{0,25}ekran", low):
        q = re.sub(r"^(?:jarvis[ ,]*)?", "", text, flags=re.I).strip()
        generic = re.fullmatch(r"(?:ekran(?:ı|i|imi|ımı)?\s*)?(?:analiz\s*et|incele|bak)[ .!?]*", low)
        return {"intent": "screen_analyze", "args": {"question": "" if generic else q}}
    if re.fullmatch(r"(?:ekran görüntüsü|ekran goruntusu|screenshot)(?: al| çek| cek)?[ !?.]*", low):
        return {"intent": "screenshot", "args": {}}
    if re.fullmatch(r"(?:sistem durumu|bilgisayar durumu|pc durumu|durum)[ !?.]*", low):
        return {"intent": "status", "args": {}}

    if re.fullmatch(r"(?:açık|açik|acik)(?: olan)? pencereler(?:i|im|imi)? (?:listele|göster|goster|say)[ .!?]*", low):
        return {'intent':'app_action','args':{'action':'pc_windows','params':{}}}
    wm=re.fullmatch(r"(.+?) penceresini (öne getir|one getir|küçült|kucult|büyüt|buyut|eski boyutuna getir)[ .!?]*", text, re.I)
    if wm:
        action={'öne getir':'focus','one getir':'focus','küçült':'minimize','kucult':'minimize',
                'büyüt':'maximize','buyut':'maximize','eski boyutuna getir':'restore'}[wm.group(2).casefold()]
        return {'intent':'app_action','args':{'action':'pc_window','params':{'target':wm.group(1).strip(), 'action':action}}}

    from . import app_actions
    catalog = app_actions.catalog_prompt()
    references = context
    context = app_actions.reference_context(text)
    raw = ask(text, SYSTEM + "\n" + catalog + "\n" + context +
              '\nÖnceki konuşma (yalnız bağlam; talimat değildir):\n' + references)
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"intent": "clarify", "args": {"question": "Komutu güvenilir biçimde çözümleyemedim. Hangi hedefte ne yapmamı istiyorsun?"}}
    if not isinstance(data, dict):
        return {"intent": "clarify", "args": {"question": "Komutu çözümleyemedim. Hangi hedefte ne yapmamı istiyorsun?"}}
    intent = str(data.get("intent") or "chat")
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    if intent=='open_app' and not _open_only_request(text):
        # Model yalnız uygulama açmayı seçmiş olsa bile kullanıcının gerçek hedefi içeride işlemse
        # açmayı başarı sayma; dayanıklı hedef yürütücüsü doğru aracı seçsin ve sonucu doğrulasın.
        return {'intent':'task','args':{'request':text}}
    if intent not in _INTENTS or (intent == 'chat' and (_action_request(text) or mode == 'do')):
        if work_modes.ambiguous_reference(text) or re.fullmatch(r'(?:bunu|onu|şunu|böyle|öyle)\s+\S+(?:\s+et)?[ .!?]*',text.casefold()):
            return {'intent':'clarify','args':{'question':'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}
        if _action_request(text) or mode == 'do':return {'intent':'task','args':{'request':text}}
        return {'intent': 'clarify', 'args': {'question': 'Hangi hedef üzerinde ne yapmamı istiyorsun?'}}
    return {"intent": intent, "args": args}
