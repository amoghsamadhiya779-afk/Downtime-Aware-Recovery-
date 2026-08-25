"""Hidden ground truth. NEVER imported from agent/ — enforced by tests/test_isolation.py.

`p_*` fields ARE the response model, expressed per record rather than as one global
constant. That is what the biggest technical risk in PRODUCT_THESIS.md rests on: every
rupee figure downstream of these fields is an assumption, declared here and swept in
Phase 3, never shown to the agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.models import Recoverability


class GroundTruth(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    true_class: Recoverability
    ambiguity: Literal["CLEAN", "AMBIGUOUS"]
    p_organic: float = Field(ge=0.0, le=1.0)  # recovers with NO action at all
    p_retry_now: float = Field(ge=0.0, le=1.0)
    p_retry_after_downtime: float = Field(ge=0.0, le=1.0)
    max_recoverable: bool  # for the achieved-vs-ceiling metric (Phase 3)


class BatchManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    corpus: Literal["dev", "calibration", "test"]
    seed: int
    scenario_id: str
    n: int
    generator_version: str
    times_scored: int = 0
    created_at: datetime
