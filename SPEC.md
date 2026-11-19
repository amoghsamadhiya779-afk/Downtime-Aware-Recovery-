# System Specification — Downtime-Aware Payment Recovery Control Plane

## 1. Purpose & Architectural Boundary
This control plane decides what happens **after** a payment fails across Indian rails (UPI, Cards, Netbanking, eMandates) under merchant-side fatigue, economics, and compliance limits. One unified pipeline (`agent/pipeline.py:process_case`) serves both live recovery and deterministic replay, differing only by injected `Clock` and `ExecutorPort`.

## 2. Pipeline Stages
1. **Ingest (`agent/pipeline.py:ingest`)**: Deterministic cohort assignment (`TREATED` vs `HOLDOUT`) via `SHA-256(f"{seed}:{case_id}")` (`agent/ledger.py`). Cohort immutability is enforced at the database layer via SQLite trigger `cohort_is_immutable` (`agent/db.py`).
2. **Triage (`agent/triage.py`)**: Deterministic taxonomy classifier. Clean matches bypass the LLM; unseen error combinations fail closed (`Recoverability.UNKNOWN` + `Action.STOP`); only `AMBIGUOUS` failures invoke AI-1.
3. **Diagnosis (`agent/diagnosis/port.py`)**: Pure structured-in, structured-out function (`DiagnosisPort`) holding zero tools, zero DB handles, and zero network access. `DiagnosisInput` admits enum/numeric fields only—never untrusted free text (`ErrorObj.description`).
4. **Empirical Calibration (`agent/calibration.py`)**: Closes Invariant 5 by mapping raw AI-1 self-reported confidence into Laplace-smoothed empirical bin probabilities (`BinnedCalibrator`) before policy evaluation.
5. **Zero-LLM Policy Gate (`agent/policy/engine.py`)**: Pure deterministic function consuming `agent/policy/rules.yaml` in fixed rule order (`REQUIRED_STATE`, `SUPPORTED_ACTION`, `KILL_SWITCH`, `HOLDOUT_GUARD`, `TERMINAL_CLASS`, `ATTEMPT_CAP`, `DUPLICATE_ACTION`, `EV_FLOOR`, `CONFIDENCE_FLOOR`, `DOWNTIME_DEFER`) and returning a `Verdict`.
6. **Idempotent Execution & Audit (`agent/executors/`, `agent/audit.py`)**: Executors accept `Verdict` only, deduplicate via SHA-256 `idempotency_key`, quarantine uncertain timeouts, and append every transition to an append-only SHA-256 hash chain (`audit_no_update`, `audit_no_delete`).

## 3. Security Specification: CaMeL Capability & Taint Engine (`agent/security/camel.py`)
Implements the capability-lattice and provenance-tracking defense from *"Defeating Prompt Injections by Design"* (Debenedetti et al., arXiv:2503.18813):
- **Trust Lattice (`TrustLevel(IntEnum)`)**: Strictly ordered `UNTRUSTED_EXTERNAL (0) < QUARANTINED_AI (1) < TRUSTED_SYSTEM (2)`.
- **Immutable Data Passports (`CapabilityPassport`)**: Frozen dataclass with `trust`, `allowed_sinks: frozenset[str]`, `node_id`, and `parents: tuple[str, ...]` preventing in-place privilege escalation.
- **Lattice Meet (`combine_passports`)**: Derived values inherit `min(trust)` and the intersection (`&`) of all parent `allowed_sinks`. Fails closed on empty parent input.
- **Provenance DAG (`ProvenanceGraph`)**: Append-only lineage registry (rejecting duplicate `node_id` overwrites) with O(V + E) BFS reachability (`has_untrusted_ancestor`) that fails closed on missing or `UNTRUSTED_EXTERNAL` ancestors.
- **Closed-Enum Declassification (`declassify_enum`)**: Only legal bridge from untrusted/quarantined data into a closed `Enum` subclass (`Recoverability`, `Action`, `Method`), rejecting open types (`str`/`int`) and malformed strings with `CaMeLSecurityViolation`.
- **Sink Gate (`enforce_sink`)**: Unwraps `CaMeLValue[T]` only when both `sink_name in allowed_sinks` and `trust >= min_trust`; otherwise raises `CaMeLSecurityViolation`.

## 4. Calibration Specification (`agent/calibration.py`)
- **`BinnedCalibrator`**: Partitions `[0.0, 1.0]` into M uniform bins (O(N + M) fit, O(1) lookup) using Laplace rule-of-succession smoothing `(hits + alpha) / (counts + 2 * alpha)` to prevent division by zero on empty bins and tame tiny-sample variance. Fails closed (`RuntimeError`) if called before `fit()`.
- **`expected_calibration_error`**: Computes exact M-bin ECE `sum_b (|B_b| / N) * |acc(B_b) - conf(B_b)|`.
- **Pipeline Integration**: `process_case(..., calibrator=...)` calibrates `AMBIGUOUS` AI-1 proposals and forwards `calibrated_confidence` to `agent/policy/engine.py:evaluate()`, keeping deterministic clean triage matches unaffected and `agent/policy/engine.py` 100% pure.

## 5. Non-Negotiable Invariants
All 10 invariants in `CLAUDE.md` remain enforced: single live/replay code path, zero LLM tools, no untrusted free text in prompts, unconditional `HOLDOUT_GUARD`, calibrated-only confidence gating, fail-closed unknown handling, `agent/` never imports `datagen/`, `Verdict`-only executor contract, generated evaluation provenance in `README.md`, and thresholds centralized in `agent/policy/rules.yaml`.
