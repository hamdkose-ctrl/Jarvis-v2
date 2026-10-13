"""Bounded MIME-to-text extraction. Never render HTML or fetch remote resources."""
import base64
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


def extract(payload):
    plain, html = [], []
    count, encoded = 0, 0

    def visit(part, depth=0):
        nonlocal count, encoded
        count += 1
        if count > 256 or depth > 16 or not isinstance(part, dict):
            raise ValueError('Mail MIME yapısı geçersiz veya çok büyük.')
        h = headers(part)
        # Do not interpret attached .txt/.html files or nested attached messages as body.
        if part.get('filename') or h.get('content-disposition', '').lower().startswith('attachment'):
            return
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
            if data:
                raw = base64.b64decode(data + '=' * (-len(data) % 4), altchars=b'-_', validate=True)
                message = Message()
                message['content-type'] = h.get('content-type', mime)
                charset = message.get_content_charset() or 'utf-8'
                try:
                    text = raw.decode(charset, errors='replace')
                except LookupError:
                    text = raw.decode('utf-8', errors='replace')
                if mime == 'text/html':
                    parser = _Text(); parser.feed(text); parser.close()
                    text = ''.join(parser.text)
                if text.strip():
                    (plain if mime == 'text/plain' else html).append(text.strip())
        if mime.startswith('multipart/'):
            for child in children:
                visit(child, depth + 1)
    visit(payload)
    text = '\n\n'.join(plain or html).strip()
    if not text:
        raise ValueError('Okunabilir gövde yok; ekler indirilmedi ve snippet gövde sayılmadı.')
    return {'body': text[:MAX_TEXT], 'truncated': len(text) > MAX_TEXT,
            'format': 'plain' if plain else 'html_text'}
