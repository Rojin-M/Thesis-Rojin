"""Compact paired light-curve/pixel model for the bounded AI-telescope pilot."""
from __future__ import annotations

import torch
from torch import nn


class LightCurveEncoder(nn.Module):
    def __init__(self, embedding_dim=48):
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv1d(3, 32, 7, padding=3), nn.GELU(),
            nn.Conv1d(32, 48, 5, padding=4, dilation=2), nn.GELU(),
            nn.Conv1d(48, embedding_dim, 5, padding=8, dilation=4), nn.GELU(),
        )
        self.normalization = nn.LayerNorm(embedding_dim)

    def forward(self, flux, valid, hidden=None):
        if flux.ndim != 2 or valid.shape != flux.shape:
            raise ValueError("Light-curve encoder expects aligned [batch,time] tensors")
        hidden = torch.zeros_like(flux) if hidden is None else hidden
        if hidden.shape != flux.shape:
            raise ValueError("Light-curve mask has the wrong shape")
        sequence = self.network(torch.stack([flux, valid, hidden], dim=1)).transpose(1, 2)
        weight = valid.unsqueeze(2)
        pooled = (sequence * weight).sum(dim=1) / weight.sum(dim=1).clamp_min(1.)
        return sequence, self.normalization(pooled)


class PixelCubeEncoder(nn.Module):
    def __init__(self, embedding_dim=48):
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv3d(1, 8, (3, 3, 3), padding=1), nn.GELU(),
            nn.Conv3d(8, 16, (3, 3, 3), stride=(2, 1, 1), padding=1), nn.GELU(),
            nn.Conv3d(16, 24, (3, 3, 3), stride=(2, 2, 2), padding=1), nn.GELU(),
            nn.AdaptiveAvgPool3d(1),
        )
        self.project = nn.Sequential(nn.Flatten(), nn.Linear(24, embedding_dim), nn.LayerNorm(embedding_dim))

    def forward(self, cube):
        if cube.ndim != 4:
            raise ValueError("Pixel encoder expects [batch,time,height,width]")
        return self.project(self.network(cube.unsqueeze(1)))


class MultimodalPretrainer(nn.Module):
    def __init__(self, embedding_dim=48):
        super().__init__()
        self.light = LightCurveEncoder(embedding_dim)
        self.pixel = PixelCubeEncoder(embedding_dim)
        self.light_projection = nn.Linear(embedding_dim, embedding_dim)
        self.pixel_projection = nn.Linear(embedding_dim, embedding_dim)
        self.reconstruction = nn.Sequential(
            nn.Conv1d(embedding_dim, embedding_dim, 3, padding=1), nn.GELU(),
            nn.Conv1d(embedding_dim, 1, 1),
        )

    def forward(self, flux, valid, hidden, cube):
        visible = flux.masked_fill(hidden.bool(), 0.)
        sequence, light = self.light(visible, valid, hidden)
        pixel = self.pixel(cube)
        reconstructed = self.reconstruction(sequence.transpose(1, 2)).squeeze(1)
        light_projected = torch.nn.functional.normalize(self.light_projection(light), dim=1)
        pixel_projected = torch.nn.functional.normalize(self.pixel_projection(pixel), dim=1)
        return reconstructed, light_projected, pixel_projected

    def encode(self, flux, valid, cube):
        _, light = self.light(flux, valid)
        pixel = self.pixel(cube)
        return torch.cat([light, pixel], dim=1)


class EventLocalizer(nn.Module):
    def __init__(self, embedding_dim=48):
        super().__init__()
        self.light = LightCurveEncoder(embedding_dim)
        self.pixel = PixelCubeEncoder(embedding_dim)
        self.pixel_to_sequence = nn.Linear(embedding_dim, embedding_dim)
        self.head = nn.Sequential(
            nn.Conv1d(embedding_dim * 2, embedding_dim, 5, padding=2), nn.GELU(),
            nn.Conv1d(embedding_dim, 1, 1),
        )

    def load_pretrained(self, model):
        self.light.load_state_dict(model.light.state_dict())
        self.pixel.load_state_dict(model.pixel.state_dict())

    def forward(self, flux, valid, cube):
        sequence, _ = self.light(flux, valid)
        pixel = self.pixel_to_sequence(self.pixel(cube)).unsqueeze(1).expand(-1, sequence.shape[1], -1)
        return self.head(torch.cat([sequence, pixel], dim=2).transpose(1, 2)).squeeze(1)


