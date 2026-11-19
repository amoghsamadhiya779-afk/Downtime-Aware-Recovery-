# Evaluation Report — CaMeL Security & Phase 3 Confidence Calibration

## 1. Security Evaluation: Indirect Prompt Injections (`scripts/run_camel_eval.py`)
- **Threat Model**: Attacker-controlled gateway `ErrorObj.description` strings embedding indirect prompt injections (instruction overrides, XML/system-tag spoofing, JSON schema smuggling, newline enum spoofing, and SQL/exfiltration directives).
- **Attack Matrix**: 5 realistic gateway failure prefixes x 5 distinct injection families = **25 adversarial payloads**.
- **Defenses Verified per Payload**:
  1. Direct sink gate (`enforce_sink(..., "payment_dispatch", TrustLevel.TRUSTED_SYSTEM)`) raises `CaMeLSecurityViolation`.
  2. Closed-enum declassification (`declassify_enum(..., Recoverability, {"policy_eval"})`) raises `CaMeLSecurityViolation`.
  3. Lattice Meet + DAG BFS (`combine_passports` + `ProvenanceGraph.has_untrusted_ancestor`) strips `"payment_dispatch"` and flags tainted lineage.
- **Result**: **25 / 25 blocked — 0.0% Attack Success Rate (ASR)**.

## 2. Out-of-Sample Confidence Calibration Evaluation (`scripts/run_camel_eval.py`)
- **Zero-Leakage Protocol**: `BinnedCalibrator(num_bins=10, alpha=1.0)` is fit strictly on the separate `calibration` split (`data/calibration.db`, Seed 12345, `n=156` ambiguous cases of 500) and evaluated out-of-sample on the canonical `dev` split (`data/dev.db`, Seed 42, `n=100` ambiguous cases of 300) using `StubDiagnosis`.
- **Policy Integration**: Verified end-to-end in `tests/test_calibration.py`—an overconfident diagnosis (`raw=0.95`) whose empirical bin accuracy falls below `CONFIDENCE_FLOOR` is routed to `Decision.REVIEW` (`QUARANTINED`) instead of spending an automated retry.

| Metric | Raw Confidence | Calibrated (`BinnedCalibrator`) | Relative Change |
| :--- | :---: | :---: | :---: |
| **Expected Calibration Error (ECE, 10 bins)** | `0.2660` | **`0.0340`** | **-87.2%** |
| **Brier Score** | `0.2901` | **`0.1721`** | **-40.7%** |

## 3. Automated Test & Integrity Gates
- **Pytest Suite**: `344 passed` (330 core control-plane tests + 12 adversarial CaMeL tests in `tests/test_camel_security.py` + 2 calibration/pipeline tests in `tests/test_calibration.py`).
- **Docs Anti-Drift Gate (`scripts/docs_check.py`)**: Verified passing (`14 known rule ids, numeric provenance verified`).

## 4. Exact Reproduction Commands
```powershell
Set-Location "D:\Desktop\Razor Pay AI Buildathon"
& ".venv\Scripts\python.exe" -m pytest -q
& ".venv\Scripts\python.exe" scripts/run_camel_eval.py
& ".venv\Scripts\python.exe" scripts/docs_check.py
```
