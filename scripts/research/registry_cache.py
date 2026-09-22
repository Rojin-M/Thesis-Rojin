"""Bounded, immutable catalog bundles reused across proposals on the same TIC.

No Kepler-to-TIC guess is made. Offline/stale snapshots never establish novelty.
The existing registry matcher and its required-source policy remain authoritative.
"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import requests

from scripts.vetting.registry import CatalogRecord, CatalogSnapshot, SourceState, normalize_tic_id
from scripts.vetting.sources import (CatalogClient, EXOFOP_TOI_URL, EXOFOP_CTOI_URL,
                                     parse_exofop_toi, parse_exofop_ctoi)
from .protocol import ROOT, canonical_json, digest, utc_now, ValidationError

MAX_RESPONSE = 16 * 1024 ** 2
MAX_REFRESH_BYTES = 64 * 1024 ** 2
TTL_SECONDS = 24 * 3600


def _atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _age(timestamp):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()


class BoundedCatalogClient(CatalogClient):
    def __init__(self, cache_dir):
        super().__init__(cache_dir, timeout_seconds=10, attempts=2)
        self.downloaded_bytes = 0

    def _request(self, url, **kwargs):
        last = None
        for attempt in range(self.attempts):
            try:
                # Redirects are followed by requests only to the official service's
                # response; the caller cannot supply arbitrary URLs through HTTP.
                with self.session.get(url, timeout=(5, 10), stream=True, **kwargs) as response:
                    response.raise_for_status()
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) > MAX_RESPONSE:
                        raise requests.RequestException("Catalog Content-Length exceeds 16 MiB")
                    parts, size = [], 0
                    began = time.monotonic()
                    for chunk in response.iter_content(65536):
                        size += len(chunk); self.downloaded_bytes += len(chunk)
                        if size > MAX_RESPONSE or self.downloaded_bytes > MAX_REFRESH_BYTES or time.monotonic() - began > 30:
                            raise requests.RequestException("Catalog byte/time budget exceeded")
                        parts.append(chunk)
                    response._content = b"".join(parts)
                    response._content_consumed = True
                    return response
            except (requests.RequestException, ValueError) as exc:
                last = exc
                if attempt + 1 < self.attempts and self.downloaded_bytes < MAX_REFRESH_BYTES:
                    time.sleep(1)
        raise requests.RequestException(str(last))


def _encode(snapshot):
    value = snapshot.to_dict()
    value.pop("matching_record_count", None)
    value["records"] = [asdict(row) for row in snapshot.records]
    return value


def _decode(value, root):
    value = dict(value)
    value["state"] = SourceState(value["state"])
    value["records"] = [CatalogRecord(**row) for row in value["records"]]
    checksum = value["payload_sha256"]
    if checksum:
        if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValidationError("Invalid cached catalog hash")
        path = root / "raw" / checksum
        if not path.is_file() or path.stat().st_size > MAX_RESPONSE:
            raise ValidationError("Cached catalog bytes unavailable or oversized")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise ValidationError("Cached catalog checksum mismatch")
        value["raw_payload"] = payload
    return CatalogSnapshot(**value)


def _legacy_offline(tic):
    client = CatalogClient(ROOT / "data/raw/vetting/registry")
    snapshots = []
    for key, url, parser in (("exofop_toi", EXOFOP_TOI_URL, parse_exofop_toi),
                             ("exofop_ctoi", EXOFOP_CTOI_URL, parse_exofop_ctoi)):
        # The original command uses a cache/ child directory in some reports.
        for directory in (ROOT / "data/raw/vetting/registry", ROOT / "data/raw/vetting/registry/cache"):
            client.cache_dir = directory
            path = directory / (key + ".csv")
            if path.is_file() and path.stat().st_size <= MAX_RESPONSE:
                payload, metadata = client._load_cache(key, url)
                if payload is not None:
                    try:
                        snapshots.append(CatalogSnapshot(key, "ExoFOP-TESS", url, True, SourceState.CACHED_STALE,
                            metadata["retrieved_at_utc"], records=parser(payload, tic), payload_sha256=hashlib.sha256(payload).hexdigest(),
                            raw_payload=payload, error="Legacy snapshot not revalidated by this run"))
                    except (ValueError, KeyError):
                        pass
                    break
    return snapshots


def fetch_bundle(cache_root, tic_id, mode="offline", force=False):
    """Call in bounded_call(seconds=180). One lock serializes refreshes on this host."""
    if mode not in ("offline", "live"):
        raise ValidationError("Catalog mode must be offline or live")
    tic = normalize_tic_id(tic_id)
    root = Path(cache_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pointer = root / ("tic-" + tic + ".json")
    with (root / "refresh.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TimeoutError("Another bounded catalog refresh holds the cache lock; retry later") from exc
        cached, corruption = None, None
        if pointer.is_file():
            try:
                if pointer.stat().st_size > MAX_RESPONSE:
                    raise ValidationError("Catalog bundle exceeds bound")
                envelope = json.loads(pointer.read_text())
                cached = envelope["bundle"]
                if envelope["sha256"] != digest(cached) or cached["tic_id"] != tic:
                    raise ValidationError("Catalog bundle checksum/identity mismatch")
                snapshots = [_decode(s, root) for s in cached["snapshots"]]
                age = _age(cached["checked_at"])
                complete = all(s.is_current for s in snapshots) and len(snapshots) == 4
                ttl = TTL_SECONDS if complete else 15 * 60
                if not force and 0 <= age <= ttl:
                    return {**cached, "snapshots": snapshots, "cache_use": "within_ttl", "downloaded_bytes_this_call": 0}
            except (ValueError, KeyError, OSError) as exc:
                cached, corruption = None, str(exc)
        if mode == "offline":
            if cached is not None:
                snapshots = [replace(s, state=SourceState.CACHED_STALE, error="Snapshot TTL expired; offline mode cannot revalidate")
                             for s in snapshots]
                checked_at = cached["checked_at"]
            else:
                snapshots = _legacy_offline(tic)
                checked_at = None
            return {"schema": 1, "tic_id": tic, "checked_at": checked_at, "snapshots": snapshots,
                    "cache_use": "offline_stale_or_missing", "downloaded_bytes_this_call": 0,
                    "cache_error": corruption, "mode": mode, "ttl_seconds": TTL_SECONDS}
        client = BoundedCatalogClient(root / "conditional")
        snapshots = client.lookup(tic)
        for snapshot in snapshots:
            if snapshot.raw_payload is not None:
                if hashlib.sha256(snapshot.raw_payload).hexdigest() != snapshot.payload_sha256:
                    raise ValidationError("Catalog receipt does not match downloaded bytes")
                raw = root / "raw" / snapshot.payload_sha256
                if not raw.exists():
                    _atomic(raw, snapshot.raw_payload)
        bundle = {"schema": 1, "tic_id": tic, "checked_at": utc_now(), "snapshots": [_encode(s) for s in snapshots],
                  "mode": mode, "ttl_seconds": TTL_SECONDS, "downloaded_bytes": client.downloaded_bytes,
                  "cache_error": corruption, "limits": {"targets_per_call": 1, "attempts_per_source": 2,
                  "max_response_bytes": MAX_RESPONSE, "max_refresh_bytes": MAX_REFRESH_BYTES, "hard_deadline_seconds": 180}}
        envelope = canonical_json({"bundle": bundle, "sha256": digest(bundle)}).encode()
        _atomic(root / "bundles" / (digest(bundle) + ".json"), envelope)
        _atomic(pointer, envelope)
        return {**bundle, "snapshots": snapshots, "cache_use": "refreshed", "downloaded_bytes_this_call": client.downloaded_bytes}
