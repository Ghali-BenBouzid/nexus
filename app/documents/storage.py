"""The bucket the original uploads live in (Cloudflare R2, over the S3 API).

Only the file bytes go here; their text goes in the database, because that is
what the agents read. Keeping the original means the interface can show the real
document beside what was said about it, and a better parser can revisit it later.

boto3 is synchronous, so each call runs in a worker thread. Configuration is
optional: with no bucket configured ``available()`` is False and uploads are
refused with a clear error instead of failing deep inside a request.
"""

import asyncio
import uuid
from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


class StorageError(Exception):
    """The bucket could not be reached, or refused the operation."""


def available() -> bool:
    return bool(
        settings.r2_bucket
        and settings.r2_endpoint_url
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
    )


@cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # R2 ignores regions but the SDK insists on one; "auto" is what it wants.
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def key_for(user_id: int, filename: str) -> str:
    """A unique key, namespaced by owner. The name is not taken from the user's
    filename: it could collide, or carry path separators."""
    from app.documents.parser import suffix_of

    return f"documents/{user_id}/{uuid.uuid4().hex}{suffix_of(filename)}"


async def put(key: str, data: bytes, media_type: str) -> None:
    await _run(
        lambda: _client().put_object(
            Bucket=settings.r2_bucket, Key=key, Body=data, ContentType=media_type
        )
    )


async def get(key: str) -> bytes:
    response = await _run(
        lambda: _client().get_object(Bucket=settings.r2_bucket, Key=key)
    )
    return await asyncio.to_thread(response["Body"].read)


async def delete(key: str) -> None:
    await _run(lambda: _client().delete_object(Bucket=settings.r2_bucket, Key=key))


async def _run(call):
    if not available():
        raise StorageError("File storage is not configured.")
    try:
        return await asyncio.to_thread(call)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"File storage failed: {exc}") from exc
