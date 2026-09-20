"""Command-line entry point for a current, evidence-backed candidate check."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, Optional

from scripts.paths import ROOT
from scripts.vetting.registry import Candidate, MatchPolicy, assess_candidate, utc_now
from scripts.vetting.sources import CatalogClient


DEFAULT_CACHE_DIR = ROOT / "data" / "raw" / "vetting" / "registry" / "cache"
DEFAULT_SNAPSHOT_ROOT = ROOT / "data" / "raw" / "vetting" / "registry" / "snapshots"
DEFAULT_REPORT_ROOT = ROOT / "outputs" / "vetting"


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


def _run_id(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def persist_source_snapshots(
    snapshots: Iterable,
    destination: Path,
) -> Path:
    """Write immutable raw responses and a manifest for one lookup."""
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "candidate-registry-snapshot-v1", "sources": []}
    for snapshot in sorted(snapshots, key=lambda item: item.source_id):
        source_entry = snapshot.to_dict()
        if snapshot.raw_payload is not None:
            suffix = ".csv" if snapshot.source_id.startswith("exofop") else ".json"
            filename = snapshot.source_id + suffix
            _atomic_write(destination / filename, snapshot.raw_payload)
            source_entry["raw_file"] = filename
        else:
            source_entry["raw_file"] = None
        manifest["sources"].append(source_entry)
    manifest_path = destination / "manifest.json"
    _atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    return manifest_path


def render_markdown(report: Dict[str, Any]) -> str:
    """Render a short human-readable dossier without changing the decision."""
    candidate = report["candidate"]
    study = report["study_evidence"]
    lines = [
        f"# Candidate registry check: TIC {candidate['tic_id']}",
        "",
        f"- **Status:** `{report['status']}`",
        f"- **Catalog coverage:** `{report['coverage']}`",
        f"- **Study stage:** `{study['stage']}`",
        f"- **Human review required:** `{str(report['human_review_required']).lower()}`",
        f"- **Checked at:** `{report['generated_at_utc']}`",
        "",
        report["summary"],
        "",
        "## Proposed signal",
        "",
        f"- TIC: `{candidate['tic_id']}`",
        f"- Period: `{candidate['period_days']}` days",
        f"- Epoch: `{candidate['epoch_bjd_tdb']}` BJD-TDB",
    ]
    if candidate.get("duration_hours") is not None:
        lines.append(f"- Duration: `{candidate['duration_hours']}` hours")
    if candidate.get("candidate_id"):
        lines.append(f"- Candidate label: `{candidate['candidate_id']}`")
    lines.extend(
        [
            "",
            "## Public study evidence",
            "",
            (
                "- Currently being studied: cannot be determined reliably from public catalogs; "
                "this report only shows deposited evidence."
            ),
            (
                "- Public follow-up recorded: "
                + str(study["public_follow_up_recorded"]).lower()
            ),
            "- Research completion percentage: not defined by any authoritative catalog.",
        ]
    )
    counts = study["target_follow_up_counts"]
    if any(value is not None for value in counts.values()):
        lines.append(
            "- Target-level ExoFOP follow-up counts: imaging={}, spectroscopy={}, "
            "time-series={}".format(
                counts["imaging_observations"],
                counts["spectroscopy_observations"],
                counts["time_series_observations"],
            )
        )
    for reference in study["papers_or_references"]:
        lines.append(f"- Paper/reference: {reference}")
    lines.extend(["", "## Catalog evidence", ""])
    if report["matches"]:
        for match in report["matches"]:
            lines.append(
                "- `{}` from `{}`: disposition `{}`, ephemeris `{}`, period `{}` days, "
                "updated `{}` — {}".format(
                    match["record_id"],
                    match["source_id"],
                    match["disposition"],
                    match["ephemeris_match"],
                    match["catalog_period_days"],
                    match["row_updated_at"],
                    match["evidence_url"],
                )
            )
    else:
        lines.append("- No same-TIC catalog record was found.")
    lines.extend(["", "## Sources", ""])
    for source in report["sources"]:
        lines.append(
            "- `{}`: `{}`; retrieved `{}`; catalog update `{}`; SHA-256 `{}`".format(
                source["source_id"],
                source["state"],
                source["retrieved_at_utc"],
                source["catalog_updated_at"],
                source["payload_sha256"],
            )
        )
    lines.extend(["", "> " + report["not_a_discovery_claim"], ""])
    return "\n".join(lines)


def run_check(
    candidate: Candidate,
    client: CatalogClient,
    snapshot_root: Path,
    report_root: Path,
    policy: Optional[MatchPolicy] = None,
    generated_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch catalogs, assess one signal, and publish an auditable dossier."""
    generated_at_utc = generated_at_utc or utc_now()
    run_id = _run_id(generated_at_utc)
    snapshots = client.lookup(candidate.tic_id)
    snapshot_dir = Path(snapshot_root) / run_id / f"TIC{candidate.tic_id}"
    manifest_path = persist_source_snapshots(snapshots, snapshot_dir)
    report = assess_candidate(candidate, snapshots, policy, generated_at_utc)
    report["source_snapshot_manifest"] = str(manifest_path.resolve())
    report_dir = Path(report_root) / f"TIC{candidate.tic_id}" / run_id
    json_path = report_dir / "assessment.json"
    markdown_path = report_dir / "assessment.md"
    report["report_paths"] = {
        "json": str(json_path.resolve()),
        "markdown": str(markdown_path.resolve()),
    }
    _atomic_write(
        json_path,
        json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    _atomic_write(markdown_path, render_markdown(report).encode("utf-8"))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether a periodic TESS signal already appears in current ExoFOP and "
            "NASA Exoplanet Archive catalogs."
        )
    )
    parser.add_argument("--tic-id", required=True)
    parser.add_argument("--period-days", type=float, required=True)
    epoch = parser.add_mutually_exclusive_group(required=True)
    epoch.add_argument("--epoch-bjd-tdb", type=float)
    epoch.add_argument(
        "--epoch-btjd",
        type=float,
        help="TESS BTJD epoch; converted to BJD-TDB by adding 2457000",
    )
    parser.add_argument("--duration-hours", type=float)
    parser.add_argument("--candidate-id")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    epoch_bjd_tdb = (
        args.epoch_bjd_tdb if args.epoch_bjd_tdb is not None else args.epoch_btjd + 2457000.0
    )
    candidate = Candidate(
        tic_id=args.tic_id,
        period_days=args.period_days,
        epoch_bjd_tdb=epoch_bjd_tdb,
        duration_hours=args.duration_hours,
        candidate_id=args.candidate_id,
    )
    client = CatalogClient(args.cache_dir, timeout_seconds=args.timeout_seconds)
    report = run_check(
        candidate,
        client,
        args.snapshot_root,
        args.report_root,
    )
    print(report["summary"])
    print("Status:", report["status"])
    print("JSON:", report["report_paths"]["json"])
    print("Markdown:", report["report_paths"]["markdown"])
    return 2 if report["status"] == "INCOMPLETE_LOOKUP" else 0


if __name__ == "__main__":
    raise SystemExit(main())
