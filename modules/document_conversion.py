"""Shared document model. No cloud calls or instructions from source documents."""
from dataclasses import dataclass, field
from pathlib import Path
import csv
import io
import re


@dataclass
class Block:
    kind: str
    text: str = ''
    rows: list = field(default_factory=list)
    image: bytes = b''
    level: int = 0


@dataclass
class Content:
    title: str
    blocks: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    sheets: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    questions: list = field(default_factory=list)


def text_blocks(text):
    """Parse Markdown headings, paragraphs, lists and pipe tables without a model."""
    blocks=[];paragraph=[];lines=text.splitlines();i=0
    def flush():
        if paragraph:blocks.append(Block('paragraph', '\n'.join(paragraph)));paragraph.clear()
    while i < len(lines):
        line=lines[i]
        if not line.strip():flush();i+=1;continue
        if '|' in line and i+1 < len(lines) and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*',lines[i+1]):
            flush();rows=[[c.strip() for c in line.strip().strip('|').split('|')]];i+=2
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')]);i+=1
            blocks.append(Block('table',rows=rows));continue
        heading=re.match(r'^\s*(#{1,6})\s+(.+)',line)
        if heading:flush();blocks.append(Block('heading',heading[2],level=len(heading[1])))
        elif re.match(r'^\s*(?:[-*+]\s+|\d+\.\s+)',line):flush();blocks.append(Block('paragraph',line.strip()))
        else:paragraph.append(line)
        i+=1
    flush();return blocks


def read_source(source):
    source=Path(source);suffix=source.suffix.lower();content=Content(source.stem)
    if suffix=='.pdf':
        from modules.pdf_runtime import open_pdf
        from modules.exam_conversion import extract_questions
        with open_pdf(source) as pdf:
            for page in pdf:
                text=page.get_textpage()
                try:
                    content.pages.append(text.get_text_bounded())
                finally:
                    text.close();page.close()
        content.questions=extract_questions(content.pages)
        content.warnings.append('PDF sayfa görüntüleri korunur; çıkarılan metin ve formüller kaynakla karşılaştırılmalıdır.')
    elif suffix=='.docx':
        from docx import Document
        from docx.text.paragraph import Paragraph
        from docx.table import Table
        doc=Document(str(source))
        for element in doc.element.body.iterchildren():
            if element.tag.endswith('}p'):
                p=Paragraph(element,doc);name=p.style.name if p.style else ''
                level=int(name.rsplit(' ',1)[1]) if re.fullmatch(r'Heading [1-9]',name) else 0
                if p.text.strip():content.blocks.append(Block('heading' if level else 'paragraph',p.text,level=level))
                for blip in element.xpath('.//a:blip'):
                    rel=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    if rel and rel in doc.part.related_parts:content.blocks.append(Block('image',image=doc.part.related_parts[rel].blob))
            elif element.tag.endswith('}tbl'):
                table=Table(element,doc)
                content.blocks.append(Block('table',rows=[[c.text for c in row.cells] for row in table.rows]))
        content.warnings.append('Metin, tablo sırası ve gömülü görseller korunur; birleşik hücreler açılır. Word temaları ve sayfa yerleşimi birebir kopyalanmaz.')
    elif suffix=='.xlsx':
        from openpyxl import load_workbook
        workbook=load_workbook(source,data_only=False);cached=load_workbook(source,data_only=True)
        try:
            for sheet in workbook:
                rows=[]
                for row in sheet:
                    values=[]
                    for cell in row:
                        value=cell.value
                        if cell.data_type=='f':
                            saved=cached[sheet.title][cell.coordinate].value
                            value=saved if saved is not None else 'Formül (hesaplanmış değer yok): '+value
                        values.append(value)
                    rows.append(values)
                while rows and all(v is None for v in rows[-1]):rows.pop()
                content.sheets.append((sheet.title,rows))
                content.blocks.append(Block('heading',sheet.title,level=1))
                if rows:content.blocks.append(Block('table',rows=rows))
                for image in sheet._images:
                    content.blocks.append(Block('image',image=image._data()))
        finally:workbook.close();cached.close()
        content.warnings.append('Formüller yeniden hesaplanmaz; kayıtlı sonuç yoksa formül açıkça gösterilir. Grafikler ve hücre stilleri diğer biçimlere birebir taşınmaz.')
    elif suffix=='.csv':
        text=source.read_text(encoding='utf-8-sig')
        try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
        except csv.Error:dialect=csv.excel
        rows=list(csv.reader(io.StringIO(text),dialect))
        def typed(value):
            if re.fullmatch(r'[+-]?(?:0|[1-9]\d*)',value):return int(value)
            if re.fullmatch(r'[+-]?(?:0|[1-9]\d*)\.\d+',value):return float(value)
            return value
        rows=[[typed(value) for value in row] for row in rows]
        content.sheets.append((source.stem,rows));content.blocks.append(Block('table',rows=rows))
    elif suffix in ('.txt','.md'):
        content.blocks=text_blocks(source.read_text(encoding='utf-8-sig'))
    else:
        raise ValueError('Yapılı dönüşüm PDF, DOCX, XLSX, CSV, TXT ve MD kaynaklarını destekler. Eski DOC/XLS dosyasını önce yeni biçimde kaydet.')
    return content


def page_image(pdf,index,scale=1.4):
    page=pdf[index]
    bitmap=page.render(scale=scale)
    try:
        image=bitmap.to_pil();out=io.BytesIO();image.convert('RGB').save(out,format='JPEG',quality=88)
        return out.getvalue(),image.size
    finally:bitmap.close();page.close()
