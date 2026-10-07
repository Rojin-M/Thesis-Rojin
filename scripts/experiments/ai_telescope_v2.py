#!/usr/bin/env python3
"""Extend the paired TESS pilot with instrument-state and host-context encoders."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import IsolationForest
from torch.utils.data import DataLoader, TensorDataset

from scripts.experiments.ai_telescope import (event_metrics, choose_threshold,
                                               predict_localizer)
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import (EventLocalizer, ExtendedEventLocalizer,
                                   ExtendedMultimodalPretrainer, MultimodalPretrainer)

VERSION = "ai_telescope_instrument_context_v2"
FIELDS = {"schema_version", "base_run", "physical_run", "output", "embedding_dim",
          "instrument_channels", "auxiliary_pretrain_epochs", "localization_epochs",
          "batch_size", "learning_rate", "weight_decay", "mask_fraction",
          "contrastive_temperature", "instrument_contrastive_weight",
          "context_contrastive_weight", "modality_dropout", "maximum_positive_weight",
          "calibration_fpr_target", "seed", "cpu_threads"}
CONTEXT_FEATURES = (
    "tess_magnitude", "log_effective_temperature", "log_stellar_radius", "surface_gravity",
    "metallicity", "signed_log_pmra", "signed_log_pmdec", "sin_ra", "cos_ra",
    "sin_dec", "cos_dec", "sector", "camera", "ccd", "crowding", "flux_fraction",
)


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("Context-v2 configuration differs from schema")
    for key in ("base_run", "physical_run", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Context-v2 paths must remain inside the project")
    for key, low, high in (
        ("embedding_dim", 16, 256), ("instrument_channels", 3, 3),
        ("auxiliary_pretrain_epochs", 1, 100), ("localization_epochs", 1, 100),
        ("batch_size", 4, 256), ("seed", 0, 2**31 - 1), ("cpu_threads", 1, 8)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    for key, low, high in (
        ("learning_rate", 1e-6, .1), ("weight_decay", 0., 1.),
        ("mask_fraction", .05, .8), ("contrastive_temperature", .01, 2.),
        ("instrument_contrastive_weight", 0., 10.),
        ("context_contrastive_weight", 0., 10.), ("modality_dropout", 0., .8),
        ("maximum_positive_weight", 1., 1000.), ("calibration_fpr_target", 0., .5)):
        item = value[key]
        if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError("Invalid " + key)
    return value


def _checked_json(path, expected=None):
    value = json.loads(path.read_text())
    if expected is not None and value.get("status") != expected:
        raise ValueError("Incomplete receipt: " + str(path))
    return value


def load_base(config):
    base = ROOT / config["base_run"]
    complete = _checked_json(base / "complete.json", "complete")
    for name, checksum in complete["files"].items():
        if file_sha256(base / name) != checksum:
            raise ValueError("Base-run checksum mismatch: " + name)
    dataset_receipt = _checked_json(base / "dataset_complete.json", "complete")
    dataset_path = base / "dataset.npz"
    if dataset_receipt["files"]["dataset.npz"] != file_sha256(dataset_path):
        raise ValueError("Base dataset checksum mismatch")
    with np.load(dataset_path, allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in saved.files}
    required = {"flux", "valid", "pixel", "event", "start", "target_id", "role", "sector"}
    if not required.issubset(arrays) or len({len(arrays[x]) for x in required}) != 1:
        raise ValueError("Base dataset has an unexpected array contract")
    return arrays, complete, dataset_receipt


def _number(context, key):
    try:
        value = float(context.get(key))
    except (TypeError, ValueError):
        return np.nan
    return value if np.isfinite(value) else np.nan


def context_vector(context):
    value = lambda key: _number(context, key)
    positive_log = lambda x: math.log(x) if np.isfinite(x) and x > 0 else np.nan
    signed_log = lambda x: math.copysign(math.log1p(abs(x)), x) if np.isfinite(x) else np.nan
    ra, dec = value("RA_OBJ"), value("DEC_OBJ")
    ra = math.radians(ra) if np.isfinite(ra) else np.nan
    dec = math.radians(dec) if np.isfinite(dec) else np.nan
    return np.asarray([
        value("TESSMAG"), positive_log(value("TEFF")), positive_log(value("RADIUS")),
        value("LOGG"), value("MH"), signed_log(value("PMRA")), signed_log(value("PMDEC")),
        math.sin(ra) if np.isfinite(ra) else np.nan,
        math.cos(ra) if np.isfinite(ra) else np.nan,
        math.sin(dec) if np.isfinite(dec) else np.nan,
        math.cos(dec) if np.isfinite(dec) else np.nan,
        value("SECTOR"), value("CAMERA"), value("CCD"), value("CROWDSAP"), value("FLFRCSAP"),
    ], dtype=np.float32)


def normalize_instrument(pixels):
    if pixels.position_correction is None or pixels.background_flux is None:
        raise ValueError("TPF lacks pointing corrections or background flux")
    raw = np.column_stack([pixels.position_correction, pixels.background_flux]).astype(np.float32)
    if raw.shape != (len(pixels.time), 3):
        raise ValueError("Instrument channels are misaligned")
    valid = (pixels.quality == 0) & np.isfinite(pixels.time)
    output = np.zeros_like(raw, dtype=np.float32)
    for column in range(raw.shape[1]):
        use = valid & np.isfinite(raw[:, column])
        if use.sum() < 128:
            raise ValueError("Instrument channel has insufficient valid samples")
        center = float(np.median(raw[use, column]))
        scale = 1.4826 * float(np.median(np.abs(raw[use, column] - center)))
        if not np.isfinite(scale) or scale <= 1e-8:
            scale = float(np.std(raw[use, column]))
        scale = scale if np.isfinite(scale) and scale > 1e-8 else 1.
        output[use, column] = np.clip((raw[use, column] - center) / scale, -10, 10)
    return output.T


def _atomic_npz(path, **arrays):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def _starts_sha(starts):
    return hashlib.sha256(np.asarray(starts, dtype=np.int32).tobytes()).hexdigest()


def _receipt_key(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def prepare_dataset(config, base_arrays, output, spec_sha):
    physical = ROOT / config["physical_run"]
    physical_complete = _checked_json(physical / "complete.json", "complete")
    for name in ("cohort.json", "download_plan.json"):
        if physical_complete["files"][name] != file_sha256(physical / name):
            raise ValueError("Physical-run checksum mismatch: " + name)
    plan = _checked_json(physical / "download_plan.json")
    products = {str(row["target_id"]): row for row in plan["products"]}
    cache = output / "auxiliary"; cache.mkdir(parents=True, exist_ok=True)
    target_ids = base_arrays["target_id"].astype(str)
    unique = list(dict.fromkeys(target_ids.tolist()))
    completed, failures = [], []
    for number, target_id in enumerate(unique, 1):
        indices = np.flatnonzero(target_ids == target_id)
        starts = base_arrays["start"][indices].astype(np.int32)
        product = products.get(target_id)
        path = (ROOT / "data/raw/tess/target_pixels" / ("TIC" + target_id)
                / product["filename"]) if product else None
        data_path = cache / ("TIC" + target_id + ".npz")
        receipt_path = cache / ("TIC" + target_id + ".json")
        try:
            if data_path.is_file() and receipt_path.is_file():
                receipt = _checked_json(receipt_path, "complete")
                if (receipt.get("spec_sha256") != spec_sha
                        or receipt.get("sha256") != file_sha256(data_path)
                        or receipt.get("starts_sha256") != _starts_sha(starts)):
                    raise ValueError("Auxiliary target receipt mismatch")
            else:
                if path is None:
                    raise ValueError("No target-pixel product is planned")
                pixels = read_target_pixels(path, target_id)
                instrument = normalize_instrument(pixels)
                length = base_arrays["flux"].shape[1]
                if np.any(starts < 0) or np.any(starts + length > instrument.shape[1]):
                    raise ValueError("Base window exceeds the auxiliary cadence range")
                windows = np.stack([instrument[:, start:start + length] for start in starts])
                context = np.repeat(context_vector(pixels.context)[None, :], len(starts), axis=0)
                _atomic_npz(data_path, start=starts, instrument=windows.astype(np.float16),
                            context_raw=context)
                atomic_json(receipt_path, {"status": "complete", "target_id": target_id,
                    "spec_sha256": spec_sha, "source_sha256": pixels.sha256,
                    "starts_sha256": _starts_sha(starts), "windows": len(starts),
                    "sha256": file_sha256(data_path)})
            completed.append((target_id, indices, data_path, receipt_path))
        except Exception as exc:
            failures.append({"target_id": target_id, "type": type(exc).__name__, "reason": str(exc)})
        if number % 25 == 0 or number == len(unique):
            print(json.dumps({"stage": "auxiliary_dataset", "processed": number,
                              "targets": len(unique), "complete": len(completed),
                              "failures": len(failures)}), flush=True)
    if len(completed) != len(unique):
        raise ValueError("Every base-run target must have aligned auxiliary data")
    instrument = np.empty((len(target_ids), 3, base_arrays["flux"].shape[1]), dtype=np.float16)
    context_raw = np.full((len(target_ids), len(CONTEXT_FEATURES)), np.nan, dtype=np.float32)
    for target_id, indices, data_path, _ in completed:
        with np.load(data_path, allow_pickle=False) as saved:
            if not np.array_equal(saved["start"], base_arrays["start"][indices]):
                raise ValueError("Auxiliary windows changed order for TIC " + target_id)
            instrument[indices] = saved["instrument"]
            context_raw[indices] = saved["context_raw"]
    train_indices = np.flatnonzero(base_arrays["role"] == "train")
    _, first = np.unique(target_ids[train_indices], return_index=True)
    train_context = context_raw[train_indices[first]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        center = np.nanmedian(train_context, axis=0)
        scale = 1.4826 * np.nanmedian(np.abs(train_context - center), axis=0)
        fallback = np.nanstd(train_context, axis=0)
    center = np.where(np.isfinite(center), center, 0.)
    scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, fallback)
    scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, 1.)
    available = np.isfinite(context_raw)
    standardized = np.clip((context_raw - center) / scale, -10, 10)
    standardized[~available] = 0
    context = np.concatenate([standardized, available.astype(np.float32)], axis=1).astype(np.float32)
    arrays = {**base_arrays, "instrument": instrument, "context": context}
    dataset_path = output / "dataset.npz"
    _atomic_npz(dataset_path, **arrays)
    context_stats = {"features": list(CONTEXT_FEATURES), "fit_scope": "unique_train_hosts_only",
                     "center": center.astype(float).tolist(), "scale": scale.astype(float).tolist(),
                     "availability": {name: int(available[:, i].sum())
                                      for i, name in enumerate(CONTEXT_FEATURES)}}
    atomic_json(output / "context_stats.json", context_stats)
    receipt = {"status": "complete", "version": VERSION, "created_at": utc_now(),
               "targets": len(completed), "windows": len(target_ids), "failures": failures,
               "roles": {role: int(np.sum(base_arrays["role"] == role)) for role in
                         ("train", "selection", "calibration", "audit")},
               "files": {"dataset.npz": file_sha256(dataset_path),
                         "context_stats.json": file_sha256(output / "context_stats.json")},
               "target_receipts": {_receipt_key(path): file_sha256(path)
                                   for _, _, _, path in completed}}
    atomic_json(output / "dataset_complete.json", receipt)
    return arrays, receipt


def load_dataset(output, spec_sha):
    receipt_path = output / "dataset_complete.json"
    if not receipt_path.is_file():
        return None, None
    receipt = _checked_json(receipt_path, "complete")
    for name, checksum in receipt["files"].items():
        if file_sha256(output / name) != checksum:
            raise ValueError("Context-v2 dataset checksum mismatch: " + name)
    sample = next((output / "auxiliary").glob("TIC*.json"))
    if _checked_json(sample)["spec_sha256"] != spec_sha:
        raise ValueError("Context-v2 cached dataset specification mismatch")
    with np.load(output / "dataset.npz", allow_pickle=False) as saved:
        return {key: saved[key] for key in saved.files}, receipt


def tensors(arrays, use):
    target_ids = arrays["target_id"].astype(str)
    mapping = {target: number for number, target in enumerate(sorted(set(target_ids.tolist())))}
    groups = np.asarray([mapping[x] for x in target_ids], dtype=np.int64)
    return TensorDataset(torch.from_numpy(arrays["flux"][use]),
                         torch.from_numpy(arrays["valid"][use].astype(np.float32)),
                         torch.from_numpy(arrays["pixel"][use].astype(np.float32)),
                         torch.from_numpy(arrays["event"][use].astype(np.float32)),
                         torch.from_numpy(arrays["instrument"][use].astype(np.float32)),
                         torch.from_numpy(arrays["context"][use].astype(np.float32)),
                         torch.from_numpy(groups[use]))


def loader(dataset, batch, shuffle, seed):
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(dataset, batch_size=batch, shuffle=shuffle, generator=generator,
                      num_workers=0, drop_last=shuffle and len(dataset) >= batch)


def symmetric_contrastive(left, right, temperature):
    similarity = left @ right.T / temperature
    target = torch.arange(len(left), device=left.device)
    return (torch.nn.functional.cross_entropy(similarity, target)
            + torch.nn.functional.cross_entropy(similarity.T, target)) / 2


def grouped_contrastive(left, right, groups, temperature):
    similarity = left @ right.T / temperature
    positive = groups[:, None] == groups[None, :]
    def direction(scores, mask):
        numerator = torch.logsumexp(scores.masked_fill(~mask, -torch.inf), dim=1)
        denominator = torch.logsumexp(scores, dim=1)
        return torch.mean(denominator - numerator)
    return (direction(similarity, positive) + direction(similarity.T, positive.T)) / 2


def auxiliary_views(model, flux, valid, hidden, instrument, context):
    visible = flux.masked_fill(hidden.bool(), 0.)
    with torch.no_grad():
        _, light = model.light(visible, valid, hidden)
        light = torch.nn.functional.normalize(model.light_projection(light), dim=1)
    instrument_value = torch.nn.functional.normalize(
        model.instrument_projection(model.instrument(instrument, valid)), dim=1)
    context_value = torch.nn.functional.normalize(
        model.context_projection(model.context(context)), dim=1)
    return light, instrument_value, context_value


def train_auxiliary(arrays, config, output):
    torch.manual_seed(config["seed"])
    base_checkpoint = torch.load(ROOT / config["base_run"] / "pretrained.pt",
                                 map_location="cpu", weights_only=True)
    base = MultimodalPretrainer(config["embedding_dim"])
    base.load_state_dict(base_checkpoint["model_state"])
    model = ExtendedMultimodalPretrainer(arrays["context"].shape[1], config["embedding_dim"],
                                         config["instrument_channels"])
    model.load_light_pixel(base); model.freeze_light_pixel()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                  lr=config["learning_rate"], weight_decay=config["weight_decay"])
    train_use, selection_use = arrays["role"] == "train", arrays["role"] == "selection"
    train_loader = loader(tensors(arrays, train_use), config["batch_size"], True, config["seed"])
    selection_loader = loader(tensors(arrays, selection_use), config["batch_size"], False, config["seed"])
    best, best_loss, history = None, np.inf, []
    mask_generator = torch.Generator().manual_seed(config["seed"] + 200)
    for epoch in range(1, config["auxiliary_pretrain_epochs"] + 1):
        model.train(); train_values = []
        for flux, valid, _, _, instrument, context, groups in train_loader:
            hidden = ((torch.rand(flux.shape, generator=mask_generator) < config["mask_fraction"])
                      & valid.bool()).float()
            optimizer.zero_grad(set_to_none=True)
            light, instrument_value, context_value = auxiliary_views(
                model, flux, valid, hidden, instrument, context)
            instrument_loss = symmetric_contrastive(
                light, instrument_value, config["contrastive_temperature"])
            context_loss = grouped_contrastive(
                light, context_value, groups, config["contrastive_temperature"])
            loss = (config["instrument_contrastive_weight"] * instrument_loss
                    + config["context_contrastive_weight"] * context_loss)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            train_values.append((float(loss.detach()), float(instrument_loss.detach()),
                                 float(context_loss.detach())))
        model.eval(); selection_values = []
        validation_generator = torch.Generator().manual_seed(config["seed"] + 2000 + epoch)
        with torch.inference_mode():
            for flux, valid, _, _, instrument, context, groups in selection_loader:
                hidden = ((torch.rand(flux.shape, generator=validation_generator)
                           < config["mask_fraction"]) & valid.bool()).float()
                light, instrument_value, context_value = auxiliary_views(
                    model, flux, valid, hidden, instrument, context)
                instrument_loss = symmetric_contrastive(
                    light, instrument_value, config["contrastive_temperature"])
                context_loss = grouped_contrastive(
                    light, context_value, groups, config["contrastive_temperature"])
                selection_values.append(float(
                    config["instrument_contrastive_weight"] * instrument_loss
                    + config["context_contrastive_weight"] * context_loss))
        mean_train = np.mean(train_values, axis=0)
        row = {"epoch": epoch, "train_loss": float(mean_train[0]),
               "train_instrument_contrastive": float(mean_train[1]),
               "train_context_contrastive": float(mean_train[2]),
               "selection_loss": float(np.mean(selection_values))}
        history.append(row); print(json.dumps({"stage": "auxiliary_pretrain", **row}), flush=True)
        if row["selection_loss"] < best_loss:
            best_loss, best = row["selection_loss"], copy.deepcopy(model.state_dict())
    model.load_state_dict(best); model.eval()
    torch.save({"version": VERSION, "config": config, "model_state": best,
                "best_selection_loss": best_loss, "history": history},
               output / "extended_pretrained.pt")
    return model, history


def predict_extended(model, dataset, batch_size, use_instrument=True, use_context=True):
    model.eval(); values = []
    with torch.inference_mode():
        for flux, valid, pixel, _, instrument, context, _ in loader(dataset, batch_size, False, 0):
            values.append(model(flux, valid, pixel, instrument, context,
                                use_instrument=use_instrument,
                                use_context=use_context).numpy())
    return np.concatenate(values)


def train_extended(arrays, config, pretrained, seed):
    torch.manual_seed(seed)
    model = ExtendedEventLocalizer(arrays["context"].shape[1], config["embedding_dim"],
                                   config["instrument_channels"])
    if pretrained is not None:
        model.load_pretrained(pretrained)
    train_use, selection_use = arrays["role"] == "train", arrays["role"] == "selection"
    train_data, selection_data = tensors(arrays, train_use), tensors(arrays, selection_use)
    y, valid = arrays["event"][train_use], arrays["valid"][train_use].astype(bool)
    positive, negative = int(y[valid].sum()), int(valid.sum() - y[valid].sum())
    positive_weight = min(negative / max(positive, 1), config["maximum_positive_weight"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    drop_generator = torch.Generator().manual_seed(seed + 4000)
    best, best_ap, history = None, -1., []
    for epoch in range(1, config["localization_epochs"] + 1):
        model.train(); losses = []
        for flux, batch_valid, pixel, event, instrument, context, _ in loader(
                train_data, config["batch_size"], True, seed + epoch):
            use_instrument = bool(torch.rand((), generator=drop_generator) >= config["modality_dropout"])
            use_context = bool(torch.rand((), generator=drop_generator) >= config["modality_dropout"])
            optimizer.zero_grad(set_to_none=True)
            logits = model(flux, batch_valid, pixel, instrument, context,
                           use_instrument=use_instrument, use_context=use_context)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                logits[batch_valid.bool()], event[batch_valid.bool()],
                pos_weight=torch.tensor(positive_weight))
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            losses.append(float(loss.detach()))
        selection_logits = predict_extended(model, selection_data, config["batch_size"])
        score = event_metrics(arrays["event"][selection_use], selection_logits,
                              arrays["valid"][selection_use])["average_precision"]
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)),
               "selection_event_ap": score}
        history.append(row); print(json.dumps(
            {"stage": "extended_localize", "pretrained": pretrained is not None, **row}), flush=True)
        if score > best_ap:
            best_ap, best = score, copy.deepcopy(model.state_dict())
    model.load_state_dict(best); model.eval()
    return model, history, positive_weight


def base_predictions(config, arrays, use):
    checkpoint = torch.load(ROOT / config["base_run"] / "ai_telescope.pt",
                            map_location="cpu", weights_only=True)
    model = EventLocalizer(config["embedding_dim"])
    model.load_state_dict(checkpoint["localizer"])
    basic = TensorDataset(torch.from_numpy(arrays["flux"][use]),
                          torch.from_numpy(arrays["valid"][use].astype(np.float32)),
                          torch.from_numpy(arrays["pixel"][use].astype(np.float32)),
                          torch.from_numpy(arrays["event"][use].astype(np.float32)))
    return predict_localizer(model, basic, config["batch_size"])


def build_anomalies(model, arrays, config, output):
    all_data = tensors(arrays, np.ones(len(arrays["role"]), dtype=bool))
    embeddings = []
    model.eval()
    with torch.inference_mode():
        for flux, valid, pixel, _, instrument, context, _ in loader(
                all_data, config["batch_size"], False, 0):
            embeddings.append(model.encode(flux, valid, pixel, instrument, context).numpy())
    embeddings = np.concatenate(embeddings)
    train = arrays["role"] == "train"
    detector = IsolationForest(n_estimators=300, max_samples="auto", contamination="auto",
                               random_state=config["seed"], n_jobs=config["cpu_threads"]).fit(embeddings[train])
    score = -detector.score_samples(embeddings)
    frame = pd.DataFrame({"target_id": arrays["target_id"], "sector": arrays["sector"],
                          "role": arrays["role"], "window_start": arrays["start"],
                          "event_fraction": arrays["event"].mean(axis=1),
                          "anomaly_score": score})
    frame.sort_values("anomaly_score", ascending=False).to_csv(
        output / "anomalies_extended.csv", index=False)
    return {"method": "isolation_forest_on_frozen_four_view_embeddings",
            "fit_windows": int(train.sum()),
            "top_audit": frame[frame.role.eq("audit")].nlargest(10, "anomaly_score").to_dict("records")}


def run(config, arrays, dataset_receipt, output):
    pretrainer, pretrain_history = train_auxiliary(arrays, config, output)
    pretrained, pretrained_history, positive_weight = train_extended(
        arrays, config, pretrainer, config["seed"] + 10)
    scratch, scratch_history, _ = train_extended(arrays, config, None, config["seed"] + 10)
    predictions = {role: {} for role in ("calibration", "audit")}
    labels, valid = {}, {}
    for role in predictions:
        use = arrays["role"] == role
        data = tensors(arrays, use)
        labels[role], valid[role] = arrays["event"][use], arrays["valid"][use]
        predictions[role]["base_v1"] = base_predictions(config, arrays, use)
        predictions[role]["extended_scratch"] = predict_extended(
            scratch, data, config["batch_size"])
        predictions[role]["extended_full"] = predict_extended(
            pretrained, data, config["batch_size"])
        predictions[role]["extended_no_instrument"] = predict_extended(
            pretrained, data, config["batch_size"], use_instrument=False)
        predictions[role]["extended_no_context"] = predict_extended(
            pretrained, data, config["batch_size"], use_context=False)
        predictions[role]["extended_no_auxiliary"] = predict_extended(
            pretrained, data, config["batch_size"], use_instrument=False, use_context=False)
    thresholds = {name: choose_threshold(labels["calibration"], values,
                                          valid["calibration"], config["calibration_fpr_target"])
                  for name, values in predictions["calibration"].items()}
    audit = {name: event_metrics(labels["audit"], values, valid["audit"],
                                 thresholds[name]["threshold"])
             for name, values in predictions["audit"].items()}
    original = _checked_json(ROOT / config["base_run"] / "summary.json")["localization"]["audit"]["pretrained"]
    if abs(audit["base_v1"]["average_precision"] - original["average_precision"]) > 1e-9:
        raise ValueError("Recomputed v1 audit result differs from the frozen base receipt")
    anomaly = build_anomalies(pretrainer, arrays, config, output)
    torch.save({"version": VERSION, "config": config, "pretrainer": pretrainer.state_dict(),
                "localizer": pretrained.state_dict(), "threshold": thresholds["extended_full"]},
               output / "ai_telescope_context.pt")
    full, base, scratch = audit["extended_full"], audit["base_v1"], audit["extended_scratch"]
    beat_controls = (full["average_precision"] > max(base["average_precision"], scratch["average_precision"])
                     and full["threshold"]["recall"] >= max(
                         base["threshold"]["recall"], scratch["threshold"]["recall"]))
    modalities_help = (full["average_precision"] > audit["extended_no_instrument"]["average_precision"]
                       and full["average_precision"] > audit["extended_no_context"]["average_precision"])
    return {"status": "complete", "version": VERSION, "completed_at": utc_now(),
            "dataset": {key: dataset_receipt[key] for key in ("targets", "windows", "roles")},
            "objectives": ["inherited_masked_light_curve_reconstruction",
                           "inherited_light_pixel_contrastive_alignment",
                           "light_instrument_contrastive_alignment",
                           "same_host_light_context_contrastive_alignment",
                           "per_cadence_event_localization", "four_view_embedding_anomaly_ranking"],
            "auxiliary_pretraining": {"frozen_base_during_auxiliary_pretraining": True,
                                      "best_selection_loss": min(x["selection_loss"] for x in pretrain_history),
                                      "history": pretrain_history},
            "localization": {"positive_weight": positive_weight,
                             "pretrained_history": pretrained_history,
                             "scratch_history": scratch_history,
                             "calibration_thresholds": thresholds, "audit": audit},
            "anomaly": anomaly,
            "claims": {"extended_model_beats_v1_and_scratch_on_declared_metrics": bool(beat_controls),
                       "both_new_modalities_help_audit_ap_in_ablation": bool(modalities_help),
                       "gaia_catalog_integrated": False, "raw_spectra_integrated": False,
                       "blind_planet_discovery": False, "deployed_to_watcher": False,
                       "planet_probability": False},
            "limitations": [
                "Host context comes from SPOC/TIC headers; a separately provenance-checked Gaia table is not yet integrated",
                "Pointing corrections and background flux are instrument proxies, not the complete spacecraft event stream",
                "Known catalog ephemerides still define event-localization supervision",
                "Audit hosts are group-disjoint but validation-derived and were reused by the v1 pilot",
                "Ablations zero pretrained branches and are diagnostic rather than independently retrained models",
            ]}


def write_report(path, summary):
    audit = summary["localization"]["audit"]
    names = ("base_v1", "extended_scratch", "extended_no_auxiliary",
             "extended_no_instrument", "extended_no_context", "extended_full")
    lines = ["# AI-telescope instrument and host-context v2", "",
             "The frozen winning light/pixel representation is extended with TESS pointing, background, "
             "SPOC/TIC host and observing-context views.", "",
             "| Method | Event AP | ROC AUC | Brier | Recall @ calibration FPR | Audit FPR |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in names:
        row, threshold = audit[name], audit[name]["threshold"]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | "
                     f"{row['roc_auc']:.4f} | {row['brier']:.4f} | "
                     f"{threshold['recall']:.4f} | {threshold['fpr']:.4f} |")
    lines += ["", "## Declared outcomes", "",
              f"Beat frozen v1 and extended scratch on AP and recall: "
              f"**{summary['claims']['extended_model_beats_v1_and_scratch_on_declared_metrics']}**.",
              f"Both new modalities improved full-model audit AP in zero-branch ablations: "
              f"**{summary['claims']['both_new_modalities_help_audit_ap_in_ablation']}**.",
              "", "## Boundaries", "", *["- " + x for x in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_context_v2.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    torch.set_num_threads(config["cpu_threads"])
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    base_arrays, base_complete, _ = load_base(config)
    physical_complete = _checked_json(ROOT / config["physical_run"] / "complete.json", "complete")
    sources = ("scripts/experiments/ai_telescope_v2.py", "training/ai_telescope.py",
               "scripts/research/pixels.py", "scripts/experiments/ai_telescope.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "base_spec_sha256": base_complete["spec_sha256"],
            "physical_spec_sha256": physical_complete["spec_sha256"],
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.is_file() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing context-v2 output uses a different specification")
    if (output / "complete.json").is_file():
        raise ValueError("Context-v2 experiment is already complete")
    atomic_json(spec_path, spec)
    arrays, dataset_receipt = load_dataset(output, spec_sha)
    if arrays is None:
        arrays, dataset_receipt = prepare_dataset(config, base_arrays, output, spec_sha)
    summary = run(config, arrays, dataset_receipt, output)
    summary["spec_sha256"] = spec_sha
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "dataset_complete.json", "context_stats.json", "summary.json",
              "report.md", "extended_pretrained.pt", "ai_telescope_context.pt",
              "anomalies_extended.csv")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output),
                      "claims": summary["claims"],
                      "audit": summary["localization"]["audit"]}, indent=2))


if __name__ == "__main__":
    main()
