"""Small helpers for publishing verified result tables and figures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

METRIC_LABELS = {
    "accuracy": "Accuracy",
    "f1": "F1",
    "pr_auc": "Average precision",
    "roc_auc": "ROC-AUC",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Publication:
    def __init__(self, work: Path, destination: Path) -> None:
        self.work = work
        self.destination = destination
        self.sources: dict[str, str] = {}

    def portable(self, value):
        if isinstance(value, dict):
            return {self.portable(key): self.portable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.portable(item) for item in value]
        if isinstance(value, str):
            if value == str(ROOT):
                return "."
            value = value.replace(str(ROOT) + "/", "")
            if not self.work.is_relative_to(ROOT):
                value = value.replace(str(self.work) + "/", "workflow/")
            return value
        return value

    def remember(self, path: Path) -> Path:
        self.sources[self.portable(str(path.resolve()))] = sha256(path)
        return path

    def read_json(self, path: Path) -> dict:
        return json.loads(self.remember(path).read_text())

    def write(self, name: str, content: str) -> None:
        target = self.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n")

    def write_json(self, name: str, value: dict) -> None:
        self.write(name, json.dumps(self.portable(value), indent=2, allow_nan=False))

    def write_csv(self, name: str, frame: pd.DataFrame) -> None:
        target = self.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        output = frame.copy()
        for column in output.select_dtypes(include="object"):
            output[column] = output[column].map(self.portable)
        output.to_csv(target, index=False)

    def verify_hashes(self, values: dict[str, str]) -> None:
        for value, expected in values.items():
            path = Path(value)
            if not path.is_absolute():
                path = ROOT / path
            if sha256(self.remember(path)) != expected:
                raise ValueError(f"Saved evidence changed: {path}")

    def small_plot(self, frame: pd.DataFrame, title: str, name: str,
                   metrics: tuple[str, ...] = ("pr_auc", "f1")) -> None:
        labels = [METRIC_LABELS.get(metric, metric.capitalize()) for metric in metrics]
        figure, axis = plt.subplots(figsize=(8.5, 4.8))
        positions = np.arange(len(metrics))
        width = .75 / len(frame)
        colors = ("#0072B2", "#D55E00", "#009E73")
        for index, (_, row) in enumerate(frame.iterrows()):
            values = [row["test_" + metric] for metric in metrics]
            bars = axis.bar(
                positions + (index - (len(frame) - 1) / 2) * width,
                values,
                width,
                label=row["model"],
                color=colors[index % len(colors)],
            )
            axis.bar_label(bars, labels=[f"{value:.4f}" for value in values], fontsize=8, padding=3)
        axis.set(
            xticks=positions,
            xticklabels=labels,
            ylim=(0, 1.13),
            ylabel="Test score",
            title=title,
        )
        axis.set_yticks(np.arange(0, 1.01, .2))
        axis.legend(loc="upper center", bbox_to_anchor=(.5, -.10), ncol=len(frame), frameon=False)
        axis.grid(axis="y", alpha=.2)
        axis.set_axisbelow(True)
        figure.text(
            .5,
            .015,
            "Individual runs; thresholds selected on validation. No seed uncertainty estimate.",
            ha="center",
            fontsize=8,
        )
        figure.tight_layout(rect=(0, .08, 1, 1))
        target = self.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(target.with_suffix(".png"), dpi=220, bbox_inches="tight")
        plt.close(figure)
