"""Turn an uploaded file into text the agents can read.

One function, ``parse``, picks an extractor from the file's extension: pymupdf4llm
for PDFs, python-docx for .docx, a decode for plain text formats. Anything else, or
a file that yields no text, raises ``ParseError`` with a message meant for the user.

PDFs come back as Markdown, not a flat dump: pymupdf4llm keeps headings, lists and
tables, which is what lets an agent quote a section or check a claim against the
paragraph it came from. The cost is the licence, AGPL, which the project accepts.

A scanned page carries no text, only a picture of one. Those pages are read by
OCR (RapidOCR, which pymupdf4llm picks up automatically), at about three seconds
a page, so a long scan is refused rather than left running: see ``max_ocr_pages``.
Text that came from OCR is marked as such, because it contains recognition
mistakes the agents should treat with more caution than a digital file.
"""

import io
from dataclasses import dataclass

import pymupdf
import pymupdf4llm
from docx import Document as DocxDocument

from app.core.config import settings

# Enough of a page to count as text rather than a picture of text. A scanned page
# often carries a few characters of metadata or a watermark, so "any text at all"
# is too generous.
_MIN_CHARS_PER_PAGE = 50
_MIN_CHARS = 20

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".rst", ".log"}
SUPPORTED = {".pdf", ".docx", *TEXT_SUFFIXES}


class ParseError(Exception):
    """The file cannot be turned into text. The message is shown to the user."""


@dataclass
class Parsed:
    text: str
    pages: int | None  # PDFs only
    ocr: bool = False  # some pages were read by OCR, so the text may have errors


def suffix_of(filename: str) -> str:
    _, dot, suffix = filename.rpartition(".")
    return f".{suffix.lower()}" if dot else ""


def parse(filename: str, data: bytes) -> Parsed:
    suffix = suffix_of(filename)
    if suffix == ".pdf":
        parsed = _pdf(data)
    elif suffix == ".docx":
        parsed = _docx(data)
    elif suffix in TEXT_SUFFIXES:
        parsed = _plain(data)
    else:
        supported = ", ".join(sorted(SUPPORTED))
        raise ParseError(
            f"{filename} is not a file type Nexus can read. Supported: {supported}."
        )
    if len(parsed.text.strip()) < _MIN_CHARS:
        raise ParseError(f"No text could be read from {filename}.")
    return parsed


def _pdf(data: bytes) -> Parsed:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError("This PDF could not be read; it may be damaged.") from exc

    with document:
        if document.needs_pass:
            # An empty owner password unlocks many "protected" PDFs; a real one
            # cannot be guessed, and nothing can be read from a locked file.
            if not document.authenticate(""):
                raise ParseError("This PDF is password protected.")
        pages = document.page_count
        scanned = _pages_without_text(document)
        if len(scanned) > settings.max_ocr_pages:
            raise ParseError(
                f"This PDF looks scanned and has {len(scanned)} pages of images. "
                f"Scanned documents are read up to {settings.max_ocr_pages} pages."
            )
        try:
            text = pymupdf4llm.to_markdown(document, show_progress=False).strip()
        except Exception as exc:
            raise ParseError("This PDF could not be read; it may be damaged.") from exc

    return Parsed(text=text, pages=pages, ocr=bool(scanned))


def _pages_without_text(document: "pymupdf.Document") -> list[int]:
    """The pages that hold a picture of text rather than text: what OCR will have
    to read, and what makes a document slow."""
    return [
        page.number
        for page in document
        if len(page.get_text().strip()) < _MIN_CHARS_PER_PAGE
    ]


def _docx(data: bytes) -> Parsed:
    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise ParseError("This Word document could not be read.") from exc
    blocks = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return Parsed(text="\n\n".join(blocks), pages=None)


def _plain(data: bytes) -> Parsed:
    # Replaces undecodable bytes rather than failing: a stray byte in an otherwise
    # readable file should not cost the user their upload.
    return Parsed(text=data.decode("utf-8", errors="replace").strip(), pages=None)
