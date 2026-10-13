"""Format-specific outputs for the shared content model."""
from pathlib import Path
from datetime import date, datetime
import io
import re
import textwrap
from modules.document_conversion import text_blocks


def cell_value(value):
    if isinstance(value,str) and len(value)>32767:
        raise ValueError('Bir hücre Excel metin sınırını aşıyor; içerik kesilmeden dönüştürülemiyor.')
    return value


def write_xlsx(content,destination,source=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font,Alignment,PatternFill
    from openpyxl.drawing.image import Image
    from modules.document_conversion import page_image
    wb=Workbook();wb.remove(wb.active)
    def sheet(name,rows,widths=None):
        name=re.sub(r'[\\/*?:\[\]]',' ',name)[:31] or 'Belge'
        base=name;n=2
        while name in wb.sheetnames:name=base[:27]+f' {n}';n+=1
        ws=wb.create_sheet(name);ws.sheet_view.showGridLines=False
        for row in rows:
            ws.append([cell_value(v) for v in row])
            for cell in ws[ws.max_row]:
                if isinstance(cell.value,str):cell.data_type='s' # source strings never become formulas
                cell.alignment=Alignment(wrap_text=True,vertical='top')
                if isinstance(cell.value,datetime):cell.number_format='dd/mm/yyyy hh:mm'
                elif isinstance(cell.value,date):cell.number_format='dd/mm/yyyy'
        if ws.max_row:
            for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='25465F')
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for i in range(1,ws.max_column+1):
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(i)].width=(widths[i-1] if widths and i<=len(widths) else 30)
        for row in range(2,ws.max_row+1):
            lines=[]
            for cell in ws[row]:
                capacity=max(8,int(ws.column_dimensions[cell.column_letter].width*.9))
                lines.append(sum(max(1,len(textwrap.wrap(part,width=capacity))) for part in str(cell.value or '').split('\n')))
            ws.row_dimensions[row].height=min(409,max(30,16*max(lines,default=1)+8))
        return ws
    if content.questions:
        rows=[['Ders kodu','Ders','Soru no','Soru metni','A','B','C','D','Doğru cevap','PDF sayfası','Kontrol notu']]
        for q in content.questions:
            rows.append([q.code,q.course,q.number,q.text,*[q.options.get(k,'') for k in 'ABCD'],q.answer,q.page,'; '.join(q.checks)])
        questions=sheet('Sorular',rows,[12,27,10,75,30,30,30,30,14,12,46]);questions.freeze_panes='D2'
        # Compact editable study view; keep all extracted source fields in Sorular.
        study_rows=[['Ders','No','Soru ve seçenekler','Cevabım','Doğru cevap','Sonuç','Kaynak sayfa','Kontrol notu']]
        for q in content.questions:
            choices='\n'.join(f'{k}) {v}' for k,v in q.options.items())
            study_rows.append([q.course,q.number,q.text+'\n\n'+choices,'',q.answer,'',q.page,'; '.join(q.checks)])
        study=sheet('Çalışma',study_rows,[24,7,92,12,12,13,12,36])
        wb.move_sheet(study,offset=-len(wb.worksheets)+1)
        from openpyxl.worksheet.table import Table,TableStyleInfo
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.formatting.rule import CellIsRule
        table=Table(displayName='CalismaSorulari',ref=study.dimensions)
        table.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=True)
        study.add_table(table);study.freeze_panes='C2';study.sheet_view.zoomScale=85
        validation=DataValidation(type='list',formula1='"A,B,C,D,E"',allow_blank=True)
        validation.errorTitle='Geçersiz seçenek';validation.error='A, B, C, D veya E seç.';validation.showErrorMessage=True
        study.add_data_validation(validation);validation.add(f'D2:D{study.max_row}')
        for row,q in enumerate(content.questions,2):
            study.cell(row,6,f'=IF(D{row}="","",IF(E{row}="","Anahtar yok",IF(UPPER(D{row})=E{row},"Doğru","Yanlış")))')
            study.cell(row,4).font=Font(color='0000FF',size=11)
            study.cell(row,7).hyperlink=f"#'Sorular'!J{row}"
        for value,color in [('Doğru','DCF3E5'),('Yanlış','FBE5E5')]:
            study.conditional_formatting.add(f'F2:F{study.max_row}',CellIsRule(operator='equal',formula=['"'+value+'"'],fill=PatternFill('solid',fgColor=color)))
        study.print_title_rows='1:1';study.sheet_properties.pageSetUpPr.fitToPage=True
        study.page_setup.orientation='landscape';study.page_setup.paperSize=study.PAPERSIZE_A3
        study.page_setup.fitToWidth=1;study.page_setup.fitToHeight=0
        study.print_area=f'A1:H{study.max_row}'
    elif content.sheets:
        for name,rows in content.sheets:sheet(name,rows or [['Boş sayfa']])
    else:
        records=[['Tür','İçerik']];tables=[]
        for block in content.blocks:
            if block.kind=='table':
                tables.append(block);records.append(['Tablo',f'Tablo {len(tables)}'])
            elif block.kind!='image':records.append(['Başlık' if block.kind=='heading' else 'Paragraf',block.text])
        if content.pages:
            records=[['PDF sayfası','Metin']]+[[i+1,text.replace('\x02','')] for i,text in enumerate(content.pages)]
        sheet('Belge',records,[18,105])
        for i,table in enumerate(tables,1):sheet(f'Tablo {i}',table.rows)
    if content.pages:
        from modules.pdf_runtime import open_pdf
        ws=sheet('Kaynak sayfalar',[['PDF sayfası','Kaynak görünümü']],[16,90]);ws.auto_filter.ref=None
        with open_pdf(source) as pdf:
            for i in range(len(pdf)):
                data,size=page_image(pdf,i)
                image=Image(io.BytesIO(data));image.width=650;image.height=650*size[1]/size[0]
                anchor=2+i*72;ws.cell(anchor,1,i+1);ws.add_image(image,f'B{anchor}')
                for r in range(anchor,anchor+72):ws.row_dimensions[r].height=15
        if content.questions:
            for row,q in enumerate(content.questions,2):
                cell=questions.cell(row,10);cell.hyperlink=f"#'Kaynak sayfalar'!A{2+(q.page-1)*72}";cell.font=Font(color='0563C1',underline='single')
    images=[b.image for b in content.blocks if b.kind=='image']
    if images:
        ws=sheet('Görseller',[['Görsel','Kaynak görünümü']],[16,90])
        for i,data in enumerate(images):
            image=Image(io.BytesIO(data));ratio=min(1,650/image.width,900/image.height);image.width*=ratio;image.height*=ratio
            anchor=2+i*72;ws.cell(anchor,1,i+1);ws.add_image(image,f'B{anchor}')
    if content.warnings:sheet('Dönüşüm notları',[['Not']]+[[n] for n in content.warnings],[110])
    wb.save(destination)


