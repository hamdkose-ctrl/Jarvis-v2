"""Döküman analizi: PDF/DOCX/XLSX/PPTX/CSV/HTML/TXT oku, özetle, içgörü çıkar."""
import re
from pathlib import Path

from .diagnostics import record_failure as _record_failure
from .llm import ask

SUPPORTED = (".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".csv", ".html", ".htm", ".txt", ".md", ".rtf", ".odt", ".json")
_LEGACY = {".doc": "Word", ".xls": "Excel", ".ppt": "PowerPoint"}
# PDF ve CSV bilerek kendi okuyucularında kalır: MarkItDown CSV'de Türkçe kodlamayı (cp1254) ve ';' ayracını bozuyor.
_MARKITDOWN = {".docx", ".xlsx", ".xlsm", ".pptx", ".html", ".htm"}
_OOXML = {".docx", ".xlsx", ".xlsm", ".pptx"}
_MAX_UNZIPPED = 500 * 1024 * 1024      # açılmış Office içeriği üst sınırı (zip bombası)
_MAX_OUTPUT = 20_000_000               # alt süreçten alınan en fazla Markdown karakteri
_CHUNK = 30000        # tek istekte gönderilen en fazla karakter
_MAX_CHUNKS = 5       # çok uzun belgelerde istek (kota) harcamamak için üst sınır

class PdfReadTimeout(RuntimeError):
    """İzole PDF okuyucu süresi doldu; ana süreçte sınırsız tekrar okunmaz."""


def read_pdf_isolated(path: str) -> str:
    """PDF metnini AYRI bir Python sürecinde okur; tüm proje için tek PDF okuma yoludur.

    pypdf saf Python olduğu için büyük kitapta dakikalarca işlemciyi tutup Jarvis'in
    arayüzünü ve sesini yavaşlatıyordu; ayrı süreç bunu ana programdan ayırır.
    Ağır Jarvis modülleri bu alt süreçte yüklenmez. Sayfalar form-feed (\f) ile ayrılır.
    """
    import subprocess, sys, logging
    root = Path(__file__).resolve().parent.parent
    code = ("import sys,logging;logging.getLogger('pypdf').setLevel(logging.ERROR);from pypdf import PdfReader;"
            "sys.stdout.buffer.write(chr(12).join(p.extract_text() or '' for p in PdfReader(sys.argv[1]).pages)"
            ".encode('utf-8'))")
    try:
        cp = subprocess.run([sys.executable, "-c", code, str(path)], cwd=str(root), capture_output=True, timeout=900,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
    except subprocess.TimeoutExpired as exc:
        raise PdfReadTimeout("PDF okuma süresi doldu; ana işlemde sınırsız tekrar denenmedi.") from exc
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(err[-1] if err else "PDF okunamadı")
    return cp.stdout.decode("utf-8", "replace")


def check_office_file(p: Path) -> None:
    """Şifreli, bozuk veya açılınca aşırı büyüyen Office dosyasını okumadan reddeder."""
    import zipfile
    with open(p, "rb") as f:
        head = f.read(8)
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("Bu dosya parola korumalı (şifreli) görünüyor. Parolayı kaldırıp kaydettikten sonra tekrar dene.")
    try:
        with zipfile.ZipFile(p) as z:
            rows = z.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError("Dosya bozuk ya da gerçek bir Office dosyası değil.") from exc
    if len(rows) > 20000 or sum(r.file_size for r in rows) > _MAX_UNZIPPED:
        raise ValueError("Dosya açıldığında çok büyüyor; güvenlik için okumadım.")


def markitdown_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("markitdown") is not None


def read_markitdown_isolated(path: str) -> str | None:
    """MarkItDown ile Markdown'a çevirir; AYRI süreçte, süre sınırıyla ve eklentiler kapalı çalışır.

    Kurulu değilse ya da dosyayı çeviremezse None döner ve çağıran mevcut okuyucuya düşer.
    """
    import subprocess, sys
    if not markitdown_available():
        return None
    root = Path(__file__).resolve().parent.parent
    code = ("import sys;from markitdown import MarkItDown;"
            "r=MarkItDown(enable_plugins=False).convert_local(sys.argv[1]);"
            "sys.stdout.buffer.write((r.text_content or '').encode('utf-8'))")
    try:
        cp = subprocess.run([sys.executable, "-c", code, str(Path(path).resolve())], cwd=str(root), capture_output=True, timeout=300,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Dosyayı okumak çok uzun sürdü; daha küçük bir dosyayla dene.") from exc
    if cp.returncode != 0:
        return None
    text = cp.stdout[:_MAX_OUTPUT * 4].decode("utf-8", "replace")[:_MAX_OUTPUT]
    return text if text.strip() else None


def decode_text(raw: bytes) -> str:
    """Metin dosyası baytlarını çözer: BOM'lu UTF-16 (Not Defteri "Unicode"), UTF-8, yoksa Türkçe Windows (cp1254).

    Gerçek cp1254 Türkçe metin geçerli UTF-8 olmadığı için yanlış seçilmez; harfler sessizce silinmez.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1254", "replace")


def _read_csv(p: Path) -> str:
    import csv
    text = decode_text(p.read_bytes())               # Türkçe Excel'in kaydettiği CSV cp1254 olur
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    return "\n".join(" | ".join(row) for row in csv.reader(text.splitlines(), dialect) if any(c.strip() for c in row))


def _read_html(p: Path) -> str:
    from html.parser import HTMLParser

    class Text(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts = []; self.skip = 0
        def handle_starttag(self, tag, attrs):
            self.skip += tag in ("script", "style")
        def handle_endtag(self, tag):
            if tag in ("script", "style") and self.skip:
                self.skip -= 1
            elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table"):
                self.parts.append("\n")
        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    parser = Text()
    parser.feed(decode_text(p.read_bytes()))
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def _read_pptx(p: Path) -> str:
    """MarkItDown yoksa: slaytlardaki metin kutuları (ek paket gerekmez)."""
    import html, re, zipfile
    with zipfile.ZipFile(p) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        out = []
        for i, name in enumerate(names, 1):
            xml = z.read(name).decode("utf-8", "replace")
            paras = [" ".join(html.unescape(t) for t in re.findall(r"<a:t>([^<]*)</a:t>", para))
                     for para in re.findall(r"<a:p>.*?</a:p>", xml, re.S)]
            out.append(f"[Slayt {i}]\n" + "\n".join(x for x in paras if x.strip()))
    return "\n\n".join(out)


_CACHE: dict = {}
_CACHE_LOCK = __import__("threading").Lock()


def read_document(path: str, keep_pages: bool = False, cache: bool = False) -> str:
    """Belge metni. keep_pages=True PDF sayfalarını form-feed (\\f) ile ayrı tutar.

    cache=True aynı dosyanın (yol + boyut + değişiklik zamanı) art arda iki kez ayrı süreçte okunmasını önler;
    örn. sohbette özetlenen dosya hemen ardından aranabilir dosyalara eklenirken.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Dosya bulunamadı: {path}")
    if not cache:
        text = _read_raw(p)
    else:
        st = p.stat()
        key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
        with _CACHE_LOCK:
            text = _CACHE.get(key)
        if text is None:
            text = _read_raw(p)
            with _CACHE_LOCK:
                if len(_CACHE) >= 4:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = text
    return text if keep_pages else text.replace("\f", "\n")


_FORMULA_SCAN_ROWS = 5000
_FORMULA_SCAN_COLS = 100


def _clean_excel(text: str, p: Path) -> str:
    """MarkItDown (pandas) boş hücreyi ve kayıtlı sonucu olmayan formülü "NaN" yazar: boş bırakır, formülleri not düşer."""
    text = re.sub(r"(?m)(?<=\| )NaN(?= \|)", "", text)
    text = re.sub(r"(?m)^\|(?: *\|)+ *\n?", "", text)     # tamamen boşalan satır
    notes = []
    try:
        from openpyxl import load_workbook
        values = load_workbook(p, read_only=True, data_only=True)
        formulas = load_workbook(p, read_only=True)
        try:
            for sheet in formulas.worksheets:
                cached = values[sheet.title]
                # sınırlı tarama: boyutu yanlış yazılmış çalışma kitabı (milyon satır) süreyi tüketmesin
                for frow, vrow in zip(sheet.iter_rows(max_row=_FORMULA_SCAN_ROWS, max_col=_FORMULA_SCAN_COLS),
                                      cached.iter_rows(max_row=_FORMULA_SCAN_ROWS, max_col=_FORMULA_SCAN_COLS)):
                    for f, v in zip(frow, vrow):
                        if isinstance(f.value, str) and f.value.startswith("=") and v.value is None:
                            notes.append(f"{sheet.title}!{f.coordinate}")
                            if len(notes) >= 20:
                                raise StopIteration
        finally:
            values.close()
            formulas.close()
    except StopIteration:
        pass
    except Exception:
        _record_failure('modules/docs.py:_clean_excel')   # not eklenemezse metin yine de verilir
    if notes:
        text += ("\n\nNot: şu hücrelerde formül var ama dosyada kayıtlı sonucu yok (Excel'de açıp kaydedince dolar): "
                 + ", ".join(notes))
    return text


_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "themedata",
             "datastore", "latentstyles", "listtable", "listoverridetable", "rsidtbl", "generator"}


def _read_rtf(p: Path) -> str:
    """RTF'yi ek paket olmadan düz metne çevirir (yazı tipi/renk tabloları atlanır, \\'hh ve \\uN çözülür)."""
    import re
    raw = p.read_bytes().decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", raw)
    codec = f"cp{m.group(1)}" if m else "cp1252"
    out, stack, skip_depth, i, n, uc = [], [], None, 0, len(raw), 1
    pending = bytearray()

    def flush():
        if pending:
            out.append(bytes(pending).decode(codec, "replace")); pending.clear()

    while i < n:
        c = raw[i]
        if c == "{":
            stack.append(uc); i += 1
        elif c == "}":
            flush()
            if stack:
                uc = stack.pop()
            if skip_depth is not None and len(stack) < skip_depth:
                skip_depth = None
            i += 1
        elif c == "\\":
            i += 1
            if i >= n:
                break
            c = raw[i]
            if c == "'":
                if skip_depth is None and re.fullmatch(r"[0-9a-fA-F]{2}", raw[i + 1:i + 3]):
                    pending.append(int(raw[i + 1:i + 3], 16))
                i += 3
                continue
            flush()
            if c in "\\{}":
                if skip_depth is None:
                    out.append(c)
                i += 1
            elif c == "*":
                if skip_depth is None:
                    skip_depth = len(stack)
                i += 1
            elif c.isalpha():
                m = re.compile(r"([a-zA-Z]+)(-?\d+)? ?").match(raw, i)
                word, arg = m.group(1), m.group(2)
                i = m.end()
                if word in _RTF_SKIP and skip_depth is None:
                    skip_depth = len(stack)
                elif skip_depth is not None:
                    pass
                elif word in ("par", "line", "sect", "page"):
                    out.append("\n")
                elif word == "tab":
                    out.append("\t")
                elif word == "uc" and arg:
                    uc = int(arg)
                elif word == "u" and arg:
                    cp = int(arg)
                    out.append(chr(cp + 65536 if cp < 0 else cp))
                    i += uc if raw[i:i + 1] == "?" or uc > 1 else 0    # yedek karakteri atla
            else:
                i += 1
        elif c in "\r\n":
            i += 1
        else:
            if skip_depth is None:
                pending.extend(c.encode("latin-1", "replace"))
            i += 1
    flush()
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def _read_odt(p: Path) -> str:
    import zipfile
    from xml.etree import ElementTree
    check_office_file(p)
    try:
        with zipfile.ZipFile(p) as z:
            data = z.read("content.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("Dosya bozuk ya da gerçek bir ODT dosyası değil.") from exc
    root = ElementTree.fromstring(data)
    parts = []

    def walk(node):
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in ("p", "h"):
            parts.append("".join(node.itertext()))
            return
        if tag == "table-row":
            parts.append(" | ".join("".join(c.itertext()) for c in node if c.tag.rsplit("}", 1)[-1] == "table-cell"))
            return
        for child in node:
            walk(child)

    walk(root)
    return "\n".join(x for x in parts if x.strip())


def _read_json(p: Path) -> str:
    import json
    text = decode_text(p.read_bytes())
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text                                # bozuk JSON da düz metin olarak okunur


def _read_raw(p: Path) -> str:
    ext = p.suffix.lower()

    if ext in _LEGACY:
        raise ValueError(f"Eski {_LEGACY[ext]} biçimini ({ext}) okuyamıyorum. Dosyayı {_LEGACY[ext]}'de açıp "
                         f"“{ext}x” olarak kaydet, sonra tekrar dene.")

    if ext == ".pdf":
        # Tüm projede tek PDF okuma yolu: ayrı süreçte okur (arayüzü kilitlemez).
        try:
            return read_pdf_isolated(str(p))
        except RuntimeError as exc:
            if isinstance(exc, PdfReadTimeout) or not any(w in str(exc).casefold() for w in ("decrypt", "password", "encrypt")):
                raise
            raise ValueError("Bu PDF parola korumalı. Parolasız bir kopyasını kaydedip tekrar dene.") from exc

    if ext in _OOXML:
        check_office_file(p)
    if ext in _MARKITDOWN:
        # MarkItDown birincil okuyucu; kurulu değilse ya da çeviremezse aşağıdaki okuyuculara düşülür.
        text = read_markitdown_isolated(str(p))
        if text is not None:
            return _clean_excel(text, p) if ext in (".xlsx", ".xlsm") else text

    if ext == ".docx":
        import docx

        document = docx.Document(str(p))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)

    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook   # makrolar asla çalıştırılmaz; openpyxl yalnız hücre değerini okur

        workbook = load_workbook(p, read_only=True, data_only=True)
        try:
            lines = []
            for sheet in workbook.worksheets:
                lines.append(f"[Sayfa: {sheet.title}]")
                for row in sheet.iter_rows():
                    values = [f"{cell.coordinate}: {cell.value}" for cell in row if cell.value is not None]
                    if values:
                        lines.append(" | ".join(values))
            return "\n".join(lines)
        finally:
            workbook.close()

    if ext == ".pptx":
        return _read_pptx(p)

    if ext == ".csv":
        return _read_csv(p)

    if ext in (".html", ".htm"):
        return _read_html(p)

    if ext in (".txt", ".md"):
        return decode_text(p.read_bytes())

    if ext == ".rtf":
        return _read_rtf(p)

    if ext == ".odt":
        return _read_odt(p)

    if ext == ".json":
        return _read_json(p)

    raise ValueError("PDF, Word, Excel, PowerPoint, CSV, HTML, TXT, MD, RTF, ODT veya JSON dosyası seç.")


def choose_document() -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        path = filedialog.askopenfilename(
            parent=root,
            title="Jarvis için belge seç",
            filetypes=[
                ("Desteklenen belgeler", "*.pdf *.docx *.xlsx *.xlsm *.pptx *.csv *.html *.htm *.txt *.md *.rtf *.odt *.json"),
                ("PDF dosyaları", "*.pdf"),
                ("Word dosyaları", "*.docx"),
                ("Excel dosyaları", "*.xlsx *.xlsm *.csv"),
                ("PowerPoint dosyaları", "*.pptx"),
                ("Metin dosyaları", "*.txt *.md"),
            ],
        )
    finally:
        root.destroy()

    return path or None


def _chunks(text: str, size: int = _CHUNK):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def no_text_message(path: str) -> str:
    """Boş metin çıkan dosya için mesaj; PDF'te mevcut yerel OCR komutunu önerir (kendiliğinden OCR çalıştırmaz)."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return (f"{p.name} içinden okunabilir metin çıkaramadım; taranmış bir görüntü olabilir. Yerel OCR denemek için: "
                f"“\"{p}\" yerel OCR ile oku”.")
    return f"{p.name} içinden okunabilir metin çıkaramadım; dosya boş ya da yalnız görüntüden oluşuyor olabilir."


def _read_text(path: str) -> str:
    text = read_document(path, cache=True).strip()
    if not text:
        raise ValueError(no_text_message(path))
    return text


def summarize(path: str) -> str:
    text = _read_text(path)
    chunks = list(_chunks(text))
    note = ""
    if len(chunks) > _MAX_CHUNKS:
        chunks = chunks[:_MAX_CHUNKS]
        note = f"\n\n(Belge çok uzun; yalnızca ilk {_MAX_CHUNKS * _CHUNK:,} karakter özetlendi.)".replace(",", ".")
    if len(chunks) == 1:
        return ask(f"Bu belgeyi Türkçe, kısa ve net özetle:\n{chunks[0]}") + note
    partial = [ask(f"Bu bölümü kısaca özetle:\n{c}") for c in chunks]
    return ask("Şu kısmi özetleri tek tutarlı Türkçe özette birleştir:\n" + "\n".join(partial)) + note


def insights(path: str, question: str = "") -> str:
    text = _read_text(path)[:40000]
    q = question or "Ana bulgular, riskler, aksiyon maddeleri ve dikkat çeken detaylar neler?"
    return ask(f"Döküman:\n{text}\n\nSoru: {q}\nTürkçe yanıtla.")
