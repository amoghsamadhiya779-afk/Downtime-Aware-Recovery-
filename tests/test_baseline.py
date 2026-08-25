"""The baseline arm's defining property is that it ignores context. These tests
exist so that stays true — a future edit that makes it branch on error reason or
downtime would quietly invalidate every A3-vs-A1 comparison built on it, and the
resulting number would look fine while measuring the wrong thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.diagnosis.baseline import FIXED_DELAY_MINUTES, BaselineDiagnosis
from agent.diagnosis.port import DiagnosisInput
from agent.models import Action, DowntimeContext, ErrorObj, Method, Recoverability

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _inp(reason: str, *, downtime: DowntimeContext | None = None, **kwargs) -> DiagnosisInput:
    defaults = dict(
        method=Method.UPI,
        error=ErrorObj(code="X", source="gateway", step="payment_authorization", reason=reason),
        amount_paise=100_00,
        attempt_no=1,
        prior_failures=0,
        downtime=downtime or DowntimeContext(),
    )
    defaults.update(kwargs)
    return DiagnosisInput(**defaults)


def test_identical_output_regardless_of_error_reason():
    """A terminal failure and a transient one get the same answer — that IS the
    baseline. If this ever fails, the baseline has started diagnosing."""
    diag = BaselineDiagnosis()
    terminal = diag.diagnose(_inp("account_closed"))
    transient = diag.diagnose(_inp("gateway_timeout"))
    unseen = diag.diagnose(_inp("some_reason_nobody_has_seen"))

    for other in (transient, unseen):
        assert other.recoverability == terminal.recoverability
        assert other.proposed_action == terminal.proposed_action
        assert other.proposed_delay_minutes == terminal.proposed_delay_minutes


def test_ignores_downtime_context():
    """The downtime signal is the AI arm's main advantage. The baseline must not
    consult it, or the ablation measures nothing."""
    diag = BaselineDiagnosis()
    no_downtime = diag.diagnose(_inp("payment_failed", downtime=DowntimeContext()))
    heavy_downtime = diag.diagnose(_inp("payment_failed", downtime=DowntimeContext(
        active=True, severity="high", scheduled=False, instrument_match=True,
        expected_end=NOW + timedelta(hours=3),
    )))
    assert no_downtime.proposed_delay_minutes == heavy_downtime.proposed_delay_minutes
    assert no_downtime.proposed_action == heavy_downtime.proposed_action


def test_ignores_attempt_history_and_amount():
    diag = BaselineDiagnosis()
    first = diag.diagnose(_inp("payment_failed", attempt_no=1, prior_failures=0, amount_paise=100))
    later = diag.diagnose(_inp("payment_failed", attempt_no=3, prior_failures=2, amount_paise=5_000_00))
    assert first.proposed_action == later.proposed_action
    assert first.proposed_delay_minutes == later.proposed_delay_minutes


def test_always_proposes_a_fixed_retry():
    diag = BaselineDiagnosis()
    p = diag.diagnose(_inp("payment_failed"))
    assert p.recoverability is Recoverability.TRANSIENT_INFRA
    assert p.proposed_action is Action.RETRY
    assert p.proposed_delay_minutes == FIXED_DELAY_MINUTES


def test_cites_no_evidence_and_stays_below_the_confidence_gate():
    """It has no basis for a view, so it must not claim one. The same rule that
    governs the AI arm (confidence >= 0.7 requires evidence) applies here, and
    this arm is structurally unable to satisfy it — so it stays under the line."""
    from agent.diagnosis.prompting import MIN_CONFIDENCE_REQUIRING_EVIDENCE

    p = BaselineDiagnosis().diagnose(_inp("payment_failed"))
    assert p.evidence == []
    assert p.confidence < MIN_CONFIDENCE_REQUIRING_EVIDENCE


def test_output_is_schema_valid_like_any_other_port():
    """It must be a drop-in DiagnosisPort, not a special case the pipeline has to
    know about — otherwise swapping arms wouldn't be a clean single-component change."""
    from agent.models import DiagnosisProposal

    p = BaselineDiagnosis().diagnose(_inp("payment_failed"))
    assert isinstance(p, DiagnosisProposal)
    DiagnosisProposal.model_validate(p.model_dump(mode="json"))
