"""Train a bounded, sealed Transformer expert for behavioral fusion."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from scripts.experiments.adaptation_data import INPUTS, MissionBatchPlan, load_prepared
from scripts.experiments.adaptation_metrics import fit_temperature, metrics
from scripts.experiments.mission_adaptation import atomic_json, validate_config as validate_adaptation_config
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.transformer_expert import TransitTransformer

VERSION = "bounded_transit_transformer_v1"
DEFAULTS = {"schema_version": 1, "seeds": [311, 313, 317], "steps": 120, "batch_size": 32,
            "eval_every": 30, "learning_rate": .0003, "weight_decay": .001, "gradient_clip": 1.,
            "d_model": 32, "heads": 4, "layers": 1, "dropout": .15, "cpu_threads": 2}


def validate_transformer_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown Transformer configuration fields")
    c = {**DEFAULTS, **value}
    for key, low, high in (("schema_version", 1, 1), ("steps", 20, 10000), ("batch_size", 2, 256),
                           ("eval_every", 1, 1000), ("d_model", 8, 128), ("heads", 1, 16),
                           ("layers", 1, 4), ("cpu_threads", 1, 4)):
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError("Invalid " + key)
    if c["batch_size"] % 2 or c["steps"] % c["eval_every"] or c["d_model"] % c["heads"]:
        raise ValueError("Invalid Transformer divisibility settings")
    if (not isinstance(c["seeds"], list) or not 1 <= len(c["seeds"]) <= 5
            or len(c["seeds"]) != len(set(c["seeds"])) or any(type(x) is not int for x in c["seeds"])):
        raise ValueError("Invalid Transformer seeds")
    for key in ("learning_rate", "weight_decay", "gradient_clip", "dropout"):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]):
            raise ValueError("Invalid " + key)
    if not (0 < c["learning_rate"] <= .1 and 0 <= c["weight_decay"] <= 1
            and 0 < c["gradient_clip"] <= 100 and 0 <= c["dropout"] < .8):
        raise ValueError("Unsafe Transformer settings")
    return c


def predict(model, part, batch_size):
    model.eval(); chunks = []
    with torch.inference_mode():
        for start in range(0, len(part["y"]), batch_size):
            chunks.append(model(*[part[key][start:start + batch_size] for key in INPUTS]))
    value = torch.cat(chunks).numpy()
    if value.shape != (len(part["y"]),) or not np.isfinite(value).all():
        raise ValueError("Invalid Transformer predictions")
    return value


def model_from_config(c):
    return TransitTransformer(c["d_model"], c["heads"], c["layers"], c["dropout"])


def train_seed(seed, c, adaptation_config, data, spec_sha, folder):
    torch.manual_seed(seed)
    model = model_from_config(c)
    optimizer = torch.optim.AdamW(model.parameters(), lr=c["learning_rate"], weight_decay=c["weight_decay"])
    plan = MissionBatchPlan(data, c["batch_size"], seed)
    selection = data["tess"]["selection"]
    best, best_ap, best_step, history = None, -1., None, []
    for step in range(c["steps"]):
        model.train()
        rows = plan.indices("tess", step, c["batch_size"])
        part = data["tess"]["train"]
        inputs = [part[key][rows] for key in INPUTS]
        target = part["y"][rows]
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(model(*inputs), target)
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite Transformer loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), c["gradient_clip"], error_if_nonfinite=True)
        optimizer.step()
        if (step + 1) % c["eval_every"] == 0:
            score = metrics(selection["y"].numpy(), predict(model, selection, c["batch_size"]))["average_precision"]
            history.append({"step": step + 1, "selection_ap": score, "training_loss": float(loss.detach())})
            print(json.dumps({"seed": seed, **history[-1]}), flush=True)
            if score > best_ap:
                best, best_ap, best_step = copy.deepcopy(model.state_dict()), score, step + 1
    if best is None:
        raise ValueError("No Transformer checkpoint selected")
    model.load_state_dict(best)
    calibration = data["tess"]["calibration"]
    cal_logits = predict(model, calibration, c["batch_size"])
    temperature = fit_temperature(calibration["y"].numpy(), cal_logits)
    audit = data["tess"]["audit"]
    audit_logits = predict(model, audit, c["batch_size"])
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = {"version": VERSION, "spec_sha256": spec_sha, "seed": seed, "step": best_step,
                  "model_config": {k: c[k] for k in ("d_model", "heads", "layers", "dropout")},
                  "input_contract": "shared_v1", "model_state": best}
    torch.save(checkpoint, folder / "best_model.pt")
    result = {"seed": seed, "best_step": best_step, "selection_ap": best_ap, "history": history,
              "calibration": temperature, "audit": {"raw": metrics(audit["y"].numpy(), audit_logits),
              "calibrated": metrics(audit["y"].numpy(), audit_logits, temperature["temperature"])},
              "checkpoint_sha256": file_sha256(folder / "best_model.pt")}
    atomic_json(folder / "result.json", result)
    atomic_json(folder / "complete.json", {"spec_sha256": spec_sha, "files": {
        name: file_sha256(folder / name) for name in ("best_model.pt", "result.json")}})
    return result


def load_models(output, expected_spec_sha):
    output = Path(output)
    complete = json.loads((output / "complete.json").read_text())
    if complete["spec_sha256"] != expected_spec_sha:
        raise ValueError("Transformer suite identity mismatch")
    spec = json.loads((output / "spec.json").read_text())
    models = []
    for seed in spec["config"]["seeds"]:
        folder = output / f"seed-{seed}"
        receipt = json.loads((folder / "complete.json").read_text())
        for name, digest in receipt["files"].items():
            if file_sha256(folder / name) != digest:
                raise ValueError("Transformer artifact hash mismatch")
        checkpoint = torch.load(folder / "best_model.pt", map_location="cpu", weights_only=True)
        model = TransitTransformer(**checkpoint["model_config"])
        model.load_state_dict(checkpoint["model_state"], strict=True); model.eval()
        models.append(({"arm": "transformer", "seed": seed,
                        "model_sha256": receipt["files"]["best_model.pt"]}, model))
    return models


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/transformer_expert_pilot_v1.json")
    parser.add_argument("--adaptation-config", default="configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--output", default="outputs/research/transformer_expert/pilot-v1")
    args = parser.parse_args(argv)
    c = validate_transformer_config(json.loads((ROOT / args.config).read_text()))
    adaptation = validate_adaptation_config(json.loads((ROOT / args.adaptation_config).read_text()))
    output = ROOT / args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError("Transformer output already exists")
    output.mkdir(parents=True, exist_ok=True)
    data, provenance = load_prepared(ROOT, adaptation)
    spec = {"version": VERSION, "config": c, "adaptation_config": adaptation, "prepared_data": provenance,
            "source_files": {name: file_sha256(ROOT / name) for name in
                ("training/transformer_expert.py", "scripts/experiments/transformer_expert.py",
                 "scripts/experiments/adaptation_data.py", "scripts/experiments/adaptation_metrics.py")}}
    spec_sha = hashlib.sha256(canonical_json(spec).encode()).hexdigest()
    atomic_json(output / "spec.json", spec)
    results = [train_seed(seed, c, adaptation, data, spec_sha, output / f"seed-{seed}") for seed in c["seeds"]]
    summary = {"status": "complete", "version": VERSION, "generated_at": utc_now(), "spec_sha256": spec_sha,
               "results": results, "audit_ap_mean": float(np.mean([x["audit"]["raw"]["average_precision"] for x in results])),
               "claims": {"original_test_evaluated": False, "search_ready": False}}
    atomic_json(output / "summary.json", summary)
    atomic_json(output / "complete.json", {"status": "complete", "spec_sha256": spec_sha,
        "files": {name: file_sha256(output / name) for name in ("spec.json", "summary.json")}})
    print(json.dumps({"status": "complete", "output": str(output), "audit_ap_mean": summary["audit_ap_mean"]}, indent=2))


if __name__ == "__main__":
    main()
