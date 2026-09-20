"""Deterministic identity, ephemeris, and catalog-status assessment."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus


class AssessmentStatus(str, Enum):
    """Conclusions that the catalog checker is allowed to report."""

    CONFIRMED_PLANET = "CONFIRMED_PLANET"
    CONFIRMED_CONTROVERSIAL = "CONFIRMED_CONTROVERSIAL"
    KNOWN_PLANET = "KNOWN_PLANET"
    KNOWN_CANDIDATE = "KNOWN_CANDIDATE"
    KNOWN_FALSE_POSITIVE = "KNOWN_FALSE_POSITIVE"
    KNOWN_FALSE_ALARM = "KNOWN_FALSE_ALARM"
    AMBIGUOUS_ALIAS = "AMBIGUOUS_ALIAS"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    CONFLICTING_RECORDS = "CONFLICTING_RECORDS"
    UNMATCHED = "UNMATCHED"
    INCOMPLETE_LOOKUP = "INCOMPLETE_LOOKUP"


class SourceState(str, Enum):
    """Acquisition state for one catalog snapshot."""

    OK = "OK"
    NOT_MODIFIED = "NOT_MODIFIED"
    CACHED_STALE = "CACHED_STALE"
    UNAVAILABLE = "UNAVAILABLE"
    SCHEMA_ERROR = "SCHEMA_ERROR"


class EphemerisMatch(str, Enum):
    """Relationship between a proposed signal and a catalog ephemeris."""

    DIRECT = "DIRECT"
    HALF_PERIOD_ALIAS = "HALF_PERIOD_ALIAS"
    DOUBLE_PERIOD_ALIAS = "DOUBLE_PERIOD_ALIAS"
    THIRD_PERIOD_ALIAS = "THIRD_PERIOD_ALIAS"
    TRIPLE_PERIOD_ALIAS = "TRIPLE_PERIOD_ALIAS"
    MISMATCH = "MISMATCH"
    INCOMPLETE = "INCOMPLETE"


CURRENT_SOURCE_STATES = {SourceState.OK, SourceState.NOT_MODIFIED}
REQUIRED_SOURCE_IDS = {"exofop_toi", "exofop_ctoi", "nasa_ps"}
CONFIRMED_DISPOSITIONS = {"CONFIRMED", "CP", "KP"}
CANDIDATE_DISPOSITIONS = {"PC", "APC"}
FALSE_POSITIVE_DISPOSITIONS = {"FP"}
FALSE_ALARM_DISPOSITIONS = {"FA"}


def utc_now() -> str:
    """Return a stable UTC timestamp for reports and provenance."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_tic_id(value: Any) -> str:
    """Normalize a TIC identifier without accepting fuzzy host names."""
    text = str(value).strip()
    text = re.sub(r"^TIC\s*", "", text, flags=re.IGNORECASE)
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("tic_id must be a positive integer or a 'TIC <integer>' string")
    return str(int(text))


