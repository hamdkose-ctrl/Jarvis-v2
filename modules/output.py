from modules.diagnostics import record_failure as _record_failure
import os
from pathlib import Path
import re


def _save_path(source_path: str | None, label: str, excel_only: bool = False, preferred: str | None = None):
    from tkinter import Tk, filedialog   # pencere gerektiğinde yüklenir

    source = Path(source_path) if source_path else None
    stem = source.stem if source else "Jarvis"
    safe_label = re.sub(r"[^\w-]+", "_", label, flags=re.UNICODE)

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        if excel_only or preferred == "xlsx":
            path = filedialog.asksaveasfilename(
                parent=root,
                title="Excel dosyasını kaydet",
                initialfile=f"{stem}_{safe_label}.xlsx",
                defaultextension=".xlsx",
                filetypes=[("Excel çalışma kitabı", "*.xlsx")],
            )
        elif preferred == "docx":
            path = filedialog.asksaveasfilename(
                parent=root, title="Word dosyasını kaydet", initialfile=f"{stem}_{safe_label}.docx",
                defaultextension=".docx", filetypes=[("Word dosyası", "*.docx")])
        elif preferred == "pdf":
            path = filedialog.asksaveasfilename(
                parent=root, title="PDF dosyasını kaydet", initialfile=f"{stem}_{safe_label}.pdf",
                defaultextension=".pdf", filetypes=[("PDF dosyası", "*.pdf")])
        else:
            path = filedialog.asksaveasfilename(
                parent=root,
                title="Jarvis sonucunu kaydet",
                initialfile=f"{stem}_{safe_label}",
                defaultextension=".docx",
                filetypes=[
                    ("Word dosyası", "*.docx"),
                    ("PDF dosyası", "*.pdf"),
                    ("Excel dosyası", "*.xlsx"),
                ],
            )
    finally:
        root.destroy()

    if not path:
        return None

    # Eğer kullanıcı uzantı yazmadıysa varsayılanı ekle
    path_obj = Path(path)
    if not path_obj.suffix:
        path_obj = path_obj.with_suffix(".xlsx" if excel_only else "." + (preferred or "docx"))
        path = str(path_obj)

    if source and path_obj.resolve() == source.resolve():
        raise ValueError("Sonucu kaynak dosyanın üzerine kaydetme; farklı bir dosya adı seç.")

    return path


def choose_excel_translation_path(source_path: str, target: str):
    return _save_path(source_path, f"{target}_ceviri", excel_only=True)


def save_text_result(text: str, source_path: str | None, label: str, preferred: str | None = None):
    path = _save_path(source_path, label, preferred=preferred)
    if not path:
        return None

    from modules.conversion import save_text
    save_text(text, path, label)
    return path


def convert_document(source_path: str, preferred: str):
    """Convert the document itself, not a flattened read_document string."""
    path = _save_path(source_path, 'donusturulmus', preferred=preferred)
    if not path:
        return None
    from modules.conversion import convert
    result = convert(source_path, path)
    return result
