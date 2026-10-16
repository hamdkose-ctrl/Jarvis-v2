"""Document, folder and photo actions, isolated from the engine loop."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

def _file_command(runtime, command: str) -> str | None:
    """Yeni arayüzün dosya düğmeleri: tırnak içindeki tam yol + işlem. Yol yoksa/izinsizse açık hata döner."""
    from modules import nxapi, workbench
    m = runtime._FILE_CMD.match(command.strip())
    if not m:
        try:   # "şu sütunu ekle", "tabloyu Word'de ver": son tablonun yeni sürümü
            return workbench.followup(runtime.profile.slug, command)
        except ValueError as e:
            return str(e)
    raw_paths = runtime.re.findall(r'"([^"]{4,400})"', m.group(1))
    paths = [nxapi.allowed(r) for r in raw_paths]
    if any(p is None or not p.is_file() for p in paths):
        return 'Bu dosyaya erişemiyorum: yalnızca İndirilenler, Masaüstü, Belgeler, Resimler ve Jarvis Dosyaları klasörlerindeki dosyalarla çalışırım.'
    act = runtime._tr_lower(m.group(2))
    if runtime.re.fullmatch(r'(?:yerel\s+)?ocr(?:\s+ile)?\s+(?:oku|metni\s+çıkar)[.! ]*', act.strip()):
        if len(paths) != 1 or paths[0].suffix.lower() != '.pdf':
            return 'Yerel OCR için tek bir PDF dosyası seç.'
        from modules import local_ocr
        try:
            with paths[0].open('rb') as stream:
                result = local_ocr.read(stream.read(local_ocr.MAX_BYTES + 1))
        except ValueError as exc:
            return str(exc)
        runtime._session().last_doc = (result['body'], str(paths[0]), 'yerel_ocr')
        return (result['body'] + '\n\nYerel OCR çıktısıdır; harf ve sayıları asıl belgeyle kontrol et.' +
                (' İlk sayfa/metin sınırında kesildi.' if result['truncated'] else '') +
                '\nDosya olarak almak istersen çıktı al de.')
    as_files = [str(p) for p in paths]
    images = [x for x in as_files if x.lower().endswith(runtime._IMG_EXT)]
    if not images and 'dönüştür' not in act and 'donustur' not in act and workbench.wants(act, as_files):
        try:   # belge masası: önemli yerler tablosu, karşılaştırma, birleştirme, gruplama
            return workbench.handle(runtime.profile.slug, as_files, m.group(2).strip())
        except ValueError as e:
            return str(e)
    if len(paths) > 1:   # tablo işi değilse her dosya kendi başına işlenir
        return '\n\n'.join(f'**{p.name}**\n' + (_file_command(runtime, f'"{p}" {m.group(2).strip()}') or '') for p in paths)
    p = paths[0]
    path = str(p)
    is_img = path.lower().endswith(runtime._IMG_EXT)
    if 'telefon' in act:
        from modules import filesend
        return filesend.send(p)
    if 'metni çıkar' in act or ('metin' in act and is_img):
        return runtime.ask_image(path, 'Bu görseldeki tüm yazıyı olduğu gibi, satır düzenini koruyarak çıkar. Açıklama ekleme.', runtime.profile.system_prompt(), max_tokens=3500).strip() or 'Görselde okunabilir yazı bulamadım.'
    if is_img and runtime.re.search('analiz|özetle|incele|açıkla', act):
        result = runtime.ask_image(path, 'Bu görseli Türkçe ve ayrıntılı analiz et: ne görünüyor, önemli ayrıntılar, varsa üzerindeki yazılar ve teknik bilgiler, son olarak kısa öneriler.', runtime.profile.system_prompt(), max_tokens=3000).strip()
        runtime._session().last_doc = (result, path, 'gorsel_analiz')
        return result
    language_target = runtime.tr.target_from_command(act)
    if ('çevir' in act or 'cevir' in act) and language_target:
        return runtime._translate_file(path, language_target)
    if 'dönüştür' in act or 'donustur' in act or (runtime.re.search('çevir|cevir', act) and runtime.re.search('excel|word|pdf', act)):
        fmt = 'xlsx' if 'excel' in act else 'docx' if 'word' in act else 'pdf' if 'pdf' in act else ''
        if not fmt:
            return 'Hangi biçime dönüştüreyim: Excel, Word ya da PDF?'
        saved = runtime.output.convert_document(path, fmt)
        return (f'Dosyayı {fmt.upper()} biçiminde kaydettim: {saved["path"]}' + ('\n' + saved['note'] if saved['note'] else '')) if saved else 'Dönüştürme iptal edildi.'
    if 'çevir' in act or 'cevir' in act:
        return 'Hangi dile çevireyim? Örneğin: Türkçeye çevir.'
    if 'özetle' in act or 'özet' in act:
        result = runtime.docs.summarize(path)
        runtime._session().last_doc = (result, path, 'ozet')
        runtime.kb.remember(runtime.profile, path)   # sonra "hangi dosyadaydı?" diye aranabilsin
        return result + '\n\nDosya olarak almak istersen çıktı al de.'
    if 'analiz' in act or 'incele' in act:
        result = runtime.docs.insights(path, '')
        runtime._session().last_doc = (result, path, 'analiz')
        runtime.kb.remember(runtime.profile, path)
        return result + '\n\nDosya olarak almak istersen çıktı al de.'
    question = m.group(2).strip()
    if is_img:
        result = runtime.ask_image(path, question + '\nTürkçe yanıtla.', runtime.profile.system_prompt(), max_tokens=3000).strip()
    else:
        result = runtime.docs.insights(path, question)
        runtime.kb.remember(runtime.profile, path)
    runtime._session().last_doc = (result, path, 'analiz')
    return result

def _resolve_doc(runtime, raw, command: str='') -> tuple[str | None, str | None]:
    """Modelin verdiği 'path' değerini gerçek dosyaya çevirir.

    Dönüş: (dosya_yolu, klasör_yanıtı). 'İndirilenler' gibi klasör adı gelirse klasördeki dosyaları listeler;
    yalnız dosya adı gelirse kullanıcının klasörlerinde arar; 'yüklediğim dosya' denirse en son yükleneni alır."""
    from pathlib import Path
    from modules import nxapi
    name = str(raw or '').strip().strip('"\'')
    low = runtime._tr_lower(name).strip(' /\\')
    folder = None
    if low in runtime._HOME_DIRS:
        for base in (nxapi.HOME, nxapi.HOME / 'OneDrive'):
            if (base / runtime._HOME_DIRS[low]).is_dir():
                folder = base / runtime._HOME_DIRS[low]
                break
    elif low in ('jarvis dosyaları', 'jarvis dosyalari', 'yüklediklerim'):
        folder = nxapi.FILES_DIR
    elif name:
        p = Path(runtime.os.path.expandvars(runtime.os.path.expanduser(name)))
        if p.is_dir() and nxapi.allowed(p):
            folder = p
        elif p.is_file() and nxapi.allowed(p):
            return (str(p), None)
    if folder is not None:
        return (None, runtime._folder_overview(folder))
    try:
        items = nxapi.list_files(800)['files']
    except Exception:
        _record_failure('modules/main_documents.py:_resolve_doc')
        items = []
    if name:
        key = runtime._tr_lower(Path(name).name)
        stem = runtime._tr_lower(Path(name).stem)
        hit = [f for f in items if runtime._tr_lower(f['name']) == key] or [f for f in items if stem and stem in runtime._tr_lower(f['name'])]
        hit.sort(key=lambda f: (not f.get('mine'), -f['mtime']))
        if hit:
            return (hit[0]['path'], None)
    if runtime.re.search('yükled|yukled|eklediğ|ekledig|son (?:dosya|eklenen|yüklenen)|bu dosya', runtime._tr_lower(command)):
        mine = [f for f in items if f.get('mine')]
        if mine:
            return (mine[0]['path'], None)
    if name:
        return (None, f'“{name}” adlı bir dosya bulamadım. İndirilenler, Masaüstü, Belgeler, Resimler ve Jarvis Dosyaları klasörlerine baktım. Dosyalar sayfasından seçip “Analiz Et”e basabilirsin.')
    return (None, None)

def _folder_overview(runtime, folder) -> str:
    """Klasördeki dosyaları (alt klasörlere inmeden) listeler ve türlerine göre kısaca özetler."""
    from modules import nxapi
    files = []
    for p in folder.iterdir():
        try:
            if p.is_file() and (not p.name.startswith(('~$', '.'))) and (p.name.lower() != 'desktop.ini'):
                files.append((p.stat().st_mtime, p))
        except OSError:
            continue
    title = 'Jarvis Dosyaları' if folder == nxapi.FILES_DIR else nxapi._TR.get(folder.name, folder.name)
    if not files:
        return f'{title} klasörü boş.'
    files.sort(reverse=True)
    from collections import Counter
    kinds = Counter((nxapi._cat(p.suffix.lower()) if p.suffix.lower() in nxapi._ALL else 'diğer' for _, p in files))
    tr_kind = {'pdf': 'PDF', 'word': 'Word', 'excel': 'Excel', 'image': 'görsel', 'other': 'diğer', 'diğer': 'diğer'}
    head = f'{title} klasöründe {len(files)} dosya var: ' + ', '.join((f'{n} {tr_kind[k]}' for k, n in kinds.most_common())) + '.'
    lines = []
    for mt, p in files[:25]:
        size = p.stat().st_size
        sz = f'{size / 1048576:.1f} MB' if size >= 1048576 else f'{max(1, size // 1024)} KB'
        lines.append(f"• {p.name} — {sz}, {runtime.datetime.fromtimestamp(mt).strftime('%d.%m.%Y')}")
    more = f'\n…ve {len(files) - 25} dosya daha.' if len(files) > 25 else ''
    return head + '\nEn yeniden eskiye:\n' + '\n'.join(lines) + more + '\n\nBirini incelememi istersen adını söyle, örneğin: “' + files[0][1].name + ' dosyasını özetle”.'

def _translate_file(runtime, path: str, target: str) -> str:
    """Excel dışı belgeyi çevirir, kaydetmeden gösterir; 'çıktı al' ile kaydedilir."""
    pass
    if path.lower().endswith('.xlsx'):
        return runtime.tr.translate_document(path, target)
    result = runtime.tr.translate_text_document(path, target)
    runtime._session().last_doc = (result, path, 'ceviri')
    runtime._session().speech_override = 'Çeviri hazır, metni ekrana yazdım. Dosya olarak almak istersen çıktı al de.'
    return result + '\n\nDosya olarak almak istersen çıktı al de.'

def _keep_photo(runtime, src: str) -> str:
    """Telefondan gelen fotoğrafı kalıcı klasöre taşır (fotoğraflı notlar için); 30 günden eski, notta olmayanları siler."""
    d = runtime._PHOTO_DIR / runtime.profile.slug
    d.mkdir(parents=True, exist_ok=True)
    dest = d / (runtime.time.strftime('%Y%m%d_%H%M%S') + '_' + runtime.secrets.token_hex(16) + runtime.os.path.splitext(src)[1].lower())
    try:
        runtime.os.replace(src, dest)
    except OSError:
        import shutil
        shutil.copyfile(src, dest)
    try:
        used = {it.get('photo') for it in runtime.profile.data.get('items', [])}
        for f in d.iterdir():
            if runtime.time.time() - f.stat().st_mtime > 30 * 86400 and str(f) not in used:
                f.unlink()
    except OSError:
        pass
    return str(dest)

def _photo_action(runtime, path: str, question: str) -> str:
    """Fotoğrafla istenen işi yapar: not olarak kaydet, yazıyı çevir ya da analiz et / soruyu cevapla."""
    if (msg := runtime.privacy.blocked('camera')):
        return msg
    q = (question or '').strip()
    ql = runtime._tr_lower(q)
    if runtime.re.search('\\bnot\\b|not\\s*(?:al|ekle|et|olarak)|nota\\b|notlara|kaydet|sakla', ql) and (not runtime.re.search('analiz|çevir|çöz', ql)):
        text = runtime.re.sub('(?:(?:bu|şu)\\s+)?(?:resmi|fotoğrafı|fotoyu|görseli)?\\s*(?:not\\s+olarak\\s+)?(?:not\\s+(?:al|ekle|et)\\w*|nota\\s+(?:ekle|al)\\w*|notlara\\s+ekle\\w*|kaydet\\w*|sakla\\w*|ekle\\w*)', ' ', q, flags=runtime.re.I)
        text = runtime._plain(runtime.re.sub('^\\s*(?:bu|şu)\\s+(?:resmi|fotoğrafı|fotoyu|görseli)\\b', '', text, flags=runtime.re.I)) or 'Fotoğraf'
        runtime._add_note(text, photo=path)
        runtime.privacy.audit('fotoğraflı not', text[:60])
        return f'Fotoğraflı not aldım: {text}'
    photo_sys = f'Sen {runtime.ASSISTANT_NAME} adlı, Türkçe konuşan bir asistansın; {runtime.profile.name} ile konuşuyorsun. Bu yanıt ekranda okunacak: anlaşılır ve gerektiği kadar ayrıntılı yaz. LaTeX ($...$, \\frac gibi) kullanma; düz metin ve Unicode yaz (x², √x, a/b, ≤, ×). Markdown başlıkları ve emoji kullanma; adımları 1), 2) diye numarala. Emin değilsen söyle.'
    if runtime.re.search('çevir|tercüme|translate', ql):
        langs = {'ingilizce': 'İngilizce', 'almanca': 'Almanca', 'arapça': 'Arapça', 'rusça': 'Rusça', 'fransızca': 'Fransızca', 'japonca': 'Japonca', 'çince': 'Çince', 'korece': 'Korece', 'italyanca': 'İtalyanca', 'ispanyolca': 'İspanyolca'}
        target = next((v for k, v in langs.items() if k in ql), 'Türkçe')
        prompt = f'Fotoğraftaki bütün yazıları oku ve {target} diline çevir. Önce “Metin:” satırlarıyla özgün yazıyı, sonra “Çeviri:” satırlarıyla çeviriyi yaz. Fotoğrafta yazı yoksa bunu söyle.'
        runtime.privacy.audit('fotoğraf çevirisi', target)
    else:
        prompt = "Bu bir telefon kamerasıyla çekilmiş fotoğraf. Önce fotoğrafta ne olduğuna bak. İçinde bir soru, problem ya da alıştırma (matematik, fizik, test vb.) varsa şu biçimde yanıtla: 1) Soruyu kendi cümlelerinle yaz. 2) Çözümü numaralı adımlarla ayrıntılı anlat; her adımda ne yaptığını ve nedenini açıkla, ara işlemleri göster. 3) 'Sonuç:' satırıyla cevabı net yaz. 4) Kısa bir doğrulama ya da ipucu ekle. Soru yoksa görüneni Türkçe ve anlaşılır biçimde anlat."
        if q and (not runtime.re.fullmatch('(?:bunu |şunu )?(?:analiz et|incele|ne var|bu ne|açıkla|anlat)\\w*', ql.strip(' .!?'))):
            prompt += f'\nKullanıcının isteği (öncelikle buna cevap ver): {q}'
        runtime.privacy.audit('fotoğraf analizi', q[:60] or '-')
    return runtime.ask_image(path, prompt, photo_sys, max_tokens=3500).strip() or 'Fotoğraftan bir şey çıkaramadım.'