def _finite_positive(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


@dataclass(frozen=True)
class Candidate:
    """A proposed periodic TESS signal in the BJD-TDB time system."""

    tic_id: str
    period_days: float
    epoch_bjd_tdb: float
    duration_hours: Optional[float] = None
    candidate_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tic_id", normalize_tic_id(self.tic_id))
        object.__setattr__(self, "period_days", _finite_positive(self.period_days, "period_days"))
        object.__setattr__(self, "epoch_bjd_tdb", _finite_positive(self.epoch_bjd_tdb, "epoch_bjd_tdb"))
        if not 2_000_000 <= self.epoch_bjd_tdb <= 3_000_000:
            raise ValueError(
                "epoch_bjd_tdb must be an absolute BJD-TDB value; convert TESS BTJD by adding 2457000"
            )
        if self.duration_hours is not None:
            object.__setattr__(
                self,
                "duration_hours",
                _finite_positive(self.duration_hours, "duration_hours"),
            )
            if self.duration_hours >= self.period_days * 24.0:
                raise ValueError("duration_hours must be shorter than one orbital period")
        if self.candidate_id is not None:
            candidate_id = str(self.candidate_id).strip()
            object.__setattr__(self, "candidate_id", candidate_id or None)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["epoch_time_system"] = "BJD-TDB"
        return result


@dataclass(frozen=True)
class MatchPolicy:
    """Explicit tolerances used for catalog matching."""

    period_relative_tolerance: float = 0.001
    period_absolute_tolerance_days: float = 0.001
    epoch_absolute_tolerance_days: float = 0.05
    epoch_duration_fraction: float = 0.5
    maximum_epoch_tolerance_fraction_of_period: float = 0.05

    def __post_init__(self) -> None:
        values = {
            "period_relative_tolerance": self.period_relative_tolerance,
            "period_absolute_tolerance_days": self.period_absolute_tolerance_days,
            "epoch_absolute_tolerance_days": self.epoch_absolute_tolerance_days,
            "epoch_duration_fraction": self.epoch_duration_fraction,
            "maximum_epoch_tolerance_fraction_of_period": (
                self.maximum_epoch_tolerance_fraction_of_period
            ),
        }
        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("all match-policy tolerances must be finite and positive")
        if self.period_relative_tolerance > 0.1:
            raise ValueError("period_relative_tolerance must not exceed 0.1")
        if self.epoch_duration_fraction > 1.0:
            raise ValueError("epoch_duration_fraction must not exceed 1.0")
        if self.maximum_epoch_tolerance_fraction_of_period > 0.25:
            raise ValueError("maximum epoch tolerance must not exceed one quarter-period")

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogRecord:
    """One normalized signal-level record from an authoritative catalog."""

    source_id: str
    authority: str
    record_id: str
    tic_id: str
    disposition: str
    period_days: Optional[float]
    epoch_bjd_tdb: Optional[float]
    duration_hours: Optional[float]
    row_updated_at: Optional[str]
    evidence_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tic_id", normalize_tic_id(self.tic_id))
        object.__setattr__(self, "disposition", str(self.disposition or "UNKNOWN").upper())


@dataclass
class CatalogSnapshot:
    """A fetched catalog response plus enough metadata to audit it."""

    source_id: str
    authority: str
    endpoint: str
    required_for_unmatched: bool
    state: SourceState
    retrieved_at_utc: str
    records: List[CatalogRecord] = field(default_factory=list)
    catalog_updated_at: Optional[str] = None
    payload_sha256: Optional[str] = None
    etag: Optional[str] = None
    query: Optional[str] = None
    error: Optional[str] = None
    raw_payload: Optional[bytes] = field(default=None, repr=False)

    @property
    def is_current(self) -> bool:
        return self.state in CURRENT_SOURCE_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "authority": self.authority,
            "endpoint": self.endpoint,
            "query": self.query,
            "required_for_unmatched": self.required_for_unmatched,
            "state": self.state.value,
            "retrieved_at_utc": self.retrieved_at_utc,
            "catalog_updated_at": self.catalog_updated_at,
            "payload_sha256": self.payload_sha256,
            "etag": self.etag,
            "matching_record_count": len(self.records),
            "error": self.error,
        }


def _period_tolerance(period_days: float, policy: MatchPolicy) -> float:
    return max(
        policy.period_absolute_tolerance_days,
        policy.period_relative_tolerance * period_days,
    )


def _epoch_tolerance(
    candidate: Candidate,
    record: CatalogRecord,
    policy: MatchPolicy,
) -> float:
    durations = [
        value
        for value in (candidate.duration_hours, record.duration_hours)
        if value is not None
    ]
    duration_tolerance = 0.0
    if durations:
        duration_tolerance = policy.epoch_duration_fraction * max(durations) / 24.0
    uncapped = max(policy.epoch_absolute_tolerance_days, duration_tolerance)
    if record.period_days is None:
        return uncapped
    maximum = (
        policy.maximum_epoch_tolerance_fraction_of_period
        * min(candidate.period_days, record.period_days)
    )
    return min(uncapped, maximum)


