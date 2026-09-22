"""Small source manifests; never scan data or load/modify model checkpoints."""
import hashlib
import platform
from pathlib import Path
import subprocess

from .protocol import ROOT, digest, utc_now


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def code_snapshot(root=ROOT):
    root = Path(root)
    files = {}
    for directory in ("scripts", "training", "configs"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".js", ".css", ".html") and "__pycache__" not in path.parts:
                files[str(path.relative_to(root))] = file_sha256(path)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                                capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root,
                                   check=True, capture_output=True, text=True, timeout=5).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    return {"git_commit": commit, "working_tree_dirty": dirty, "files": files,
            "python": platform.python_version(), "manifest_sha256": digest(files)}


def register_code(store):
    snapshot = code_snapshot()
    return store.register_provenance(kind="code", identity="research-application-source",
                                     sha256_digest=snapshot["manifest_sha256"], retrieved_at=utc_now(), details=snapshot)
