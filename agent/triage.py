"""Deterministic classification of the unambiguous majority.

This is the cheap layer, and it exists so the model is only asked the questions rules
cannot answer. Three outcomes:

  CLEAN      -> a definite class. Never reaches the model.
  AMBIGUOUS  -> the same reason string maps to different classes depending on latent
                state the rules cannot see. This is AI-1's entire job.
  UNKNOWN    -> unseen combination. Fails closed (invariant 6): STOP + human queue,
                never an attempt.

The vocabulary below is authored against Razorpay's documented error envelope
(EVIDENCE.md E9). E11 records that no exhaustive public list of `reason` values
exists, so this table is deliberately incomplete and UNKNOWN is a real, expected
outcome rather than a defensive afterthought.
"""

from __future__ import annotations

from agent.models import Recoverability

# Reason -> definite class. Rules answer these; the model never sees them.
CLEAN: dict[str, Recoverability] = {
    # customer can fix it themselves
    "insufficient_funds": Recoverability.CUSTOMER_FIXABLE,
    "payment_cancelled_by_user": Recoverability.CUSTOMER_FIXABLE,
    "invalid_otp": Recoverability.CUSTOMER_FIXABLE,
    "otp_attempts_exceeded": Recoverability.CUSTOMER_FIXABLE,
    # the instrument itself is the problem
    "card_expired": Recoverability.INSTRUMENT_INVALID,
    "invalid_card_number": Recoverability.INSTRUMENT_INVALID,
    "card_blocked": Recoverability.INSTRUMENT_INVALID,
    "invalid_vpa": Recoverability.INSTRUMENT_INVALID,
    # nothing will bring this back
    "account_closed": Recoverability.TERMINAL,
    "fraud_suspected": Recoverability.TERMINAL,
    "payment_frozen": Recoverability.TERMINAL,
    "international_transaction_not_allowed": Recoverability.TERMINAL,
    "mandate_revoked": Recoverability.TERMINAL,
    # infrastructure, will pass
    "gateway_timeout": Recoverability.TRANSIENT_INFRA,
    "issuer_down": Recoverability.TRANSIENT_INFRA,
    "npci_unavailable": Recoverability.TRANSIENT_INFRA,
    "server_error": Recoverability.TRANSIENT_INFRA,
}

# Genuinely ambiguous in production: the same string covers several root causes, and
# which one applies depends on attempt history, concurrent downtime, and amount.
AMBIGUOUS: frozenset[str] = frozenset(
    {
        "payment_failed",  # the real-world catch-all
        "payment_declined_by_bank",  # funds? risk? issuer trouble?
        "authentication_failed",  # customer mistyped, or the issuer's ACS is sick
        "collect_request_expired",  # customer ignored it, or their PSP was down
        "transaction_limit_exceeded",  # per-transaction limit, or account restriction
    }
)


class TriageResult:
    __slots__ = ("recoverability", "is_ambiguous", "matched")

    def __init__(self, recoverability: Recoverability, is_ambiguous: bool, matched: str) -> None:
        self.recoverability = recoverability
        self.is_ambiguous = is_ambiguous
        self.matched = matched

    def as_payload(self) -> dict[str, object]:
        return {
            "recoverability": self.recoverability.value,
            "is_ambiguous": self.is_ambiguous,
            "matched": self.matched,
        }


def triage(reason: str) -> TriageResult:
    if reason in CLEAN:
        return TriageResult(CLEAN[reason], False, "clean")
    if reason in AMBIGUOUS:
        return TriageResult(Recoverability.UNKNOWN, True, "ambiguous")
    return TriageResult(Recoverability.UNKNOWN, False, "unseen")
