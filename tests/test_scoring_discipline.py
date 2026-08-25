"""Tests for anti-cherry-picking scoring discipline and sealed corpus protection (PREREGISTRATION.md §2).

Verifies:
1. An append-only sidecar log data/<corpus>_scoring_log.jsonl is updated on every scoring run.
2. The sealed ground-truth corpus is never mutated.
3. Scoring a sealed corpus a second time without --rescore raises ConfigurationError and exits non-zero.
4. Scoring with --rescore succeeds, records rescore_override in the sidecar log, and notes it in the report.
5. build_report() prints times_scored in every report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from agent import db as agent_db
from agent.config import ConfigurationError
from agent.policy.engine import load_rules
from datagen.generate import generate, write_ground_truth, write_operational_db
from evalharness.metrics import build_report
from evalharness.run import read_scoring_log, record_scoring_run, run


def _setup_sealed_corpus(tmp_path: Path, seed: int = 777001, n: int = 100) -> tuple[Path, Path]:
    """Creates a temporary sealed test corpus (corpus='test')."""
    records, windows, manifest = generate(seed=seed, n=n, corpus="test", scenario_id="S1")
    db_path = tmp_path / "test.db"
    gt_path = tmp_path / "test_ground_truth.jsonl"

    conn = agent_db.connect(db_path)
    rules = load_rules()
    write_operational_db(conn, records, windows, seed, rules)
    write_ground_truth(gt_path, records, manifest)
    conn.close()
    return db_path, gt_path


def test_sealed_corpus_scoring_log_and_rescore_protection(tmp_path):
    db_path, gt_path = _setup_sealed_corpus(tmp_path, seed=777001, n=50)
    out_path = tmp_path / "report_test.md"

    gt_bytes_initial = gt_path.read_bytes()

    # 1. First score attempt on sealed corpus -> MUST succeed
    rep1 = run(db_path, gt_path, out_path, seed=777001, provider="stub", rescore=False)
    assert out_path.exists()
    assert "times_scored=1" in rep1

    # Ground truth file must NEVER be mutated
    assert gt_path.read_bytes() == gt_bytes_initial, "Ground truth corpus was mutated!"

    # Sidecar log must exist and have 1 entry
    log = read_scoring_log("test", tmp_path)
    assert len(log) == 1
    assert log[0]["corpus"] == "test"
    assert log[0]["seed"] == 777001
    assert log[0]["rescore_override"] is False

    # 2. Second score attempt on sealed corpus WITHOUT rescore -> MUST raise ConfigurationError
    with pytest.raises(ConfigurationError) as excinfo:
        run(db_path, gt_path, out_path, seed=777001, provider="stub", rescore=False)
    assert "is sealed and has already been scored" in str(excinfo.value)
    assert "--rescore" in str(excinfo.value)

    # Sidecar log count must remain 1 after refused attempt
    log_after_refusal = read_scoring_log("test", tmp_path)
    assert len(log_after_refusal) == 1

    # 3. Third score attempt WITH rescore=True -> MUST succeed
    rep2 = run(db_path, gt_path, out_path, seed=777001, provider="stub", rescore=True)
    assert "times_scored=2" in rep2

    # Sidecar log must now have 2 entries, with the second marked rescore_override=True
    log_after_rescore = read_scoring_log("test", tmp_path)
    assert len(log_after_rescore) == 2
    assert log_after_rescore[1]["rescore_override"] is True

    # Ground truth still never mutated
    assert gt_path.read_bytes() == gt_bytes_initial


def test_cli_second_score_without_rescore_exits_nonzero(tmp_path):
    """Subprocess CLI test: running evalharness.run on a sealed corpus a second time
    without --rescore must exit with a non-zero exit code."""
    db_path, gt_path = _setup_sealed_corpus(tmp_path, seed=777002, n=50)
    out_path = tmp_path / "report_cli.md"

    # First run via CLI -> exit code 0
    cmd1 = [
        sys.executable,
        "-m",
        "evalharness.run",
        "--db",
        str(db_path),
        "--gt",
        str(gt_path),
        "--out",
        str(out_path),
    ]
    proc1 = subprocess.run(cmd1, capture_output=True, text=True)
    assert proc1.returncode == 0, f"First run failed: {proc1.stderr}"

    # Second run via CLI without --rescore -> exit code MUST be non-zero (1)
    proc2 = subprocess.run(cmd1, capture_output=True, text=True)
    assert proc2.returncode != 0, "Second score run without --rescore should have exited non-zero!"
    assert "ConfigurationError" in proc2.stderr or "is sealed and has already been scored" in proc2.stderr

    # Third run via CLI with --rescore -> exit code 0
    cmd3 = cmd1 + ["--rescore"]
    proc3 = subprocess.run(cmd3, capture_output=True, text=True)
    assert proc3.returncode == 0, f"Rescore run failed: {proc3.stderr}"
