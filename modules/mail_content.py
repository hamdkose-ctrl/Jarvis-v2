"""Bounded MIME-to-text extraction. Never render HTML or fetch remote resources."""
import base64
import codecs
import re
from email.message import Message
from html.parser import HTMLParser

MAX_TEXT = 20000
MAX_ENCODED = 2000000


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        if not self.hidden and tag in ('br', 'p', 'div', 'li', 'tr'):
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def headers(payload):
    rows = payload.get('headers', [])
    if not isinstance(rows, list):
        raise ValueError('Mail başlıkları geçersiz.')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(row.get('value'), str):
            raise ValueError('Mail başlığı geçersiz.')
        result[row['name'].lower()] = row['value'][:2000]
    return result


# Gmail "full" yanıtında metin parçası bildirilen charset'ten farklı (UTF-8) baytlarla gelebilir; gönderen de
# windows-1254/iso-8859-9 deyip UTF-8 yollayabilir. Bu tek baytlı ailelerde baytlar geçerli UTF-8 ise UTF-8 okunur;
# Türkçe windows-1254 metni neredeyse hiçbir zaman geçerli UTF-8 değildir. Karakter düzeyinde değiştirme yapılmaz.
_SINGLE_BYTE = re.compile(r'(us-)?ascii|ansi_x3\.4-1968|(iso[-_]?)?8859[-_]?\d+|latin[-_]?\d*|l\d|(windows|cp|x-cp)[-_]?125\d|ibm857|cp857')
_META = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9._:-]{1,40})', re.I)


def _known(charset):
    try:
        return codecs.lookup(charset).name
    except (LookupError, TypeError, ValueError):
        return None


def decode(raw, declared, mime='text/plain'):
    declared = (declared or '').strip().strip('"\'').lower()
    if mime == 'text/html' and not _known(declared):
        found = _META.search(raw[:4096])
        declared = found.group(1).decode('ascii').lower() if found else declared
    codec = _known(declared)
    if codec is None or codec == 'utf-8' or _SINGLE_BYTE.fullmatch(declared):
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            pass
    return raw.decode(codec or 'utf-8', errors='replace')


def extract(payload):
    count, encoded = 0, 0

    def visit(part, depth=0):
        """Return [(kind, text)] in reading order for this part."""
        nonlocal count, encoded
        count += 1
        if count > 256 or depth > 16 or not isinstance(part, dict):
            raise ValueError('Mail MIME yapısı geçersiz veya çok büyük.')
        h = headers(part)
        # Do not interpret attached .txt/.html files or nested attached messages as body.
        if part.get('filename') or h.get('content-disposition', '').lower().startswith('attachment'):
            return []
        children = part.get('parts', [])
        if not isinstance(children, list):
            raise ValueError('Mail MIME parçaları geçersiz.')
        mime = part.get('mimeType', '').lower()
        if mime in ('text/plain', 'text/html'):
            body = part.get('body', {})
            if not isinstance(body, dict):
                raise ValueError('Mail gövdesi geçersiz.')
            data = body.get('data', '')
            if not isinstance(data, str):
                raise ValueError('Mail gövde kodlaması geçersiz.')
            encoded += len(data)
            if encoded > MAX_ENCODED:
                raise ValueError('Mail gövdesi okuma sınırını aşıyor.')
            if not data:
                return []
            raw = base64.b64decode(data + '=' * (-len(data) % 4), altchars=b'-_', validate=True)
            message = Message()
            message['content-type'] = h.get('content-type', mime)
            text = decode(raw, message.get_content_charset(), mime)
            if mime == 'text/html':
                parser = _Text(); parser.feed(text); parser.close()
                text = ''.join(parser.text)
            return [('plain' if mime == 'text/plain' else 'html', text.strip())] if text.strip() else []
        if not mime.startswith('multipart/'):
            return []
        results = [visit(child, depth + 1) for child in children]
        if mime == 'multipart/alternative':
            # Aynı içeriğin farklı biçimleri: düz metni içeren seçeneği, yoksa ilk dolu seçeneği al.
            filled = [r for r in results if r]
            return next((r for r in filled if all(kind == 'plain' for kind, _ in r)), filled[0] if filled else [])
        return [segment for r in results for segment in r]
    segments = visit(payload)
    text = '\n\n'.join(t for _, t in segments).strip()
    if not text:
        raise ValueError('Okunabilir gövde yok; ekler indirilmedi ve snippet gövde sayılmadı.')
    return {'body': text[:MAX_TEXT], 'truncated': len(text) > MAX_TEXT,
            'format': 'plain' if all(kind == 'plain' for kind, _ in segments) else 'html_text'}
