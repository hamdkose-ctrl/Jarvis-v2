"""Conservative multiple-choice extraction; answers are never inferred."""
from dataclasses import dataclass, field
import re


@dataclass
class Question:
    course: str
    code: str
    number: int
    page: int
    text: str = ''
    options: dict = field(default_factory=dict)
    answer: str = ''
    checks: list = field(default_factory=list)


def course_key(code, name):
    name = name.upper()
    language = next((lang for lang in ('İNGİLİZCE', 'ALMANCA', 'FRANSIZCA') if lang in name), '')
    return str(code), language


def join_lines(lines):
    text = '\n'.join(lines).replace('\x02', '')
    text = re.sub(r'[\u00ad-]\s*\n\s*(?=[a-zçğıöşü])', '', text)
    text = text.replace('\u00ad', '-')
    return re.sub(r'\s+', ' ', text).strip()


def extract_questions(pages):
    """Only recognize a bank with course headings, choices and an answer-key section."""
    if not any('CEVAP ANAHTARI' in text.upper() for text in pages):
        return []
    questions = []; answers = {}; course = ''; code = ''; current = None
    stem = []; choice = None; parts = {}; key_mode = False; header = False

    def flush():
        nonlocal current, stem, choice, parts
        if current:
            current.text = join_lines(stem)
            current.options = {key: join_lines(value) for key, value in parts.items()}
            questions.append(current)
        current = None; stem = []; choice = None; parts = {}

    for page_number, text in enumerate(pages, 1):
        if 'DERS KODU VE ADI SAYFA' in text or 'ADAYLARIN DİKKATİNE' in text or 'CEVAP KÂĞIDI VE SORU KİTAPÇIĞI İLE İLGİLİ AÇIKLAMALAR' in text:
            flush();course='';code='';header=False
            continue
        if 'CEVAP ANAHTARI' in text.upper():
            flush(); key_mode = True
        elif key_mode:
            # Answer appendices must remain an appendix; never parse them as questions.
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith(('TEST BİTTİ.', 'CEVAPLARINIZI KONTROL EDİNİZ.')):
                continue
            if not line or re.fullmatch(r'\d+|\d+\.\s*OTURUM', line):
                continue
            heading = re.match(r'^\((\d{3,4})\)\s*(.*)', line)
            if heading:
                flush(); code, course = heading.groups(); header = True
                continue
            number = re.match(r'^(\d{1,3})\.\s*(.*)', line)
            if header and not number:
                if not re.search(r'[–-]\s*\d+\s*$', course):
                    course += ' ' + line
                continue
            if not code:
                continue
            if key_mode:
                answer = re.fullmatch(r'(\d{1,3})\.\s*([A-E])', line)
                if answer:
                    header = False
                    key = (*course_key(code, course), int(answer[1]))
                    if key in answers and answers[key] != answer[2]:
                        answers[key] = ''  # conflicting keys require review
                    else:
                        answers[key] = answer[2]
                continue
            if number and (current is None or int(number[1]) == current.number + 1):
                flush(); header = False
                current = Question(course.strip(), code, int(number[1]), page_number)
                line = number[2]
            if current is None:
                continue
            matches = list(re.finditer(r'(?:^|\s)([A-E])\)\s*', line))
            if matches:
                prefix = line[:matches[0].start()].strip()
                if prefix:
                    (parts.setdefault(choice, []) if choice else stem).append(prefix)
                for i, match in enumerate(matches):
                    choice = match[1]
                    end = matches[i+1].start() if i+1 < len(matches) else len(line)
                    parts.setdefault(choice, []).append(line[match.end():end])
            else:
                (parts.setdefault(choice, []) if choice else stem).append(line)
    flush()
    if len(questions) < 3:
        return []
    seen = set()
    for q in questions:
        key = (*course_key(q.code, q.course), q.number)
        q.answer = answers.get(key, '')
        if key in seen:q.checks.append('Yinelenen ders/soru numarası')
        seen.add(key)
        if not q.text:q.checks.append('Soru metni okunamadı')
        if any(not q.options.get(k) for k in 'ABCD'):q.checks.append('Eksik veya görsel seçenek; kaynak sayfayı kontrol et')
        if not q.answer:q.checks.append('Cevap anahtarı eşleşmedi')
        if re.search(r'[\u0600-\u06ff]|\b(?:şekil|grafik|tablo)\w*', q.text, re.I) or q.code in ('421','425','432','436','479','609','999'):
            q.checks.append('Şekil, formül veya özel yazı: kaynak görünümünü kontrol et')
    return questions
