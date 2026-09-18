import io

import pytest
from docx import Document as DocxDocument

from app.documents.parser import ParseError, parse

# A minimal one-page PDF with a text object, written by hand so the test needs no
# PDF writer. Enough for pypdf to extract "Heat pumps move heat, they do not ..."
_TEXT = (
    "Heat pumps move heat instead of making it, which is why they can deliver "
    "more energy than they consume."
)


def _pdf(text: str = _TEXT, pages: int = 1) -> bytes:
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(pages)]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")
    objects.append(
        f"2 0 obj<</Type/Pages/Count {pages}/Kids[{kids}]>>endobj\n".encode()
    )
    objects.append(b"3 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n")
    for index, pid in enumerate(page_ids):
        stream = f"BT /F1 12 Tf 72 720 Td ({text} page {index + 1}) Tj ET".encode()
        objects.append(
            (
                f"{pid} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
                f"/Resources<</Font<</F1 3 0 R>>>>/Contents {pid + 1} 0 R>>endobj\n"
            ).encode()
        )
        objects.append(
            f"{pid + 1} 0 obj<</Length {len(stream)}>>stream\n".encode()
            + stream
            + b"\nendstream endobj\n"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(out))
        out += obj
    start = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer<</Size {count}/Root 1 0 R>>\nstartxref\n{start}\n%%EOF\n".encode()
    return bytes(out)


def _scanned_pdf() -> bytes:
    """A valid PDF whose pages carry no real text: what a scan looks like to a
    parser, which finds a stray label at most."""
    return _pdf(text="", pages=2)


def _docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    document = DocxDocument()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        added = document.add_table(rows=len(table), cols=len(table[0]))
        for row, values in zip(added.rows, table, strict=True):
            for cell, value in zip(row.cells, values, strict=True):
                cell.text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_pdf_gives_its_text_and_page_count() -> None:
    parsed = parse("report.pdf", _pdf(pages=2))

    assert "Heat pumps move heat" in parsed.text
    assert "page 2" in parsed.text
    assert parsed.pages == 2


def test_a_scanned_pdf_is_refused_and_says_why() -> None:
    # It parses fine and yields almost nothing: the failure a user must understand.
    with pytest.raises(ParseError, match="scanned"):
        parse("scan.pdf", _scanned_pdf())


def test_a_damaged_pdf_is_refused() -> None:
    with pytest.raises(ParseError, match="could not be read"):
        parse("broken.pdf", b"%PDF-1.4\nnot really a pdf")


def test_a_word_document_gives_its_paragraphs_and_tables() -> None:
    data = _docx(
        ["The rules of the tender are set out below." * 2],
        table=[["Criterion", "Weight"], ["Price", "40%"]],
    )

    parsed = parse("tender.docx", data)

    assert "The rules of the tender" in parsed.text
    assert "Criterion | Weight" in parsed.text
    assert "Price | 40%" in parsed.text
    assert parsed.pages is None


def test_plain_text_survives_a_stray_byte() -> None:
    parsed = parse("notes.md", b"# Notes\n\nSomething worth keeping." + b"\xff")

    assert parsed.text.startswith("# Notes")


def test_an_unsupported_type_is_named_in_the_error() -> None:
    with pytest.raises(ParseError, match="not a file type"):
        parse("slides.pptx", b"whatever")


def test_a_file_with_no_readable_text_is_refused() -> None:
    with pytest.raises(ParseError, match="No text"):
        parse("empty.txt", b"  \n ")
