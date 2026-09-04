"""THE write rule.

"Store everything" is not a design, so this is a gate, not a heuristic. A candidate fact is
written only if it passes all five checks. Each returns a named failure so a rejection is
explainable rather than mysterious.

Gate 3 is a security control, not bookkeeping. It requires the fact's `source_quote` to appear
verbatim in the *user's own message*. An injection sitting in an issue body or comment therefore
cannot earn a persistent write however convincingly it is phrased, because its text is not in the
user turn. Without that, one malicious comment poisons every future session -- much worse than one
bad answer. The DB `CHECK` on `source` backs the same rule up one layer down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KINDS = ("preference", "decision", "mapping", "constraint")

#: Gate 2. Reusability is not fully decidable, so it is approximated by deciding *in advance*
#: which subjects are worth persisting: facts about how the user works. Anything else is not
#: reusable by definition, and an allowlist also stops key sprawl.
REUSABLE_NAMESPACES = (
    "priority",
    "preference",
    "convention",
    "constraint",
    "decision",
    "owner",
    "policy",
)

#: Gate 1. Values that are observations of a moment rather than durable positions.
TRANSIENT_VALUE_RE = re.compile(
    r"\b(today|yesterday|tomorrow|right now|currently open|just now|this morning)\b"
    r"|^\s*\d+\s*$"
    r"|\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)

#: Gate 4. Anything re-readable from the tools in one call must not be stored.
DERIVABLE_KEY_RE = re.compile(r"^(issue|label|milestone|comment|assignee|count|state)\b", re.I)
DERIVABLE_VALUE_RE = re.compile(
    r"#\d+|\b\d+\s+(comments?|issues?|labels?|milestones?)\b|\bis (open|closed|blocked)\b",
    re.IGNORECASE,
)

MAX_VALUE_CHARS = 120
_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip().casefold())


@dataclass(frozen=True)
class Candidate:
    key: str
    value: str
    kind: str
    source_quote: str
    scope: str = "global"
    source: str = "user_asserted"


@dataclass
class Verdict:
    accepted: bool
    failed_gates: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(self.failed_gates) if self.failed_gates else "passed all five gates"


def _gate_durable(c: Candidate) -> str | None:
    if c.kind not in KINDS:
        return f"durable: kind {c.kind!r} is not one of {', '.join(KINDS)}"
    if TRANSIENT_VALUE_RE.search(c.value):
        return f"durable: value {c.value!r} reads as a momentary observation, not a position"
    return None


def _gate_reusable(c: Candidate) -> str | None:
    namespace, _, attribute = c.key.partition(".")
    if not attribute:
        return f"reusable: key {c.key!r} must be '<namespace>.<attribute>'"
    if namespace.lower() not in REUSABLE_NAMESPACES:
        return (
            f"reusable: namespace {namespace!r} is not one we persist "
            f"(allowed: {', '.join(REUSABLE_NAMESPACES)})"
        )
    return None


def _gate_user_asserted(c: Candidate, user_message: str) -> str | None:
    """The security gate. See the module docstring."""
    if c.source not in ("user_asserted", "user_confirmed"):
        return f"user_asserted: source {c.source!r} is not the user"
    if not c.source_quote.strip():
        return "user_asserted: no source quote, so provenance cannot be checked"
    if _norm(c.source_quote) not in _norm(user_message):
        return (
            "user_asserted: source quote is not present in the user's own message "
            "(it may have come from untrusted tool text)"
        )
    return None


def _gate_not_derivable(c: Candidate) -> str | None:
    if DERIVABLE_KEY_RE.match(c.key):
        return f"not_derivable: key {c.key!r} names data the tools can re-read"
    if DERIVABLE_VALUE_RE.search(c.value):
        return f"not_derivable: value {c.value!r} is retrievable from the tools"
    return None


def _gate_atomic(c: Candidate) -> str | None:
    """Atomic + attributable.

    Only the value is checked here: `session_id` and `created_at` are stamped by the store, not
    proposed by the model, so attribution cannot be missing by the time a row is written. The
    quote half of attribution is already enforced by gate 3.
    """
    if len(c.value) > MAX_VALUE_CHARS:
        return f"atomic: value is {len(c.value)} chars (max {MAX_VALUE_CHARS}); split it"
    if re.search(r"\b(and|also|plus)\b", c.value, re.IGNORECASE):
        return f"atomic: value {c.value!r} bundles more than one fact"
    return None


def evaluate(candidate: Candidate, *, user_message: str) -> Verdict:
    """Apply all five gates. Every failure is collected, so one rejection explains everything."""
    failures = [
        gate
        for gate in (
            _gate_durable(candidate),
            _gate_reusable(candidate),
            _gate_user_asserted(candidate, user_message),
            _gate_not_derivable(candidate),
            _gate_atomic(candidate),
        )
        if gate
    ]
    return Verdict(accepted=not failures, failed_gates=failures)
