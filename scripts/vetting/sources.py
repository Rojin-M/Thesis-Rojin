"""Live public-catalog adapters with schema validation and provenance."""
import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from scripts.vetting.registry import (
    CatalogRecord,
    CatalogSnapshot,
    SourceState,
    normalize_tic_id,
    utc_now,
)


EXOFOP_TOI_URL = "https://exofop.ipac.caltech.edu/tess/json/tois.csv"
EXOFOP_CTOI_URL = "https://exofop.ipac.caltech.edu/tess/json/ctois.csv"
NASA_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"


class CatalogSchemaError(ValueError):
    """Raised when an upstream response no longer matches its documented schema."""


def _optional_float(value: Any) -> Optional[float]:
    if value is None or str(value).strip().lower() in {"", "null", "none"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise CatalogSchemaError(f"invalid numeric catalog value: {value!r}") from error
    if not math.isfinite(number):
        raise CatalogSchemaError(f"non-finite numeric catalog value: {value!r}")
    return number


def _optional_positive_float(value: Any, field_name: str) -> Optional[float]:
    number = _optional_float(value)
    if number is not None and number <= 0:
        raise CatalogSchemaError(f"{field_name} must be positive, received {value!r}")
    return number


def _optional_bjd(value: Any, field_name: str) -> Optional[float]:
    number = _optional_positive_float(value, field_name)
    if number is not None and not 2_000_000 <= number <= 3_000_000:
        raise CatalogSchemaError(f"{field_name} is not a plausible absolute BJD: {value!r}")
    return number


def _optional_int(value: Any) -> Optional[int]:
    number = _optional_float(value)
    if number is None:
        return None
    if number < 0 or not number.is_integer():
        raise CatalogSchemaError(f"catalog count must be a non-negative integer: {value!r}")
    return int(number)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _plain_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value))).strip()
    return text or None


def _decode_csv(payload: bytes, required_columns: set) -> csv.DictReader:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CatalogSchemaError("catalog response is not UTF-8 CSV") from error
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    missing = sorted(required_columns - columns)
    if missing:
        raise CatalogSchemaError("catalog CSV is missing columns: " + ", ".join(missing))
    return reader


def parse_exofop_toi(payload: bytes, tic_id: str) -> List[CatalogRecord]:
    """Parse current ExoFOP TOI CSV rows for one exact TIC."""
    required = {
        "TIC ID",
        "TOI",
        "TESS Disposition",
        "TFOPWG Disposition",
        "Epoch (BJD)",
        "Period (days)",
        "Duration (hours)",
        "Date TOI Updated (UTC)",
    }
    records = []
    for row in _decode_csv(payload, required):
        try:
            row_tic_id = normalize_tic_id(row["TIC ID"])
        except ValueError:
            continue
        if row_tic_id != tic_id:
            continue
        raw_identifier = str(row["TOI"]).strip()
        disposition = (
            str(row.get("TFOPWG Disposition") or "").strip()
            or str(row.get("TESS Disposition") or "").strip()
            or "UNKNOWN"
        )
        records.append(
            CatalogRecord(
                source_id="exofop_toi",
                authority="ExoFOP-TESS",
                record_id="TOI-" + raw_identifier,
                tic_id=row_tic_id,
                disposition=disposition,
                period_days=_optional_positive_float(row.get("Period (days)"), "Period (days)"),
                epoch_bjd_tdb=_optional_bjd(row.get("Epoch (BJD)"), "Epoch (BJD)"),
                duration_hours=_optional_positive_float(
                    row.get("Duration (hours)"), "Duration (hours)"
                ),
                row_updated_at=(
                    str(row.get("Date TOI Updated (UTC)") or row.get("Date Modified") or "").strip()
                    or None
                ),
                evidence_url=(
                    "https://exofop.ipac.caltech.edu/tess/target.php?id=" + row_tic_id
                ),
                metadata={
                    "tess_disposition": str(row.get("TESS Disposition") or "").strip() or None,
                    "tfopwg_disposition": (
                        str(row.get("TFOPWG Disposition") or "").strip() or None
                    ),
                    "imaging_observations": _optional_int(row.get("Imaging Observations")),
                    "spectroscopy_observations": _optional_int(
                        row.get("Spectroscopy Observations")
                    ),
                    "time_series_observations": _optional_int(
                        row.get("Time Series Observations")
                    ),
                    "comments": str(row.get("Comments") or "").strip() or None,
                    "source_pipeline": str(row.get("Source") or "").strip() or None,
                },
            )
        )
    return records


