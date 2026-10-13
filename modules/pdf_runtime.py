"""Keep all PDFium work serialized and file names outside its native path API."""
from contextlib import contextmanager, nullcontext
from pathlib import Path
import threading

_LOCK = threading.RLock()


class PdfReadError(ValueError):
    pass


@contextmanager
def open_pdf(path):
    # PDFium disallows concurrent calls even for separate documents.
    with _LOCK:
        import pypdfium2 as pdfium
        input_context = nullcontext(path) if isinstance(path, bytes) else Path(path).open('rb')
        with input_context as stream:
            try:
                with pdfium.PdfDocument(stream) as document:
                    yield document
            except pdfium.PdfiumError as exc:
                reason = 'PDF şifreli; şifresiz bir kopya gerekli.' if exc.err_code == 4 else 'PDF okuyucusu bu dosyanın sayfa görünümünü açamadı.'
                raise PdfReadError(reason) from exc
