"""Audited prepared inputs and deterministic mission-balanced training batches."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
import torch

from scripts.data.tess_dataset import apply_normalization, validate_dataset
from scripts.data.tess_selection import grouped_splits
from scripts.research.provenance import file_sha256
from scripts.research.scoring import NORMALIZER_SHA

MISSIONS = ("kepler", "tess")
INPUTS = ("x_global", "x_local", "x_scalar", "x_flat")


def audit_partitions(frame, splits):
    """Check original identities even when no original test is evaluated."""
    if frame.star_id.isna().any() or frame.split_group.isna().any():
        raise ValueError("Missing host/group identity")
    for name in ("train", "val", "test"):
        idx = np.asarray(splits[name + "_idx"])
        if not np.array_equal(idx, np.flatnonzero(frame.split.eq(name))):
            raise ValueError("Prepared split membership changed")
    for field in ("star_id", "split_group"):
        if (frame.groupby(field).split.nunique() > 1).any():
            raise ValueError("Host/proximity group crosses original partitions")
    if (frame.groupby("star_id").split_group.nunique() > 1).any():
        raise ValueError("Host assigned multiple proximity groups")


def make_roles(frame, partition_seed, max_train_groups):
    train = frame[frame.split.eq("train")]
    groups = sorted(train.split_group.unique(), key=lambda g: hashlib.sha256(
        f"{partition_seed}:{g}".encode()).hexdigest())
    if max_train_groups:
        groups = groups[:max_train_groups]
    roles = {"train": np.flatnonzero(frame.split.eq("train") & frame.split_group.isin(groups))}
    val_idx = np.flatnonzero(frame.split.eq("val"))
    val = frame.iloc[val_idx].reset_index(drop=True).copy()
    val["tic_id"] = val.star_id  # Temporary generic host alias, never persisted as a TIC.
    sub = grouped_splits(val, seed=partition_seed, val_size=.25, test_size=.25)
    for role, key in (("selection", "train_idx"), ("calibration", "val_idx"), ("audit", "test_idx")):
        roles[role] = val_idx[sub[key]]
    seen = set()
    for role, idx in roles.items():
        if set(frame.iloc[idx].y) != {0, 1}:
            raise ValueError(f"{role} lacks both labels; increase a prespecified group budget")
        group_set = set(frame.iloc[idx].split_group)
        if group_set & seen:
            raise ValueError("Experiment roles share host/proximity groups")
        seen |= group_set
        if frame.iloc[idx].split.eq("test").any():
            raise ValueError("Original test rows cannot enter an experiment role")
    return roles


def load_prepared(root, config):
    """NPZ bytes contain the old test; no test row is returned to the trainer.

    Integrity checks read full arrays/manifest. Only train and validation roles
    are normalized and materialized as model tensors; normalization never fits.
    """
    root = Path(root)
    norm = root / "data/processed/kepler/shared_v1/kepler_train_normalization.npz"
    if file_sha256(norm) != NORMALIZER_SHA:
        raise ValueError("Frozen reference normalization changed")
    with np.load(norm, allow_pickle=False) as z:
        stats = {key: z[key] for key in z.files}
    overlap_path = root / "data/processed/tess/v0/kepler_overlap.csv"
    overlap = pd.read_csv(overlap_path)
    receipts = {str(norm.relative_to(root)): file_sha256(norm),
                str(overlap_path.relative_to(root)): file_sha256(overlap_path)}
    data, selection = {}, {}
    for mission in MISSIONS:
        folder = root / "data/processed" / mission / "shared_v1"
        summary_path = folder / "preparation_summary.json"
        summary = json.loads(summary_path.read_text())
        paths = [folder / f"dataset_{mission}_shared_v1.npz",
                 folder / f"manifest_{mission}_shared_v1.csv",
                 folder / f"splits_{mission}_shared_v1_seed42.npz"]
        for path in paths:
            actual = file_sha256(path)
            if summary["outputs"][path.name] != actual:
                raise ValueError(f"Prepared source hash mismatch: {path}")
            receipts[str(path.relative_to(root))] = actual
        receipts[str(summary_path.relative_to(root))] = file_sha256(summary_path)
        with np.load(paths[0], allow_pickle=False) as z:
            arrays = {key: z[key] for key in z.files}
        frame = pd.read_csv(paths[1])
        with np.load(paths[2], allow_pickle=False) as z:
            splits = {key: z[key] for key in z.files}
        alias = frame.copy()
        alias["tic_id"] = frame.star_id
        validate_dataset(arrays, alias, splits,
                         forbidden_tic_ids=overlap.tic_id if mission == "tess" else ())
        audit_partitions(frame, splits)
        roles = make_roles(frame, config["partition_seed"], config["max_train_groups"])
        data[mission], selection[mission] = {}, {}
        for role, idx in roles.items():
            subset = frame.iloc[idx]
            normalized = apply_normalization({k: arrays[k][idx] for k in
                                               ("X_global", "X_local", "X_scalar", "X")}, stats)
            data[mission][role] = {key: torch.from_numpy(normalized[key]) for key in INPUTS}
            data[mission][role]["y"] = torch.from_numpy(arrays["y"][idx]).float()
            # Preserve physical metadata independently of normalized scalars.
            data[mission][role]["metadata"] = subset[["candidate_id", "star_id", "split_group",
                "period", "epoch_bjd", "duration_hours"]].to_dict("records")
            selection[mission][role] = {"row_indices": idx.tolist(),
                "candidate_ids": subset.candidate_id.tolist(),
                "groups": sorted(subset.split_group.unique().tolist()),
                "class_counts": {str(y): int((subset.y == y).sum()) for y in (0, 1)}}
    return data, {"files": receipts, "roles": selection,
                  "normalization": "frozen_Kepler_TRAIN_common_to_all_arms",
                  "normalizer_sha256": NORMALIZER_SHA,
                  "test_policy": "integrity_checked_only_never_trained_selected_calibrated_or_predicted",
                  "time_contract": "epoch_bjd=BJD_TDB_days; period=days; duration_hours=hours",
                  "known_ephemerides": True, "cross_mission_quarantine": "existing_5_arcsec_Kepler_overlap_exclusions"}


class MissionBatchPlan:
    """Stateless per-step batches: deterministic shuffled cycles, no workers.

    Mixed arms get exactly half their examples from each mission. Unequal domain
    sizes cannot silently change the loss weighting. Cycling smaller sets is
    explicit; this is mission balancing, not class or host balancing.
    """
    def __init__(self, data, batch_size, seed):
        if batch_size < 2 or batch_size % 2:
            raise ValueError("An even batch size >= 2 is required")
        self.data, self.batch_size, self.seed = data, batch_size, seed

    def indices(self, mission, step, count):
        n = len(self.data[mission]["train"]["y"])
        if n == 0:
            raise ValueError("Empty training mission")
        result = []
        cursor = step * count
        while len(result) < count:
            cycle, offset = divmod(cursor, n)
            order = np.random.default_rng(np.random.SeedSequence(
                [self.seed, MISSIONS.index(mission), cycle])).permutation(n)
            take = min(count - len(result), n - offset)
            result.extend(order[offset:offset + take].tolist())
            cursor += take
        return torch.tensor(result, dtype=torch.long)

    def batch(self, arm, step, pretrain_steps, device="cpu"):
        if arm == "tess_only" or (arm == "fine_tuned" and step >= pretrain_steps):
            missions = ("tess",)
        elif arm == "kepler_only" or arm == "fine_tuned":
            missions = ("kepler",)
        elif arm in ("pooled", "dann"):
            missions = MISSIONS
        else:
            raise ValueError("Unknown experiment arm")
        count = self.batch_size // len(missions)
        chunks, labels, domains = [], [], []
        for mission in missions:
            rows = self.indices(mission, step, count)
            part = self.data[mission]["train"]
            chunks.append([part[key][rows] for key in INPUTS])
            labels.append(part["y"][rows])
            domains.append(torch.full((count,), MISSIONS.index(mission), dtype=torch.long))
        return ([torch.cat([chunk[k] for chunk in chunks]).to(device) for k in range(4)],
                torch.cat(labels).to(device), torch.cat(domains).to(device))
