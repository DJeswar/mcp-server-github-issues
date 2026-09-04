"""Outbound guard: scan the answer before the user sees it.

The check most likely to matter on a machine that has real keys is the **environment-value
comparison** -- it looks for the actual values of `*_TOKEN`/`*_KEY`/`*_SECRET` variables appearing
verbatim in the answer. Pattern lists always lag behind new credential formats; comparing against
what is actually in the environment does not.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

from .detectors import (
    CREDENTIAL_PATTERNS,
    DEFAULT_ALLOWED_HOSTS,
    SECRET_ENV_RE,
    URL_RE,
)

#: Below this length an environment value is too short to be a credential and too likely to be a
#: common word ("1", "true", "main"), which would redact ordinary prose.
MIN_SECRET_LENGTH = 12

REFUSAL = (
    "I am not going to answer that as written. Text retrieved from this repository attempted to "
    "make me {what}, and the answer I was about to give would have complied. The retrieved text "
    "is data to report on, not an instruction I follow. Ask me about the issue's contents and I "
    "will describe them."
)

#: Refusal reasons are deliberately generic where the specifics came from the attacker.
#:
#: Echoing a payload's host back into the answer reproduces attacker-controlled text in a place a
#: UI may hyperlink, which is a small vector for no benefit. The operator still gets the exact
#: host and secret name in the event log and the `guardrail_events` table -- detail goes to
#: whoever is investigating, not into the user-facing sentence.
REASON_EXTERNAL_ADDRESS = "send repository data to an external address"
REASON_NAMED_SECRET = "disclose a credential that the retrieved text named"


@dataclass
class OutboundEvent:
    detector: str
    action: str
    detail: str = ""


@dataclass
class OutboundResult:
    text: str
    blocked: bool = False
    events: list[OutboundEvent] = field(default_factory=list)


def _live_secret_values(env: dict[str, str] | None) -> list[tuple[str, str]]:
    source = env if env is not None else dict(os.environ)
    return [
        (name, value)
        for name, value in source.items()
        if SECRET_ENV_RE.match(name) and len(value or "") >= MIN_SECRET_LENGTH
    ]


def scan_outbound(
    text: str,
    *,
    indicators: dict[str, list[str]] | None = None,
    env: dict[str, str] | None = None,
    allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS,
    mode: str = "enforce",
) -> OutboundResult:
    """Check, and in `enforce` mode repair or block, an outgoing answer.

    `indicators` comes from `inbound.escalated_indicators()`: the hosts and secret names an
    injection asked for. If the answer contains any of them, the agent complied with text it was
    supposed to refuse, and no amount of redaction makes that answer safe to send.
    """
    events: list[OutboundEvent] = []
    result = text
    blocked_reason: str | None = None

    # 1. live secret values -- the reliable check
    for name, value in _live_secret_values(env):
        if value in result:
            events.append(
                OutboundEvent(
                    detector="live_secret_value",
                    action="blocked",
                    detail=f"the value of {name} appeared in the answer",
                )
            )
            blocked_reason = blocked_reason or f"disclose the value of {name}"

    # 2. compliance with a flagged injection
    indicators = indicators or {}
    for host in indicators.get("hosts", []):
        if host.lower() in result.lower():
            events.append(
                OutboundEvent(
                    detector="injection_compliance",
                    action="blocked",
                    detail=f"answer references exfiltration host {host}",
                )
            )
            blocked_reason = blocked_reason or REASON_EXTERNAL_ADDRESS
    for secret in indicators.get("secrets", []):
        if secret in result:
            events.append(
                OutboundEvent(
                    detector="injection_compliance",
                    action="blocked",
                    detail=f"answer names solicited secret {secret}",
                )
            )
            blocked_reason = blocked_reason or REASON_NAMED_SECRET

    if blocked_reason and mode == "enforce":
        return OutboundResult(
            text=REFUSAL.format(what=blocked_reason), blocked=True, events=events
        )

    # 3. credential-shaped strings -- redact rather than block; the rest of the answer is fine
    for kind, pattern in CREDENTIAL_PATTERNS:
        if pattern.search(result):
            events.append(
                OutboundEvent(
                    detector="credential_shape", action="redacted", detail=f"{kind} pattern"
                )
            )
            if mode == "enforce":
                result = pattern.sub(f"[REDACTED:{kind}]", result)

    # 4. links to hosts we did not retrieve from
    allowed = {host.lower() for host in allowed_hosts}
    for host in {h.lower() for h in URL_RE.findall(result)}:
        if host in allowed or any(host.endswith("." + a) for a in allowed):
            continue
        events.append(
            OutboundEvent(
                detector="external_link", action="stripped", detail=f"host {host}"
            )
        )
        if mode == "enforce":
            result = URL_RE.sub(
                lambda m: "[external link removed]"
                if m.group(1).lower() == host
                else m.group(0),
                result,
            )

    return OutboundResult(
        text=result if mode == "enforce" else text,
        blocked=bool(blocked_reason) and mode == "enforce",
        events=events,
    )
