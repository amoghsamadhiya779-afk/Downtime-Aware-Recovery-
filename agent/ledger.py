"""Cohort assignment. Seeded, one-shot per case, and the database (not this module)
is what actually enforces immutability afterwards (agent/db.py: cohort_is_immutable).

Assignment happens by hashing the case_id against the seed rather than drawing from a
shared Random instance, so cohort membership is reproducible independent of
processing order — replaying the same corpus in a different order yields the same
holdout, which matters once the pipeline is ever run concurrently.
"""

from __future__ import annotations

import hashlib

from agent.models import Cohort


def assign_cohort(case_id: str, seed: int, holdout_fraction: float) -> Cohort:
    if not 0.0 <= holdout_fraction <= 1.0:
        raise ValueError("holdout_fraction must be in [0, 1]")
    digest = hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()
    # top 8 hex chars -> uniform in [0, 1)
    frac = int(digest[:8], 16) / 0xFFFFFFFF
    return Cohort.HOLDOUT if frac < holdout_fraction else Cohort.TREATED