def write_docx(content,destination,source=None):
    from docx import Document
    from docx.shared import Inches,Pt
    from docx.enum.text import WD_BREAK
    from modules.document_conversion import page_image
    doc=Document();doc.styles['Normal'].font.name='Arial';doc.styles['Normal'].font.size=Pt(11)
    from docx.shared import RGBColor
    for name in ['Title','Heading 1','Heading 2','Heading 3','Heading 4']:
        doc.styles[name].font.color.rgb=RGBColor(0,0,0)
    if content.pages:
        # Editable text is primary. Never silently replace text pages with pictures.
        from modules.pdf_runtime import open_pdf
        section=doc.sections[0];section.page_width=Inches(8.27);section.page_height=Inches(11.69)
        section.left_margin=section.right_margin=Inches(.75)
        section.top_margin=section.bottom_margin=Inches(.7)
        doc.add_heading(content.title,0)
        if content.questions:
            course=None
            for q in content.questions:
                key=(q.code,q.course)
                if key!=course:
                    heading=doc.add_heading(f'{q.course} ({q.code})',1)
                    heading.paragraph_format.page_break_before=course is not None
                    course=key
                p=doc.add_paragraph();p.add_run(f'{q.number}. ').bold=True;p.add_run(q.text)
                p.paragraph_format.keep_with_next=True
                for index,(key,value) in enumerate(q.options.items()):
                    p=doc.add_paragraph(f'{key}) {value}');p.paragraph_format.space_after=Pt(3)
                    p.paragraph_format.keep_with_next=index<len(q.options)-1
                p=doc.add_paragraph(f'Doğru cevap: {q.answer or "Anahtar eşleşmedi"} · Kaynak PDF sayfası: {q.page}')
                p.paragraph_format.space_after=Pt(14)
                if q.checks:
                    doc.add_paragraph('Kontrol: '+'; '.join(q.checks)).runs[0].font.size=Pt(9)
        else:
            for i,text in enumerate(content.pages):
                heading=doc.add_heading(f'Kaynak sayfa {i+1}',1)
                heading.paragraph_format.page_break_before=bool(i)
                if text.strip():
                    for paragraph in text_blocks(text.replace('\x02','')):
                        doc.add_paragraph(paragraph.text)
                else:
                    # Scanned pages cannot become editable text without OCR.
                    with open_pdf(source) as pdf:
                        data,size=page_image(pdf,i)
                    doc.add_paragraph('Bu sayfada metin katmanı yok; OCR gerekir.')
                    doc.add_picture(io.BytesIO(data),width=Inches(6.5))
        # Reference appendix retains diagrams/formulas without pretending pictures
        # are editable. The document's main text remains native Word paragraphs.
        doc.add_heading('Kaynak sayfa görünümleri',1).paragraph_format.page_break_before=True
        doc.add_paragraph('Metin ve seçenekler önceki bölümde düzenlenebilir. Şekil, formül ve özel yazıları aşağıdaki kaynak görüntüleriyle karşılaştır.')
        with open_pdf(source) as pdf:
            for i in range(len(pdf)):
                if i:doc.add_paragraph().paragraph_format.page_break_before=True
                doc.add_paragraph(f'Kaynak PDF sayfası {i+1}')
                data,size=page_image(pdf,i,scale=1.4)
                doc.add_picture(io.BytesIO(data),width=Inches(min(6.5,8.6*size[0]/size[1])))
    else:
        doc.add_heading(content.title,0)
        for block in content.blocks:
            if block.kind=='heading':doc.add_heading(block.text,min(4,block.level or 1))
            elif block.kind=='paragraph':doc.add_paragraph(block.text)
            elif block.kind=='table':
                width=max((len(r) for r in block.rows),default=0)
                if not width:continue
                table=doc.add_table(rows=0,cols=width);table.style='Table Grid'
                for values in block.rows:
                    cells=table.add_row().cells
                    for i,value in enumerate(values):cells[i].text='' if value is None else str(value)
            elif block.kind=='image':
                from PIL import Image
                with Image.open(io.BytesIO(block.image)) as image:
                    width=min(6,8*image.width/image.height)
                doc.add_picture(io.BytesIO(block.image),width=Inches(width))
    doc.save(destination)