def parse_exofop_ctoi(payload: bytes, tic_id: str) -> List[CatalogRecord]:
    """Parse current ExoFOP Community Candidate CSV rows for one exact TIC."""
    required = {
        "TIC ID",
        "CTOI",
        "Promoted to TOI",
        "User Disposition",
        "TFOPWG Disposition",
        "Transit Epoch (BJD)",
        "Period (days)",
        "Duration (hrs)",
        "CTOI Lastmod",
    }
    records = []
    for row in _decode_csv(payload, required):
        try:
            row_tic_id = normalize_tic_id(row["TIC ID"])
        except ValueError:
            continue
        if row_tic_id != tic_id:
            continue
        raw_identifier = str(row["CTOI"]).strip()
        disposition = (
            str(row.get("TFOPWG Disposition") or "").strip()
            or str(row.get("User Disposition") or "").strip()
            or "UNKNOWN"
        )
        records.append(
            CatalogRecord(
                source_id="exofop_ctoi",
                authority="ExoFOP-TESS",
                record_id="CTOI-" + raw_identifier,
                tic_id=row_tic_id,
                disposition=disposition,
                period_days=_optional_positive_float(row.get("Period (days)"), "Period (days)"),
                epoch_bjd_tdb=_optional_bjd(
                    row.get("Transit Epoch (BJD)"), "Transit Epoch (BJD)"
                ),
                duration_hours=_optional_positive_float(
                    row.get("Duration (hrs)"), "Duration (hrs)"
                ),
                row_updated_at=str(row.get("CTOI Lastmod") or "").strip() or None,
                evidence_url=(
                    "https://exofop.ipac.caltech.edu/tess/target.php?id=" + row_tic_id
                ),
                metadata={
                    "user_disposition": str(row.get("User Disposition") or "").strip() or None,
                    "tfopwg_disposition": (
                        str(row.get("TFOPWG Disposition") or "").strip() or None
                    ),
                    "promoted_to_toi": str(row.get("Promoted to TOI") or "").strip() or None,
                    "paper": str(row.get("Paper") or "").strip() or None,
                    "notes": str(row.get("Notes") or "").strip() or None,
                },
            )
        )
    return records


def _decode_json_rows(payload: bytes) -> List[Dict[str, Any]]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogSchemaError("NASA TAP response is not valid JSON") from error
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CatalogSchemaError("NASA TAP response must be a JSON array of records")
    return value


def _validate_json_columns(rows: List[Dict[str, Any]], required_columns: set) -> None:
    if not rows:
        return
    missing = sorted(required_columns - set(rows[0]))
    if missing:
        raise CatalogSchemaError("NASA TAP response is missing columns: " + ", ".join(missing))


def parse_nasa_ps(payload: bytes, tic_id: str, evidence_url: str) -> List[CatalogRecord]:
    """Parse NASA's confirmed-planet rows for one exact TIC."""
    rows = _decode_json_rows(payload)
    required = {"pl_name", "tic_id", "pl_orbper", "pl_tranmid", "rowupdate"}
    _validate_json_columns(rows, required)
    records = []
    for row in rows:
        try:
            row_tic_id = normalize_tic_id(row.get("tic_id"))
        except ValueError:
            continue
        if row_tic_id != tic_id:
            continue
        time_system = str(row.get("pl_tsystemref") or "").strip()
        normalized_time_system = re.sub(r"[^A-Z]", "", time_system.upper())
        time_system_supported = normalized_time_system == "BJDTDB"
        epoch_bjd_tdb = _optional_bjd(row.get("pl_tranmid"), "pl_tranmid")
        if epoch_bjd_tdb is not None and not time_system_supported:
            epoch_bjd_tdb = None
        records.append(
            CatalogRecord(
                source_id="nasa_ps",
                authority="NASA Exoplanet Archive",
                record_id=str(row.get("pl_name") or "unnamed confirmed planet"),
                tic_id=row_tic_id,
                disposition="CONFIRMED",
                period_days=_optional_positive_float(row.get("pl_orbper"), "pl_orbper"),
                epoch_bjd_tdb=epoch_bjd_tdb,
                duration_hours=None,
                row_updated_at=str(row.get("rowupdate") or "").strip() or None,
                evidence_url=evidence_url,
                metadata={
                    "hostname": row.get("hostname"),
                    "time_system": time_system or None,
                    "time_system_supported": time_system_supported,
                    "controversial_flag": row.get("pl_controv_flag"),
                    "discovery_reference": _plain_text(row.get("disc_refname")),
                    "discovery_publication_date": row.get("disc_pubdate"),
                    "release_date": row.get("releasedate"),
                },
            )
        )
    return records


