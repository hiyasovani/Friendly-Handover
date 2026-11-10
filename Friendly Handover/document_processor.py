from pathlib import Path
import csv
import shutil
import subprocess
import tempfile
import fitz
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

SUPPORTED = {".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".xlsx", ".ppt", ".pptx"}


def _ocr_pdf_page(page):
    """Optional OCR for scanned PDF pages; requires pytesseract and Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return pytesseract.image_to_string(image).strip()
    except Exception:
        return ""


def extract_text(file_path: str, file_type: str = "") -> str:
    """Extract text while retaining page/slide/sheet locations for evidence citations."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        parts = []
        with fitz.open(path) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                page_text = page.get_text("text").strip()
                if len(page_text) < 30:
                    ocr_text = _ocr_pdf_page(page)
                    if len(ocr_text) > len(page_text):
                        page_text = ocr_text
                if page_text:
                    parts.append(f"[Page {page_number}]\n{page_text}")
                else:
                    parts.append(f"[Page {page_number}]\n[No extractable text detected. This page may be blank or require OCR setup.] ")
        return "\n\n".join(parts).strip()
    if suffix in {".doc", ".ppt"}:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            return (f"[The file {path.name} was uploaded and stored, but text extraction "
                    "requires LibreOffice. Install LibreOffice and restart the app to include "
                    "its contents in AI analysis.]")
        target_ext = ".docx" if suffix == ".doc" else ".pptx"
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [soffice, "--headless", "--convert-to", target_ext.lstrip("."),
                 "--outdir", temp_dir, str(path)],
                capture_output=True, text=True, timeout=90, check=False
            )
            converted = Path(temp_dir) / (path.stem + target_ext)
            if result.returncode != 0 or not converted.exists():
                return f"[The file {path.name} was uploaded, but LibreOffice could not convert it for text extraction.]"
            return extract_text(str(converted), target_ext)
    if suffix == ".docx":
        doc = Document(path)
        parts = []
        for number, paragraph in enumerate(doc.paragraphs, start=1):
            if paragraph.text.strip():
                parts.append(f"[Paragraph {number}] {paragraph.text.strip()}")
        for table_number, table in enumerate(doc.tables, start=1):
            parts.append(f"[Table {table_number}]")
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts).strip()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            return "\n".join(f"[Row {i}] " + " | ".join(row) for i, row in enumerate(csv.reader(handle), start=1))
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        parts = []
        for sheet in workbook.worksheets:
            parts.append(f"[Sheet: {sheet.title}]")
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = [str(value) if value is not None else "" for value in row]
                if any(values):
                    parts.append(f"[Row {row_number}] " + " | ".join(values))
        workbook.close()
        return "\n".join(parts).strip()
    if suffix == ".pptx":
        presentation = Presentation(path)
        parts = []
        for number, slide in enumerate(presentation.slides, start=1):
            parts.append(f"[Slide {number}]")
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text.strip():
                    parts.append(shape.text.strip())
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts).strip()
    raise ValueError("Unsupported file type. Use PDF, DOC, DOCX, TXT, MD, CSV, XLSX, PPT or PPTX.")


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    return "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:120] or "upload"
