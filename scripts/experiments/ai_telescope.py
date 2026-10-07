#!/usr/bin/env python3
"""Resumable light-curve/pixel self-supervision and direct event-localization pilot."""
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
from scipy.special import expit
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.detection import phase_distance
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import EventLocalizer, MultimodalPretrainer

VERSION = "ai_telescope_multimodal_pilot_v1"
FIELDS = {"schema_version", "cohort", "physical_run", "output", "window_length",
          "pixel_frames", "spatial_size", "random_windows_per_target",
          "event_windows_per_candidate", "embedding_dim", "pretrain_epochs",
          "localization_epochs", "batch_size", "learning_rate", "weight_decay",
          "mask_fraction", "contrastive_temperature", "contrastive_weight",
          "maximum_positive_weight", "calibration_fpr_target", "seed", "cpu_threads"}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("AI-telescope configuration differs from schema")
    for key in ("cohort", "physical_run", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("AI-telescope paths must remain inside the project")
    for key, low, high in (
        ("window_length", 64, 2048), ("pixel_frames", 8, 128), ("spatial_size", 7, 31),
        ("random_windows_per_target", 1, 32), ("event_windows_per_candidate", 1, 8),
        ("embedding_dim", 16, 256), ("pretrain_epochs", 1, 100),
        ("localization_epochs", 1, 100), ("batch_size", 4, 256),
        ("seed", 0, 2**31 - 1), ("cpu_threads", 1, 8)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    for key, low, high in (
        ("learning_rate", 1e-6, .1), ("weight_decay", 0., 1.),
        ("mask_fraction", .05, .8), ("contrastive_temperature", .01, 2.),
        ("contrastive_weight", 0., 10.), ("maximum_positive_weight", 1., 1000.),
        ("calibration_fpr_target", 0., .5)):
        item = value[key]
        if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError("Invalid " + key)
    if value["window_length"] % value["pixel_frames"] or value["spatial_size"] % 2 != 1:
        raise ValueError("Window length must divide into pixel frames and spatial size must be odd")
    return value


def center_crop_or_pad(value, size):
    if value.ndim != 3:
        raise ValueError("Expected time-by-height-by-width pixel data")
    output = np.zeros((len(value), size, size), dtype=value.dtype)
    h, w = value.shape[1:]
    take_h, take_w = min(h, size), min(w, size)
    source_y, source_x = max((h - size) // 2, 0), max((w - size) // 2, 0)
    target_y, target_x = max((size - h) // 2, 0), max((size - w) // 2, 0)
    output[:, target_y:target_y + take_h, target_x:target_x + take_w] = \
        value[:, source_y:source_y + take_h, source_x:source_x + take_w]
    return output


def normalize_target(pixels, candidates):
    cube = np.asarray(pixels.flux, dtype=np.float32)
    aperture = pixels.aperture
    mask = (aperture & 2) != 0
    if not mask.any():
        mask = aperture > 0
    if not mask.any():
        raise ValueError("Target has no usable aperture")
    light = np.nansum(cube[:, mask], axis=1)
    valid = (pixels.quality == 0) & np.isfinite(pixels.time) & np.isfinite(light)
    if valid.sum() < 1024:
        raise ValueError("Target has insufficient valid cadences")
    median = float(np.median(light[valid]))
    scale = 1.4826 * float(np.median(np.abs(light[valid] - median)))
    scale = max(scale, abs(median) * 1e-5, 1e-6)
    light = np.clip((light - median) / scale, -12, 12).astype(np.float32)
    light[~valid] = 0
    event = np.zeros(len(light), dtype=bool)
    for candidate in candidates:
        period = float(candidate["period_days"])
        epoch = float(candidate["epoch_bjd_tdb"]) - 2457000.
        duration = float(candidate["duration_hours"]) / 24
        event |= np.abs(phase_distance(pixels.time, period, epoch)) <= duration / 2
    event &= valid
    return cube, light, valid, event


def window_starts(length, event, candidates, time, config, target_id):
    maximum = length - config["window_length"]
    if maximum < 0:
        return []
    rng = np.random.default_rng(np.random.SeedSequence([config["seed"], int(target_id) % (2**32)]))
    starts = []
    event_indices = np.flatnonzero(event)
    if len(event_indices):
        blocks = np.split(event_indices, np.flatnonzero(np.diff(event_indices) > 1) + 1)
        centers = [int(block[len(block) // 2]) for block in blocks]
        rng.shuffle(centers)
        wanted = max(config["event_windows_per_candidate"] * len(candidates), 1)
        for center in centers[:wanted]:
            starts.append(int(np.clip(center - config["window_length"] // 2, 0, maximum)))
    candidates_start = np.arange(maximum + 1)
    if len(candidates_start):
        for start in rng.choice(candidates_start, size=min(config["random_windows_per_target"], len(candidates_start)),
                                replace=False):
            starts.append(int(start))
    return list(dict.fromkeys(starts))


def extract_windows(target, tpf_path, config):
    pixels = read_target_pixels(tpf_path, target["target_id"])
    cube, light, valid, event = normalize_target(pixels, target["candidates"])
    starts = window_starts(len(light), event, target["candidates"], pixels.time, config, target["target_id"])
    output = {key: [] for key in ("flux", "valid", "pixel", "event", "start")}
    stride = config["window_length"] // config["pixel_frames"]
    for start in starts:
        stop = start + config["window_length"]
        chosen = start + np.arange(config["pixel_frames"]) * stride + stride // 2
        frames = cube[chosen]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            reference = np.nanmedian(cube[start:stop][valid[start:stop]], axis=0)
        finite_reference = np.abs(reference[np.isfinite(reference)])
        floor = float(np.median(finite_reference)) * 1e-3 + 1e-6 if len(finite_reference) else 1.
        denominator = np.maximum(np.abs(reference), floor)
        residual = np.clip((frames - reference) / denominator, -.25, .25) / .05
        residual[~np.isfinite(residual)] = 0
        output["flux"].append(light[start:stop])
        output["valid"].append(valid[start:stop].astype(np.uint8))
        output["event"].append(event[start:stop].astype(np.uint8))
        output["pixel"].append(center_crop_or_pad(residual.astype(np.float32), config["spatial_size"]))
        output["start"].append(start)
    if not output["flux"]:
        raise ValueError("No valid windows were extracted")
    return {"flux": np.asarray(output["flux"], np.float32),
            "valid": np.asarray(output["valid"], np.uint8),
            "event": np.asarray(output["event"], np.uint8),
            "pixel": np.asarray(output["pixel"], np.float16),
            "start": np.asarray(output["start"], np.int32),
            "target_id": np.asarray([target["target_id"]] * len(output["start"])),
            "role": np.asarray([target["candidates"][0]["role"]] * len(output["start"])),
            "sector": np.asarray([target["sector"]] * len(output["start"]), np.int16)}


def _atomic_npz(path, **arrays):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def prepare_dataset(config, output, spec_sha):
    cohort_path = ROOT / config["cohort"]
    cohort = json.loads(cohort_path.read_text())
    if cohort.get("target_count") != len(cohort.get("targets", [])) or cohort.get("status") != "frozen_before_pixel_feature_inspection":
        raise ValueError("Unexpected labelled physical cohort")
    plan = json.loads((ROOT / config["physical_run"] / "download_plan.json").read_text())
    products = {str(row["target_id"]): row for row in plan["products"]}
    cache = output / "windows"; cache.mkdir(parents=True, exist_ok=True)
    completed, failures = [], []
    for number, target in enumerate(cohort["targets"], 1):
        target_id = str(target["target_id"]); product = products.get(target_id)
        if product is None:
            failures.append({"target_id": target_id, "reason": "no_planned_tpf"}); continue
        path = ROOT / "data/raw/tess/target_pixels" / ("TIC" + target_id) / product["filename"]
        window_path, receipt_path = cache / ("TIC" + target_id + ".npz"), cache / ("TIC" + target_id + ".json")
        try:
            if window_path.is_file() and receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text())
                if receipt.get("spec_sha256") != spec_sha or receipt.get("sha256") != file_sha256(window_path):
                    raise ValueError("Cached target receipt mismatch")
            else:
                arrays = extract_windows(target, path, config)
                _atomic_npz(window_path, **arrays)
                atomic_json(receipt_path, {"status": "complete", "target_id": target_id,
                    "spec_sha256": spec_sha, "windows": len(arrays["flux"]), "sha256": file_sha256(window_path)})
            completed.append((window_path, receipt_path))
        except Exception as exc:
            failures.append({"target_id": target_id, "type": type(exc).__name__, "reason": str(exc)})
        if number % 25 == 0 or number == len(cohort["targets"]):
            print(json.dumps({"stage": "dataset", "processed": number, "targets": len(cohort["targets"]),
                              "complete": len(completed), "failures": len(failures)}), flush=True)
    if len(completed) < int(.95 * len(cohort["targets"])):
        raise ValueError("Fewer than 95% of targets produced paired windows")
    combined = {}
    for path, _ in completed:
        with np.load(path, allow_pickle=False) as saved:
            for key in saved.files:
                combined.setdefault(key, []).append(saved[key])
    combined = {key: np.concatenate(values) for key, values in combined.items()}
    dataset_path = output / "dataset.npz"
    _atomic_npz(dataset_path, **combined)
    receipt = {"status": "complete", "version": VERSION, "created_at": utc_now(),
               "targets": len(completed), "windows": len(combined["flux"]), "failures": failures,
               "roles": {role: int(np.sum(combined["role"] == role)) for role in
                         ("train", "selection", "calibration", "audit")},
               "event_cadences": int(combined["event"].sum()),
               "files": {"dataset.npz": file_sha256(dataset_path)},
               "target_receipts": {str(p.relative_to(ROOT)): file_sha256(p) for _, p in completed}}
    atomic_json(output / "dataset_complete.json", receipt)
    return combined, receipt


def load_dataset(output, spec_sha):
    receipt_path = output / "dataset_complete.json"
    if not receipt_path.is_file():
        return None, None
    receipt = json.loads(receipt_path.read_text()); path = output / "dataset.npz"
    if receipt.get("files", {}).get("dataset.npz") != file_sha256(path):
        raise ValueError("AI-telescope dataset checksum mismatch")
    # Per-target receipts carry the experiment identity and protect resumability.
    sample_receipt = next((output / "windows").glob("TIC*.json"))
    if json.loads(sample_receipt.read_text()).get("spec_sha256") != spec_sha:
        raise ValueError("AI-telescope cached dataset specification mismatch")
    with np.load(path, allow_pickle=False) as saved:
        return {key: saved[key] for key in saved.files}, receipt


def tensors(arrays, use):
    return TensorDataset(torch.from_numpy(arrays["flux"][use]),
                         torch.from_numpy(arrays["valid"][use].astype(np.float32)),
                         torch.from_numpy(arrays["pixel"][use].astype(np.float32)),
                         torch.from_numpy(arrays["event"][use].astype(np.float32)))


def loader(dataset, batch, shuffle, seed):
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(dataset, batch_size=batch, shuffle=shuffle, generator=generator,
                      num_workers=0, drop_last=shuffle and len(dataset) >= batch)


def ssl_loss(model, batch, config, generator, train=True):
    flux, valid, pixel, _ = batch
    hidden = ((torch.rand(flux.shape, generator=generator) < config["mask_fraction"])
              & valid.bool())
    reconstructed, light, image = model(flux, valid, hidden.float(), pixel)
    use = hidden & valid.bool()
    reconstruction = torch.mean((reconstructed[use] - flux[use]) ** 2) if use.any() else reconstructed.sum() * 0
    similarity = light @ image.T / config["contrastive_temperature"]
    target = torch.arange(len(flux))
    contrastive = (torch.nn.functional.cross_entropy(similarity, target)
                   + torch.nn.functional.cross_entropy(similarity.T, target)) / 2
    return reconstruction + config["contrastive_weight"] * contrastive, reconstruction, contrastive


def train_pretrainer(arrays, config, output):
    torch.manual_seed(config["seed"])
    model = MultimodalPretrainer(config["embedding_dim"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    train_use, selection_use = arrays["role"] == "train", arrays["role"] == "selection"
    train_loader = loader(tensors(arrays, train_use), config["batch_size"], True, config["seed"])
    selection_loader = loader(tensors(arrays, selection_use), config["batch_size"], False, config["seed"])
    best, best_loss, history = None, np.inf, []
    mask_generator = torch.Generator().manual_seed(config["seed"] + 1)
    for epoch in range(1, config["pretrain_epochs"] + 1):
        model.train(); train_values = []
        for batch in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss, reconstruction, contrastive = ssl_loss(model, batch, config, mask_generator)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            train_values.append((float(loss.detach()), float(reconstruction.detach()), float(contrastive.detach())))
        model.eval(); selection_values = []
        validation_generator = torch.Generator().manual_seed(config["seed"] + 1000 + epoch)
        with torch.inference_mode():
            for batch in selection_loader:
                selection_values.append(float(ssl_loss(model, batch, config, validation_generator)[0]))
        row = {"epoch": epoch, "train_loss": float(np.mean(train_values, axis=0)[0]),
               "train_reconstruction": float(np.mean(train_values, axis=0)[1]),
               "train_contrastive": float(np.mean(train_values, axis=0)[2]),
               "selection_loss": float(np.mean(selection_values))}
        history.append(row); print(json.dumps({"stage": "pretrain", **row}), flush=True)
        if row["selection_loss"] < best_loss:
            best_loss, best = row["selection_loss"], copy.deepcopy(model.state_dict())
    model.load_state_dict(best); model.eval()
    torch.save({"version": VERSION, "config": config, "model_state": best,
                "best_selection_loss": best_loss, "history": history}, output / "pretrained.pt")
    return model, history


def event_metrics(labels, logits, valid, threshold=None):
    use = valid.astype(bool)
    y, z = labels[use].astype(int), logits[use]
    probability = expit(z)
    result = {"cadences": int(len(y)), "positive_cadences": int(y.sum()),
              "average_precision": float(average_precision_score(y, z)),
              "roc_auc": float(roc_auc_score(y, z)),
              "brier": float(np.mean((probability - y) ** 2))}
    if threshold is not None:
        selected = probability >= threshold
        tp, fp = int(np.sum(selected & (y == 1))), int(np.sum(selected & (y == 0)))
        result["threshold"] = {"value": float(threshold), "tp": tp, "fp": fp,
            "fn": int(y.sum()) - tp, "tn": int((y == 0).sum()) - fp,
            "recall": tp / int(y.sum()) if y.sum() else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "fpr": fp / int((y == 0).sum()) if (y == 0).sum() else None}
    return result


def predict_localizer(model, dataset, batch_size):
    model.eval(); values = []
    with torch.inference_mode():
        for flux, valid, pixel, _ in loader(dataset, batch_size, False, 0):
            values.append(model(flux, valid, pixel).numpy())
    return np.concatenate(values)


def train_localizer(arrays, config, pretrained, seed):
    torch.manual_seed(seed)
    model = EventLocalizer(config["embedding_dim"])
    if pretrained is not None:
        model.load_pretrained(pretrained)
    train_use, selection_use = arrays["role"] == "train", arrays["role"] == "selection"
    train_data, selection_data = tensors(arrays, train_use), tensors(arrays, selection_use)
    y, valid = arrays["event"][train_use], arrays["valid"][train_use].astype(bool)
    positive, negative = int(y[valid].sum()), int(valid.sum() - y[valid].sum())
    positive_weight = min(negative / max(positive, 1), config["maximum_positive_weight"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    best, best_ap, history = None, -1., []
    for epoch in range(1, config["localization_epochs"] + 1):
        model.train(); losses = []
        for flux, batch_valid, pixel, event in loader(train_data, config["batch_size"], True, seed + epoch):
            optimizer.zero_grad(set_to_none=True); logits = model(flux, batch_valid, pixel)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                logits[batch_valid.bool()], event[batch_valid.bool()],
                pos_weight=torch.tensor(positive_weight))
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            losses.append(float(loss.detach()))
        selection_logits = predict_localizer(model, selection_data, config["batch_size"])
        score = event_metrics(arrays["event"][selection_use], selection_logits,
                              arrays["valid"][selection_use])["average_precision"]
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), "selection_event_ap": score}
        history.append(row); print(json.dumps({"stage": "localize", "pretrained": pretrained is not None, **row}), flush=True)
        if score > best_ap:
            best_ap, best = score, copy.deepcopy(model.state_dict())
    model.load_state_dict(best); model.eval()
    return model, history, positive_weight


def choose_threshold(labels, logits, valid, fpr_target):
    use = valid.astype(bool); y, probability = labels[use].astype(int), expit(logits[use])
    negatives = y == 0
    threshold = float(np.quantile(probability[negatives], 1 - fpr_target, method="higher"))
    return {"threshold": threshold, "target_fpr": fpr_target,
            "scope": "calibration_hosts_only", "negative_cadences": int(negatives.sum())}


def build_anomalies(model, arrays, config, output):
    all_data = tensors(arrays, np.ones(len(arrays["role"]), dtype=bool))
    embeddings = []
    model.eval()
    with torch.inference_mode():
        for flux, valid, pixel, _ in loader(all_data, config["batch_size"], False, 0):
            embeddings.append(model.encode(flux, valid, pixel).numpy())
    embeddings = np.concatenate(embeddings)
    train = arrays["role"] == "train"
    detector = IsolationForest(n_estimators=300, max_samples="auto", contamination="auto",
                               random_state=config["seed"], n_jobs=config["cpu_threads"]).fit(embeddings[train])
    score = -detector.score_samples(embeddings)
    frame = pd.DataFrame({"target_id": arrays["target_id"], "sector": arrays["sector"],
                          "role": arrays["role"], "window_start": arrays["start"],
                          "event_fraction": arrays["event"].mean(axis=1), "anomaly_score": score})
    frame.sort_values("anomaly_score", ascending=False).to_csv(output / "anomalies.csv", index=False)
    return {"method": "isolation_forest_on_frozen_multimodal_embeddings",
            "fit_windows": int(train.sum()), "top_audit": frame[frame.role.eq("audit")]
            .nlargest(10, "anomaly_score").to_dict("records")}


def run(config, arrays, dataset_receipt, output):
    pretrainer, pretrain_history = train_pretrainer(arrays, config, output)
    pretrained, pretrained_history, positive_weight = train_localizer(
        arrays, config, pretrainer, config["seed"] + 10)
    scratch, scratch_history, _ = train_localizer(arrays, config, None, config["seed"] + 10)
    roles = {}
    for role in ("calibration", "audit"):
        use = arrays["role"] == role; data = tensors(arrays, use)
        roles[role] = {"labels": arrays["event"][use], "valid": arrays["valid"][use],
                       "pretrained": predict_localizer(pretrained, data, config["batch_size"]),
                       "scratch": predict_localizer(scratch, data, config["batch_size"]),
                       "flux_baseline": -arrays["flux"][use]}
    thresholds = {name: choose_threshold(roles["calibration"]["labels"], roles["calibration"][name],
                                         roles["calibration"]["valid"], config["calibration_fpr_target"])
                  for name in ("pretrained", "scratch", "flux_baseline")}
    audit = {name: event_metrics(roles["audit"]["labels"], roles["audit"][name],
                                 roles["audit"]["valid"], thresholds[name]["threshold"])
             for name in thresholds}
    anomaly = build_anomalies(pretrainer, arrays, config, output)
    torch.save({"version": VERSION, "config": config, "pretrainer": pretrainer.state_dict(),
                "localizer": pretrained.state_dict(), "threshold": thresholds["pretrained"]},
               output / "ai_telescope.pt")
    improvement = (audit["pretrained"]["average_precision"] > audit["scratch"]["average_precision"]
                   and audit["pretrained"]["threshold"]["recall"] >= audit["scratch"]["threshold"]["recall"])
    summary = {"status": "complete", "version": VERSION, "completed_at": utc_now(),
               "dataset": {key: dataset_receipt[key] for key in ("targets", "windows", "roles", "event_cadences")},
               "objectives": ["masked_light_curve_reconstruction", "paired_light_pixel_contrastive_alignment",
                              "per_cadence_event_localization", "embedding_anomaly_ranking"],
               "pretraining": {"best_selection_loss": min(x["selection_loss"] for x in pretrain_history),
                               "history": pretrain_history},
               "localization": {"positive_weight": positive_weight,
                                "pretrained_history": pretrained_history, "scratch_history": scratch_history,
                                "calibration_thresholds": thresholds, "audit": audit},
               "anomaly": anomaly,
               "claims": {"pretraining_improves_localization_on_reused_audit": bool(improvement),
                          "foundation_model": False, "blind_planet_discovery": False,
                          "planet_probability": False, "deployed_to_watcher": False},
               "limitations": ["Bounded 829-host candidate-enriched cohort, not a survey-scale foundation model",
                   "Event supervision uses known catalog ephemerides and detects events rather than planet identity",
                   "Audit hosts are group-disjoint but validation-derived and not a prospective discovery sample",
                   "Anomaly scores prioritize review and do not establish astrophysical novelty"]}
    return summary


def write_report(path, summary):
    audit = summary["localization"]["audit"]
    lines = ["# Autonomous AI-telescope multimodal pilot", "",
             "Self-supervised paired TESS light-curve/pixel pretraining followed by direct per-cadence event localization.", "",
             "| Method | Event AP | ROC AUC | Brier | Recall @ calibration FPR | Audit FPR |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in ("flux_baseline", "scratch", "pretrained"):
        row, threshold = audit[name], audit[name]["threshold"]
        lines.append(f"| {name.replace('_', ' ')} | {row['average_precision']:.4f} | {row['roc_auc']:.4f} | "
                     f"{row['brier']:.4f} | {threshold['recall']:.4f} | {threshold['fpr']:.4f} |")
    lines += ["", f"Pretraining improved the declared AP/recall criteria: "
              f"**{summary['claims']['pretraining_improves_localization_on_reused_audit']}**.",
              "", "## Boundaries", "", *["- " + item for item in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_pilot_v1.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    torch.set_num_threads(config["cpu_threads"])
    output = ROOT / config["output"]; output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/ai_telescope.py", "training/ai_telescope.py",
               "scripts/research/pixels.py", "scripts/research/detection.py")
    spec = {"version": VERSION, "config": config, "config_sha256": file_sha256(config_path),
            "cohort_sha256": file_sha256(ROOT / config["cohort"]),
            "physical_spec_sha256": json.loads((ROOT / config["physical_run"] / "complete.json").read_text())["spec_sha256"],
            "source_files": {name: file_sha256(ROOT / name) for name in sources}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.is_file() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing AI-telescope output uses a different specification")
    if (output / "complete.json").is_file():
        raise ValueError("AI-telescope pilot is already complete")
    atomic_json(spec_path, spec)
    arrays, dataset_receipt = load_dataset(output, spec_sha)
    if arrays is None:
        arrays, dataset_receipt = prepare_dataset(config, output, spec_sha)
    summary = run(config, arrays, dataset_receipt, output)
    summary["spec_sha256"] = spec_sha
    atomic_json(output / "summary.json", summary); write_report(output / "report.md", summary)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "dataset_complete.json", "summary.json", "report.md",
              "pretrained.pt", "ai_telescope.pt", "anomalies.csv")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": str(output),
                      "claim": summary["claims"]["pretraining_improves_localization_on_reused_audit"],
                      "audit": summary["localization"]["audit"]}, indent=2))


if __name__ == "__main__":
    main()
