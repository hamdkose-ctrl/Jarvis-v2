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


def extract(raw,suffix):
    if not raw or len(raw)>MAX_BYTES:raise ValueError('Belge boyutu geçersiz.')
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
                    if count>1_000_000:raise ValueError('PDF metin sınırı aşılıyor.')
                    add(textpage.get_text_range(0,min(count,max(0,MAX_TEXT+1-length))) if count else '')
                    if length>MAX_TEXT:truncated=True;break
                finally:
                    if textpage is not None:textpage.close()
                    page.close()
    elif suffix in ('.docx','.xlsx','.pptx'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows=archive.infolist()
            if len(rows)>512 or sum(r.file_size for r in rows)>16*1024*1024 or len({r.filename for r in rows})!=len(rows):raise ValueError('Office arşivi sınırı aşıyor.')
            if any(r.flag_bits&1 or r.file_size>4*1024*1024 or r.file_size>max(1,r.compress_size)*1000 or 'vbaproject' in r.filename.lower() for r in rows):raise ValueError('Şifreli/makrolu veya aşırı sıkıştırılmış Office eki reddedildi.')
            def xml(name):
                text=archive.read(name).decode('utf-8-sig')
                if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('Office XML varlıkları reddedildi.')
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
                            if not 0<=index<len(shared):raise ValueError('Excel metin kimliği geçersiz.')
                            value=shared[index]
                        elif cell.get('t')=='inlineStr':value=''.join(n.text or '' for n in cell.iter() if n.tag.endswith('}t'))
                        if any(n.tag.endswith('}f') for n in cell) and not value:value='[Formülün kayıtlı sonucu yok; hesaplanmadı.]'
                        add((cell.get('r','')+': '+value) if value else '')
    else:raise ValueError('Belge türü desteklenmiyor.')
    text='\n'.join(chunks)
    if not text.strip():raise ValueError('Okunabilir metin yok; görüntü/taranmış belge için OCR gerekir.')
    return {'body':text[:MAX_TEXT],'truncated':truncated or len(text)>MAX_TEXT}


def read(raw,suffix):
    try:
        result=subprocess.run([sys.executable,'-m','modules.attachment_documents',suffix],input=raw,capture_output=True,
                              timeout=30,cwd=str(Path(__file__).resolve().parents[1]),check=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if len(result.stdout)>100000:raise ValueError('Belge çıktısı sınırı aşıyor.')
        data=json.loads(result.stdout)
        if not isinstance(data,dict) or not isinstance(data.get('body'),str) or not data['body'].strip() or len(data['body'])>MAX_TEXT or type(data.get('truncated')) is not bool:raise ValueError('Belge çıktısı geçersiz.')
        return data
    except (OSError,subprocess.SubprocessError,ValueError):
        raise ValueError('Ek belge okunamadı: bozuk/şifreli/taranmış belge, eksik okuyucu veya süre/boyut sınırı. OCR ve dış bağlantı kullanılmadı.') from None


if __name__=='__main__':
    data=sys.stdin.buffer.read(MAX_BYTES+1)
    # JSON escapes keep the subprocess protocol independent of Windows code pages.
    print(json.dumps(extract(data,sys.argv[1]),ensure_ascii=True))
