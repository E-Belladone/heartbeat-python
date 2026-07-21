"""API models for the signal ingest service (M17)."""

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["SignalKind", "SignalRequest", "SignalResponse"]

SignalKind = Literal["start", "stop", "pulse"]
"""The pinned kind set; mirrored by the CHECK on signal.events."""


class SignalRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    kind: SignalKind


class SignalResponse(BaseModel):
    id: int
    device: str
    source: str
    kind: SignalKind
    at: int
    """Server-stamped arrival time (epoch seconds) — the client sent none."""