def _phase_residual_days(first_epoch: float, second_epoch: float, cycle_days: float) -> float:
    cycles = round((first_epoch - second_epoch) / cycle_days)
    return abs(first_epoch - (second_epoch + cycles * cycle_days))


def compare_ephemeris(
    candidate: Candidate,
    record: CatalogRecord,
    policy: MatchPolicy,
) -> Tuple[EphemerisMatch, Dict[str, Optional[float]]]:
    """Compare periods and epochs while explicitly separating aliases."""
    if record.period_days is None or record.epoch_bjd_tdb is None:
        return EphemerisMatch.INCOMPLETE, {
            "period_difference_days": None,
            "period_tolerance_days": None,
            "epoch_phase_difference_days": None,
            "epoch_tolerance_days": None,
        }

    period_difference = abs(candidate.period_days - record.period_days)
    period_tolerance = _period_tolerance(record.period_days, policy)
    epoch_tolerance = _epoch_tolerance(candidate, record, policy)
    direct_phase_difference = _phase_residual_days(
        candidate.epoch_bjd_tdb,
        record.epoch_bjd_tdb,
        record.period_days,
    )
    metrics = {
        "period_difference_days": period_difference,
        "period_tolerance_days": period_tolerance,
        "epoch_phase_difference_days": direct_phase_difference,
        "epoch_tolerance_days": epoch_tolerance,
    }
    if period_difference <= period_tolerance and direct_phase_difference <= epoch_tolerance:
        return EphemerisMatch.DIRECT, metrics

    aliases = (
        (0.5, EphemerisMatch.HALF_PERIOD_ALIAS),
        (2.0, EphemerisMatch.DOUBLE_PERIOD_ALIAS),
        (1.0 / 3.0, EphemerisMatch.THIRD_PERIOD_ALIAS),
        (3.0, EphemerisMatch.TRIPLE_PERIOD_ALIAS),
    )
    for ratio, match_type in aliases:
        target_period = record.period_days * ratio
        alias_difference = abs(candidate.period_days - target_period)
        alias_tolerance = _period_tolerance(target_period, policy)
        alias_cycle = min(candidate.period_days, record.period_days)
        alias_phase_difference = _phase_residual_days(
            candidate.epoch_bjd_tdb,
            record.epoch_bjd_tdb,
            alias_cycle,
        )
        if alias_difference <= alias_tolerance and alias_phase_difference <= epoch_tolerance:
            metrics.update(
                {
                    "period_difference_days": alias_difference,
                    "period_tolerance_days": alias_tolerance,
                    "epoch_phase_difference_days": alias_phase_difference,
                }
            )
            return match_type, metrics
    return EphemerisMatch.MISMATCH, metrics


def disposition_family(disposition: str) -> str:
    """Reduce source-specific disposition codes to decision families."""
    normalized = str(disposition or "UNKNOWN").upper()
    if normalized in CONFIRMED_DISPOSITIONS:
        return "confirmed"
    if normalized in CANDIDATE_DISPOSITIONS:
        return "candidate"
    if normalized in FALSE_POSITIVE_DISPOSITIONS:
        return "false_positive"
    if normalized in FALSE_ALARM_DISPOSITIONS:
        return "false_alarm"
    return "unknown"


