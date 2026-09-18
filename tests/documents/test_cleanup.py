import pytest

from app.documents import service, storage


class _FakeClient:
    """Enough of the S3 client for delete_prefix: a paginator and a bulk delete."""

    def __init__(self, keys: list[str], page_size: int = 2) -> None:
        self.keys = keys
        self.page_size = page_size
        self.deleted: list[str] = []

    def get_paginator(self, name: str) -> "_FakeClient":
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 -- boto3's spelling
        matching = [key for key in self.keys if key.startswith(Prefix)]
        for start in range(0, len(matching), self.page_size):
            yield {
                "Contents": [
                    {"Key": k} for k in matching[start : start + self.page_size]
                ]
            }
        if not matching:
            yield {}

    def delete_objects(self, Bucket: str, Delete: dict) -> dict:  # noqa: N803
        self.deleted += [item["Key"] for item in Delete["Objects"]]
        return {}


@pytest.fixture
def client(monkeypatch) -> _FakeClient:
    fake = _FakeClient(
        [
            "documents/7/a.pdf",
            "documents/7/b.docx",
            "documents/7/c.txt",
            "documents/8/keep.pdf",
        ]
    )
    monkeypatch.setattr(storage, "available", lambda: True)
    monkeypatch.setattr(storage, "_client", lambda: fake)
    return fake


async def test_deleting_an_account_removes_only_its_files(client: _FakeClient) -> None:
    removed = await service.forget_account(7)

    assert removed == 3
    assert sorted(client.deleted) == [
        "documents/7/a.pdf",
        "documents/7/b.docx",
        "documents/7/c.txt",
    ]


async def test_an_account_with_no_files_deletes_nothing(client: _FakeClient) -> None:
    assert await service.forget_account(99) == 0
    assert client.deleted == []


async def test_without_a_bucket_there_is_nothing_to_forget(monkeypatch) -> None:
    # The account still goes; its files were never stored in the first place.
    monkeypatch.setattr(storage, "available", lambda: False)

    assert await service.forget_account(7) == 0
