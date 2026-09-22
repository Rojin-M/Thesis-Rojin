"""Finite, resumable five-arm research experiments; never used by live scoring.

Run with .venv/bin/python -m scripts.experiments.mission_adaptation --help.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import time
import importlib.metadata

import numpy as np
import torch
from torch import nn

from .adaptation_data import INPUTS, MISSIONS, MissionBatchPlan, load_prepared
from .adaptation_metrics import choose_thresholds, fit_temperature, metrics, paired_group_bootstrap
from scripts.research.protocol import ROOT, canonical_json, utc_now
from scripts.research.provenance import file_sha256
from training.cnn.mission_adaptation import MissionAdaptationCNN, reversal_schedule

ARMS = ("tess_only", "kepler_only", "fine_tuned", "pooled", "dann")
DEFAULTS = {"schema_version": 1, "seeds": [42, 43, 44], "arms": list(ARMS),
    "steps": 120, "pretrain_steps": 60, "batch_size": 32, "eval_every": 30,
    "learning_rate": .0003, "weight_decay": .0001, "gradient_clip": 1.,
    "mission_loss_weight": .1, "grl_max": 1., "partition_seed": 2718,
    "max_train_groups": 512, "cpu_threads": 2, "device": "cpu",
    "max_seconds": 3600, "invocation_seconds": 1800, "max_attempts": 3,
    "precision_target": .9, "fpr_target": .05, "bootstrap_repeats": 200}
SOURCE_PATHS = ["scripts/experiments/mission_adaptation.py", "scripts/experiments/adaptation_data.py",
    "scripts/experiments/adaptation_metrics.py", "training/cnn/mission_adaptation.py",
    "training/cnn/train_kepler_cnn.py", "scripts/data/tess_dataset.py", "scripts/data/tess_selection.py",
    "scripts/research/scoring.py", "scripts/research/protocol.py", "scripts/research/provenance.py"]


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Unknown experiment configuration fields")
    c = {**DEFAULTS, **value}
    bounds = {"schema_version": (1, 1), "steps": (2, 100000), "pretrain_steps": (1, 99999),
              "batch_size": (2, 256), "eval_every": (1, 10000), "partition_seed": (0, 2**31-1),
              "max_train_groups": (0, 100000), "cpu_threads": (1, 4), "max_seconds": (1, 43200),
              "invocation_seconds": (1, 7200), "max_attempts": (1, 3), "bootstrap_repeats": (20, 2000)}
    for key, (low, high) in bounds.items():
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError(f"Invalid {key}")
    if (c["batch_size"] % 2 or c["pretrain_steps"] >= c["steps"] or c["eval_every"] > c["steps"]
            or c["invocation_seconds"] > c["max_seconds"]):
        raise ValueError("Invalid batch, pretraining, evaluation or runtime budget")
    for key in ("learning_rate", "weight_decay", "gradient_clip", "mission_loss_weight", "grl_max",
                "precision_target", "fpr_target"):
        if type(c[key]) not in (int, float) or not math.isfinite(c[key]) or c[key] < 0:
            raise ValueError(f"Invalid {key}")
    if not (0 < c["learning_rate"] <= .1 and 0 < c["gradient_clip"] <= 100
            and 0 < c["precision_target"] <= 1 and 0 <= c["fpr_target"] < 1
            and c["grl_max"] <= 10 and c["mission_loss_weight"] <= 10):
        raise ValueError("Hyperparameters exceed supported bounds")
    if (not isinstance(c["seeds"], list) or not 1 <= len(c["seeds"]) <= 10
            or any(type(s) is not int or not 0 <= s < 2**31 for s in c["seeds"])
            or len(set(c["seeds"])) != len(c["seeds"])):
        raise ValueError("Expected one to ten distinct explicit seeds")
    if (not isinstance(c["arms"], list) or not c["arms"] or set(c["arms"]) - set(ARMS)
            or len(set(c["arms"])) != len(c["arms"])):
        raise ValueError("Invalid arms")
    if c["device"] != "cpu":
        raise ValueError("This bounded pilot interface uses CPU; GPU allocation support is not yet enabled")
    return c


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    tmp.replace(path)


def torch_save(path, value):
    tmp = path.with_name(path.name + ".tmp")
    torch.save(value, tmp)
    tmp.replace(path)


def identity(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@contextmanager
def deadline(seconds):
    def expired(*_):
        raise TimeoutError("Finite experiment invocation budget exhausted; resume only within remaining budget")
    previous = signal.signal(signal.SIGALRM, expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
        signal.signal(signal.SIGALRM, previous)


def predict(model, part, batch_size):
    model.eval()
    output = []
    with torch.inference_mode():
        for start in range(0, len(part["y"]), batch_size):
            result = model(*[part[k][start:start + batch_size] for k in INPUTS])
            if result.ndim != 1 or not torch.isfinite(result).all():
                raise ValueError("Nonfinite or malformed model predictions")
            output.extend(result.tolist())
    return np.asarray(output)


def evaluate_arm(model, data, config, arm, seed, best_step, history, checkpoint_sha):
    source = "kepler" if arm == "kepler_only" else "tess"
    select = data[source]["selection"]
    selected_logits = predict(model, select, config["batch_size"])
    thresholds = choose_thresholds(select["y"].numpy(), selected_logits,
                                   config["precision_target"], config["fpr_target"])
    cal = data[source]["calibration"]
    cal_logits = predict(model, cal, config["batch_size"])
    calibration = {**fit_temperature(cal["y"].numpy(), cal_logits), "mission": source}
    result = {"arm": arm, "seed": seed, "status": "complete", "best_step": best_step,
              "updates": config["steps"], "examples_drawn": config["steps"] * config["batch_size"],
              "selection_mission": source, "selection_metric": "average_precision",
              "checkpoint_sha256": checkpoint_sha, "history": history, "calibration": calibration,
              "thresholds": thresholds, "audit": {}, "mission_head_balanced_accuracy": None,
              "planet_parameters": sum(p.numel() for n, p in model.named_parameters() if not n.startswith("mission_head.")),
              "mission_parameters": sum(p.numel() for n, p in model.named_parameters() if n.startswith("mission_head."))}
    predictions = {}
    for mission in MISSIONS:
        part = data[mission]["audit"]
        logits = predict(model, part, config["batch_size"])
        y = part["y"].numpy()
        result["audit"][mission] = {"raw": metrics(y, logits, thresholds=thresholds),
            "calibrated": metrics(y, logits, calibration["temperature"], thresholds),
            "period_subgroups": {name: metrics(y[mask], logits[mask]) if mask.any() else {"n": 0}
                 for name, mask in (("below_10_days", np.array([m["period"] < 10 for m in part["metadata"]])),
                                     ("at_least_10_days", np.array([m["period"] >= 10 for m in part["metadata"]])))}}
        predictions[mission] = [{**meta, "label": int(label), "logit": float(logit)}
                                for meta, label, logit in zip(part["metadata"], y, logits)]
    if model.mission_head is not None:
        accuracy = []
        with torch.inference_mode():
            for domain, mission in enumerate(MISSIONS):
                part = data[mission]["audit"]
                correct = 0
                for start in range(0, len(part["y"]), config["batch_size"]):
                    _, logits = model(*[part[k][start:start + config["batch_size"]] for k in INPUTS], grl_strength=0.)
                    correct += int((logits.argmax(1) == domain).sum())
                accuracy.append(correct / len(part["y"]))
        result["mission_head_balanced_accuracy"] = float(np.mean(accuracy))
    return result, predictions


def run_arm(folder, data, c, arm, seed, spec_sha, progress, on_checkpoint=None):
    folder.mkdir(exist_ok=True)
    result_path = folder / "result.json"
    if (folder / "complete.json").exists():
        receipt = json.loads((folder / "complete.json").read_text())
        if receipt["spec_sha256"] != spec_sha:
            raise ValueError("Completed arm identity mismatch")
        for name, checksum in receipt["files"].items():
            if file_sha256(folder / name) != checksum:
                raise ValueError("Completed arm artifact corrupt: " + name)
        return json.loads(result_path.read_text())
    torch.manual_seed(seed)
    model = MissionAdaptationCNN(adversarial=arm == "dann")
    # Mission-head initialization must not change the shared dropout RNG stream.
    torch.manual_seed(seed + 100000)
    optimizer = torch.optim.AdamW(model.parameters(), lr=c["learning_rate"], weight_decay=c["weight_decay"])
    plan = MissionBatchPlan(data, c["batch_size"], seed)
    history, best, best_ap, best_step, start = [], None, -1., None, 0
    state_path = folder / "progress.json"
    if state_path.exists():
        saved = json.loads(state_path.read_text())
        path = folder / saved["checkpoint"]
        if file_sha256(path) != saved["sha256"]:
            raise ValueError("Restart checkpoint checksum mismatch")
        state = torch.load(path, map_location="cpu", weights_only=True)
        if state["spec_sha256"] != spec_sha:
            raise ValueError("Restart checkpoint identity mismatch")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["rng"])
        history, best, best_ap, best_step, start = (state[k] for k in
            ("history", "best", "best_ap", "best_step", "step"))
    class_loss, domain_loss = nn.BCEWithLogitsLoss(), nn.CrossEntropyLoss()
    selection_mission = "kepler" if arm == "kepler_only" else "tess"
    block_loss = []
    for step in range(start, c["steps"]):
        if arm == "fine_tuned" and step == c["pretrain_steps"]:
            # Reset optimizer moments on domain switch; weights and BN statistics carry forward.
            optimizer = torch.optim.AdamW(model.parameters(), lr=c["learning_rate"], weight_decay=c["weight_decay"])
        model.train()
        x, y, domain = plan.batch(arm, step, c["pretrain_steps"])
        optimizer.zero_grad(set_to_none=True)
        strength = reversal_schedule(step, c["steps"], c["grl_max"])
        if arm == "dann":
            logits, mission_logits = model(*x, grl_strength=strength)
            mission_loss = domain_loss(mission_logits, domain)
            loss = class_loss(logits, y) + c["mission_loss_weight"] * mission_loss
        else:
            logits = model(*x)
            mission_loss = torch.tensor(0.)
            loss = class_loss(logits, y)
        if not torch.isfinite(loss):
            raise ValueError("Training produced nonfinite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), c["gradient_clip"], error_if_nonfinite=True)
        optimizer.step()
        block_loss.append(float(loss.detach()))
        done = step + 1
        if done % c["eval_every"] and done != c["steps"] and done != c["pretrain_steps"]:
            continue
        eligible = arm != "fine_tuned" or done > c["pretrain_steps"]
        score = None
        if eligible:
            part = data[selection_mission]["selection"]
            score = metrics(part["y"].numpy(), predict(model, part, c["batch_size"]))["average_precision"]
            if score > best_ap:  # Strict improvement; ties keep the earlier checkpoint.
                best_ap, best_step = score, done
                best = copy.deepcopy(model.state_dict())
        history.append({"step": done, "phase": "kepler_pretrain" if arm == "fine_tuned" and not eligible else "training",
                        "mean_training_loss": float(np.mean(block_loss)), "selection_ap": score,
                        "last_mission_loss": float(mission_loss.detach()) if arm == "dann" else None,
                        "grl_strength": strength if arm == "dann" else None})
        block_loss = []
        filename = f"checkpoint-{done:06d}.pt"
        torch_save(folder / filename, {"spec_sha256": spec_sha, "step": done, "model": model.state_dict(),
            "optimizer": optimizer.state_dict(), "rng": torch.get_rng_state(), "history": history,
            "best": best, "best_ap": best_ap, "best_step": best_step})
        previous = json.loads(state_path.read_text())["checkpoint"] if state_path.exists() else None
        atomic_json(state_path, {"checkpoint": filename, "sha256": file_sha256(folder / filename), "step": done})
        # Only superseded restart snapshots from this owned arm are removed.
        if previous and previous != filename:
            (folder / previous).unlink(missing_ok=True)
        progress(arm, seed, done)
        if on_checkpoint:
            on_checkpoint(arm, seed, done)
    if best is None:
        raise ValueError("No eligible validation-selected checkpoint")
    model.load_state_dict(best)
    torch_save(folder / "best_model.pt", {"model_state": best, "spec_sha256": spec_sha, "arm": arm,
        "seed": seed, "step": best_step, "input_contract": "shared_v1", "normalizer_scope": "frozen_Kepler_TRAIN"})
    result, predictions = evaluate_arm(model, data, c, arm, seed, best_step, history,
                                      file_sha256(folder / "best_model.pt"))
    atomic_json(folder / "predictions.json", predictions)
    atomic_json(result_path, result)
    atomic_json(folder / "complete.json", {"spec_sha256": spec_sha, "files": {
        name: file_sha256(folder / name) for name in ("result.json", "predictions.json", "best_model.pt")}})
    return result


def summarize(results, output, c, provenance):
    summary = {"schema_version": 1, "status": "complete", "cohort": provenance.get("cohort", "archival_labelled_validation_pilot"),
        "generated_at": utc_now(), "config": c, "runs": results, "by_arm": {}, "paired_dann_pooled": [],
        "claims": {"improvement_established": False, "search_ready": False, "novelty_established": False,
                   "test_set_evaluated": False, "deployed_to_candidate_scoring": False},
        "limitations": ["Known catalog ephemerides; not blind recovery", "Short budgets; no convergence claim",
            "Validation-derived audit; previously consulted benchmark is not an untouched test",
            "TESS-only weights share frozen Kepler TRAIN normalization",
            "Kepler-only selects and calibrates on Kepler; other arms on TESS",
            "Empirical labelled-negative FPR is not survey false-alarm calibration",
            "DANN uses both missions' labels; no unsupervised-adaptation claim",
            "Mission head accuracy alone does not prove invariant representations",
            "Calibrated scores are not planet confirmation probabilities"]}
    for arm in c["arms"]:
        runs = [r for r in results if r["arm"] == arm]
        summary["by_arm"][arm] = {"n_seeds": len(runs)}
        for mode in ("raw", "calibrated"):
            for key in ("average_precision", "roc_auc", "brier", "nll", "ece_10_equal_width"):
                values = [r["audit"]["tess"][mode][key] for r in runs]
                summary["by_arm"][arm][mode + "_" + key] = {"mean": float(np.mean(values)),
                    "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None, "values": values}
    if {"pooled", "dann"} <= set(c["arms"]):
        for seed in c["seeds"]:
            pair = [json.loads((output / f"{arm}-seed{seed}" / "predictions.json").read_text())["tess"]
                    for arm in ("pooled", "dann")]
            if [r["candidate_id"] for r in pair[0]] != [r["candidate_id"] for r in pair[1]]:
                raise ValueError("Paired audit identities differ")
            values = [[r["logit"] for r in rows] for rows in pair]
            summary["paired_dann_pooled"].append({"seed": seed, **paired_group_bootstrap(
                [r["label"] for r in pair[0]], [r["split_group"] for r in pair[0]],
                values[0], values[1], c["partition_seed"], c["bootstrap_repeats"])})
    return summary


def write_report(output, summary):
    lines = ["# Bounded mission-adaptation pilot", "", "Known-ephemeris classification on validation-derived audit groups.",
        "No original test evaluation, deployment, survey-readiness or novelty claim.", "",
        "| Arm | Seeds | TESS audit AP (mean ± seed SD) | Raw Brier | Calibrated Brier |",
        "| --- | --- | --- | --- | --- |"]
    for arm, row in summary["by_arm"].items():
        ap = row["raw_average_precision"]
        sd = f"{ap['sd']:.4f}" if ap["sd"] is not None else "unavailable"
        lines.append(f"| {arm} | {row['n_seeds']} | {ap['mean']:.4f} ± {sd} | "
                     f"{row['raw_brier']['mean']:.4f} | {row['calibrated_brier']['mean']:.4f} |")
    lines += ["", f"Each arm: {summary['config']['steps']} updates × {summary['config']['batch_size']} examples; "
              f"seeds {summary['config']['seeds']}. Fine-tuning includes pretraining in that total.", "",
              "Calibration and threshold outcomes, actual row identities, parameter counts, model hashes, histories, "
              "and paired group-bootstrap intervals are recorded in summary.json and per-arm outputs.", ""]
    lines += ["- " + limitation for limitation in summary["limitations"]]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    arms = list(summary["by_arm"])
    for i, arm in enumerate(arms):
        row = summary["by_arm"][arm]
        axes[0].scatter([i] * row["n_seeds"], row["raw_average_precision"]["values"], label=arm)
        for mode, offset, color in (("raw", -.15, "#777777"), ("calibrated", .15, "#1877aa")):
            axes[1].bar(i + offset, row[mode + "_brier"]["mean"], width=.28, color=color,
                        label=mode if i == 0 else None)
    for ax in axes:
        ax.set_xticks(range(len(arms)), [a.replace("_", "\n") for a in arms])
    axes[0].set(ylabel="Average precision", ylim=(0, 1), title="TESS audit · each seed")
    axes[1].set(ylabel="Brier score (lower is better)", title="TESS audit · seed mean")
    axes[1].legend()
    fig.suptitle("Bounded known-ephemeris pilot — not search validation")
    fig.savefig(output / "comparison.png", dpi=150)
    plt.close(fig)


def run_suite(config, output, data, provenance, *, resume=False, on_checkpoint=None):
    c = validate_config(config)
    output = Path(output)
    if output.exists() and not resume:
        raise ValueError("Output already exists; use --resume for the exact frozen specification")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Experiment already has an active owner") from exc
        sources = {name: file_sha256(ROOT / name) for name in SOURCE_PATHS}
        spec = {"config": c, "data": provenance, "source_files": sources,
                "environment": {"python": platform.python_version(), "torch": str(torch.__version__),
                                "numpy": np.__version__, "device": "cpu", "deterministic": True,
                                "packages": {name: importlib.metadata.version(name) for name in
                                             ("scipy", "scikit-learn", "pandas", "matplotlib")}}}
        spec_sha = identity(spec)
        spec_path = output / "spec.json"
        if spec_path.exists():
            if json.loads(spec_path.read_text()) != spec:
                raise ValueError("Frozen experiment specification changed; choose a new output directory")
        else:
            atomic_json(spec_path, spec)
            for name in sources:
                destination = output / "source" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / name).read_bytes())
                if file_sha256(destination) != sources[name]:
                    raise ValueError("Source changed while freezing experiment")
        completion = output / "complete.json"
        if completion.exists():
            receipt = json.loads(completion.read_text())
            for name, sha in receipt["files"].items():
                if file_sha256(output / name) != sha:
                    raise ValueError("Completed experiment artifact checksum mismatch")
            # Verify every model, prediction and result too; replay does no training.
            for seed in c["seeds"]:
                for arm in c["arms"]:
                    run_arm(output / f"{arm}-seed{seed}", data, c, arm, seed, spec_sha, lambda *_: None)
            return {"already_complete": True, "output": str(output), "spec_sha256": spec_sha}
        state_path = output / "state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {
            "status": "queued", "attempts": 0, "runtime_charged": 0., "events": []}
        remaining = c["max_seconds"] - state["runtime_charged"]
        if remaining <= 0 or state["attempts"] >= c["max_attempts"]:
            raise ValueError("Persistent runtime/attempt budget exhausted")
        allowance = min(remaining, c["invocation_seconds"])
        base_charge = state["runtime_charged"]
        state.update(status="running", attempts=state["attempts"] + 1,
                     runtime_charged=base_charge + allowance, started_at=utc_now(), error=None,
                     spec_sha256=spec_sha)
        state["events"].append({"status": "started", "at": utc_now(), "reserved_seconds": allowance})
        atomic_json(state_path, state)  # Hard crashes conservatively retain the full reservation.
        started = time.monotonic()
        torch.set_num_threads(c["cpu_threads"])
        torch.use_deterministic_algorithms(True)
        def progress(arm, seed, step):
            state.update(arm=arm, seed=seed, step=step, heartbeat_at=utc_now())
            atomic_json(state_path, state)
            print(json.dumps({"arm": arm, "seed": seed, "step": step, "seconds": round(time.monotonic()-started, 2)}), flush=True)
        try:
            with deadline(allowance):
                results = []
                for seed in c["seeds"]:
                    for arm in c["arms"]:
                        progress(arm, seed, 0)
                        results.append(run_arm(output / f"{arm}-seed{seed}", data, c, arm, seed,
                                               spec_sha, progress, on_checkpoint))
                summary = summarize(results, output, c, provenance)
                summary["spec_sha256"] = spec_sha
                atomic_json(output / "summary.json", summary)
                write_report(output, summary)
                atomic_json(completion, {"spec_sha256": spec_sha, "completed_at": utc_now(),
                    "files": {name: file_sha256(output / name) for name in
                              ("spec.json", "summary.json", "report.md", "comparison.png")}})
                state["status"] = "complete"
        except BaseException as exc:
            state.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)[:1000]})
            raise
        finally:
            state["runtime_charged"] = base_charge + min(allowance, time.monotonic() - started)
            state["events"].append({"status": state["status"], "at": utc_now(), "error": state.get("error")})
            atomic_json(state_path, state)
        return {"already_complete": False, "output": str(output), "spec_sha256": spec_sha,
                "runtime_seconds": state["runtime_charged"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/mission_adaptation_pilot_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Resume/replay only an identical frozen experiment")
    parser.add_argument("--audit-only", action="store_true", help="Validate and print actual group counts; no output/model writes")
    args = parser.parse_args()
    c = validate_config(json.loads(args.config.read_text()))
    data, provenance = load_prepared(ROOT, c)
    if args.audit_only:
        print(json.dumps({m: {r: {"rows": len(v["candidate_ids"]), "groups": len(v["groups"]),
                                  "class_counts": v["class_counts"]} for r,v in roles.items()}
                          for m,roles in provenance["roles"].items()}, indent=2))
        return
    print(json.dumps(run_suite(c, args.output, data, provenance, resume=args.resume), indent=2))


if __name__ == "__main__":
    main()
