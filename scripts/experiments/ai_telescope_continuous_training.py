#!/usr/bin/env python3
"""Fine-tune the four-view localizer for continuous low-depth event scans."""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from scripts.experiments.ai_telescope import event_metrics, normalize_target
from scripts.experiments.ai_telescope_blind_scan import (
    _checked_complete, _context, _pixel_window, scan_starts,
    validate_config as validate_scan_config,
)
from scripts.experiments.ai_telescope_continuous_validation import (
    aperture_mask, inject_transits, inverted_residual_control,
)
from scripts.experiments.ai_telescope_v2 import normalize_instrument
from scripts.experiments.mission_adaptation import atomic_json
from scripts.research.pixels import read_target_pixels
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.ai_telescope import ExtendedEventLocalizer

VERSION = "ai_telescope_continuous_training_v3"
FIELDS = {
    "schema_version", "base_model_run", "physical_run", "scan_config", "output",
    "depths", "durations_hours", "hard_negative_candidates", "epochs", "batch_size",
    "learning_rate", "weight_decay", "maximum_positive_weight",
    "synthetic_window_weight", "dice_weight", "distillation_weight",
    "modality_dropout", "seed", "cpu_threads",
}
ARRAY_KEYS = ("flux", "valid", "pixel", "event", "instrument", "context")


