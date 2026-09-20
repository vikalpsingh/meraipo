from pathlib import Path
from typing import Protocol
from uuid import uuid4

import boto3

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class DocumentStorage(Protocol):
    def put(self, content: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...


def validate(content, content_type):
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document must be between 1 byte and 10 MB")
    if content_type != "application/pdf" or not content.startswith(b"%PDF-"):
        raise ValueError("Only PDF documents are supported")


def safe_key(key):
    from re import fullmatch

    if not fullmatch(r"[a-f0-9]{32}\.pdf", key):
        raise ValueError("Invalid storage key")
    return key


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def put(self, content: bytes, content_type: str) -> str:
        validate(content, content_type)
        self.root.mkdir(parents=True, exist_ok=True)
        key = uuid4().hex + ".pdf"
        (self.root / key).write_bytes(content)
        return key

    def get(self, key: str) -> bytes:
        return (self.root / safe_key(key)).read_bytes()


class S3Storage:
    def __init__(self, bucket: str, endpoint: str | None = None):
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint)

    def put(self, content: bytes, content_type: str) -> str:
        validate(content, content_type)
        key = uuid4().hex + ".pdf"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return key

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=safe_key(key))["Body"].read()