def parse_nasa_toi(payload: bytes, tic_id: str, evidence_url: str) -> List[CatalogRecord]:
    """Parse NASA's weekly TOI mirror rows for one exact TIC."""
    rows = _decode_json_rows(payload)
    required = {"toi", "tid", "tfopwg_disp", "pl_orbper", "pl_tranmid", "rowupdate"}
    _validate_json_columns(rows, required)
    records = []
    for row in rows:
        try:
            row_tic_id = normalize_tic_id(row.get("tid"))
        except ValueError:
            continue
        if row_tic_id != tic_id:
            continue
        records.append(
            CatalogRecord(
                source_id="nasa_toi",
                authority="NASA Exoplanet Archive",
                record_id="TOI-" + str(row.get("toi")),
                tic_id=row_tic_id,
                disposition=str(row.get("tfopwg_disp") or "UNKNOWN"),
                period_days=_optional_positive_float(row.get("pl_orbper"), "pl_orbper"),
                epoch_bjd_tdb=_optional_bjd(row.get("pl_tranmid"), "pl_tranmid"),
                duration_hours=_optional_positive_float(row.get("pl_trandurh"), "pl_trandurh"),
                row_updated_at=str(row.get("rowupdate") or "").strip() or None,
                evidence_url=evidence_url,
                metadata={"ctoi_alias": row.get("ctoi_alias")},
            )
        )
    return records


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class CatalogClient:
    """Fetch current public catalogs and return fail-closed source snapshots."""

    def __init__(
        self,
        cache_dir: Path,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 120.0,
        attempts: int = 3,
        clock: Callable[[], str] = utc_now,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.clock = clock
        self.sleeper = sleeper
        if hasattr(self.session, "headers"):
            self.session.headers.update(
                {"User-Agent": "Thesis-Rojin candidate-registry-checker/1.0"}
            )

    def _request(self, url: str, **kwargs: Any) -> requests.Response:
        last_error = None
        for attempt in range(self.attempts):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < self.attempts:
                        retry_after = response.headers.get("Retry-After", "1")
                        try:
                            delay = min(max(float(retry_after), 0.0), 5.0)
                        except ValueError:
                            delay = 1.0
                        self.sleeper(delay)
                        continue
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt + 1 < self.attempts:
                    self.sleeper(min(2 ** attempt, 5))
        if last_error is not None:
            raise last_error
        raise requests.RequestException("catalog request failed without a response")

    def _cache_paths(self, source_id: str) -> Tuple[Path, Path]:
        return (
            self.cache_dir / f"{source_id}.csv",
            self.cache_dir / f"{source_id}.metadata.json",
        )

    def _load_cache(
        self,
        source_id: str,
        endpoint: str,
    ) -> Tuple[Optional[bytes], Dict[str, Any]]:
        payload_path, metadata_path = self._cache_paths(source_id)
        if not payload_path.is_file() or not metadata_path.is_file():
            return None, {}
        try:
            payload = payload_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, {}
        if metadata.get("source_id") != source_id or metadata.get("endpoint") != endpoint:
            return None, {}
        if metadata.get("payload_sha256") != _sha256(payload):
            return None, {}
        return payload, metadata

    def _save_cache(
        self,
        source_id: str,
        payload: bytes,
        endpoint: str,
        etag: Optional[str],
        last_modified: Optional[str],
        retrieved_at_utc: str,
    ) -> None:
        payload_path, metadata_path = self._cache_paths(source_id)
        metadata = {
            "source_id": source_id,
            "endpoint": endpoint,
            "retrieved_at_utc": retrieved_at_utc,
            "etag": etag,
            "last_modified": last_modified,
            "payload_sha256": _sha256(payload),
        }
        _atomic_write(payload_path, payload)
        _atomic_write(
            metadata_path,
            json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        )

    def _exofop_snapshot(
        self,
        source_id: str,
        authority: str,
        endpoint: str,
        tic_id: str,
        parser: Callable[[bytes, str], List[CatalogRecord]],
    ) -> CatalogSnapshot:
        retrieved_at = self.clock()
        cached_payload, cached_metadata = self._load_cache(source_id, endpoint)
        headers = {}
        if cached_payload is not None:
            if cached_metadata.get("etag"):
                headers["If-None-Match"] = cached_metadata["etag"]
            if cached_metadata.get("last_modified"):
                headers["If-Modified-Since"] = cached_metadata["last_modified"]
        try:
            response = self._request(endpoint, headers=headers)
            if response.status_code == 304:
                if cached_payload is None:
                    raise CatalogSchemaError("server returned 304 without a valid local snapshot")
                payload = cached_payload
                state = SourceState.NOT_MODIFIED
                etag = cached_metadata.get("etag")
                last_modified = cached_metadata.get("last_modified")
            else:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if content_type and "csv" not in content_type:
                    raise CatalogSchemaError("ExoFOP response is not CSV")
                payload = response.content
                state = SourceState.OK
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
            records = parser(payload, tic_id)
            if state == SourceState.OK:
                self._save_cache(
                    source_id,
                    payload,
                    endpoint,
                    etag,
                    last_modified,
                    retrieved_at,
                )
            return CatalogSnapshot(
                source_id=source_id,
                authority=authority,
                endpoint=endpoint,
                required_for_unmatched=True,
                state=state,
                retrieved_at_utc=retrieved_at,
                records=records,
                catalog_updated_at=last_modified,
                payload_sha256=_sha256(payload),
                etag=etag,
                raw_payload=payload,
            )
        except CatalogSchemaError as error:
            return CatalogSnapshot(
                source_id=source_id,
                authority=authority,
                endpoint=endpoint,
                required_for_unmatched=True,
                state=SourceState.SCHEMA_ERROR,
                retrieved_at_utc=retrieved_at,
                error=str(error),
            )
        except requests.RequestException as error:
            return CatalogSnapshot(
                source_id=source_id,
                authority=authority,
                endpoint=endpoint,
                required_for_unmatched=True,
                state=SourceState.UNAVAILABLE,
                retrieved_at_utc=retrieved_at,
                error=f"{type(error).__name__}: {error}",
            )

    def fetch_exofop_toi(self, tic_id: str) -> CatalogSnapshot:
        return self._exofop_snapshot(
            "exofop_toi",
            "ExoFOP-TESS",
            EXOFOP_TOI_URL,
            normalize_tic_id(tic_id),
            parse_exofop_toi,
        )

    def fetch_exofop_ctoi(self, tic_id: str) -> CatalogSnapshot:
        return self._exofop_snapshot(
            "exofop_ctoi",
            "ExoFOP-TESS",
            EXOFOP_CTOI_URL,
            normalize_tic_id(tic_id),
            parse_exofop_ctoi,
        )

    def _nasa_snapshot(
        self,
        source_id: str,
        tic_id: str,
        query: str,
        required_for_unmatched: bool,
        parser: Callable[[bytes, str, str], List[CatalogRecord]],
    ) -> CatalogSnapshot:
        retrieved_at = self.clock()
        try:
            response = self._request(
                NASA_TAP_URL,
                params={"query": query, "format": "json"},
            )
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if content_type and "json" not in content_type:
                raise CatalogSchemaError("NASA TAP response is not JSON")
            payload = response.content
            evidence_url = getattr(response, "url", NASA_TAP_URL)
            records = parser(payload, tic_id, evidence_url)
            updated_dates = sorted(
                record.row_updated_at for record in records if record.row_updated_at
            )
            return CatalogSnapshot(
                source_id=source_id,
                authority="NASA Exoplanet Archive",
                endpoint=evidence_url,
                query=query,
                required_for_unmatched=required_for_unmatched,
                state=SourceState.OK,
                retrieved_at_utc=retrieved_at,
                records=records,
                catalog_updated_at=updated_dates[-1] if updated_dates else None,
                payload_sha256=_sha256(payload),
                raw_payload=payload,
            )
        except CatalogSchemaError as error:
            return CatalogSnapshot(
                source_id=source_id,
                authority="NASA Exoplanet Archive",
                endpoint=NASA_TAP_URL,
                query=query,
                required_for_unmatched=required_for_unmatched,
                state=SourceState.SCHEMA_ERROR,
                retrieved_at_utc=retrieved_at,
                error=str(error),
            )
        except requests.RequestException as error:
            return CatalogSnapshot(
                source_id=source_id,
                authority="NASA Exoplanet Archive",
                endpoint=NASA_TAP_URL,
                query=query,
                required_for_unmatched=required_for_unmatched,
                state=SourceState.UNAVAILABLE,
                retrieved_at_utc=retrieved_at,
                error=f"{type(error).__name__}: {error}",
            )

    def fetch_nasa_ps(self, tic_id: str) -> CatalogSnapshot:
        normalized = normalize_tic_id(tic_id)
        query = (
            "select pl_name,hostname,tic_id,pl_orbper,pl_tranmid,pl_tsystemref,"
            "pl_controv_flag,disc_refname,disc_pubdate,rowupdate,releasedate from ps "
            f"where default_flag=1 and tic_id='TIC {normalized}'"
        )
        return self._nasa_snapshot("nasa_ps", normalized, query, True, parse_nasa_ps)

    def fetch_nasa_toi(self, tic_id: str) -> CatalogSnapshot:
        normalized = normalize_tic_id(tic_id)
        query = (
            "select toi,tid,ctoi_alias,tfopwg_disp,pl_orbper,pl_tranmid,"
            f"pl_trandurh,rowupdate from toi where tid={normalized}"
        )
        return self._nasa_snapshot("nasa_toi", normalized, query, False, parse_nasa_toi)

    def lookup(self, tic_id: str) -> List[CatalogSnapshot]:
        """Query every v1 source; failures remain explicit in the returned list."""
        normalized = normalize_tic_id(tic_id)
        return [
            self.fetch_exofop_toi(normalized),
            self.fetch_exofop_ctoi(normalized),
            self.fetch_nasa_ps(normalized),
            self.fetch_nasa_toi(normalized),
        ]
