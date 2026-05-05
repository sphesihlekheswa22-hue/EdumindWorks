import io
import mimetypes
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from flask import current_app


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int
    content_type: str


def _cfg() -> Tuple[str, str, str]:
    """
    Returns (url, service_key, bucket).
    Uses service role key so the server can upload/download privately.
    """
    url = (current_app.config.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (current_app.config.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    bucket = (current_app.config.get("SUPABASE_STORAGE_BUCKET") or "uploads").strip()
    return url, key, bucket


def enabled() -> bool:
    url, key, bucket = _cfg()
    return bool(url and key and bucket)


def _headers() -> dict:
    url, key, _ = _cfg()
    if not url or not key:
        return {}
    # Supabase requires both Authorization and apikey headers.
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }


def _storage_base_url() -> str:
    url, key, _ = _cfg()
    if not url or not key:
        return ""
    return f"{url}/storage/v1"


def make_ref(key: str, bucket: Optional[str] = None) -> str:
    """Store in DB as a stable reference string."""
    _, _, default_bucket = _cfg()
    b = bucket or default_bucket
    return f"supabase://{b}/{key.lstrip('/')}"


def parse_ref(ref: str) -> Optional[Tuple[str, str]]:
    if not ref:
        return None
    s = str(ref).strip()
    if not s.startswith("supabase://"):
        return None
    rest = s[len("supabase://") :]
    if "/" not in rest:
        return None
    bucket, key = rest.split("/", 1)
    bucket = bucket.strip()
    key = key.strip().lstrip("/")
    if not bucket or not key:
        return None
    return bucket, key


def put_bytes(key: str, data: bytes, content_type: Optional[str] = None, bucket: Optional[str] = None) -> StoredObject:
    url, svc_key, default_bucket = _cfg()
    if not url or not svc_key:
        raise RuntimeError("Supabase storage not configured")
    b = bucket or default_bucket
    ct = content_type or (mimetypes.guess_type(key)[0] or "application/octet-stream")
    base = _storage_base_url()
    endpoint = f"{base}/object/{b}/{key.lstrip('/')}"

    resp = requests.post(
        endpoint,
        params={"upsert": "true"},
        headers={**_headers(), "Content-Type": ct},
        data=data,
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase upload failed ({resp.status_code}): {resp.text[:300]}")

    return StoredObject(bucket=b, key=key.lstrip("/"), size_bytes=len(data), content_type=ct)


def get_bytes(ref_or_key: str, bucket: Optional[str] = None) -> bytes:
    url, svc_key, default_bucket = _cfg()
    if not url or not svc_key:
        raise RuntimeError("Supabase storage not configured")

    parsed = parse_ref(ref_or_key)
    if parsed:
        b, key = parsed
    else:
        b = bucket or default_bucket
        key = str(ref_or_key).lstrip("/")

    base = _storage_base_url()
    endpoint = f"{base}/object/{b}/{key}"
    resp = requests.get(endpoint, headers=_headers(), timeout=60)
    if resp.status_code == 404:
        raise FileNotFoundError(f"Missing object: {b}/{key}")
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase download failed ({resp.status_code}): {resp.text[:300]}")
    return resp.content


def delete(ref_or_key: str, bucket: Optional[str] = None) -> None:
    url, svc_key, default_bucket = _cfg()
    if not url or not svc_key:
        return

    parsed = parse_ref(ref_or_key)
    if parsed:
        b, key = parsed
    else:
        b = bucket or default_bucket
        key = str(ref_or_key).lstrip("/")

    base = _storage_base_url()
    endpoint = f"{base}/object/{b}/{key}"
    resp = requests.delete(endpoint, headers=_headers(), timeout=60)
    if resp.status_code in (404, 200, 204):
        return
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase delete failed ({resp.status_code}): {resp.text[:300]}")

