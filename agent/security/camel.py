"""CaMeL capability passports and provenance lattice (arXiv:2503.18813)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum,Enum
from collections import deque
from typing import Generic,TypeVar,Any,Iterable


class TrustLevel(IntEnum):
    """Total order of provenance: lower integer = less trusted."""

    UNTRUSTED_EXTERNAL = 0  # Gateway ErrorObj.description, raw webhooks
    QUARANTINED_AI = 1      # LLM-derived outputs (never authorizes spend)
    TRUSTED_SYSTEM = 2      # Deterministic config, DB rows, closed enums


@dataclass(frozen=True)
class CapabilityPassport:
    """Immutable security tag attached to a pipeline value."""

    # frozen=True + frozenset + tuple prevent downstream capability forgery.
    trust: TrustLevel
    allowed_sinks: frozenset[str]
    node_id: str
    parents: tuple[str, ...] = ()


def combine_passports(*passports: CapabilityPassport, node_id: str) -> CapabilityPassport:
    """Lattice Meet: derived value inherits min trust and intersected sinks."""
    if not passports:
        # Fail closed: ungrounded values cannot invent capabilities from nothing.
        raise ValueError("combine_passports requires at least one passport")
    min_trust = TrustLevel(min(p.trust for p in passports))
    common_sinks = frozenset(passports[0].allowed_sinks)
    for p in passports[1:]:
        common_sinks &= p.allowed_sinks  # Sink survives only if ALL parents allow it.
    return CapabilityPassport(min_trust, common_sinks, node_id, tuple(p.node_id for p in passports))
T = TypeVar("T")

@dataclass(frozen=True)
class CaMeLValue(Generic[T]):
    """ Pairs any runtime value with its immutable security passport."""
    value :T
    passport:CapabilityPassport
class ProvenanceGraph:
    """Lineage DAG mapping node_id -> CapabilityPassport for taint queries."""

    def __init__(self) -> None:
        self.nodes: dict[str, CapabilityPassport] = {}

    def register(self, passport: CapabilityPassport) -> CapabilityPassport:
        """Store a passport; reject duplicate node IDs so history stays append-only."""
        if passport.node_id in self.nodes:
            raise ValueError(f"Duplicate provenance node: {passport.node_id}")
        self.nodes[passport.node_id] = passport
        return passport

    def has_untrusted_ancestor(self, node_id: str) -> bool:
        """BFS upward over parent edges; fail closed if missing or untrusted."""
        queue = deque([node_id])
        visited: set[str] = set()
        while queue:
            curr = queue.popleft()
            if curr in visited:
                continue  # Skip already-checked nodes in diamond DAGs.
            visited.add(curr)
            passport = self.nodes.get(curr)
            if passport is None or passport.trust == TrustLevel.UNTRUSTED_EXTERNAL:
                return True  # Missing provenance fails closed; external data is tainted.
            queue.extend(passport.parents)
        return False
E =TypeVar("E",bound=Enum)

class CaMeLSecurityViolation(PermissionError):
    """ Raised when tainted , unverified , pr unauthorized data hits a sink. """

def declassify_enum(
    camel_val:CaMeLValue[Any],
    enum_cls:type[E],
    target_sinks:Iterable[str],
    *,
    node_id:str|None=None,
)    ->CaMeLValue[E]:
   """ Only legal bridge from untrusted data into a fixed -vocabulary Enum."""
   if not (isinstance(enum_cls,type) and issubclass(enum_cls,Enum)):
    # Never allow open types like str/int here -that would reopen injection smuggling
      raise  TypeError("enum_cls must be an Enum subclass")
   try:
        member=enum_cls(camel_val.value)
   except(ValueError,TypeError) as exc:
       raise CaMeLSecurityViolation(
        f"Cannot decalssify {camel_val.value!r} into closed enum {enum_cls.__name__}"

       ) from exc

   new_id= node_id or f"{camel_val.passport.node_id} ::enum {enum_cls.__name__}"
   #Closed enum member cannot carry free text, so trust rises to TRUSTED_SYSTEM
   #ONLY for the explicit 'target_sinks' while keeping parent lineage intact.
   passport=CapabilityPassport(
    trust=TrustLevel.TRUSTED_SYSTEM,
    allowed_sinks=frozenset(target_sinks),
    node_id=new_id,
    parents=(camel_val.passport.node_id,),

   )
   return CaMeLValue(value=member, passport=passport)


def enforce_sink(
    camel_val: CaMeLValue[T],
    sink_name: str,
    min_trust: TrustLevel = TrustLevel.TRUSTED_SYSTEM,
) -> T:
    """Gatekeeper: unwrap value only if sink is allowed AND trust meets min_trust."""
    passport = camel_val.passport
    if sink_name not in passport.allowed_sinks:
        raise CaMeLSecurityViolation(
            f"Sink {sink_name!r} denied for node {passport.node_id!r}"
        )
    if passport.trust < min_trust:
        raise CaMeLSecurityViolation(
            f"Trust {passport.trust.name} below {min_trust.name} for sink {sink_name!r}"
        )
    return camel_val.value