class InstrumentEncoder(nn.Module):
    """Encode pointing corrections and background trends aligned to a light curve."""

    def __init__(self, embedding_dim=48, channels=3):
        super().__init__()
        self.channels = int(channels)
        self.network = nn.Sequential(
            nn.Conv1d(self.channels + 1, 24, 7, padding=3), nn.GELU(),
            nn.Conv1d(24, 32, 5, stride=2, padding=2), nn.GELU(),
            nn.Conv1d(32, embedding_dim, 5, stride=2, padding=2), nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.normalization = nn.LayerNorm(embedding_dim)

    def forward(self, instrument, valid):
        if instrument.ndim != 3 or instrument.shape[1] != self.channels:
            raise ValueError("Instrument encoder expects [batch,channels,time]")
        if valid.ndim != 2 or valid.shape != (instrument.shape[0], instrument.shape[2]):
            raise ValueError("Instrument validity mask is misaligned")
        masked = instrument * valid.unsqueeze(1)
        value = self.network(torch.cat([masked, valid.unsqueeze(1)], dim=1)).squeeze(2)
        return self.normalization(value)


class ContextEncoder(nn.Module):
    """Encode standardized host and observing-context values plus missingness flags."""

    def __init__(self, input_dim, embedding_dim=48):
        super().__init__()
        self.input_dim = int(input_dim)
        self.network = nn.Sequential(
            nn.Linear(self.input_dim, 64), nn.GELU(), nn.LayerNorm(64),
            nn.Linear(64, embedding_dim), nn.LayerNorm(embedding_dim),
        )

    def forward(self, context):
        if context.ndim != 2 or context.shape[1] != self.input_dim:
            raise ValueError("Context encoder received the wrong feature shape")
        return self.network(context)


class ExtendedMultimodalPretrainer(nn.Module):
    """Add instrument and host-context views to the light/pixel representation."""

    def __init__(self, context_dim, embedding_dim=48, instrument_channels=3):
        super().__init__()
        self.light = LightCurveEncoder(embedding_dim)
        self.pixel = PixelCubeEncoder(embedding_dim)
        self.instrument = InstrumentEncoder(embedding_dim, instrument_channels)
        self.context = ContextEncoder(context_dim, embedding_dim)
        self.light_projection = nn.Linear(embedding_dim, embedding_dim)
        self.pixel_projection = nn.Linear(embedding_dim, embedding_dim)
        self.instrument_projection = nn.Linear(embedding_dim, embedding_dim)
        self.context_projection = nn.Linear(embedding_dim, embedding_dim)
        self.reconstruction = nn.Sequential(
            nn.Conv1d(embedding_dim, embedding_dim, 3, padding=1), nn.GELU(),
            nn.Conv1d(embedding_dim, 1, 1),
        )

    def load_light_pixel(self, model):
        self.light.load_state_dict(model.light.state_dict())
        self.pixel.load_state_dict(model.pixel.state_dict())
        self.light_projection.load_state_dict(model.light_projection.state_dict())
        self.pixel_projection.load_state_dict(model.pixel_projection.state_dict())
        self.reconstruction.load_state_dict(model.reconstruction.state_dict())

    def freeze_light_pixel(self):
        for module in (self.light, self.pixel, self.light_projection,
                       self.pixel_projection, self.reconstruction):
            for parameter in module.parameters():
                parameter.requires_grad_(False)

    def forward(self, flux, valid, hidden, cube, instrument, context):
        visible = flux.masked_fill(hidden.bool(), 0.)
        sequence, light = self.light(visible, valid, hidden)
        pixel = self.pixel(cube)
        instrument_embedding = self.instrument(instrument, valid)
        context_embedding = self.context(context)
        reconstructed = self.reconstruction(sequence.transpose(1, 2)).squeeze(1)
        project = lambda layer, value: torch.nn.functional.normalize(layer(value), dim=1)
        return (reconstructed, project(self.light_projection, light),
                project(self.pixel_projection, pixel),
                project(self.instrument_projection, instrument_embedding),
                project(self.context_projection, context_embedding))

    def encode(self, flux, valid, cube, instrument, context):
        _, light = self.light(flux, valid)
        return torch.cat([light, self.pixel(cube), self.instrument(instrument, valid),
                          self.context(context)], dim=1)


class ExtendedEventLocalizer(nn.Module):
    """Condition per-cadence event localization on pixels, instrument state and host context."""

    def __init__(self, context_dim, embedding_dim=48, instrument_channels=3):
        super().__init__()
        self.light = LightCurveEncoder(embedding_dim)
        self.pixel = PixelCubeEncoder(embedding_dim)
        self.instrument = InstrumentEncoder(embedding_dim, instrument_channels)
        self.context = ContextEncoder(context_dim, embedding_dim)
        self.pixel_to_sequence = nn.Linear(embedding_dim, embedding_dim)
        self.instrument_to_sequence = nn.Linear(embedding_dim, embedding_dim)
        self.context_to_sequence = nn.Linear(embedding_dim, embedding_dim)
        self.head = nn.Sequential(
            nn.Conv1d(embedding_dim * 4, embedding_dim * 2, 5, padding=2), nn.GELU(),
            nn.Conv1d(embedding_dim * 2, 1, 1),
        )

    def load_pretrained(self, model):
        for name in ("light", "pixel", "instrument", "context"):
            getattr(self, name).load_state_dict(getattr(model, name).state_dict())

    @staticmethod
    def _broadcast(value, sequence):
        return value.unsqueeze(1).expand(-1, sequence.shape[1], -1)

    def forward(self, flux, valid, cube, instrument, context,
                use_instrument=True, use_context=True):
        sequence, _ = self.light(flux, valid)
        pixel = self._broadcast(self.pixel_to_sequence(self.pixel(cube)), sequence)
        if use_instrument:
            instrument_value = self.instrument_to_sequence(self.instrument(instrument, valid))
        else:
            instrument_value = torch.zeros_like(pixel[:, 0])
        if use_context:
            context_value = self.context_to_sequence(self.context(context))
        else:
            context_value = torch.zeros_like(pixel[:, 0])
        instrument_value = self._broadcast(instrument_value, sequence)
        context_value = self._broadcast(context_value, sequence)
        joined = torch.cat([sequence, pixel, instrument_value, context_value], dim=2)
        return self.head(joined.transpose(1, 2)).squeeze(1)