def _match_to_dict(
    snapshot: CatalogSnapshot,
    record: CatalogRecord,
    match_type: EphemerisMatch,
    metrics: Dict[str, Optional[float]],
) -> Dict[str, Any]:
    return {
        "source_id": snapshot.source_id,
        "source_state": snapshot.state.value,
        "source_current": snapshot.is_current,
        "record_id": record.record_id,
        "tic_id": record.tic_id,
        "disposition": record.disposition,
        "disposition_family": disposition_family(record.disposition),
        "identity_match": "TIC_EXACT",
        "ephemeris_match": match_type.value,
        "catalog_period_days": record.period_days,
        "catalog_epoch_bjd_tdb": record.epoch_bjd_tdb,
        "catalog_duration_hours": record.duration_hours,
        "row_updated_at": record.row_updated_at,
        "evidence_url": record.evidence_url,
        "metrics": metrics,
        "metadata": record.metadata,
    }


def _has_conflict(families: Sequence[str]) -> bool:
    groups = set()
    for family in families:
        if family == "confirmed":
            groups.add("planet")
        elif family == "candidate":
            groups.add("candidate")
        elif family in {"false_positive", "false_alarm"}:
            groups.add("rejected")
    return "rejected" in groups and bool(groups.intersection({"planet", "candidate"}))


def _status_for_dispositions(dispositions: Sequence[str]) -> AssessmentStatus:
    families = {disposition_family(value) for value in dispositions}
    if "confirmed" in families:
        return AssessmentStatus.KNOWN_PLANET
    if "false_positive" in families:
        return AssessmentStatus.KNOWN_FALSE_POSITIVE
    if "false_alarm" in families:
        return AssessmentStatus.KNOWN_FALSE_ALARM
    if "candidate" in families:
        return AssessmentStatus.KNOWN_CANDIDATE
    return AssessmentStatus.AMBIGUOUS_MATCH


def _summary(status: AssessmentStatus, direct_ids: Sequence[str]) -> str:
    identifiers = ", ".join(direct_ids) if direct_ids else "the proposed signal"
    messages = {
        AssessmentStatus.CONFIRMED_PLANET: (
            f"NASA Exoplanet Archive currently lists {identifiers} as a confirmed planet "
            "with a matching host and ephemeris."
        ),
        AssessmentStatus.CONFIRMED_CONTROVERSIAL: (
            f"NASA Exoplanet Archive lists {identifiers} as a confirmed planet but marks "
            "the record controversial; human review is required."
        ),
        AssessmentStatus.KNOWN_PLANET: (
            f"ExoFOP currently labels {identifiers} as a confirmed or known planet; "
            "the matching NASA confirmed-planet record was not used for this conclusion."
        ),
        AssessmentStatus.KNOWN_CANDIDATE: (
            f"ExoFOP currently lists {identifiers} as a planet candidate."
        ),
        AssessmentStatus.KNOWN_FALSE_POSITIVE: (
            f"ExoFOP currently lists {identifiers} as a false positive."
        ),
        AssessmentStatus.KNOWN_FALSE_ALARM: (
            f"ExoFOP currently lists {identifiers} as a false alarm."
        ),
        AssessmentStatus.AMBIGUOUS_ALIAS: (
            "A catalog signal on the same TIC matches at a small-integer period harmonic; "
            "human ephemeris review is required."
        ),
        AssessmentStatus.AMBIGUOUS_MATCH: (
            "A same-host catalog record is incomplete or inconsistent with the primary sources; "
            "human review is required."
        ),
        AssessmentStatus.CONFLICTING_RECORDS: (
            "Current authoritative sources disagree for the same host and ephemeris; "
            "no automatic disposition is safe."
        ),
        AssessmentStatus.UNMATCHED: (
            "No matching signal was found in all required current catalog snapshots. "
            "This does not establish novelty or planetary nature."
        ),
        AssessmentStatus.INCOMPLETE_LOOKUP: (
            "At least one required live source could not be checked, so catalog completeness "
            "and novelty cannot be assessed."
        ),
    }
    return messages[status]


