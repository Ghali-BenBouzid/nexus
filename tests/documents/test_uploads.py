import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.documents import storage
from tests.documents.test_parser import _docx, _pdf
from tests.research.test_research import _use_fake_pipeline


@pytest.fixture
def bucket(monkeypatch) -> dict[str, bytes]:
    """A bucket in memory: uploads never reach Cloudflare in the tests."""
    files: dict[str, bytes] = {}

    async def put(key: str, data: bytes, media_type: str) -> None:
        files[key] = data

    async def get(key: str) -> bytes:
        if key not in files:
            raise storage.StorageError("no such key")
        return files[key]

    async def delete(key: str) -> None:
        files.pop(key, None)

    monkeypatch.setattr(storage, "available", lambda: True)
    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(storage, "get", get)
    monkeypatch.setattr(storage, "delete", delete)
    return files


async def _conversation(client: AsyncClient, headers: dict[str, str]) -> int:
    # Uploads are about documents, not research: a scripted pipeline keeps the
    # conversation's first turn from needing a real provider.
    _use_fake_pipeline(sub_questions=["q1"])
    response = await client.post(
        "/conversations", json={"prompt": "hello"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(name: str, data: bytes, media_type: str) -> dict:
    return {"file": (name, data, media_type)}


async def test_uploading_a_pdf_keeps_its_text_and_its_file(
    client: AsyncClient, auth_headers: dict[str, str], bucket: dict[str, bytes]
) -> None:
    conversation_id = await _conversation(client, auth_headers)
    pdf = _pdf(pages=2)

    response = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("heat-pumps.pdf", pdf, "application/pdf"),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    document = response.json()
    assert document["filename"] == "heat-pumps.pdf"
    assert document["pages"] == 2
    assert document["chars"] > 0
    assert not document["truncated"]
    # The original is in the bucket, and comes back byte for byte.
    assert list(bucket.values()) == [pdf]
    download = await client.get(
        f"/documents/{document['id']}/file", headers=auth_headers
    )
    assert download.status_code == 200
    assert download.content == pdf


async def test_the_conversation_lists_what_is_attached_to_it(
    client: AsyncClient, auth_headers: dict[str, str], bucket: dict[str, bytes]
) -> None:
    conversation_id = await _conversation(client, auth_headers)
    await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload(
            "notes.md", b"# Notes\n\nWorth keeping, at length.", "text/markdown"
        ),
        headers=auth_headers,
    )

    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    listing = await client.get(
        f"/conversations/{conversation_id}/documents", headers=auth_headers
    )

    assert [d["filename"] for d in detail.json()["documents"]] == ["notes.md"]
    assert [d["filename"] for d in listing.json()] == ["notes.md"]


async def test_an_unreadable_file_is_refused_with_a_reason(
    client: AsyncClient, auth_headers: dict[str, str], bucket: dict[str, bytes]
) -> None:
    conversation_id = await _conversation(client, auth_headers)

    response = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("deck.pptx", b"whatever", "application/vnd.ms-powerpoint"),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "not a file type" in response.json()["detail"]
    assert bucket == {}  # nothing is stored for a file that could not be read


async def test_a_file_over_the_size_limit_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    bucket: dict[str, bytes],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 0.001)
    conversation_id = await _conversation(client, auth_headers)

    response = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("big.txt", b"x" * 5000, "text/plain"),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "larger than" in response.json()["detail"]


async def test_long_text_is_cut_and_says_so(
    client: AsyncClient,
    auth_headers: dict[str, str],
    bucket: dict[str, bytes],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_document_chars", 100)
    conversation_id = await _conversation(client, auth_headers)

    response = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("long.txt", b"word " * 500, "text/plain"),
        headers=auth_headers,
    )

    assert response.json()["chars"] == 100
    assert response.json()["truncated"]


async def test_a_conversation_stops_accepting_documents_at_the_limit(
    client: AsyncClient,
    auth_headers: dict[str, str],
    bucket: dict[str, bytes],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_documents_per_conversation", 1)
    conversation_id = await _conversation(client, auth_headers)
    first = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload(
            "one.txt", b"The first document, long enough to read.", "text/plain"
        ),
        headers=auth_headers,
    )
    assert first.status_code == 201

    second = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload(
            "two.txt", b"The second document, long enough to read.", "text/plain"
        ),
        headers=auth_headers,
    )

    assert second.status_code == 400
    assert "already has 1 documents" in second.json()["detail"]


async def test_deleting_a_document_removes_its_file_too(
    client: AsyncClient, auth_headers: dict[str, str], bucket: dict[str, bytes]
) -> None:
    conversation_id = await _conversation(client, auth_headers)
    created = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload(
            "report.docx",
            _docx(["A paragraph long enough to keep."]),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        headers=auth_headers,
    )
    document_id = created.json()["id"]

    response = await client.delete(f"/documents/{document_id}", headers=auth_headers)

    assert response.status_code == 204
    assert bucket == {}
    listing = await client.get(
        f"/conversations/{conversation_id}/documents", headers=auth_headers
    )
    assert listing.json() == []


async def test_someone_elses_document_is_not_reachable(
    client: AsyncClient, auth_headers: dict[str, str], bucket: dict[str, bytes]
) -> None:
    from tests.accounts import login_as

    conversation_id = await _conversation(client, auth_headers)
    created = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("mine.txt", b"Private notes, long enough to read.", "text/plain"),
        headers=auth_headers,
    )
    other = await login_as(client, "Someone else")

    assert (
        await client.get(f"/documents/{created.json()['id']}/file", headers=other)
    ).status_code == 404
    assert (
        await client.delete(f"/documents/{created.json()['id']}", headers=other)
    ).status_code == 404
    assert (
        await client.get(f"/conversations/{conversation_id}/documents", headers=other)
    ).status_code == 404


async def test_uploads_are_refused_when_no_bucket_is_configured(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setattr(storage, "available", lambda: False)
    conversation_id = await _conversation(client, auth_headers)

    response = await client.post(
        f"/conversations/{conversation_id}/documents",
        files=_upload("notes.txt", b"Some notes, long enough to read.", "text/plain"),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]