def _unicode_pdf_font():
    import os
    fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    candidates = [fonts / name for name in ('arial.ttf', 'segoeui.ttf', 'calibri.ttf')]
    candidates.extend([
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
        Path('/Library/Fonts/Arial.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
    ])
    return next((font for font in candidates if font.is_file()), None)


def write_pdf(content,destination):
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle,Image
    font = _unicode_pdf_font()
    if font is None:raise ValueError('Türkçe PDF için Unicode yazı tipi bulunamadı; eksik harfli çıktı üretilmedi.')
    pdfmetrics.registerFont(TTFont('JarvisConversion',str(font)))
    style=ParagraphStyle('body',fontName='JarvisConversion',fontSize=10,leading=14,spaceAfter=8)
    title=ParagraphStyle('title',parent=style,fontSize=16,leading=21,spaceAfter=15)
    story=[Paragraph(escape(content.title),title)];width=landscape(A4)[0]-72
    para=lambda v:Paragraph(escape('' if v is None else str(v)).replace('\n','<br/>'),style)
    for block in content.blocks:
        if block.kind in ('paragraph','heading'):story.append(Paragraph(escape(block.text).replace('\n','<br/>'),title if block.kind=='heading' else style))
        elif block.kind=='table':
            cols=max((len(r) for r in block.rows),default=0)
            # Partition very wide tables; retain every column with visible labels.
            for start in range(0,cols,6):
                count=min(6,cols-start)
                if cols>6:story.append(para(f'Sütunlar {start+1}–{start+count}'))
                rows=[[para(v) for v in (r+[None]*cols)[start:start+count]] for r in block.rows]
                table=LongTable(rows,colWidths=[width/count]*count,repeatRows=1,splitInRow=1)
                table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,'#D9D9D9'),('BACKGROUND',(0,0),(-1,0),'#E5EDF3'),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6)]))
                story.extend([table,Spacer(1,12)])
        elif block.kind=='image':
            image=Image(io.BytesIO(block.image));ratio=min(width/image.imageWidth,460/image.imageHeight,1)
            image.drawWidth=image.imageWidth*ratio;image.drawHeight=image.imageHeight*ratio;story.extend([image,Spacer(1,10)])
    SimpleDocTemplate(str(destination),pagesize=landscape(A4),leftMargin=36,rightMargin=36,topMargin=36,bottomMargin=36).build(story)
