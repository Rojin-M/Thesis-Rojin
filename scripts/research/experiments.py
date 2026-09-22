"""Read-only, bounded publication of local experiment completion receipts.

No model imports, training endpoint, filesystem paths from clients or arbitrary
file serving. Failed and unfinished runs remain visible without invented scores.
"""
import hashlib
import json
from pathlib import Path
import re

from .protocol import NotFoundError, ValidationError, digest

MAX_JSON = 4 * 1024 * 1024
EXPORTS = {"report.json": ("summary.json", "application/json"),
           "report.md": ("report.md", "text/markdown; charset=utf-8"),
           "comparison.png": ("comparison.png", "image/png")}


def _bytes(path, cap=MAX_JSON):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise ValidationError("Experiment file missing, unsafe or too large")
    with path.open("rb") as handle:
        value = handle.read(cap + 1)
    if len(value) > cap:
        raise ValidationError("Experiment export exceeds its size limit")
    return value


def _json(path):
    try:
        return json.loads(_bytes(path), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise ValidationError("Malformed experiment record") from exc


def _folder(root, identifier):
    root = Path(root)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", identifier):
        raise NotFoundError("Invalid experiment ID")
    folder = root / identifier
    if root.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise NotFoundError("Experiment unavailable")
    return folder


def verified_summary(folder):
    receipt = _json(folder / "complete.json")
    expected_names = {"spec.json", "summary.json", "report.md", "comparison.png"}
    if set(receipt.get("files", {})) != expected_names:
        raise ValidationError("Invalid experiment completion receipt")
    for name, checksum in receipt["files"].items():
        if hashlib.sha256(_bytes(folder / name)).hexdigest() != checksum:
            raise ValidationError("Experiment export checksum mismatch")
    spec, summary = _json(folder / "spec.json"), _json(folder / "summary.json")
    if (digest(spec) != receipt.get("spec_sha256") or summary.get("spec_sha256") != digest(spec)
            or summary.get("status") != "complete" or summary.get("config") != spec.get("config")
            or summary.get("claims", {}).get("search_ready") is not False
            or summary.get("claims", {}).get("deployed_to_candidate_scoring") is not False):
        raise ValidationError("Inconsistent experiment completion identity")
    return summary, receipt


def list_experiments(root):
    root = Path(root)
    if not root.exists():
        return {"items": [], "truncated": False}
    if root.is_symlink():
        raise ValidationError("Experiment root must not be a symlink")
    names = []
    # Cap the directory scan too, not just its returned results.
    import itertools
    entries = list(itertools.islice(root.iterdir(), 101))
    for path in sorted(entries, key=lambda p: p.name):
        if path.is_dir() and not path.is_symlink() and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", path.name):
            names.append(path.name)
    items = []
    for name in names[:50]:
        folder = _folder(root, name)
        row = {"id": name, "status": "incomplete", "verified": False, "results": None}
        try:
            if (folder / "state.json").exists():
                state = _json(folder / "state.json")
                row.update({key: state.get(key) for key in ("status", "attempts", "runtime_charged",
                                                           "arm", "seed", "step", "heartbeat_at", "error")})
            if (folder / "complete.json").exists():
                summary, receipt = verified_summary(folder)
                row.update(status="complete", verified=True, cohort=summary["cohort"],
                    results=summary["by_arm"], config=summary["config"], limitations=summary["limitations"],
                    claims=summary["claims"], spec_sha256=summary["spec_sha256"], completed_at=receipt["completed_at"],
                    verification="Export hashes and frozen specification checked; model receipts are in the local run",
                    runs=[{key: r[key] for key in ("arm", "seed", "best_step", "updates", "examples_drawn",
                          "calibration", "mission_head_balanced_accuracy")} for r in summary["runs"]],
                    links={key: f"/api/experiments/{name}/{key}" for key in EXPORTS})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(status="verification_failed", verified=False, results=None,
                       error={"type": type(exc).__name__, "message": str(exc)[:500]})
        items.append(row)
    return {"items": items, "truncated": len(entries) > 100 or len(names) > 50}


def read_export(root, identifier, name):
    if name not in EXPORTS:
        raise NotFoundError("Unknown experiment export")
    folder = _folder(root, identifier)
    if not (folder / "complete.json").exists():
        raise NotFoundError("Experiment has no verified completed export")
    _, receipt = verified_summary(folder)
    filename, media_type = EXPORTS[name]
    payload = _bytes(folder / filename)
    if hashlib.sha256(payload).hexdigest() != receipt["files"][filename]:
        raise ValidationError("Experiment export changed during read")
    return payload, media_type
