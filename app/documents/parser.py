"""Turn an uploaded file into text the agents can read.

One function, ``parse``, picks an extractor from the file's extension: pypdf for
PDFs, python-docx for .docx, a decode for plain text formats. Anything else, or a
file that yields no text, raises ``ParseError`` with a message meant for the user.

A scanned PDF is the common case that yields nothing: its pages are images, and
no amount of parsing finds words in them. It is refused rather than stored empty,
so no agent ever answers from a document that turned out to be blank.
"""

import io
from dataclasses import dataclass

import pypdf
from docx import Document as DocxDocument

# Enough of a page to count as real text. A scanned PDF often carries a few
# characters of metadata or a watermark, so "any text at all" is too generous.
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
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An empty user password unlocks many "protected" PDFs; a real one
            # cannot be guessed, and pypdf reads nothing from a locked file.
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ParseError("This PDF is password protected.") from exc
        pages = [page.extract_text() or "" for page in reader.pages]
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("This PDF could not be read; it may be damaged.") from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if pages and len(text) < _MIN_CHARS_PER_PAGE * len(pages):
        raise ParseError(
            "This PDF looks scanned: its pages are images, with no text to read. "
            "Reading scanned documents is not supported yet."
        )
    return Parsed(text=text, pages=len(pages))


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
