"""Candidate-level TESS labels, conservative sky quarantine, and grouped splits.

Sky proximity is a leakage precaution, not an assertion that a TIC and KIC are
the same object. Coordinates are catalog ICRS degrees, without proper-motion
propagation. This module neither changes nor reassigns the Kepler source rows.
"""
from __future__ import annotations

from collections import Counter
import math
import re

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import SkyCoord, search_around_sky
from sklearn.model_selection import GroupShuffleSplit


LABELS = {"CP": 1, "KP": 1, "FP": 0, "FA": 0}
CATALOG_COLUMNS = {"tid", "toi", "tfopwg_disp", "pl_orbper", "pl_tranmid", "pl_trandurh", "ra", "dec"}
OVERLAP_COLUMNS = ["tic_id", "kepid", "separation_arcsec", "reason"]


def _require_columns(frame, required, name):
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


def _identifier(value):
    """Accept integer identifiers without rounding an imprecise float or string."""
    if pd.isna(value) or isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value) or value != int(value) or abs(value) >= 2 ** 53:
            return None
        value = int(value)
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        return None
    integer = int(text)
    return integer if 0 < integer <= np.iinfo(np.int64).max else None


def _identifiers(values):
    # Series.map can promote integers plus a missing value to float, losing
    # identity before a subsequent nullable-integer cast gets a chance to help.
    return pd.Series(pd.array([_identifier(value) for value in values], dtype="Int64"),
                     index=values.index)


