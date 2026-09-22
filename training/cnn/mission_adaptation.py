"""Retained shared_v1 encoder with a testable gradient-reversal mission head.

The reference implementation/checkpoints are not edited. Planet parameters keep
their original names and shape. Only the optional mission head adds capacity.
"""
import math

import torch
from torch import nn

from training.cnn.train_kepler_cnn import ExoMinerStyleCNN


class GradientReversal(torch.autograd.Function):
    @staticmethod
    def forward(ctx, value, strength):
        if not math.isfinite(float(strength)) or strength < 0:
            raise ValueError("Gradient reversal strength must be finite and nonnegative")
        ctx.strength = float(strength)
        return value.view_as(value)

    @staticmethod
    def backward(ctx, gradient):
        return -ctx.strength * gradient, None


def reverse_gradient(value, strength=1.0):
    return GradientReversal.apply(value, strength)


def reversal_schedule(step, total_steps, maximum=1.0):
    if not 0 <= step < total_steps or total_steps < 2:
        raise ValueError("Schedule requires 0 <= step < total_steps and at least two steps")
    progress = step / (total_steps - 1)
    return maximum * (2.0 / (1.0 + math.exp(-10.0 * progress)) - 1.0)


class MissionAdaptationCNN(ExoMinerStyleCNN):
    """Exact retained fusion; supervised DANN operates before the planet head."""
    def __init__(self, adversarial=False, dropout=.2, scalar_dropout=.1):
        super().__init__(scalar_features=7, flat_features=907, dropout=dropout,
                         scalar_dropout=scalar_dropout, wide_dropout=.15,
                         use_wide_branch=False, use_aux_branch=False)
        self.mission_head = (nn.Sequential(nn.Linear(576, 128), nn.LayerNorm(128),
                                          nn.SiLU(), nn.Linear(128, 2))
                             if adversarial else None)

    def encode(self, x_global, x_local, x_scalar, x_flat):
        n = x_scalar.shape[0]
        if (x_global.shape != (n, 200, 3) or x_local.shape != (n, 100, 3)
                or x_scalar.shape != (n, 7) or x_flat.shape != (n, 907)):
            raise ValueError("Expected normalized shared_v1 200x3 / 100x3 / 7 / 907 contract")
        g = self.global_branch(x_global)
        l = self.local_branch(x_local)
        s = self.scalar_branch(x_scalar)
        return torch.cat([g, l, torch.abs(g - l), g * l, s], dim=1)

    def forward(self, x_global, x_local, x_scalar, x_flat, *, grl_strength=None):
        embedding = self.encode(x_global, x_local, x_scalar, x_flat)
        planet = self.classifier(embedding).squeeze(1)
        if grl_strength is None:
            return planet
        if self.mission_head is None:
            raise ValueError("No mission head on this comparator")
        return planet, self.mission_head(reverse_gradient(embedding, grl_strength))
