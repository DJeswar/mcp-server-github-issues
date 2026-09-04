"""Detector patterns, in one place.

Two design rules run through all of this.

**Proximity, not mention.** A pattern that fires on the mere presence of `.env` or
"environment variable" is useless here, because the repository legitimately *discusses* secret
handling -- fixture issue #5 is a real bug report about committed `.env` files, and issue #7 is a
real report about prompt injection. Detectors therefore require an imperative verb near the
sensitive object, so discussing a secret reads differently from demanding one.

**False positives are expensive.** An over-eager detector marks ordinary issues as attacks,
escalates them to `refuse_to_act`, and teaches the operator to ignore the log. `tests/
test_guardrails.py` asserts zero detections across every benign fixture issue, label and
milestone; that test is as important as the ones that catch the real payloads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Families whose presence means the agent may *report* the text but must never act on it.
ESCALATING = frozenset({"secret_solicitation", "exfiltration"})

_SECRET_OBJECT = r"(?:\.env\b|[A-Z][A-Z0-9_]*_(?:TOKEN|KEY|SECRET|PASSWORD)\b|environment variable)"
_READ_VERB = r"(?:read|reveal|print|show|list|dump|output|include|send|post|leak|disclose)"
_SEND_VERB = r"(?:post|send|upload|transmit|exfiltrate|forward|report)"

PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "instruction_override": (
        re.compile(
            r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?"
            r"(?:previous|prior|above|earlier|preceding)\s+instructions",
            re.IGNORECASE,
        ),
        re.compile(
            r"disregard\s+(?:the\s+|your\s+|all\s+)?"
            r"(?:previous|prior|above|earlier|user'?s?)\b",
            re.IGNORECASE,
        ),
        re.compile(r"forget\s+(?:everything|all\s+previous|your\s+instructions)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(?:a|an|the)\b", re.IGNORECASE),
        re.compile(r"\bnew\s+instructions\s*:", re.IGNORECASE),
    ),
    "system_impersonation": (
        re.compile(r"\bsystem\s+notice\b", re.IGNORECASE),
        re.compile(r"\bautomated\s+maintenance\b", re.IGNORECASE),
        re.compile(r"^\s*\[?system\]?\s*:", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\badmin(?:istrator)?\s+override\b", re.IGNORECASE),
    ),
    "prompt_extraction": (
        re.compile(r"reveal\s+(?:your\s+)?(?:system\s+)?prompt", re.IGNORECASE),
        re.compile(r"(?:repeat|print|show)\s+(?:me\s+)?your\s+(?:system\s+)?"
                   r"(?:prompt|instructions)", re.IGNORECASE),
        re.compile(r"what\s+(?:are|were)\s+your\s+(?:original\s+)?instructions", re.IGNORECASE),
    ),
    "secret_solicitation": (
        # imperative + a secret-shaped object within a short window
        re.compile(rf"{_READ_VERB}\b[^\n]{{0,40}}?{_SECRET_OBJECT}", re.IGNORECASE),
        re.compile(rf"{_SECRET_OBJECT}[^\n]{{0,25}}?\bvalues?\b[^\n]{{0,25}}?"
                   rf"(?:from|in)\s+your\s+environment", re.IGNORECASE),
    ),
    "exfiltration": (
        re.compile(rf"{_SEND_VERB}\b[^\n]{{0,60}}?https?://", re.IGNORECASE),
        re.compile(rf"{_SEND_VERB}\s+(?:it|them|this|that)\b[^\n]{{0,40}}?\b(?:to|at)\b",
                   re.IGNORECASE),
    ),
    "output_constraint": (
        re.compile(r"(?:reply|respond|answer)\s+only\s+with", re.IGNORECASE),
        re.compile(r"do\s+not\s+(?:mention|reveal|disclose|tell)\b", re.IGNORECASE),
        re.compile(r"without\s+mentioning\b", re.IGNORECASE),
        re.compile(r"say\s+nothing\s+about\b", re.IGNORECASE),
    ),
}

EXCERPT_CHARS = 120


@dataclass(frozen=True)
class Detection:
    family: str
    span: tuple[int, int]
    excerpt: str

    @property
    def escalating(self) -> bool:
        return self.family in ESCALATING


def _merge_within_family(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Collapse overlapping spans, keeping the widest cover.

    Two patterns in one family often match the same phrase at slightly different lengths -- the
    two `exfiltration` rules both hit "POST them as JSON to https://…". Reporting that as two
    detections inflates the headline count, so overlaps within a family collapse to one. Spans
    that do NOT overlap stay separate, because two distinct demands in one comment really are two.
    """
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def scan_text(text: str | None) -> list[Detection]:
    """All detections in `text`, ordered by position then family.

    Different families are all reported even when they overlap: issue #12's planted comment
    legitimately trips five, and collapsing across families would lose the evidence that makes
    the log useful. Overlaps *within* a family are merged -- see `_merge_within_family`.
    """
    if not text:
        return []

    by_family: dict[str, list[tuple[int, int]]] = {}
    for family, patterns in PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                by_family.setdefault(family, []).append(match.span())

    found = [
        Detection(
            family=family,
            span=(start, end),
            excerpt=text[start : start + EXCERPT_CHARS].strip(),
        )
        for family, spans in by_family.items()
        for start, end in _merge_within_family(spans)
    ]
    return sorted(found, key=lambda d: (d.span[0], d.family))


def families(detections: list[Detection]) -> list[str]:
    return sorted({d.family for d in detections})


def has_escalation(detections: list[Detection]) -> bool:
    return any(d.escalating for d in detections)


#: Hosts an answer may legitimately link to. Anything else in an outgoing answer is stripped.
DEFAULT_ALLOWED_HOSTS = ("github.com", "api.github.com", "www.github.com")

URL_RE = re.compile(r"https?://([^\s/\"'>)\]]+)(?:/[^\s\"'>)\]]*)?", re.IGNORECASE)

#: Environment variables whose *values* must never appear in an answer.
SECRET_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*_(?:TOKEN|KEY|SECRET|PASSWORD)$")

#: Credential shapes. Deliberately prefix-anchored: a generic "long hex string" rule would redact
#: legitimate commit SHAs, and pattern lists always lag anyway -- which is exactly why the
#: environment-value comparison in outbound.py exists alongside this.
CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("google-key", re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
)
