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
    if len(paths) == 1 and paths[0] is not None and paths[0].is_dir() and not paths[0].is_file():   # '"…\\Proje" klasörünü incele'
        from modules import folder_analysis
        return folder_analysis.analyze(runtime.profile, paths[0])
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
    if 'görselleştir' in act or 'gorsellestir' in act:
        from modules import visual_commands
        from modules.image_gen import ImageGenError
        kind = visual_commands.detect_type(act) or 'visualize'
        try:
            content = runtime.docs.summarize(path)
        except Exception as exc:
            _record_failure('modules/main_documents.py:_file_command:gorsellestir')
            from modules import failure_policy
            return 'Dosya özetlenemedi: ' + failure_policy.user_message(exc)
        try:
            result = visual_commands.create_visual(act, content, slug=runtime.profile.slug, kind=kind)
        except ImageGenError as exc:
            return f'Görsel üretilemedi ({exc.reason_code}). Cloudflare hesap/anahtar ayarını kontrol et.'
        except ValueError as exc:
            return str(exc)
        runtime._session().last_visual = {'text': act, 'content': content, 'kind': kind}
        return (f'{result.label.capitalize()} hazır, Dosyalar sayfasına kaydettim: {result.path}\n'
                'Beğenmezsen "yeniden dene" diyebilirsin.')
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

def _photo_action(runtime, path: str, operation: str, *, question: str = "",
                  target: str = "", note_text: str = "") -> str:
    """Apply the Core-validated photo operation; this executor never selects the operation."""
    if (msg := runtime.privacy.blocked('camera')):
        return msg
    if operation == 'note':
        text = note_text or 'Fotoğraf'
        runtime._add_note(text, photo=path)
        runtime.privacy.audit('fotoğraflı not', text[:60])
        return f'Fotoğraflı not aldım: {text}'
    photo_sys = f'Sen {runtime.ASSISTANT_NAME} adlı, Türkçe konuşan bir asistansın; {runtime.profile.name} ile konuşuyorsun. Bu yanıt ekranda okunacak: anlaşılır ve gerektiği kadar ayrıntılı yaz. LaTeX ($...$, \\frac gibi) kullanma; düz metin ve Unicode yaz (x², √x, a/b, ≤, ×). Markdown başlıkları ve emoji kullanma; adımları 1), 2) diye numarala. Emin değilsen söyle.'
    if operation == 'translate':
        prompt = f'Fotoğraftaki bütün yazıları oku ve {target or "Türkçe"} diline çevir. Önce “Metin:” satırlarıyla özgün yazıyı, sonra “Çeviri:” satırlarıyla çeviriyi yaz. Fotoğrafta yazı yoksa bunu söyle.'
        runtime.privacy.audit('fotoğraf çevirisi', target or 'Türkçe')
    elif operation == 'analyze':
        prompt = "Bu bir telefon kamerasıyla çekilmiş fotoğraf. Önce fotoğrafta ne olduğuna bak. İçinde bir soru, problem ya da alıştırma (matematik, fizik, test vb.) varsa şu biçimde yanıtla: 1) Soruyu kendi cümlelerinle yaz. 2) Çözümü numaralı adımlarla ayrıntılı anlat; her adımda ne yaptığını ve nedenini açıkla, ara işlemleri göster. 3) 'Sonuç:' satırıyla cevabı net yaz. 4) Kısa bir doğrulama ya da ipucu ekle. Soru yoksa görüneni Türkçe ve anlaşılır biçimde anlat."
        if question:
            prompt += f'\nKullanıcının isteği (öncelikle buna cevap ver): {question}'
        runtime.privacy.audit('fotoğraf analizi', question[:60] or '-')
    else:
        return 'Fotoğraf işlemi doğrulanamadı; işlem başlatılmadı.'
    return runtime.ask_image(path, prompt, photo_sys, max_tokens=3500).strip() or 'Fotoğraftan bir şey çıkaramadım.'
