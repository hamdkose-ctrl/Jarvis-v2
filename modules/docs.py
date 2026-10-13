"""Döküman analizi: PDF/DOCX/XLSX/PPTX/CSV/HTML/TXT oku, özetle, içgörü çıkar."""
from pathlib import Path

from .llm import ask

SUPPORTED = (".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".csv", ".html", ".htm", ".txt", ".md")
_LEGACY = {".doc": "Word", ".xls": "Excel", ".ppt": "PowerPoint"}
_MARKITDOWN = {".docx", ".xlsx", ".xlsm", ".pptx", ".csv", ".html", ".htm"}   # PDF bilerek mevcut okuyucuda kalır
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


def _read_csv(p: Path) -> str:
    import csv
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1254", "replace")      # Türkçe Excel'in kaydettiği CSV
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
    parser.feed(p.read_text(encoding="utf-8", errors="ignore"))
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
            return text

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
        return p.read_text(encoding="utf-8", errors="ignore")

    raise ValueError("PDF, Word, Excel, PowerPoint, CSV, HTML, TXT veya MD dosyası seç.")


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
                ("Desteklenen belgeler", "*.pdf *.docx *.xlsx *.xlsm *.pptx *.csv *.html *.htm *.txt *.md"),
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


def _read_text(path: str) -> str:
    text = read_document(path, cache=True).strip()
    if not text:
        raise ValueError("Dosyadan okunabilir metin çıkaramadım (taranmış bir görüntü olabilir).")
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
