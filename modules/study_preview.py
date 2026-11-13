"""Render the source page, without rebuilding its text or layout."""
import base64
import io


def pdf_page(path, page=1):
    from modules.pdf_runtime import open_pdf
    if isinstance(page, bool) or not isinstance(page, int):
        raise ValueError('Geçersiz sayfa.')
    with open_pdf(path) as document:
        count = len(document)
        if not 1 <= page <= count:
            raise ValueError('Sayfa belgenin dışında.')
        source = document[page-1]
        try:
            width, height = source.get_size()
            bitmap = source.render(scale=min(2, 2000/max(width, height)))
            try:
                image = bitmap.to_pil().convert('RGB').copy()
            finally:
                bitmap.close()
        finally:
            source.close()
    return image, count


def image_url(image):
    image = image.copy()
    image.thumbnail((1400, 1800))
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


def selected_page(path, selection, key):
    from modules.math_tutor import _crop
    import tempfile
    from pathlib import Path
    if not isinstance(selection, dict) or selection.get('image_id') != key:
        raise ValueError('Kaynak veya sayfa değişti; yeniden seç.')
    image, count = pdf_page(str(path), selection.get('page', 1))
    if selection.get('full_page') is True:
        return image, count
    with tempfile.TemporaryDirectory(prefix='jarvis-page-') as tmp:
        saved = Path(tmp)/'page.png'
        image.save(saved, 'PNG')
        return _crop(saved, selection, {'image': key}), count


def source(profile, doc_id=0, page=1):
    from modules import study
    from modules.pdf_runtime import PdfReadError
    items = study._state(profile).get('docs') or []
    item = next((d for d in items if int(d['id']) == int(doc_id)), None) if doc_id else (items[-1] if items else None)
    if not item:
        raise ValueError('Geçerli bir kaynak seç.')
    path = study._dir(profile) / f"{int(item['id'])}.source.pdf"
    preview_error = None
    if path.is_file():
        try:
            image, count = pdf_page(str(path), page)
            return {'id': item['id'], 'title': item['title'], 'image': image_url(image),
                    'page': page, 'pages': count, 'source_page': True, 'image_id': f"source:{item['id']}:{page}"}
        except PdfReadError as exc:
            preview_error = str(exc)
    info, text = study.source_info(profile, doc_id)
    note = 'Bu kaydın özgün PDF dosyası saklanmamış. Sayfa düzeni için PDF’yi yeniden yükle.' if str(item['title']).lower().endswith('.pdf') else 'Metin görünümü; özgün sayfa düzeni için PDF veya görsel yükle.'
    if preview_error:
        note = preview_error + ' Kayıtlı metin gösteriliyor. Özgün dosyayı yeniden bağlamayı deneyebilirsin; sorun sürerse PDF’nin kendisi incelenmeli.'
    return {**info, 'text': text[:50000], 'note': note,
            'missing_original': str(item['title']).lower().endswith('.pdf')}


def restore_original(profile, doc_id, path):
    """Attach the verified original to an existing source; keep its ID and progress."""
    import hashlib
    import os
    import re
    import tempfile
    from pathlib import Path
    from modules import file_resource_guard, nxapi, study
    allowed = nxapi.allowed(path)
    if allowed is None or not allowed.is_file() or allowed.suffix.lower() != '.pdf':
        raise ValueError('İzinli klasörden özgün PDF dosyasını seç.')
    with study._jobs_lock:
        state = study._state(profile)
        item = next((d for d in state.get('docs', []) if int(d['id']) == int(doc_id)), None)
        if item is None:
            raise ValueError('Kaynak bulunamadı; yeniden seç.')
        generation = state.get('source_generation', 0)
        expected_hash = item.get('source_hash')
        original_text = (study._dir(profile) / f"{int(item['id'])}.txt").read_text(encoding='utf8')
    with tempfile.TemporaryDirectory(prefix='jarvis-original-pdf-') as tmp:
        import shutil
        snapshot = Path(tmp) / 'source.pdf'
        # A source file being changed by a cooperating Jarvis writer may
        # not be treated as the verified PDF original.
        with file_resource_guard.claim_paths(allowed):
            shutil.copyfile(allowed, snapshot)
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if expected_hash:
            matches = digest == expected_hash
        else:
            extracted = study._read_isolated(str(snapshot))
            normalize = lambda text: re.sub(r'\s+', '', text)
            matches = bool(normalize(original_text)) and normalize(original_text) == normalize(extracted)
        if not matches:
            raise ValueError('Bu PDF mevcut kaynağın özgünüyle eşleşmiyor. Doğru dosyayı seç.')
        pdf_page(str(snapshot), 1)  # Reject unreadable PDFs before changing the record.
        with study._jobs_lock:
            state = study._state(profile)
            if state.get('source_generation', 0) != generation or not any(d is item for d in state.get('docs', [])):
                raise ValueError('Kaynak değişti; yeniden seç.')
            target = study._dir(profile) / f"{int(item['id'])}.source.pdf"
            # Only install missing originals. An existing PDF (including an
            # unreadable one) is not authority to overwrite a possibly foreign
            # or concurrently modified file.
            with file_resource_guard.claim_paths(target):
                with tempfile.NamedTemporaryFile(
                        mode='wb', prefix='.jarvis-original-',
                        suffix='.tmp', dir=target.parent, delete=False) as stream:
                    staging = Path(stream.name)
                    with snapshot.open('rb') as verified:
                        shutil.copyfileobj(verified, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(staging, target)
                    before_flag = item.get('original_pdf')
                    before_hash = item.get('source_hash')
                    try:
                        item['original_pdf'] = True
                        item['source_hash'] = digest
                        profile.save()
                    except Exception:
                        if before_flag is None:
                            item.pop('original_pdf', None)
                        else:
                            item['original_pdf'] = before_flag
                        if before_hash is None:
                            item.pop('source_hash', None)
                        else:
                            item['source_hash'] = before_hash
                        target.unlink(missing_ok=True)
                        raise
                finally:
                    staging.unlink(missing_ok=True)
    return {'ok': True, 'id': int(item['id'])}
