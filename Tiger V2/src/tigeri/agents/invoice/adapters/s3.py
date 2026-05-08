"""S3-backed implementation of InboxAdapter for the Invoice Agent.

Supports both standard S3 buckets and S3 Express One Zone (Directory) buckets.
A directory bucket name has the suffix ``--x-s3`` (e.g.
``trigeri--global--use1-az4--x-s3``). boto3 ≥ 1.35 routes those names to the
correct S3 Express endpoint automatically — we just have to skip parameters
that Directory buckets reject (like ``ServerSideEncryption``, since they
auto-encrypt with SSE-S3).

Uses boto3's default credentials chain so EC2 instance profiles work without
any code changes.
"""

import asyncio
from dataclasses import dataclass

import boto3
from botocore.config import Config

from tigeri.core.config import get_settings


def _is_directory_bucket(bucket: str) -> bool:
    return bucket.endswith("--x-s3")


@dataclass
class S3DocumentRef:
    bucket: str
    key: str

    @classmethod
    def parse(cls, content_ref: str) -> "S3DocumentRef":
        # Accept either ``s3://bucket/key`` or ``s3:bucket:key``
        if content_ref.startswith("s3://"):
            without = content_ref[len("s3://") :]
            bucket, _, key = without.partition("/")
            return cls(bucket=bucket, key=key)
        if content_ref.startswith("s3:"):
            without = content_ref[len("s3:") :]
            bucket, _, key = without.partition(":")
            return cls(bucket=bucket, key=key)
        raise ValueError(f"unsupported s3 ref: {content_ref}")


class S3InboxAdapter:
    """Reads invoice documents from S3 (standard or Directory).

    `bucket` defaults to TIGERI_S3_DOCUMENTS_BUCKET. content_ref formats:
    - ``s3://bucket/key``
    - ``s3:bucket:key``
    - ``key`` (uses default bucket)
    """

    def __init__(self, bucket: str | None = None, region_name: str | None = None) -> None:
        settings = get_settings()
        self._bucket = bucket or settings.s3_documents_bucket
        self._client = boto3.client(
            "s3",
            region_name=region_name or settings.aws_region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    async def fetch_document(self, content_ref: str) -> str:
        body, _ = await self.fetch_bytes(content_ref)
        return body.decode("utf-8")

    async def fetch_bytes(self, content_ref: str) -> tuple[bytes, str]:
        ref = self._resolve(content_ref)
        body, content_type = await asyncio.to_thread(self._get_object_with_type, ref)
        return body, content_type or "application/octet-stream"

    async def put_document(self, key: str, body: bytes, content_type: str) -> S3DocumentRef:
        ref = S3DocumentRef(bucket=self._bucket, key=key)
        params: dict = {
            "Bucket": ref.bucket,
            "Key": ref.key,
            "Body": body,
            "ContentType": content_type,
        }
        # Standard S3 accepts SSE-AES256; Directory buckets auto-encrypt and
        # reject the parameter, so we skip it for them.
        if not _is_directory_bucket(ref.bucket):
            params["ServerSideEncryption"] = "AES256"
        await asyncio.to_thread(self._client.put_object, **params)
        return ref

    async def presign_upload(self, key: str, content_type: str, expires_in: int = 900) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )

    def _resolve(self, content_ref: str) -> S3DocumentRef:
        if content_ref.startswith("s3:"):
            return S3DocumentRef.parse(content_ref)
        if not self._bucket:
            raise ValueError("default bucket not configured (TIGERI_S3_DOCUMENTS_BUCKET)")
        return S3DocumentRef(bucket=self._bucket, key=content_ref)

    def _get_object(self, ref: S3DocumentRef) -> bytes:
        resp = self._client.get_object(Bucket=ref.bucket, Key=ref.key)
        return resp["Body"].read()

    def _get_object_with_type(self, ref: S3DocumentRef) -> tuple[bytes, str]:
        resp = self._client.get_object(Bucket=ref.bucket, Key=ref.key)
        return resp["Body"].read(), resp.get("ContentType", "")
