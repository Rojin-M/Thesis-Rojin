"""Frozen eleven-expert v2 inference, without labels, fitting or catalog access."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

from .contracts import validate_shared_inputs
from .protocol import ROOT, ValidationError, digest
from .provenance import file_sha256
from .scoring import NORMALIZER_SHA, verified_bytes

RELEASE = ROOT / "configs/watcher_supermodel_v2.json"
MODEL_NAME = "crossfit_nonlinear_supermodel_v2"
MODEL_SHA256 = "487bc15021319dbf16d1a9b10c672b1d27491f398ccd02c6701f5245d1f355b7"
EXPERT_NAMES = ("tess_only", "kepler_only", "fine_tuned", "pooled", "dann", "transformer",
                "transit_morphology", "stellar_variability", "tls", "aperture_photometry", "difference_image")


def load_release(path=RELEASE):
    value = json.loads(Path(path).read_text())
    if value.get("version") != "watcher_supermodel_v2_release1":
        raise ValidationError("Unknown watcher supermodel release")
    if set(value.get("runs", {})) != {"cnn", "transformer", "diagnostic", "physical", "supermodel"}:
        raise ValidationError("Supermodel release must pin all five suites")
    for relative, checksum in value["files"].items():
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT) or file_sha256(target) != checksum:
            raise ValidationError("Supermodel release checksum mismatch: " + relative)
    return value


class SupermodelScorer:
    """Reuse the audited expert weights, context ordering, blend and temperature."""
    def __init__(self, release_path=RELEASE):
        import joblib
        import torch
        from scripts.experiments.crossfit_competence import EXPERTS
        from scripts.experiments.diagnostic_experts import load_models as diagnostics
        from scripts.experiments.physical_experts import FEATURES, KINDS
        from scripts.experiments.transformer_expert import load_models as transformers
        from .model_comparison import ComparisonScorer

        self.release = load_release(release_path)
        self.release_id = digest(self.release)
        runs = self.release["runs"]
        cnn = ROOT / runs["cnn"]["path"]
        reference = ComparisonScorer(cnn.parent, cnn.name, runs["cnn"]["spec_sha256"])
        self.stats = reference.stats
        self.models = reference.models + transformers(ROOT / runs["transformer"]["path"], runs["transformer"]["spec_sha256"])
        self.models += diagnostics(ROOT / runs["diagnostic"]["path"], runs["diagnostic"]["spec_sha256"])
        self.experts, self.physical_kinds = list(EXPERTS), KINDS
        self.physical_columns = [name for kind in KINDS for name in FEATURES[kind]]
        physical = runs["physical"]["path"] + "/physical_experts.pt"
        self.physical = torch.load(io.BytesIO(verified_bytes(ROOT / physical, self.release["files"][physical])),
                                   map_location="cpu", weights_only=True)["experts"]
        relative = runs["supermodel"]["path"] + "/supermodel.joblib"
        if self.release["files"][relative] != MODEL_SHA256 or set(self.experts) != set(EXPERT_NAMES):
            raise ValidationError("Release does not contain the audited v2 model")
        self.artifact = joblib.load(io.BytesIO(verified_bytes(ROOT / relative, self.release["files"][relative])))
        if self.artifact["version"] != MODEL_NAME or self.artifact["experts"] != self.experts:
            raise ValidationError("Supermodel artifact identity differs")
        self.temperature = float(self.artifact["calibration_temperature"])
        if not np.isfinite(self.temperature) or not .05 <= self.temperature <= 20:
            raise ValidationError("Invalid frozen supermodel temperature")
        self.manifest = {
            "model_name": MODEL_NAME, "model_sha256": self.release["files"][relative],
            "normalization_sha256": NORMALIZER_SHA, "input_contract": "shared_v1",
            "additional_input_contract": "blind_tls_aperture_difference_image_v1",
            "release_id": self.release_id, "experts": self.experts,
            "calibration_temperature": self.temperature,
            "calibration": "not_calibrated_for_blind_search",
            "calibration_scope": "frozen_labelled_calibration_temperature_only",
            "semantics": "ranking_score_not_planet_confirmation_probability",
            "ml_hard_veto": False, "validation_threshold": None,
            "uncertainty": "not_estimated", "device": "cpu",
        }

    def predict(self, arrays, metadata, physical_rows):
        """Return scores and exact expert/context evidence; labels are not accepted."""
        import torch
        from scipy.special import expit
        from scripts.data.tess_dataset import apply_normalization
        from scripts.experiments.adaptation_data import INPUTS
        from scripts.experiments.crossfit_competence import context_matrix
        from scripts.experiments.crossfit_supermodel_v2 import blend_logits, meta_logits, static_logits

        validate_shared_inputs(arrays)
        size = len(arrays["X"])
        if not 1 <= size <= 64 or len(metadata) != size or len(physical_rows) != size:
            raise ValidationError("Supermodel rows must be aligned and bounded")
        for row in metadata:
            if set(row) != {"period", "duration_hours"}:
                raise ValidationError("Inference accepts period/duration only, never labels or catalog fields")
            if not np.isfinite([row["period"], row["duration_hours"]]).all() or not 0 < row["duration_hours"] < 12 * row["period"]:
                raise ValidationError("Invalid inferred ephemeris")
        normalized = apply_normalization(arrays, self.stats)
        part = {key: torch.from_numpy(normalized[key]) for key in INPUTS}
        part["metadata"] = metadata
        groups = {name: [] for name in self.experts[:-3]}
        with torch.inference_mode():
            for record, model in self.models:
                values = model(*[part[key] for key in INPUTS]).numpy()
                if values.shape != (size,) or not np.isfinite(values).all():
                    raise ValidationError("Malformed neural expert output")
                groups[record["arm"]].append(values)
        if any(not values for values in groups.values()):
            raise ValidationError("Missing frozen neural/diagnostic expert")
        neural = np.stack([np.stack(groups[name]).mean(axis=0) for name in groups], axis=1).astype(np.float32)
        raw = np.array([[row[name] for name in self.physical_columns] for row in physical_rows], dtype=np.float32)
        available = np.array([[bool(row["tls_available"]), bool(row["pixel_available"]),
                               bool(row["pixel_available"])] for row in physical_rows])
        physical = []
        for kind in self.physical_kinds:
            item = self.physical[kind]
            # Match the audit's float64 linear calculation before casting logits.
            values = np.array([[row[name] for name in item["features"]] for row in physical_rows], dtype=float)
            value = ((values - np.array(item["mean"])) / np.array(item["scale"])) @ np.array(item["coefficient"]) + item["intercept"]
            physical.append(value)
        base = np.concatenate([neural, np.stack(physical, axis=1).astype(np.float32)], axis=1)
        availability = np.concatenate([np.ones_like(neural, dtype=bool), available], axis=1)
        context, names = context_matrix(base, raw, available, part, self.physical_columns)
        if names != self.artifact["feature_names"] or not np.isfinite(base).all():
            raise ValidationError("Supermodel context differs from frozen training schema")
        static = static_logits(base, availability, self.artifact["prior"])
        combined = blend_logits(static, meta_logits(self.artifact["model"], context),
                                self.artifact["selected_configuration"]["blend"])
        score = expit(combined / self.temperature)
        if not np.isfinite(score).all():
            raise ValidationError("Nonfinite supermodel result")
        return [{**self.manifest, "score": float(score[i]), "logit": float(combined[i]),
                 "raw_score": float(expit(combined[i])), "static_logit": float(static[i]),
                 "expert_logits": dict(zip(self.experts, map(float, base[i]))),
                 "expert_available": dict(zip(self.experts, map(bool, availability[i]))),
                 "context": dict(zip(names, map(float, context[i]))),
                 "eligible_for_primary": bool(availability[i].all()),
                 "missing_experts": [name for name, present in zip(self.experts, availability[i]) if not present]}
                for i in range(size)]