def _study_evidence(
    status: AssessmentStatus,
    direct_matches: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    stage_by_status = {
        AssessmentStatus.CONFIRMED_PLANET: "CONFIRMED_IN_NASA_ARCHIVE",
        AssessmentStatus.CONFIRMED_CONTROVERSIAL: "NASA_CONFIRMED_BUT_CONTROVERSIAL",
        AssessmentStatus.KNOWN_PLANET: "PLANET_STATUS_RECORDED_BY_EXOFOP",
        AssessmentStatus.KNOWN_CANDIDATE: "CATALOGED_CANDIDATE",
        AssessmentStatus.KNOWN_FALSE_POSITIVE: "CATALOGED_FALSE_POSITIVE",
        AssessmentStatus.KNOWN_FALSE_ALARM: "CATALOGED_FALSE_ALARM",
        AssessmentStatus.AMBIGUOUS_ALIAS: "AMBIGUOUS_EPHEMERIS",
        AssessmentStatus.AMBIGUOUS_MATCH: "AMBIGUOUS_CATALOG_MATCH",
        AssessmentStatus.CONFLICTING_RECORDS: "CATALOG_CONFLICT",
        AssessmentStatus.UNMATCHED: "NO_PUBLIC_CATALOG_MATCH",
        AssessmentStatus.INCOMPLETE_LOOKUP: "LOOKUP_INCOMPLETE",
    }
    follow_up_values = {
        "imaging_observations": [],
        "spectroscopy_observations": [],
        "time_series_observations": [],
    }
    references = []
    for match in direct_matches:
        metadata = match.get("metadata", {})
        for key in follow_up_values:
            value = metadata.get(key)
            if isinstance(value, int):
                follow_up_values[key].append(value)
        for key in ("paper", "discovery_reference"):
            value = metadata.get(key)
            if value and value not in references:
                references.append(value)
    target_follow_up_counts = {
        key: max(values) if values else None for key, values in follow_up_values.items()
    }
    positive_counts = [value for value in target_follow_up_counts.values() if value and value > 0]
    return {
        "stage": stage_by_status[status],
        "currently_being_studied": "NOT_DETERMINABLE_FROM_PUBLIC_CATALOGS",
        "public_follow_up_recorded": bool(positive_counts or references),
        "target_follow_up_counts": target_follow_up_counts,
        "papers_or_references": references,
        "research_completion_percentage": None,
        "percentage_explanation": (
            "No authoritative catalog defines a research-completion percentage. "
            "Disposition and public follow-up evidence are reported instead."
        ),
    }


def assess_candidate(
    candidate: Candidate,
    snapshots: Iterable[CatalogSnapshot],
    policy: Optional[MatchPolicy] = None,
    generated_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce a fail-closed catalog assessment with evidence and provenance."""
    policy = policy or MatchPolicy()
    ordered_snapshots = sorted(snapshots, key=lambda item: item.source_id)
    source_counts = {
        source_id: sum(item.source_id == source_id for item in ordered_snapshots)
        for source_id in {item.source_id for item in ordered_snapshots}
    }
    duplicate_source_ids = sorted(
        source_id for source_id, count in source_counts.items() if count != 1
    )
    declared_required_ids = {
        item.source_id for item in ordered_snapshots if item.required_for_unmatched
    }
    required_source_ids = REQUIRED_SOURCE_IDS.union(declared_required_ids)
    missing_required_ids = sorted(required_source_ids - set(source_counts))
    required_snapshots = [
        item for item in ordered_snapshots if item.source_id in required_source_ids
    ]
    current_required = [item for item in required_snapshots if item.is_current]
    required_duplicates = sorted(set(duplicate_source_ids).intersection(required_source_ids))
    if (
        not missing_required_ids
        and not required_duplicates
        and len(current_required) == len(required_source_ids)
    ):
        coverage = "COMPLETE"
    elif current_required:
        coverage = "PARTIAL"
    else:
        coverage = "NONE"

    matches: List[Dict[str, Any]] = []
    for snapshot in ordered_snapshots:
        for record in snapshot.records:
            if record.tic_id != candidate.tic_id:
                continue
            match_type, metrics = compare_ephemeris(candidate, record, policy)
            matches.append(_match_to_dict(snapshot, record, match_type, metrics))
    matches.sort(key=lambda item: (item["source_id"], item["record_id"]))

    current_direct = [
        item
        for item in matches
        if item["source_current"] and item["ephemeris_match"] == EphemerisMatch.DIRECT.value
    ]
    exofop_toi_direct = [item for item in current_direct if item["source_id"] == "exofop_toi"]
    exofop_ctoi_direct = [item for item in current_direct if item["source_id"] == "exofop_ctoi"]
    nasa_ps_direct = [
        item
        for item in current_direct
        if item["source_id"] == "nasa_ps" and item["disposition_family"] == "confirmed"
    ]
    nasa_toi_direct = [item for item in current_direct if item["source_id"] == "nasa_toi"]

    direct_toi_ids = {item["record_id"] for item in exofop_toi_direct}
    independent_ctoi_direct = [
        item
        for item in exofop_ctoi_direct
        if not item["metadata"].get("promoted_to_toi")
        or "TOI-" + str(item["metadata"]["promoted_to_toi"]) not in direct_toi_ids
    ]
    primary_exofop = exofop_toi_direct + independent_ctoi_direct
    primary_families = [item["disposition_family"] for item in primary_exofop]
    if nasa_ps_direct:
        primary_families.append("confirmed")
    required_incomplete = coverage != "COMPLETE"

    reason_codes: List[str] = []
    warnings: List[str] = []
    if missing_required_ids:
        warnings.append("Required source snapshots missing: " + ", ".join(missing_required_ids))
    if duplicate_source_ids:
        warnings.append("Duplicate source snapshots supplied: " + ", ".join(duplicate_source_ids))
    if _has_conflict(primary_families):
        status = AssessmentStatus.CONFLICTING_RECORDS
        reason_codes.append("CURRENT_PRIMARY_SOURCES_CONFLICT")
    elif nasa_ps_direct:
        controversial = any(
            str(item["metadata"].get("controversial_flag") or "0").strip().lower()
            in {"1", "true", "yes"}
            for item in nasa_ps_direct
        )
        if controversial:
            status = AssessmentStatus.CONFIRMED_CONTROVERSIAL
            reason_codes.append("NASA_PS_CONTROVERSIAL_DIRECT_EPHEMERIS_MATCH")
        else:
            status = AssessmentStatus.CONFIRMED_PLANET
            reason_codes.append("NASA_PS_DIRECT_EPHEMERIS_MATCH")
        if required_incomplete:
            warnings.append("Some discovery catalogs were unavailable, but current NASA confirmation was found.")
    elif required_incomplete:
        status = AssessmentStatus.INCOMPLETE_LOOKUP
        reason_codes.append("REQUIRED_SOURCE_NOT_CURRENT")
    elif primary_exofop:
        dispositions = [item["disposition"] for item in primary_exofop]
        status = _status_for_dispositions(dispositions)
        source_name = "EXOFOP_TOI" if exofop_toi_direct else "EXOFOP_COMMUNITY_CANDIDATE"
        reason_codes.append(f"{source_name}_DIRECT_EPHEMERIS_MATCH")
    else:
        alias_matches = [
            item
            for item in matches
            if item["source_current"]
            and item["ephemeris_match"]
            in {
                EphemerisMatch.HALF_PERIOD_ALIAS.value,
                EphemerisMatch.DOUBLE_PERIOD_ALIAS.value,
                EphemerisMatch.THIRD_PERIOD_ALIAS.value,
                EphemerisMatch.TRIPLE_PERIOD_ALIAS.value,
            }
        ]
        if alias_matches:
            status = AssessmentStatus.AMBIGUOUS_ALIAS
            reason_codes.append("SMALL_INTEGER_PERIOD_CATALOG_ALIAS")
        elif any(
            item["source_current"]
            and item["ephemeris_match"] == EphemerisMatch.INCOMPLETE.value
            for item in matches
        ):
            status = AssessmentStatus.AMBIGUOUS_MATCH
            reason_codes.append("SAME_HOST_RECORD_HAS_INCOMPLETE_EPHEMERIS")
        elif nasa_toi_direct:
            status = AssessmentStatus.AMBIGUOUS_MATCH
            reason_codes.append("NASA_TOI_MIRROR_ONLY_MATCH")
        else:
            status = AssessmentStatus.UNMATCHED
            reason_codes.append("NO_MATCH_IN_COMPLETE_CURRENT_SOURCES")

    if nasa_toi_direct and primary_exofop:
        mirror_families = {item["disposition_family"] for item in nasa_toi_direct}
        exofop_families = {item["disposition_family"] for item in primary_exofop}
        if mirror_families != exofop_families:
            warnings.append("NASA's weekly TOI mirror differs from current ExoFOP evidence.")
    optional_failures = [
        item.source_id
        for item in ordered_snapshots
        if not item.required_for_unmatched and not item.is_current
    ]
    if optional_failures:
        warnings.append("Optional sources unavailable: " + ", ".join(optional_failures))

    if status in {
        AssessmentStatus.CONFIRMED_PLANET,
        AssessmentStatus.CONFIRMED_CONTROVERSIAL,
    }:
        summary_matches = nasa_ps_direct
    elif status in {
        AssessmentStatus.KNOWN_PLANET,
        AssessmentStatus.KNOWN_CANDIDATE,
        AssessmentStatus.KNOWN_FALSE_POSITIVE,
        AssessmentStatus.KNOWN_FALSE_ALARM,
    }:
        summary_matches = primary_exofop
    elif status == AssessmentStatus.CONFLICTING_RECORDS:
        summary_matches = current_direct
    elif status == AssessmentStatus.AMBIGUOUS_MATCH and nasa_toi_direct:
        summary_matches = nasa_toi_direct
    else:
        summary_matches = []
    summary_ids = sorted({item["record_id"] for item in summary_matches})
    human_review_required = status in {
        AssessmentStatus.CONFIRMED_CONTROVERSIAL,
        AssessmentStatus.KNOWN_CANDIDATE,
        AssessmentStatus.AMBIGUOUS_ALIAS,
        AssessmentStatus.AMBIGUOUS_MATCH,
        AssessmentStatus.CONFLICTING_RECORDS,
        AssessmentStatus.UNMATCHED,
        AssessmentStatus.INCOMPLETE_LOOKUP,
    }
    return {
        "schema_version": "candidate-registry-assessment-v1",
        "generated_at_utc": generated_at_utc or utc_now(),
        "candidate": candidate.to_dict(),
        "status": status.value,
        "coverage": coverage,
        "freshness": "CURRENT" if coverage == "COMPLETE" else "INCOMPLETE",
        "human_review_required": human_review_required,
        "summary": _summary(status, summary_ids),
        "study_evidence": _study_evidence(status, current_direct),
        "reason_codes": reason_codes,
        "warnings": warnings,
        "match_policy": policy.to_dict(),
        "matching_caveat": (
            "The default ephemeris tolerances are conservative triage heuristics, not a "
            "statistical identity proof; a human should inspect uncertainties and transit timing."
        ),
        "sources": [item.to_dict() for item in ordered_snapshots],
        "matches": matches,
        "human_review_urls": {
            "exofop_target": (
                "https://exofop.ipac.caltech.edu/tess/target.php?id=" + candidate.tic_id
            ),
            "tev_search": (
                "https://tev.mit.edu/data/search/?q=" + quote_plus("TIC " + candidate.tic_id)
            ),
        },
        "not_a_discovery_claim": (
            "This report checks current public catalogs. It does not validate, confirm, "
            "or announce a new planet."
        ),
    }
