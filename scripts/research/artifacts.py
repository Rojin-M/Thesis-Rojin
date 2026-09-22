"""Owned, content-addressed artifacts and bounded, dependency-free plot rendering."""
from __future__ import annotations

import hashlib
from html import escape
import json
import os
from pathlib import Path
import tempfile

from .protocol import (ARTIFACT_MEDIA_TYPES, ValidationError, ConflictError, canonical_json,
                       finite_number, nonempty, sha256)

MAX_BYTES = 64 * 1024 ** 2


def validate_plot(value):
    if not isinstance(value, dict):
        raise ValidationError("Plot must be a JSON object")
    kind = value.get("kind")
    if kind not in ("time_series", "phase_folded", "periodogram", "diagnostic"):
        raise ValidationError("Unsupported plot kind")
    for key in ("title", "x_label", "y_label"):
        nonempty(value.get(key), key, 200)
    if kind == "time_series" and value.get("time_system") not in ("BJD_TDB", "BTJD", "BKJD"):
        raise ValidationError("Time-series plots must state the TDB day system")
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, list) or not isinstance(y, list) or not 2 <= len(x) == len(y) <= 20000:
        raise ValidationError("Plots require 2–20000 paired points; thin large previews explicitly upstream")
    for a, b in zip(x, y):
        finite_number(a, "plot x")
        finite_number(b, "plot y")
    if kind == "time_series" and any(a > b for a, b in zip(x, x[1:])):
        raise ValidationError("Time-series previews must be in increasing time order")
    return value


class ArtifactStore:
    def __init__(self, root, store):
        self.root = Path(root).resolve()
        self.store = store
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, checksum):
        sha256(checksum)
        path = self.root / checksum[:2] / checksum
        if not path.resolve().is_relative_to(self.root):
            raise ValidationError("Artifact path escapes owned storage")
        return path

    def put_bytes(self, payload, *, candidate_id, artifact_key, kind, filename,
                  media_type="application/octet-stream", metadata=None, lease_token=None):
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
            raise ValidationError("Artifact must contain 1 byte to 64 MiB")
        if media_type not in ARTIFACT_MEDIA_TYPES:
            raise ValidationError("Unsupported artifact media type; active HTML/SVG uploads are forbidden")
        if kind == "plot":
            if media_type != "application/json":
                raise ValidationError("Plot artifacts must be validated JSON")
            try:
                validate_plot(json.loads(payload))
            except (ValueError, TypeError) as exc:
                raise ValidationError(f"Invalid plot: {exc}") from exc
        checksum = hashlib.sha256(payload).hexdigest()
        destination = self._path(checksum)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != checksum:
                raise ConflictError("Existing content-addressed artifact has changed")
        else:
            fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=str(destination.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        # A crash before registration can leave an unreferenced immutable blob;
        # retrying the same operation reuses it safely. There is no partial file.
        return self.store.register_artifact(candidate_id=candidate_id, artifact_key=artifact_key, kind=kind,
                                            media_type=media_type, filename=filename, sha256_digest=checksum,
                                            size_bytes=len(payload), metadata=metadata, lease_token=lease_token)

    def put_plot(self, value, **kwargs):
        validate_plot(value)
        return self.put_bytes(canonical_json(value).encode(), kind="plot", media_type="application/json", **kwargs)

    def read(self, artifact_id):
        record = self.store.get_artifact(artifact_id)
        path = self._path(record["sha256"])
        if not path.is_file():
            raise ConflictError("Recorded artifact bytes are missing")
        if path.stat().st_size != record["size_bytes"] or path.stat().st_size > MAX_BYTES:
            raise ConflictError("Artifact size differs from its immutable receipt")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ConflictError("Artifact checksum differs from its immutable receipt")
        return record, payload


def render_plot(value):
    """Render every point in a bounded preview; no silent scientific downsampling."""
    validate_plot(value)
    x, y = value["x"], value["y"]
    xmin, xmax, ymin, ymax = min(x), max(x), min(y), max(y)
    dx, dy = xmax - xmin or 1., ymax - ymin or max(abs(ymin) * .01, 1e-6)
    ymin, ymax = ymin - .08 * dy, ymax + .08 * dy
    def point(a, b):
        return 94 + (a - xmin) / dx * 836, 310 - (b - ymin) / (ymax - ymin) * 240
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 390" role="img" aria-labelledby="title desc">',
              f'<title id="title">{escape(value["title"])}</title>',
              f'<desc id="desc">{len(x)} preview samples; {escape(value["x_label"])} versus {escape(value["y_label"])}.</desc>',
              '<rect width="980" height="390" fill="#111e31"/>',
              f'<text x="94" y="35" fill="#f1f5fa" font-family="sans-serif" font-size="18">{escape(value["title"])}</text>']
    for i in range(5):
        a = xmin + (xmax - xmin) * i / 4
        b = ymin + (ymax - ymin) * i / 4
        px, py = point(a, b)
        pieces.extend([f'<path d="M94 {py:.2f} H930" stroke="#25364c"/>',
                       f'<text x="82" y="{py+4:.2f}" text-anchor="end" fill="#bccadc" font-family="monospace" font-size="12">{b:.6g}</text>',
                       f'<text x="{px:.2f}" y="336" text-anchor="middle" fill="#bccadc" font-family="monospace" font-size="12">{a:.7g}</text>'])
    pieces.append('<g fill="#6cdbd4" fill-opacity="0.75">')
    for a, b in zip(x, y):
        px, py = point(a, b)
        pieces.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="1.65"/>')
    pieces.extend(['</g>', f'<text x="500" y="373" text-anchor="middle" fill="#d6e1ee" font-family="sans-serif" font-size="14">{escape(value["x_label"])}</text>',
                   f'<text transform="translate(20 200) rotate(-90)" text-anchor="middle" fill="#d6e1ee" font-family="sans-serif" font-size="14">{escape(value["y_label"])}</text>', '</svg>'])
    return "".join(pieces).encode()
