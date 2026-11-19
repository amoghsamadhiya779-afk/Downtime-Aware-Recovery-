"""CaMeL capability tracking and taint propagation."""

from agent.security.camel import (
    CaMeLSecurityViolation,
    CaMeLValue,
    CapabilityPassport,
    ProvenanceGraph,
    TrustLevel,
    combine_passports,
    declassify_enum,
    enforce_sink,
)

__all__ = [
    "CaMeLSecurityViolation",
    "CaMeLValue",
    "CapabilityPassport",
    "ProvenanceGraph",
    "TrustLevel",
    "combine_passports",
    "declassify_enum",
    "enforce_sink",
]