def _coordinate_rows(frame, id_column):
    rows = frame[[id_column, "ra", "dec"]].copy()
    for column in ("ra", "dec"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    valid = (rows[id_column].notna() & np.isfinite(rows.ra) & np.isfinite(rows.dec)
             & rows.ra.between(0, 360) & rows.dec.between(-90, 90))
    return rows.loc[valid].drop_duplicates().reset_index(drop=True), valid


def _sky(rows):
    return SkyCoord(ra=rows.ra.to_numpy(dtype=float) * u.deg,
                    dec=rows.dec.to_numpy(dtype=float) * u.deg, frame="icrs")


def _kepler_reference(catalog, manifest):
    _require_columns(manifest, {"kepid"}, "Kepler manifest")
    _require_columns(catalog, {"kepid", "ra", "dec"}, "Kepler catalog")
    processed_ids = _identifiers(manifest.kepid)
    if processed_ids.isna().any():
        raise ValueError("Processed Kepler manifest contains invalid star identifiers")
    processed_ids = set(processed_ids)
    reference = catalog[["kepid", "ra", "dec"]].copy()
    reference["kepid"] = _identifiers(reference.kepid)
    reference = reference[reference.kepid.isin(processed_ids)]
    reference, _ = _coordinate_rows(reference, "kepid")
    missing = processed_ids - set(reference.kepid)
    if missing:
        example = ", ".join(str(value) for value in sorted(missing)[:8])
        raise ValueError(f"Cannot establish Kepler quarantine: missing valid coordinates for "
                         f"{len(missing)} processed Kepler stars (KIC {example})")
    reference["kepid"] = reference.kepid.astype(np.int64)
    return reference


def _proximity_groups(coordinates, radius):
    """Connected components include all catalog stars, even unlabeled bridges."""
    parents = {int(tic): int(tic) for tic in coordinates.tic_id.unique()}

    def root(tic):
        while parents[tic] != tic:
            parents[tic] = parents[parents[tic]]
            tic = parents[tic]
        return tic

    if len(coordinates):
        first, second, _, _ = search_around_sky(_sky(coordinates), _sky(coordinates), radius * u.arcsec)
        tics = coordinates.tic_id.to_numpy(dtype=np.int64)
        for left, right in zip(first, second):
            a, b = root(int(tics[left])), root(int(tics[right]))
            if a != b:
                parents[max(a, b)] = min(a, b)
    return {tic: f"TIC-{root(tic)}" for tic in parents}


def select_candidates(catalog: pd.DataFrame, products: pd.DataFrame,
                      kepler_catalog: pd.DataFrame, kepler_manifest: pd.DataFrame, *,
                      min_period: float = .5, max_period: float = 30,
                      min_duration_hours: float = .1, max_duration_hours: float = 20,
                      overlap_arcsec: float = 5.0) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return selected candidates, an audit of every input row, and sky matches.

    CP/KP are positive, FP/FA negative, and other dispositions remain unlabeled.
    Limits are inclusive; duration must also be shorter than one period. Epochs
    must be finite full BJD values above 2,400,000. The product manifest establishes
    archive coverage; file integrity and usable-flux checks belong to processing.
    Missing coordinates quarantine a whole TIC, as does any Kepler sky match.
    ``audit`` preserves all original columns and unselected companion ephemerides.
    """
    _require_columns(catalog, CATALOG_COLUMNS, "TOI catalog")
    _require_columns(products, {"tic_id"}, "TESS product manifest")
    bounds = [min_period, max_period, min_duration_hours, max_duration_hours, overlap_arcsec]
    if (not np.isfinite(bounds).all() or min_period <= 0 or max_period < min_period
            or min_duration_hours <= 0 or max_duration_hours < min_duration_hours
            or overlap_arcsec <= 0):
        raise ValueError("Selection bounds must be finite, positive, and ordered")
    # Build the complete processed-Kepler reference before considering any TESS
    # labels, periods or quality cuts. Missing reference stars fail closed.
    reference = _kepler_reference(kepler_catalog, kepler_manifest)
    audit = catalog.copy(deep=True).reset_index(drop=True)
    audit["toi"] = audit.toi.map(lambda value: "" if pd.isna(value) else str(value).strip())
    audit["candidate_id"] = "TOI-" + audit.toi
    audit["tic_id"] = _identifiers(audit.tid)
    audit["tfopwg_disp"] = audit.tfopwg_disp.fillna("").astype(str).str.strip().str.upper()
    audit["y"] = pd.array(audit.tfopwg_disp.map(LABELS), dtype="Int64")
    for output, source in (("period", "pl_orbper"), ("epoch_bjd", "pl_tranmid"),
                           ("duration_hours", "pl_trandurh")):
        audit[output] = pd.to_numeric(audit[source], errors="coerce")

    coordinates, valid_coordinates = _coordinate_rows(audit, "tic_id")
    missing_coordinate_tics = set(audit.loc[~valid_coordinates, "tic_id"].dropna())
    groups = _proximity_groups(coordinates, overlap_arcsec)
    audit["split_group"] = audit.tic_id.map(groups)
    overlap = pd.DataFrame(columns=OVERLAP_COLUMNS)
    if len(coordinates) and len(reference):
        tess_idx, kepler_idx, separation, _ = search_around_sky(
            _sky(coordinates), _sky(reference), overlap_arcsec * u.arcsec)
        if len(tess_idx):
            overlap = pd.DataFrame({
                "tic_id": coordinates.iloc[tess_idx].tic_id.to_numpy(dtype=np.int64),
                "kepid": reference.iloc[kepler_idx].kepid.to_numpy(dtype=np.int64),
                "separation_arcsec": separation.arcsec,
            }).groupby(["tic_id", "kepid"], as_index=False).separation_arcsec.min()
            overlap["reason"] = "kepler_proximity_quarantine"
            overlap = overlap[OVERLAP_COLUMNS].sort_values(["tic_id", "kepid"]).reset_index(drop=True)
    overlapping_tics = set(overlap.tic_id)
    product_ids = set(_identifiers(products.tic_id).dropna())

    reasons = [[] for _ in range(len(audit))]

    def flag(mask, reason):
        for index in np.flatnonzero(np.asarray(mask.fillna(True) if isinstance(mask, pd.Series) else mask,
                                               dtype=bool)):
            reasons[index].append(reason)

    valid_candidate = audit.toi.str.fullmatch(r"[0-9]+\.[0-9]+")
    flag(~valid_candidate, "invalid_candidate_id")
    flag(audit.candidate_id.duplicated(keep=False), "duplicate_candidate_id")
    flag(audit.tic_id.isna(), "invalid_tic_id")
    flag(audit.y.isna(), "unlabeled_disposition")
    finite_ephemeris = np.isfinite(audit[["period", "epoch_bjd", "duration_hours"]]).all(axis=1)
    flag(~finite_ephemeris | (audit.period <= 0) | (audit.epoch_bjd <= 2400000)
         | (audit.duration_hours <= 0), "invalid_ephemeris")
    flag(~audit.period.between(min_period, max_period), "period_out_of_range")
    flag(~audit.duration_hours.between(min_duration_hours, max_duration_hours), "duration_out_of_range")
    flag(audit.duration_hours >= 24 * audit.period, "duration_not_shorter_than_period")
    flag(~audit.tic_id.isin(product_ids), "no_manifest_lightcurve")
    missing_coordinates = ~valid_coordinates | audit.tic_id.isin(missing_coordinate_tics)
    flag(missing_coordinates, "missing_or_invalid_coordinates")
    flag(audit.tic_id.isin(overlapping_tics), "kepler_proximity_quarantine")
    audit["reason"] = [";".join(row) if row else "eligible" for row in reasons]
    audit["status"] = ["excluded" if row else "selected" for row in reasons]
    audit.loc[missing_coordinates | audit.tic_id.isin(overlapping_tics), "status"] = "quarantined"
    selected = audit.loc[audit.status == "selected"].drop(columns=["status", "reason"]).copy()
    selected["tic_id"] = selected.tic_id.astype(np.int64)
    selected["y"] = selected.y.astype(np.int64)
    return selected.reset_index(drop=True), audit, overlap


def _group_table(manifest):
    _require_columns(manifest, {"candidate_id", "tic_id", "y", "split_group"}, "TESS candidate manifest")
    if (manifest.empty or manifest.candidate_id.isna().any() or manifest.candidate_id.duplicated().any()
            or manifest.candidate_id.astype(str).str.strip().eq("").any()):
        raise ValueError("TESS manifest needs nonempty, unique candidate identifiers")
    if manifest.split_group.isna().any() or manifest.split_group.astype(str).str.strip().eq("").any():
        raise ValueError("Every TESS candidate must have a split_group")
    if _identifiers(manifest.tic_id).isna().any() or not manifest.y.isin([0, 1]).all():
        raise ValueError("Every TESS candidate must have a valid TIC and binary label")
    star_groups = pd.DataFrame({"tic_id": _identifiers(manifest.tic_id),
                               "split_group": manifest.split_group.astype(str)})
    if (star_groups.groupby("tic_id").split_group.nunique() != 1).any():
        raise ValueError("A TIC appears in multiple split groups")
    records = []
    for group, rows in manifest.assign(split_group=manifest.split_group.astype(str)).groupby("split_group", sort=True):
        records.append({"split_group": group, "signature": ",".join(str(label) for label in sorted(set(rows.y))),
                        "n0": int((rows.y == 0).sum()), "n1": int((rows.y == 1).sum())})
    return pd.DataFrame(records).set_index("split_group")


def choose_pilot(selected: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Choose a deterministic class-balanced pilot, retaining complete groups.

    The requested size is a lower target, limited by available candidates. A
    group is indivisible, so its companions may take the result above the target.
    If a class is scarce, use its available members and fill from the other class.
    """
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError("Pilot size must be a positive integer")
    table = _group_table(selected)
    if set(selected.y) != {0, 1}:
        raise ValueError("A labeled pilot requires both classes")
    n = min(n, len(selected))
    targets = np.array([n // 2, n - n // 2], dtype=int)
    available = table[["n0", "n1"]].sum().to_numpy(dtype=int)
    for label in (0, 1):
        if targets[label] > available[label]:
            targets[1 - label] += targets[label] - available[label]
            targets[label] = available[label]
    order = np.random.default_rng(seed).permutation(len(table))
    remaining = list(table.index[order])
    chosen, counts = [], np.zeros(2, dtype=int)
    while np.any(counts < targets):
        label = int(np.argmax(targets - counts))
        group = next(group for group in remaining if table.loc[group, f"n{label}"] > 0)
        chosen.append(group)
        remaining.remove(group)
        counts += table.loc[group, ["n0", "n1"]].to_numpy(dtype=int)
    return selected.loc[selected.split_group.astype(str).isin(chosen)].sort_values(
        "candidate_id", kind="stable").reset_index(drop=True)


def _allocate_strata(counts, total, lower, upper):
    """Fixed proportional integer allocation with explicit capacity constraints."""
    target = np.asarray(counts, dtype=float) * total / np.sum(counts)
    allocated = np.asarray(lower, dtype=int).copy()
    upper = np.asarray(upper, dtype=int)
    if allocated.sum() > total or upper.sum() < total:
        raise ValueError("Infeasible stratified group allocation")
    while allocated.sum() < total:
        deficit = np.where(allocated < upper, target - allocated, -np.inf)
        allocated[int(np.argmax(deficit))] += 1
    return allocated


def grouped_splits(manifest: pd.DataFrame, seed: int = 42, test_size: float = .15,
                   val_size: float = .15, train_only_groups=()) -> dict[str, np.ndarray]:
    """Make one fixed assignment, keeping each TIC/proximity group in one split.

    Fractions apply to the total number of groups, including reserved training
    groups, and are rounded up. When capacity allows, each label signature is
    proportionally stratified across all three partitions. Otherwise use a single
    GroupShuffleSplit assignment and validate it; no search over seeds or labels
    is performed. All partitions must contain both candidate labels.
    """
    table = _group_table(manifest)
    if (not np.isfinite([test_size, val_size]).all() or test_size <= 0 or val_size <= 0
            or test_size + val_size >= 1):
        raise ValueError("Validation/test fractions must be positive and sum to less than one")
    forced = {str(group) for group in train_only_groups}
    unknown = forced - set(table.index)
    if unknown:
        raise ValueError(f"Reserved training groups are absent from the manifest: {sorted(unknown)[:8]}")
    eligible = table.loc[~table.index.isin(forced)]
    n_test, n_val = math.ceil(test_size * len(table)), math.ceil(val_size * len(table))
    n_train_free = len(eligible) - n_test - n_val
    if n_train_free < 0 or n_train_free + len(forced) < 1:
        raise ValueError("Too few groups for the requested split fractions and reserved pilot groups")
    signatures = sorted(eligible.signature.unique())
    signature_counts = np.array([(eligible.signature == signature).sum() for signature in signatures])
    stratified = (len(signatures) > 0 and (signature_counts >= 3).all()
                  and min(n_test, n_val, n_train_free) >= len(signatures))
    groups = {"train": set(forced), "val": set(), "test": set()}
    if stratified:
        minimum = np.ones(len(signatures), dtype=int)
        test_counts = _allocate_strata(signature_counts, n_test, minimum, signature_counts - 2)
        val_counts = _allocate_strata(signature_counts - test_counts, n_val, minimum,
                                     signature_counts - test_counts - 1)
        rng = np.random.default_rng(seed)
        for signature, n_sig_test, n_sig_val in zip(signatures, test_counts, val_counts):
            members = rng.permutation(eligible.index[eligible.signature == signature].to_numpy())
            groups["test"].update(members[:n_sig_test])
            groups["val"].update(members[n_sig_test:n_sig_test + n_sig_val])
            groups["train"].update(members[n_sig_test + n_sig_val:])
    else:
        # Reserve no extra training group here: all remaining groups may be pilot
        # groups if the requested held-out counts already consume the remainder.
        values = eligible.index.to_numpy()
        if len(values) <= n_test or len(values) - n_test < n_val:
            raise ValueError("Too few unreserved groups for fixed validation and test partitions")
        rest_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=n_test, random_state=seed)
                                  .split(values, groups=values))
        remaining = values[rest_idx]
        groups["test"].update(values[test_idx])
        if len(remaining) == n_val:
            groups["val"].update(remaining)
        else:
            train_idx, val_idx = next(GroupShuffleSplit(n_splits=1, test_size=n_val, random_state=seed + 1)
                                     .split(remaining, groups=remaining))
            groups["train"].update(remaining[train_idx])
            groups["val"].update(remaining[val_idx])
    result = {f"{name}_idx": np.flatnonzero(manifest.split_group.astype(str).isin(members)).astype(np.int64)
              for name, members in groups.items()}
    for name in groups:
        labels = set(manifest.iloc[result[f"{name}_idx"]].y)
        if labels != {0, 1}:
            details = dict(Counter(table.signature))
            raise ValueError(f"Fixed {name} split lacks both classes; group label signatures={details}, "
                             f"reserved training groups={len(forced)}. Increase the eligible cohort or "
                             "revise prespecified fractions; do not search random seeds for a favorable split.")
    combined = np.concatenate(list(result.values()))
    if not np.array_equal(np.sort(combined), np.arange(len(manifest))):
        raise AssertionError("Grouped splits must partition every candidate exactly once")
    return result
