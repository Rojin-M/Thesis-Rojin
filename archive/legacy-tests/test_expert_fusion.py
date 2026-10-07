import unittest

import numpy as np
import torch

from scripts.experiments.expert_fusion import (
    ARMS, _apply_gate, _evaluate_abstention, _select_abstention,
    VERSION, predict_with_artifact, train_gate, validate_fusion_config,
)


class ExpertFusionTests(unittest.TestCase):
    def config(self):
        return validate_fusion_config({"steps": 120, "gate_seeds": [7], "hidden_units": 8})

    def test_context_gate_learns_feature_conditioned_expertise(self):
        rng = np.random.default_rng(4)
        context = rng.normal(size=(240, 3)).astype(np.float32)
        labels = (context[:, 0] > 0).astype(np.float32)
        good_left = np.where(context[:, 1] < 0, (labels * 2 - 1) * 5, -(labels * 2 - 1) * 5)
        good_right = np.where(context[:, 1] >= 0, (labels * 2 - 1) * 5, -(labels * 2 - 1) * 5)
        logits = np.column_stack([good_left, good_right, np.zeros((240, len(ARMS) - 2))]).astype(np.float32)
        model = train_gate(context, logits, labels, self.config(), 7)
        fused, weights = _apply_gate([model], context, logits)
        self.assertGreater(((fused >= 0) == labels).mean(), .9)
        self.assertGreater(weights[context[:, 1] < 0, 0].mean(), weights[context[:, 1] < 0, 1].mean())
        self.assertGreater(weights[context[:, 1] >= 0, 1].mean(), weights[context[:, 1] >= 0, 0].mean())

    def test_abstention_rule_is_calibration_only_and_reusable(self):
        labels = np.array([0, 0, 0, 1, 1, 1])
        logits = np.array([-4, -3, .1, -.1, 3, 4])
        experts = np.tile(logits[:, None], (1, len(ARMS)))
        rule = _select_abstention(logits, experts, labels, .9, .2)
        self.assertTrue(rule["available"])
        audit = _evaluate_abstention(rule, logits, experts, labels)
        self.assertEqual(audit["accuracy_when_retained"], 1.)
        self.assertLess(audit["coverage"], 1.)

    def test_missing_expert_is_routed_to_zero_weight(self):
        context = np.zeros((3, 2), dtype=np.float32)
        logits = np.ones((3, len(ARMS)), dtype=np.float32)
        labels = np.ones(3, dtype=np.float32)
        model = train_gate(context, logits, labels, self.config(), 7)
        available = np.ones_like(logits, dtype=bool)
        available[:, 0] = False
        _, weights = _apply_gate([model], context, logits, availability=available)
        np.testing.assert_array_equal(weights[:, 0], 0.)
        with self.assertRaises(ValueError):
            _apply_gate([model], context, logits, availability=np.zeros_like(available))

    def test_sealed_artifact_can_be_applied_without_retraining(self):
        config = self.config()
        context = np.zeros((2, 3), dtype=np.float32)
        logits = np.ones((2, len(ARMS)), dtype=np.float32)
        model = train_gate(context, logits, np.ones(2), config, 7)
        artifact = {"version": VERSION, "experts": list(ARMS), "config": config,
                    "context_mean": np.zeros(3), "context_scale": np.ones(3),
                    "contextual_gate_states": [model.state_dict()], "calibration_temperature": 1.,
                    "abstention_rule": {"available": True, "threshold": 0.}}
        result = predict_with_artifact(artifact, context, logits)
        self.assertEqual(result["weights"].shape, logits.shape)
        self.assertFalse(result["abstain"].any())

    def test_invalid_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_fusion_config({"unknown": 1})
        with self.assertRaises(ValueError):
            validate_fusion_config({"gate_seeds": [1, 1]})


if __name__ == "__main__":
    unittest.main()
