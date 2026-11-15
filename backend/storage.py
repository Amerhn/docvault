"""Storage service (Figure 3.6).

Two interchangeable backends with the same methods:
  * S3Storage    - Amazon S3 bucket with Versioning (and Object Lock), through boto3.
  * LocalStorage - keeps every version in a folder. For development and tests, no AWS needed.

Neither backend has a method that deletes or overwrites a version: the application cannot do it.
"""
import base64
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional
from urllib.parse import quote


class StorageError(Exception):
    pass


class LocalStorage:
    name = "local"

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, key: str) -> Path:
        d = self.root / base64.urlsafe_b64encode(key.encode()).decode()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write(self, key: str, version_id: str, data: bytes, metadata: Dict[str, str]) -> None:
        d = self._dir(key)
        (d / (version_id + ".bin")).write_bytes(data)
        info = {"key": key, "size": len(data), "metadata": metadata,
                "last_modified": datetime.now(timezone.utc).isoformat()}
        (d / (version_id + ".json")).write_text(json.dumps(info))

    def put_object(self, key: str, data: bytes, metadata: Optional[Dict[str, str]] = None) -> str:
        version_id = uuid.uuid4().hex
        self._write(key, version_id, data, dict(metadata or {}))
        return version_id

    def copy_version(self, key: str, source_version_id: str, metadata: Optional[Dict[str, str]] = None) -> str:
        data = self.read_version(key, source_version_id)
        version_id = uuid.uuid4().hex
        self._write(key, version_id, data, dict(metadata or {}))
        return version_id

    def read_version(self, key: str, version_id: str) -> bytes:
        path = self._dir(key) / (version_id + ".bin")
        if not path.exists():
            raise StorageError("That version was not found in storage.")
        return path.read_bytes()

    def head_version(self, key: str, version_id: str) -> Dict[str, str]:
        path = self._dir(key) / (version_id + ".json")
        if not path.exists():
            raise StorageError("That version was not found in storage.")
        return json.loads(path.read_text())["metadata"]

    def list_object_versions(self) -> Iterator[dict]:
        for info_path in self.root.glob("*/*.json"):
            info = json.loads(info_path.read_text())
            yield {"key": info["key"], "version_id": info_path.stem, "size": info["size"],
                   "last_modified": datetime.fromisoformat(info["last_modified"])}

    def presigned_url(self, key: str, version_id: str, filename: str, expires: int = 300) -> Optional[str]:
        return None  # no temporary links locally; the API serves the bytes instead


class S3Storage:
    name = "s3"

    def __init__(self, bucket: str, region: Optional[str] = None, endpoint_url: Optional[str] = None):
        if not bucket:
            raise StorageError("S3_BUCKET is not set.")
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as exc:  # pragma: no cover
            raise StorageError("boto3 is not installed. Run: pip install boto3") from exc
        self._errors = (BotoCoreError, ClientError)
        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def _call(self, fn, **kwargs):
        try:
            return fn(**kwargs)
        except self._errors as exc:
            raise StorageError("Storage error: %s" % exc) from exc

    def put_object(self, key: str, data: bytes, metadata: Optional[Dict[str, str]] = None) -> str:
        resp = self._call(self.client.put_object, Bucket=self.bucket, Key=key, Body=data, Metadata=metadata or {})
        version_id = resp.get("VersionId")
        if not version_id or version_id == "null":
            raise StorageError("Versioning is not enabled on the bucket. Run scripts/setup_s3.py first.")
        return version_id

    def copy_version(self, key: str, source_version_id: str, metadata: Optional[Dict[str, str]] = None) -> str:
        resp = self._call(
            self.client.copy_object,
            Bucket=self.bucket, Key=key,
            CopySource={"Bucket": self.bucket, "Key": key, "VersionId": source_version_id},
            Metadata=metadata or {}, MetadataDirective="REPLACE",
        )
        version_id = resp.get("VersionId")
        if not version_id:
            raise StorageError("S3 did not return a version identifier for the copy.")
        return version_id

    def read_version(self, key: str, version_id: str) -> bytes:
        resp = self._call(self.client.get_object, Bucket=self.bucket, Key=key, VersionId=version_id)
        return resp["Body"].read()

    def read_latest(self, key: str) -> Optional[bytes]:
        """The newest version of a key, or None if it does not exist (used for the database backup)."""
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self._errors:
            return None

    def head_version(self, key: str, version_id: str) -> Dict[str, str]:
        resp = self._call(self.client.head_object, Bucket=self.bucket, Key=key, VersionId=version_id)
        return resp.get("Metadata", {})

    def list_object_versions(self) -> Iterator[dict]:
        paginator = self.client.get_paginator("list_object_versions")
        try:
            for page in paginator.paginate(Bucket=self.bucket):
                for v in page.get("Versions", []):          # delete markers are ignored
                    yield {"key": v["Key"], "version_id": v["VersionId"], "size": v["Size"],
                           "last_modified": v["LastModified"]}
        except self._errors as exc:
            raise StorageError("Storage error: %s" % exc) from exc

    def presigned_url(self, key: str, version_id: str, filename: str, expires: int = 300) -> Optional[str]:
        disposition = "attachment; filename*=UTF-8''%s" % quote(filename)
        return self._call(
            self.client.generate_presigned_url, ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key, "VersionId": version_id,
                    "ResponseContentDisposition": disposition},
            ExpiresIn=expires,
        )


def make_storage(settings):
    if settings.storage_backend == "s3":
        return S3Storage(settings.s3_bucket, settings.aws_region, settings.s3_endpoint_url)
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_store_dir)
    raise StorageError("STORAGE_BACKEND must be 'local' or 's3'.")