def validate_config(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema_version") != 1:
        raise ValueError("Continuous-training config differs from schema")
    for key in ("base_model_run", "physical_run", "scan_config", "output"):
        path = Path(value[key])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Continuous-training paths must stay inside the project")
    for key, low, high in (("depths", 1e-5, .1), ("durations_hours", .25, 24.)):
        items = value[key]
        if (not isinstance(items, list) or not items or len(set(items)) != len(items)
                or any(type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high
                       for x in items)):
            raise ValueError("Invalid " + key)
    for key, low, high in (("hard_negative_candidates", 2, 32), ("epochs", 1, 50),
                           ("batch_size", 4, 256), ("seed", 0, 2**31-1),
                           ("cpu_threads", 1, 8)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid " + key)
    for key, low, high in (("learning_rate", 1e-6, .01), ("weight_decay", 0., 1.),
                           ("maximum_positive_weight", 1., 1000.),
                           ("synthetic_window_weight", 1., 20.), ("dice_weight", 0., 2.),
                           ("distillation_weight", 0., 2.), ("modality_dropout", 0., .8)):
        item = value[key]
        if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError("Invalid " + key)
    return value


def factorial_schedule(target_ids, config, role):
    target_ids = sorted(map(str, target_ids), key=int)
    grid = list(itertools.product(config["depths"], config["durations_hours"]))
    seed_offset = 0 if role == "train" else 1
    rng = np.random.default_rng(np.random.SeedSequence([config["seed"], seed_offset]))
    values = []
    while len(values) < len(target_ids):
        cycle = list(grid)
        rng.shuffle(cycle)
        values.extend(cycle)
    return {target: {"depth": float(depth), "duration_hours": float(duration),
                     "mode": "single"}
            for target, (depth, duration) in zip(target_ids, values)}


def _window(pixels, start, event, context_stats, scan):
    cube, light, valid, _ = normalize_target(pixels, [])
    stop = start + scan["window_length"]
    if start < 0 or stop > len(light) or valid[start:stop].sum() < scan["window_length"] // 2:
        raise ValueError("Synthetic window has insufficient valid cadences")
    instrument = normalize_instrument(pixels)
    return {
        "flux": light[start:stop].astype(np.float32),
        "valid": valid[start:stop].astype(np.uint8),
        "pixel": _pixel_window(cube, valid, start, scan).astype(np.float16),
        "event": event[start:stop].astype(np.uint8),
        "instrument": instrument[:, start:stop].astype(np.float16),
        "context": _context(pixels.context, context_stats).astype(np.float32),
    }


def _model_score(model, windows):
    stack = lambda key, dtype=np.float32: torch.from_numpy(
        np.stack([x[key] for x in windows]).astype(dtype))
    valid = stack("valid")
    model.eval()
    with torch.inference_mode():
        logits = model(stack("flux"), valid, stack("pixel"), stack("instrument"),
                       stack("context"))
        probability = torch.sigmoid(logits).numpy()
    mask = valid.numpy().astype(bool)
    return np.asarray([float(row[use].max()) for row, use in zip(probability, mask)])


def training_center(pixels, scan, seed):
    aperture = aperture_mask(pixels)
    light = np.nansum(pixels.flux[:, aperture], axis=1)
    valid = ((pixels.quality == 0) & np.isfinite(pixels.time) & np.isfinite(light))
    starts = scan_starts(len(pixels.time), scan["window_length"], scan["stride"])
    eligible = [start for start in starts
                if valid[start:start + scan["window_length"]].sum() >= scan["window_length"] // 2]
    if not eligible:
        raise ValueError("No injection window has enough valid cadences")
    rng = np.random.default_rng(np.random.SeedSequence(
        [seed, int(pixels.target_id) % (2**32)]))
    start = int(eligible[int(rng.integers(len(eligible)))])
    indices = np.flatnonzero(valid[start:start + scan["window_length"]]) + start
    wanted = start + scan["window_length"] // 2
    index = int(indices[np.argmin(np.abs(indices - wanted))])
    return float(pixels.time[index]), start


def make_target_examples(model, pixels, condition, context_stats, config, scan):
    center, positive_start = training_center(pixels, scan, config["seed"])
    injected, profile, realized = inject_transits(pixels, condition, [center], .15)
    positive = _window(injected, positive_start, profile > 0, context_stats, scan)

    control = inverted_residual_control(pixels)
    starts = scan_starts(len(pixels.time), scan["window_length"], scan["stride"])
    rng = np.random.default_rng(np.random.SeedSequence(
        [config["seed"] + 11, int(pixels.target_id) % (2**32)]))
    chosen = list(np.asarray(starts)[rng.permutation(len(starts))])
    negatives, negative_starts = [], []
    for start in chosen:
        try:
            negatives.append(_window(control, int(start), np.zeros(len(pixels.time), bool),
                                     context_stats, scan))
            negative_starts.append(int(start))
            if len(negatives) == config["hard_negative_candidates"]:
                break
        except ValueError:
            continue
    if not negatives:
        raise ValueError("No valid hard-control windows")
    scores = _model_score(model, negatives)
    hard = negatives[int(np.argmax(scores))]
    arrays = {key: np.stack([positive[key], hard[key]]) for key in ARRAY_KEYS}
    arrays["kind"] = np.asarray([1, 2], dtype=np.uint8)
    arrays["start"] = np.asarray(
        [positive_start, negative_starts[int(np.argmax(scores))]], dtype=np.int32)
    return arrays, {"condition": condition, "center_btjd": center,
                    "realized_aperture_depth": realized,
                    "hard_control_probability": float(scores.max()),
                    "hard_negative_candidates": len(negatives)}


def _atomic_npz(path, **arrays):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)


def build_generated_dataset(model, base_arrays, products, source_hashes, stats, config,
                            scan, output, spec_sha):
    target_role = {}
    for target, role in zip(base_arrays["target_id"].astype(str), base_arrays["role"].astype(str)):
        if target in target_role and target_role[target] != role:
            raise ValueError("Target crosses data roles")
        target_role[target] = role
    selected = {role: sorted((x for x in target_role if target_role[x] == role), key=int)
                for role in ("train", "selection")}
    schedules = {role: factorial_schedule(ids, config, role) for role, ids in selected.items()}
    cache = output / "generated"
    cache.mkdir(exist_ok=True)
    paths = []
    for role in ("train", "selection"):
        for number, target_id in enumerate(selected[role], 1):
            data_path = cache / ("TIC" + target_id + ".npz")
            receipt_path = cache / ("TIC" + target_id + ".json")
            if data_path.exists() and receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                if (receipt.get("status") != "complete" or receipt.get("spec_sha256") != spec_sha
                        or receipt.get("sha256") != file_sha256(data_path)
                        or receipt.get("source_sha256") != source_hashes.get(target_id)):
                    raise ValueError("Generated target cache mismatch: " + target_id)
            else:
                product = products[target_id]
                tpf = ROOT / "data/raw/tess/target_pixels" / ("TIC" + target_id) / product["filename"]
                pixels = read_target_pixels(tpf, target_id)
                if pixels.sha256 != source_hashes.get(target_id):
                    raise ValueError("TPF changed since v2 extraction: " + target_id)
                arrays, details = make_target_examples(
                    model, pixels, schedules[role][target_id], stats, config, scan)
                arrays["target_id"] = np.asarray([target_id, target_id])
                arrays["role"] = np.asarray([role, role])
                _atomic_npz(data_path, **arrays)
                atomic_json(receipt_path, {"status": "complete", "target_id": target_id,
                    "role": role, "source_sha256": pixels.sha256, "spec_sha256": spec_sha,
                    "sha256": file_sha256(data_path), **details})
            paths.append(data_path)
            if number % 20 == 0 or number == len(selected[role]):
                print(json.dumps({"stage": "generate_" + role, "processed": number,
                                  "hosts": len(selected[role])}), flush=True)
    combined = {}
    for path in paths:
        with np.load(path, allow_pickle=False) as saved:
            for key in saved.files:
                combined.setdefault(key, []).append(saved[key])
    combined = {key: np.concatenate(values) for key, values in combined.items()}
    generated_path = output / "generated_dataset.npz"
    _atomic_npz(generated_path, **combined)
    atomic_json(output / "generated_complete.json", {
        "status": "complete", "created_at": utc_now(), "spec_sha256": spec_sha,
        "hosts": len(paths), "windows": len(combined["kind"]),
        "roles": {role: int(np.sum(combined["role"].astype(str) == role))
                  for role in ("train", "selection")},
        "files": {"generated_dataset.npz": file_sha256(generated_path)},
        "target_receipts": {str((cache/("TIC"+target+".json")).relative_to(ROOT)):
                            file_sha256(cache/("TIC"+target+".json"))
                            for role in selected for target in selected[role]},
    })
    return combined


def combined_role(base, generated, role):
    base_use = base["role"].astype(str) == role
    generated_use = generated["role"].astype(str) == role
    arrays = {}
    for key in ARRAY_KEYS:
        arrays[key] = np.concatenate([base[key][base_use], generated[key][generated_use]])
    arrays["kind"] = np.concatenate([
        np.zeros(int(base_use.sum()), dtype=np.uint8), generated["kind"][generated_use]])
    return arrays


def tensor_data(arrays):
    return TensorDataset(
        torch.from_numpy(arrays["flux"].astype(np.float32)),
        torch.from_numpy(arrays["valid"].astype(np.float32)),
        torch.from_numpy(arrays["pixel"].astype(np.float32)),
        torch.from_numpy(arrays["event"].astype(np.float32)),
        torch.from_numpy(arrays["instrument"].astype(np.float32)),
        torch.from_numpy(arrays["context"].astype(np.float32)),
        torch.from_numpy(arrays["kind"].astype(np.int64)),
    )


def loader(data, batch_size, shuffle, seed):
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(data, batch_size=batch_size, shuffle=shuffle, generator=generator,
                      num_workers=0)


def predict(model, data, batch_size):
    logits, labels, valid, kinds = [], [], [], []
    model.eval()
    with torch.inference_mode():
        for flux, mask, pixel, event, instrument, context, kind in loader(
                tensor_data(data), batch_size, False, 0):
            logits.append(model(flux, mask, pixel, instrument, context).numpy())
            labels.append(event.numpy()); valid.append(mask.numpy()); kinds.append(kind.numpy())
    return (np.concatenate(logits), np.concatenate(labels),
            np.concatenate(valid).astype(bool), np.concatenate(kinds))


def selection_metrics(model, arrays, batch_size):
    logits, labels, valid, kind = predict(model, arrays, batch_size)
    overall = event_metrics(labels, logits, valid)
    values = {"combined_event_ap": overall["average_precision"]}
    for name, code in (("original", 0), ("injection", 1)):
        use = kind == code
        values[name + "_event_ap"] = event_metrics(labels[use], logits[use], valid[use])["average_precision"]
    use = kind == 2
    probability = 1 / (1 + np.exp(-np.clip(logits[use], -30, 30)))
    maxima = np.asarray([row[mask].max() for row, mask in zip(probability, valid[use])])
    values["hard_control_mean_max_probability"] = float(maxima.mean())
    values["hard_control_alert_fraction_at_0_5"] = float(np.mean(maxima >= .5))
    values["checkpoint_score"] = float(
        .5 * values["combined_event_ap"] + .5 * values["injection_event_ap"]
        - .1 * values["hard_control_alert_fraction_at_0_5"])
    return values


def train(base_model, train_arrays, selection_arrays, config):
    torch.manual_seed(config["seed"])
    model = copy.deepcopy(base_model)
    teacher = copy.deepcopy(base_model).eval()
    for parameter in teacher.parameters():
        parameter.requires_grad_(False)
    y, valid = train_arrays["event"], train_arrays["valid"].astype(bool)
    positive = int(y[valid].sum()); negative = int(valid.sum() - positive)
    positive_weight = min(negative / max(positive, 1), config["maximum_positive_weight"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"],
                                  weight_decay=config["weight_decay"])
    dropout = torch.Generator().manual_seed(config["seed"] + 200)
    best, best_score, history = None, -math.inf, []
    for epoch in range(1, config["epochs"] + 1):
        model.train(); losses = []
        for flux, mask, pixel, event, instrument, context, kind in loader(
                tensor_data(train_arrays), config["batch_size"], True, config["seed"] + epoch):
            optimizer.zero_grad(set_to_none=True)
            use_instrument = bool(torch.rand((), generator=dropout) >= config["modality_dropout"])
            use_context = bool(torch.rand((), generator=dropout) >= config["modality_dropout"])
            logits = model(flux, mask, pixel, instrument, context,
                           use_instrument=use_instrument, use_context=use_context)
            raw = torch.nn.functional.binary_cross_entropy_with_logits(
                logits, event, pos_weight=torch.tensor(positive_weight), reduction="none")
            sample_weight = torch.where(kind > 0, config["synthetic_window_weight"], 1.).float()
            weight = mask * sample_weight[:, None]
            bce = (raw * weight).sum() / weight.sum().clamp_min(1)
            probability = torch.sigmoid(logits) * mask
            has_event = event.sum(dim=1) > 0
            if has_event.any():
                intersection = (probability[has_event] * event[has_event]).sum(dim=1)
                denominator = probability[has_event].sum(dim=1) + event[has_event].sum(dim=1)
                dice = (1 - (2*intersection + 1) / (denominator + 1)).mean()
            else:
                dice = logits.sum() * 0
            original = kind == 0
            if original.any() and config["distillation_weight"]:
                with torch.no_grad():
                    teacher_logits = teacher(flux[original], mask[original], pixel[original],
                                             instrument[original], context[original])
                distill = torch.nn.functional.mse_loss(
                    torch.sigmoid(logits[original])[mask[original].bool()],
                    torch.sigmoid(teacher_logits)[mask[original].bool()])
            else:
                distill = logits.sum() * 0
            loss = bce + config["dice_weight"]*dice + config["distillation_weight"]*distill
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            losses.append(float(loss.detach()))
        metrics = selection_metrics(model, selection_arrays, config["batch_size"])
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), **metrics}
        history.append(row)
        print(json.dumps({"stage": "fine_tune", **row}), flush=True)
        if row["checkpoint_score"] > best_score:
            best_score, best = row["checkpoint_score"], copy.deepcopy(model.state_dict())
    model.load_state_dict(best); model.eval()
    return model, history, float(positive_weight)


def write_report(path, summary):
    best = summary["selection"]["best"]
    lines = ["# Continuous-scan-aware AI telescope v3", "",
             "The frozen v2 localizer was fine-tuned on original training windows plus one "
             "spatially coherent low-depth injection and one model-selected inverted-residual "
             "hard control per training host. Checkpoint selection used only selection hosts.", "",
             f"- Generated hosts: **{summary['dataset']['generated_hosts']}**",
             f"- Generated windows: **{summary['dataset']['generated_windows']}**",
             f"- Best epoch: **{best['epoch']}**",
             f"- Selection combined event AP: **{best['combined_event_ap']:.4f}**",
             f"- Selection injection event AP: **{best['injection_event_ap']:.4f}**",
             f"- Selection hard-control alert fraction at 0.5: **{best['hard_control_alert_fraction_at_0_5']:.1%}**",
             "", "Continuous calibration and audit are a separate frozen run; this training report "
             "does not claim an audit improvement.", "", "## Boundaries", "",
             *["- " + item for item in summary["limitations"]]]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ai_telescope_continuous_training_v3.json")
    args = parser.parse_args(argv)
    config_path = ROOT / args.config
    config = validate_config(json.loads(config_path.read_text()))
    torch.set_num_threads(config["cpu_threads"])
    base_run, physical = ROOT / config["base_model_run"], ROOT / config["physical_run"]
    base_complete, physical_complete = _checked_complete(base_run), _checked_complete(physical)
    scan = validate_scan_config(json.loads((ROOT / config["scan_config"]).read_text()))
    base_spec = json.loads((base_run / "spec.json").read_text())
    model_config = base_spec["config"]
    checkpoint = torch.load(base_run / "ai_telescope_context.pt", map_location="cpu", weights_only=True)
    stats = json.loads((base_run / "context_stats.json").read_text())
    model = ExtendedEventLocalizer(len(stats["features"])*2, model_config["embedding_dim"],
                                   model_config["instrument_channels"])
    model.load_state_dict(checkpoint["localizer"]); model.eval()
    with np.load(base_run / "dataset.npz", allow_pickle=False) as saved:
        base_arrays = {key: saved[key] for key in saved.files}
    plan = json.loads((physical / "download_plan.json").read_text())
    products = {str(x["target_id"]): x for x in plan["products"]}
    source_hashes = {}
    for path in (base_run / "auxiliary").glob("TIC*.json"):
        receipt = json.loads(path.read_text())
        source_hashes[str(receipt["target_id"])] = receipt["source_sha256"]
    output = ROOT / config["output"]
    output.mkdir(parents=True, exist_ok=True)
    sources = ("scripts/experiments/ai_telescope_continuous_training.py",
               "scripts/experiments/ai_telescope_continuous_validation.py",
               "scripts/experiments/ai_telescope_blind_scan.py",
               "training/ai_telescope.py", "scripts/research/pixels.py")
    spec = {"version": VERSION, "config": {**config,
             "embedding_dim": model_config["embedding_dim"],
             "instrument_channels": model_config["instrument_channels"]},
            "config_sha256": file_sha256(config_path),
            "base_spec_sha256": base_complete["spec_sha256"],
            "physical_spec_sha256": physical_complete["spec_sha256"],
            "scan_config": scan,
            "source_files": {name: file_sha256(ROOT / name) for name in sources},
            "protocol": {"optimization_roles": ["train", "selection"],
                         "calibration_used": False, "audit_used": False,
                         "prospective_90_host_cohort_used": False}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    spec_path = output / "spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise ValueError("Existing v3 output has a different specification")
    if (output / "complete.json").exists():
        _checked_complete(output)
        print(json.dumps({"status": "already_complete", "output": config["output"]}))
        return
    atomic_json(spec_path, spec)
    generated = build_generated_dataset(model, base_arrays, products, source_hashes, stats,
                                        config, scan, output, spec_sha)
    train_arrays = combined_role(base_arrays, generated, "train")
    selection_arrays = combined_role(base_arrays, generated, "selection")
    trained, history, positive_weight = train(model, train_arrays, selection_arrays, config)
    best = max(history, key=lambda x: x["checkpoint_score"])
    summary = {"status": "complete", "version": VERSION, "completed_at": utc_now(),
               "spec_sha256": spec_sha,
               "dataset": {"base_windows": len(base_arrays["flux"]),
                           "generated_hosts": len(generated["flux"])//2,
                           "generated_windows": len(generated["flux"]),
                           "train_windows": len(train_arrays["flux"]),
                           "selection_windows": len(selection_arrays["flux"]),
                           "kinds": {"injection": int(np.sum(generated["kind"] == 1)),
                                     "hard_control": int(np.sum(generated["kind"] == 2))}},
               "training": {"positive_weight": positive_weight, "history": history},
               "selection": {"checkpoint_rule":
                   "0.5*combined_AP+0.5*injection_AP-0.1*hard_control_alert_fraction",
                   "best": best},
               "claims": {"audit_improvement": False, "continuous_threshold_calibrated": False,
                          "calibration_or_audit_used_for_training": False,
                          "prospective_cohort_used": False, "deployed_to_watcher": False},
               "limitations": [
                   "Synthetic training transits are trapezoids rather than limb-darkened physical models",
                   "Hard controls are selected from four inverted-residual windows per host, not every continuous cadence",
                   "The model has not beaten v2 until separate continuous calibration and audit finish",
                   "One cached sector per candidate-enriched host limits survey generalization",
               ]}
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.md", summary)
    torch.save({"version": VERSION, "config": spec["config"], "localizer": trained.state_dict(),
                "threshold": {"threshold": .5, "scope": "placeholder_pending_continuous_calibration"}},
               output / "ai_telescope_context.pt")
    shutil.copy2(base_run / "context_stats.json", output / "context_stats.json")
    dataset_path = output / "dataset.npz"
    if not dataset_path.exists():
        os.link(base_run / "dataset.npz", dataset_path)
    if file_sha256(dataset_path) != file_sha256(base_run / "dataset.npz"):
        raise ValueError("Compatibility dataset differs from v2")
    auxiliary = output / "auxiliary"; auxiliary.mkdir(exist_ok=True)
    for source in (base_run / "auxiliary").glob("TIC*.json"):
        destination = auxiliary / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
    files = {name: file_sha256(output / name) for name in
             ("spec.json", "generated_complete.json", "generated_dataset.npz", "summary.json",
              "report.md", "ai_telescope_context.pt", "context_stats.json", "dataset.npz")}
    atomic_json(output / "complete.json", {"status": "complete", "completed_at": utc_now(),
                                            "spec_sha256": spec_sha, "files": files})
    print(json.dumps({"status": "complete", "output": config["output"],
                      "selection": summary["selection"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
