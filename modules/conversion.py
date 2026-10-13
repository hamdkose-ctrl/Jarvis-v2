"""Atomic structure-aware conversion with explicit fidelity limits."""
from pathlib import Path
import os
import shutil
import tempfile
from modules import requests_state
from modules.document_conversion import read_source,text_blocks,Content


def write_content(content,destination,source=None):
    from modules import conversion_writers as writers
    extension=Path(destination).suffix.lower()
    if extension=='.xlsx':writers.write_xlsx(content,destination,source)
    elif extension=='.docx':writers.write_docx(content,destination,source)
    elif extension=='.pdf':writers.write_pdf(content,destination)
    else:raise ValueError('Çıktı PDF, Word (.docx) veya Excel (.xlsx) olmalı.')


def convert(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():raise FileNotFoundError('Kaynak dosya bulunamadı.')
    if source==destination:raise ValueError('Kaynak dosyanın üzerine yazılamaz; farklı bir çıktı adı seç.')
    if destination.suffix.lower() not in ('.pdf','.docx','.xlsx'):raise ValueError('Çıktı PDF, DOCX veya XLSX olmalı.')
    if not destination.parent.is_dir():raise FileNotFoundError('Çıktı klasörü bulunamadı.')
    content=None
    fd,temp=tempfile.mkstemp(prefix='.jarvis-convert-',suffix=destination.suffix,dir=destination.parent);os.close(fd)
    try:
        if source.suffix.lower()==destination.suffix.lower():shutil.copyfile(source,temp)
        else:
            content=read_source(source);write_content(content,temp,source)
        requests_state.check()
        os.replace(temp,destination)
    finally:
        Path(temp).unlink(missing_ok=True)
    note=''
    if content and content.pages and destination.suffix.lower()=='.docx':
        note='Word metinleri ve seçenekleri düzenlenebilir olarak aktarıldı. Şekil ve formüller ek bölümde kaynak sayfa görüntüleriyle korundu; bu görüntüler düzenlenebilir metin değildir. Sayfa yerleşimi birebir korunmaz.'
    elif content and content.questions:
        note=f'{len(content.questions)} soru ayrı alanlara aktarıldı. Şekiller ve formüller için kaynak sayfa görünümleri eklendi; kontrol notlarını incele.'
    elif content and content.warnings:note=' '.join(content.warnings)
    return {'path':str(destination),'note':note,'questions':len(content.questions) if content else 0}


def save_text(text,destination,label):
    content=Content(label.replace('_',' ').title(),blocks=text_blocks(text))
    destination=Path(destination)
    fd,temp=tempfile.mkstemp(prefix='.jarvis-convert-',suffix=destination.suffix,dir=destination.parent);os.close(fd)
    try:
        write_content(content,temp)
        requests_state.check()
        os.replace(temp,destination)
    finally:
        Path(temp).unlink(missing_ok=True)
