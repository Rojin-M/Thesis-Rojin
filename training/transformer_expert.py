"""Compact dual-view Transformer for the shared_v1 light-curve contract."""
from __future__ import annotations

import math

import torch
from torch import nn


class TransformerView(nn.Module):
    def __init__(self, bins, d_model=32, heads=4, layers=1, dropout=.15):
        super().__init__()
        if d_model % heads:
            raise ValueError("Transformer width must be divisible by attention heads")
        self.bins = bins
        self.project = nn.Linear(3, d_model)
        self.cls = nn.Parameter(torch.zeros(1, 1, d_model))
        self.position = nn.Parameter(torch.zeros(1, bins + 1, d_model))
        layer = nn.TransformerEncoderLayer(d_model, heads, d_model * 2, dropout,
                                           activation="gelu", batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, norm=nn.LayerNorm(d_model))
        nn.init.normal_(self.position, std=.02)
        nn.init.normal_(self.cls, std=.02)

    def forward(self, value):
        if value.ndim != 3 or value.shape[1:] != (self.bins, 3):
            raise ValueError("Invalid Transformer view shape")
        coverage = value[:, :, 2] > .5
        token = self.project(value)
        cls = self.cls.expand(len(value), -1, -1)
        token = torch.cat([cls, token], dim=1) + self.position
        padding = torch.cat([torch.zeros((len(value), 1), dtype=torch.bool, device=value.device), ~coverage], dim=1)
        return self.encoder(token, src_key_padding_mask=padding)[:, 0]


class TransitTransformer(nn.Module):
    """Attention-based expert independent of the retained convolutional encoder."""
    def __init__(self, d_model=32, heads=4, layers=1, dropout=.15):
        super().__init__()
        self.global_view = TransformerView(200, d_model, heads, layers, dropout)
        self.local_view = TransformerView(100, d_model, heads, layers, dropout)
        self.scalar = nn.Sequential(nn.LayerNorm(7), nn.Linear(7, 16), nn.GELU())
        self.classifier = nn.Sequential(nn.LayerNorm(d_model * 2 + 16), nn.Linear(d_model * 2 + 16, 32),
                                        nn.GELU(), nn.Dropout(dropout), nn.Linear(32, 1))

    def forward(self, x_global, x_local, x_scalar, x_flat):
        n = len(x_scalar)
        if (x_global.shape != (n, 200, 3) or x_local.shape != (n, 100, 3)
                or x_scalar.shape != (n, 7) or x_flat.shape != (n, 907)):
            raise ValueError("Expected normalized shared_v1 input contract")
        encoded = torch.cat([self.global_view(x_global), self.local_view(x_local), self.scalar(x_scalar)], dim=1)
        return self.classifier(encoded).squeeze(1)
