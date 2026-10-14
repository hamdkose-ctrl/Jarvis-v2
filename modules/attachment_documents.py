"""Isolated bounded text extraction; no Office execution, external links or OCR."""
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

MAX_BYTES=4*1024*1024
MAX_TEXT=20000
TIMEOUT=30
_TAIL=' OCR ve dış bağlantı kullanılmadı.'
# Alt süreç yalnız bu kodları döndürür; belge içeriği/hata metni hata iletisine girmez.
REASONS={
    'no_text':'Ek belgede okunabilir metin yok; görüntü/taranmış belge için OCR gerekir.',
    'encrypted':'Ek belge şifreli; şifresiz bir kopya gerekli.',
    'corrupt':'Ek belge bozuk veya okuyucu tarafından açılamadı.',
    'limit':'Ek belge boyut/metin/arşiv sınırını aşıyor.',
    'rejected':'Ek belge güvenlik nedeniyle reddedildi (şifreli/makrolu Office, XML varlığı veya aşırı sıkıştırma).',
    'unsupported':'Ek belge türü desteklenmiyor.',
    'reader_missing':'PDF/Office okuyucu paketi bu Python ortamında eksik (ör. pypdfium2); kurulum.bat ile onarın.',
    'timeout':f'Ek belge {TIMEOUT} saniyelik süre sınırında okunamadı.',
    'start':'Belge okuyucu alt süreci başlatılamadı.',
    'crash':'Belge okuyucu alt süreci beklenmedik biçimde kapandı.',
    'output':'Belge okuyucu geçersiz çıktı verdi.',
}


class Rejected(ValueError):
    def __init__(self,code):
        super().__init__(REASONS[code]);self.code=code


def extract(raw,suffix):
    if not raw or len(raw)>MAX_BYTES:raise Rejected('limit')
    chunks=[];length=0;truncated=False
    def add(text):
        nonlocal length,truncated
        if text:
            remaining=MAX_TEXT+1-length
            if remaining<=0:truncated=True;return
            value=text[:remaining];chunks.append(value);length+=len(value)+1
            if len(text)>remaining or length>MAX_TEXT:truncated=True
    if suffix=='.pdf':
        from modules.pdf_runtime import open_pdf
        with open_pdf(raw) as pdf:
            truncated=len(pdf)>40
            for index in range(min(len(pdf),40)):
                page=pdf[index];textpage=None
                try:
                    textpage=page.get_textpage();count=textpage.count_chars()
                    if count>1_000_000:raise Rejected('limit')
                    add(textpage.get_text_range(0,min(count,max(0,MAX_TEXT+1-length))) if count else '')
                    if length>MAX_TEXT:truncated=True;break
                finally:
                    if textpage is not None:textpage.close()
                    page.close()
    elif suffix in ('.docx','.xlsx','.pptx'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows=archive.infolist()
            if len(rows)>512 or sum(r.file_size for r in rows)>16*1024*1024 or len({r.filename for r in rows})!=len(rows):raise Rejected('limit')
            if any(r.flag_bits&1 or r.file_size>4*1024*1024 or r.file_size>max(1,r.compress_size)*1000 or 'vbaproject' in r.filename.lower() for r in rows):raise Rejected('rejected')
            def xml(name):
                text=archive.read(name).decode('utf-8-sig')
                if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise Rejected('rejected')
                return ET.fromstring(text)
            if suffix=='.docx':
                root=xml('word/document.xml')
                for node in root.iter():
                    if node.tag.endswith('}p'):add(''.join(n.text or '' for n in node.iter() if n.tag.endswith('}t')))
            elif suffix=='.pptx':
                names=[r.filename for r in rows if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml',r.filename)]
                for name in sorted(names,key=lambda n:int(re.search(r'([0-9]+)\.xml$',n)[1])):
                    add(' '.join(n.text or '' for n in xml(name).iter() if n.tag.endswith('}t')))
            else:
                shared=[]
                if 'xl/sharedStrings.xml' in archive.namelist():
                    shared=[''.join(n.text or '' for n in item.iter() if n.tag.endswith('}t')) for item in xml('xl/sharedStrings.xml')]
                names=[r.filename for r in rows if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml',r.filename)]
                for name in sorted(names):
                    for cell in xml(name).iter():
                        if not cell.tag.endswith('}c'):continue
                        value=next((n.text for n in cell if n.tag.endswith('}v')),'') or ''
                        if cell.get('t')=='s':
                            index=int(value)
                            if not 0<=index<len(shared):raise Rejected('corrupt')
                            value=shared[index]
                        elif cell.get('t')=='inlineStr':value=''.join(n.text or '' for n in cell.iter() if n.tag.endswith('}t'))
                        if any(n.tag.endswith('}f') for n in cell) and not value:value='[Formülün kayıtlı sonucu yok; hesaplanmadı.]'
                        add((cell.get('r','')+': '+value) if value else '')
    else:raise Rejected('unsupported')
    text='\n'.join(chunks)
    if not text.strip():raise Rejected('no_text')
    return {'body':text[:MAX_TEXT],'truncated':truncated or len(text)>MAX_TEXT}


def _worker(raw,suffix):
    """Alt süreçte çalışır: sonuç ya da yalnız hata kodu döner."""
    try:
        return extract(raw,suffix)
    except Rejected as exc:code=exc.code
    except ImportError:code='reader_missing'
    except (ValueError,KeyError,IndexError,EOFError,OSError,RuntimeError,zipfile.BadZipFile,ET.ParseError) as exc:
        # PdfReadError (ValueError) şifreyi PDFium hata kodu 4 ile bildirir; diğerleri bozuk belge sayılır.
        # Beklenmeyen hatalar alt süreci düşürür ve ana süreçte "beklenmedik biçimde kapandı" olur.
        code='encrypted' if getattr(exc.__cause__,'err_code',None)==4 else 'corrupt'
    return {'error':code}


def _fail(code):
    raise ValueError(REASONS[code]+_TAIL) from None


def _python():
    # Jarvis'in kendi .venv yorumlayıcısı; pythonw.exe yerine yanındaki konsol python.exe kullanılır.
    executable=Path(sys.executable)
    console=executable.with_name('python.exe')
    return str(console if executable.name.lower()=='pythonw.exe' and console.is_file() else executable)


def read(raw,suffix):
    try:
        result=subprocess.run([_python(),'-m','modules.attachment_documents',suffix],input=raw,capture_output=True,
                              timeout=TIMEOUT,cwd=str(Path(__file__).resolve().parents[1]),check=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired:_fail('timeout')
    except subprocess.CalledProcessError:_fail('crash')
    except (OSError,subprocess.SubprocessError):_fail('start')
    if len(result.stdout)>100000:_fail('output')
    try:
        # Çıktı her zaman UTF-8 bayttır; Windows'un yerel kod sayfası (cp1254/cp857) araya girmez.
        data=json.loads(result.stdout.decode('utf-8'))
    except ValueError:_fail('output')
    if isinstance(data,dict) and set(data)=={'error'} and data['error'] in REASONS:_fail(data['error'])
    if not isinstance(data,dict) or not isinstance(data.get('body'),str) or not data['body'].strip() or len(data['body'])>MAX_TEXT or type(data.get('truncated')) is not bool:_fail('output')
    return data


if __name__=='__main__':
    data=sys.stdin.buffer.read(MAX_BYTES+1)
    # print() yerel kod sayfasıyla yazar ve Türkçe harflerde bozulur; baytları doğrudan UTF-8 yaz.
    sys.stdout.buffer.write(json.dumps(_worker(data,sys.argv[1]),ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()
