"""Frozen trained CNN inference, pinned to the audited Kepler reference bytes."""
import hashlib
import io
import json

import numpy as np

from .contracts import validate_shared_inputs
from .protocol import ROOT, ValidationError

CHECKPOINT = ROOT / "outputs/shared_cnn/kepler/dataset_kepler_shared_v1_cnn_20260915_080811/best_model.pt"
NORMALIZER = ROOT / "data/processed/kepler/shared_v1/kepler_train_normalization.npz"
CHECKPOINT_SHA = "7890efd17fc072efb74465a9fbfa6fb8b0192388d91af520961349f0066ba703"
NORMALIZER_SHA = "6f4ac773f6f2dd6c2200e68b903acb0c7a3f585a593ac2d882c03af03c705dc1"


def verified_bytes(path, expected):
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValidationError("Frozen model/normalizer checksum mismatch: " + str(path))
    return payload


class FrozenScorer:
    def __init__(self, batch_size=32):
        import torch
        from training.cnn.train_kepler_cnn import ExoMinerStyleCNN
        if type(batch_size) is not int or not 1 <= batch_size <= 64:
            raise ValidationError("Inference batch size must be 1–64")
        torch.set_num_threads(min(torch.get_num_threads(), 4))
        self.batch_size = batch_size
        checkpoint = torch.load(io.BytesIO(verified_bytes(CHECKPOINT, CHECKPOINT_SHA)), map_location="cpu", weights_only=True)
        with np.load(io.BytesIO(verified_bytes(NORMALIZER, NORMALIZER_SHA)), allow_pickle=False) as archive:
            self.stats = {key: archive[key] for key in archive.files}
        config = checkpoint["model_config"]
        if config["scalar_features"] != 7 or config["flat_features"] != 907 or config.get("use_aux_branch"):
            raise ValidationError("Checkpoint violates the shared_v1 feature contract")
        if checkpoint["config"].get("prepare_version") != "shared_v1":
            raise ValidationError("Checkpoint is not the shared_v1 reference")
        self.model = ExoMinerStyleCNN(**config)
        self.model.load_state_dict(checkpoint["model_state"], strict=True)
        self.model.eval()
        self.manifest = {"model_name": "frozen_Kepler_shared_v1_CNN_seed42", "checkpoint_path": str(CHECKPOINT),
            "model_sha256": CHECKPOINT_SHA, "normalization_path": str(NORMALIZER), "normalization_sha256": NORMALIZER_SHA,
            "input_contract": "shared_v1", "epoch": int(checkpoint["epoch"]), "model_config": config,
            "validation_threshold": float(checkpoint["val_threshold"]),
            "threshold_use": "recorded_source_validation_F1_only_not_a_search_gate",
            "normalization_scope": "frozen_Kepler_TRAIN_moments_no_target_fitting",
            "device": "cpu", "batch_size": batch_size, "torch_version": str(torch.__version__), "numpy_version": np.__version__,
            "calibration": "not_calibrated_for_blind_search", "uncertainty": "not_estimated",
            "semantics": "sigmoid_ranking_score_not_planet_confirmation_probability", "ml_hard_veto": False}
        if not np.isfinite(self.manifest["validation_threshold"]) or not 0 <= self.manifest["validation_threshold"] <= 1:
            raise ValidationError("Invalid saved validation threshold")
        # Ensure all provenance is serializable before any evidence is published.
        json.dumps(self.manifest, allow_nan=False)

    def predict(self, arrays):
        import torch
        from scripts.data.tess_dataset import apply_normalization
        validate_shared_inputs(arrays)
        normalized = apply_normalization(arrays, self.stats)
        logits, scores = [], []
        with torch.inference_mode():
            for start in range(0, len(arrays["X"]), self.batch_size):
                batch = [torch.from_numpy(normalized[key][start:start + self.batch_size])
                         for key in ("x_global", "x_local", "x_scalar", "x_flat")]
                value = self.model(*batch)
                if value.ndim != 1 or not torch.isfinite(value).all():
                    raise ValidationError("Nonfinite or malformed checkpoint output")
                logits.extend(value.tolist()); scores.extend(torch.sigmoid(value).tolist())
        return {"logits": logits, "scores": scores, "normalized": normalized}
