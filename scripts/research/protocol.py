"""Validated, content-addressed protocol and explicit ephemeris units."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "configs/research_protocol_v1.json"
COHORTS = ("synthetic_fixture", "known_object_control", "archival_pilot", "prospective_search")
STAGES = ("metadata", "selection", "acquisition", "detection", "features", "scoring", "diagnostics", "dossier")
REVIEW_STATUSES = ("unreviewed", "in_review", "on_hold", "follow_up", "rejected")
EVIDENCE_STATES = ("complete", "incomplete", "failed", "not_run")
TIME_OFFSETS = {"BJD_TDB": 0.0, "BTJD": 2457000.0, "BKJD": 2454833.0}
SCALAR_NAMES = ["depth", "symmetry", "odd_even", "bls_snr", "bls_depth", "bls_duration", "bls_period"]
REQUIRED_EVIDENCE = ("lightcurve", "detection", "shared_inputs", "model_score", "transit_diagnostics",
                     "centroid", "contamination", "registry", "controls")
ARTIFACT_MEDIA_TYPES = {"application/json", "text/plain", "text/markdown", "text/csv", "image/png",
                        "image/jpeg", "application/octet-stream"}


class ValidationError(ValueError):
    pass


class ConflictError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Expected finite JSON values") from exc


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def nonempty(value, name, maximum=200, multiline=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 and not (multiline and c in "\n\r\t") for c in value)):
        raise ValidationError(f"{name} must be nonempty text of at most {maximum} characters")
    return value


def identifier(value, name="identifier"):
    nonempty(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
        raise ValidationError(f"Invalid {name}")
    return value


def sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError("Expected a lowercase SHA-256 digest")
    return value


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Timestamp must be ISO-8601 with a timezone") from exc
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def finite_number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValidationError(f"{name} must be finite numeric data")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValidationError(f"{name} is outside the allowed range")
    return float(value)


def ephemeris(period_days, epoch, epoch_system, duration_hours):
    if epoch_system not in TIME_OFFSETS:
        raise ValidationError("epoch_system must be BJD_TDB, BTJD or BKJD (all TDB days)")
    period = finite_number(period_days, "period_days", 1e-8)
    original = finite_number(epoch, "epoch")
    absolute = original + TIME_OFFSETS[epoch_system]
    if not 2000000 < absolute < 3000000:
        raise ValidationError("Epoch is not a plausible absolute BJD TDB after conversion")
    duration = finite_number(duration_hours, "duration_hours", 1e-8)
    if duration >= period * 24:
        raise ValidationError("Duration must be shorter than the period")
    return {"period_days": period, "epoch_original": original, "epoch_system": epoch_system,
            "epoch_bjd_tdb": absolute, "duration_hours": duration}


def validate_protocol(value):
    # Freeze a JSON copy so callers cannot mutate a registered protocol in memory.
    cfg = json.loads(canonical_json(value))
    try:
        if cfg["schema_version"] != 1 or cfg["stages"] != list(STAGES) or cfg["cohorts"] != list(COHORTS):
            raise ValidationError("Unsupported protocol schema, stage order or cohorts")
        identifier(cfg["protocol_id"], "protocol_id")
        limits = cfg["limits"]
        caps = {"cpu_workers": 4, "gpu_devices": 1, "download_workers": 2,
                "download_bytes_total": 2 * 1024 ** 3, "initial_products": 20, "initial_targets": 20,
                "request_timeout_seconds": 60, "request_retries": 2, "stage_max_attempts": 3,
                "stage_lease_seconds": 3600, "metadata_pages_per_poll": 3, "metadata_rows_per_page": 100}
        for name, cap in caps.items():
            if type(limits[name]) is not int or not 1 <= limits[name] <= cap:
                raise ValidationError(f"Pilot limit {name} must be an integer from 1 to {cap}")
        if type(limits["metadata_poll_seconds"]) is not int or limits["metadata_poll_seconds"] < 3600:
            raise ValidationError("Metadata polling must be at least one hour apart")
        if cfg["watcher"]["default_mode"] != "metadata_only" or cfg["watcher"]["automatic_downloads"] is not False:
            raise ValidationError("Foundation protocol defaults to metadata-only polling")
        if (cfg["watcher"]["public_availability_required"] is not True
                or cfg["watcher"]["scheduled_sector_is_release_evidence"] is not False
                or cfg["watcher"]["budget_scope"] != "cumulative_across_restarts_not_per_poll"):
            raise ValidationError("Require observed public availability and cumulative download accounting")
        if cfg["review"]["prospective_search_ready"] is not False:
            raise ValidationError("Prospective readiness has not been validated in this protocol version")
        if cfg["search"]["known_ephemerides_in_blind_search"] is not False:
            raise ValidationError("Blind detection cannot use catalog ephemerides")
        search = cfg["search"]
        low = finite_number(search["period_min_days"], "period_min_days", 0.05)
        finite_number(search["period_max_days"], "period_max_days", low + 0.01, 100)
        for name, cap in {"max_period_grid": 20000, "max_duration_grid": 12,
                          "max_signals_per_target": 3, "max_seconds_per_target": 300}.items():
            if type(search[name]) is not int or not 1 <= search[name] <= cap:
                raise ValidationError(f"Unbounded search setting {name}")
        if type(search["minimum_sampled_events"]) is not int or not 2 <= search["minimum_sampled_events"] <= 10:
            raise ValidationError("At least two sampled events are required by this pilot")
        if cfg["inputs"]["global_shape"] != [200, 3] or cfg["inputs"]["local_shape"] != [100, 3]:
            raise ValidationError("The frozen shared_v1 view contract must be retained")
        if (cfg["inputs"]["contract"] != "shared_v1" or cfg["inputs"]["scalar_names"] != SCALAR_NAMES
                or cfg["inputs"]["canonical_epoch"] != "BJD_TDB" or cfg["inputs"]["offset_days"] != TIME_OFFSETS
                or cfg["inputs"]["period_unit"] != "day" or cfg["inputs"]["duration_unit"] != "hour"
                or cfg["inputs"]["normalization"] != "retain_frozen_training_only_moments_and_hash"):
            raise ValidationError("The feature order, time systems, units and training normalization are frozen")
        if (cfg["research"]["ml_hard_veto"] is not False or cfg["research"]["selection_data"] != "validation_only"
                or cfg["research"]["score_semantics"] != "ranking_evidence_not_planet_confirmation_probability"
                or cfg["interpretation"]["automatic_confirmation"] is not False
                or cfg["interpretation"]["human_review_required"] is not True):
            raise ValidationError("Preserve validation-only selection and the human-review scientific boundary")
        required = cfg["required_evidence"]
        if not isinstance(required, list) or not required or len(required) != len(set(required)):
            raise ValidationError("Required evidence must be a nonempty unique list")
        if not set(REQUIRED_EVIDENCE).issubset(required):
            raise ValidationError("Required diagnostics cannot be silently removed from the pilot checklist")
        for kind in required:
            identifier(kind, "evidence kind")
    except (KeyError, TypeError) as exc:
        raise ValidationError(f"Incomplete protocol: {exc}") from exc
    return cfg


def load_protocol(path=DEFAULT_PROTOCOL):
    return validate_protocol(json.loads(Path(path).read_text()))
