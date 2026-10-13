"""Validated local note images, stored separately for each profile."""
import base64
import io
import uuid
from pathlib import Path
from PIL import Image
from config import DATA_DIR


def folder(profile):
    slug = str(profile.slug)
    if not slug or '/' in slug or '\\' in slug or '..' in slug:
        raise ValueError('Geçersiz kullanıcı')
    return DATA_DIR/'fotograflar'/slug


def add(profile, text, source='', title=''):
    text = str(text or '').strip()
    if not text and not source:
        raise ValueError('Not metni veya görsel ekle.')
    saved = None
    try:
        if source:
            from modules import nxapi
            path = nxapi.allowed(source)
            if path is None or not path.is_file():
                raise ValueError('Görsele erişilemiyor.')
            if path.stat().st_size > 20*1024*1024:
                raise ValueError('Görsel en fazla 20 MB olabilir.')
            with Image.open(path) as image:
                if image.format not in ('PNG','JPEG','WEBP','GIF','BMP') or image.width*image.height > 20_000_000:
                    raise ValueError('Desteklenmeyen veya çok büyük görsel.')
                image.load()
                directory = folder(profile); directory.mkdir(parents=True,exist_ok=True)
                saved = directory/(uuid.uuid4().hex+'.png')
                image.convert('RGBA' if ('A' in image.getbands() or 'transparency' in image.info) else 'RGB').save(saved,'PNG')
        return profile.add_note_item(text or 'Görsel not', photo=str(saved) if saved else None, title=str(title or '').strip())
    except OSError:
        if saved:
            saved.unlink(missing_ok=True)
        raise


def preview(profile, note_id):
    note = next((n for n in profile.data.get('items',[]) if n.get('id')==int(note_id)),None)
    if not note or not note.get('photo'):
        raise ValueError('Bu kullanıcıya ait görselli not bulunamadı.')
    path = Path(note['photo']).resolve()
    if not path.is_relative_to(folder(profile).resolve()) or not path.is_file():
        raise ValueError('Not görseline erişilemiyor.')
    with Image.open(path) as image:
        image.thumbnail((1600,1600));out=io.BytesIO();image.convert('RGB').save(out,'JPEG',quality=88)
    return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode('ascii')
