"""Bounded adapter for already acquired public MAST TESS products.

Selection inspects identities only, never catalog periods or epochs. This does
not claim a current public-release check or download missing archive products.
"""
import csv
from pathlib import Path

from .protocol import ValidationError


def cached_tess_paths(root, target_id, max_products=1):
    if not str(target_id).isdigit() or type(max_products) is not int or not 1 <= max_products <= 20:
        raise ValidationError("Require a numeric TIC ID and a 1–20 product limit")
    raw = (Path(root) / "data/raw/tess").resolve()
    selected = []
    with (raw / "metadata/manifest.csv").open(newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle)):
            if number >= 100000:
                raise ValidationError("Cached manifest scan exceeds 100000 rows")
            if row["tic_id"] != str(target_id):
                continue
            relative = Path(row["relative_path"])
            path = (raw / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(raw):
                raise ValidationError("Manifest product path escapes the local raw root")
            if path.is_file():
                selected.append((int(row["sector"]), path.name, path))
    paths = [p for _, _, p in sorted(set(selected))[:max_products]]
    if not paths:
        raise ValidationError("No locally cached public TESS products for this target; no automatic download")
    return paths
