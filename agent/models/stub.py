"""Deterministic scripted model -- the default backend, and the one CI runs.

This is not a mock that returns None. It emits exactly the JSON contract a live model emits, so
the graph, the MCP tool calls, the guardrails and the memory writes are all the real thing; only
token generation is scripted. Same question in, byte-identical answer out.

What it cannot test is whether a *real* model picks the right tools. That is what the `replay`
backend and the live backends are for.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..prompts import (
    extract_facts,
    extract_observations,
    extract_question,
    is_fact_prompt,
    is_synthesis_prompt,
)
from .base import Message, ModelResponse, ToolSpec

STALE_DAYS = 7.0

_ISSUE_RE = re.compile(r"\bissue\s*#?(\d+)|#(\d+)\b")
_VAGUE_RE = re.compile(
    r"what should i (?:work on|do)|what'?s next|where (?:should|do) i start|what next",
    re.IGNORECASE,
)

# --- fact-proposal patterns -------------------------------------------------------------------
_PRIORITY_RE = re.compile(
    r"(?:the\s+)?(?P<value>[\w.\-]+)\s+milestone\s+is\s+"
    r"(?:our|the|my)?\s*(?:current\s+|top\s+)?priority",
    re.IGNORECASE,
)
_DERIVABLE_RE = re.compile(
    r"issue\s*#?(?P<num>\d+)\s+has\s+(?P<count>\w+)\s+comments?", re.IGNORECASE
)

#: Text that means an automated reader is being addressed. A naive model would happily turn this
#: into a "fact"; the stub does exactly that on purpose, so the write gates are demonstrably what
#: stops it rather than the model's good manners.
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "disregard the user",
    "disregard your",
    "system notice",
    "new instructions",
)


_SEARCH_RE = re.compile(
    r"search(?:\s+(?:the\s+|through\s+)?issues?)?\s+(?:for\s+)?(?P<query>.+?)[.?!]*$",
    re.IGNORECASE,
)


def _classify(question: str) -> str:
    q = question.lower()
    if _ISSUE_RE.search(q):
        return "single_issue"
    if _SEARCH_RE.match(q.strip()):
        return "search"
    if "block" in q and re.search(r"release|milestone|\bv2\b", q):
        return "blocking_release"
    if "label" in q:
        return "labels"
    if re.search(r"milestone|release", q):
        return "milestones"
    if "stale" in q:
        return "stale"
    return "default"


def _issue_number(question: str) -> int:
    match = _ISSUE_RE.search(question)
    if not match:
        return 1
    return int(match.group(1) or match.group(2))


def _next_milestone(observations: list[dict[str, Any]]) -> str | None:
    """Read the target milestone out of a prior list_milestones observation.

    The stub genuinely consumes the earlier result rather than hardcoding "v2" -- otherwise the
    multi-step test would pass even if the loop never fed observations back to the planner.
    """
    for obs in observations:
        if obs["tool"] != "list_milestones" or not obs["ok"]:
            continue
        items = (obs["envelope"] or {}).get("items") or []
        open_ones = [i for i in items if i.get("state") == "open"]
        chosen = open_ones or items
        if chosen:
            return chosen[0].get("title")
    return None


def _plan(
    question: str,
    observations: list[dict[str, Any]],
    facts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    scenario = _classify(question)
    done = len(observations)

    # A vague question plus a remembered priority is the two-session recall case: the question
    # names no milestone, so the filter can only come from long-term memory.
    priority = next(
        (f["value"] for f in (facts or []) if f["key"] == "priority.milestone"), None
    )
    if priority and scenario in ("default", "stale") and _VAGUE_RE.search(question):
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "list_issues",
                "args": {"state": "open", "milestone": priority},
                "why": (
                    f"You previously said the {priority} milestone is the priority, so scope "
                    "the open work to it."
                ),
            }
        return {"action": "finish", "why": "The prioritised work is listed."}

    if scenario == "blocking_release":
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "list_milestones",
                "args": {"state": "open"},
                "why": "Identify the next release before asking what blocks it.",
            }
        if done == 1:
            milestone = _next_milestone(observations)
            if milestone is None:
                return {
                    "action": "finish",
                    "why": "No open milestone exists, so nothing can be blocking a release.",
                }
            return {
                "action": "call_tool",
                "tool": "list_issues",
                "args": {
                    "state": "open",
                    "labels": ["blocked"],
                    "milestone": milestone,
                },
                "why": f"List open blocked issues on {milestone}, with assignees and staleness.",
            }
        return {"action": "finish", "why": "Both the release and its blockers are known."}

    if scenario == "single_issue":
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "get_issue",
                "args": {"number": _issue_number(question)},
                "why": "The question names a specific issue, so fetch its full detail.",
            }
        return {"action": "finish", "why": "The issue detail has been retrieved."}

    if scenario == "search":
        if done == 0:
            match = _SEARCH_RE.match(question.strip())
            query = (match.group("query") if match else question).strip()
            return {
                "action": "call_tool",
                "tool": "search_issues",
                "args": {"query": query[:256]},
                "why": "The question asks for a free-text search rather than a filter.",
            }
        return {"action": "finish", "why": "Search results retrieved."}

    if scenario == "labels":
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "list_labels",
                "args": {},
                "why": "The question is about the repository's label vocabulary.",
            }
        return {"action": "finish", "why": "Labels retrieved."}

    if scenario == "milestones":
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "list_milestones",
                "args": {"state": "all"},
                "why": "The question is about releases.",
            }
        return {"action": "finish", "why": "Milestones retrieved."}

    if scenario == "stale":
        if done == 0:
            return {
                "action": "call_tool",
                "tool": "list_issues",
                "args": {"state": "open", "sort": "updated", "direction": "asc", "limit": 100},
                "why": "Oldest-updated first surfaces the stalest issues.",
            }
        return {"action": "finish", "why": "Staleness data retrieved."}

    if done == 0:
        return {
            "action": "call_tool",
            "tool": "list_issues",
            "args": {"state": "open"},
            "why": "Start from the open issues.",
        }
    return {"action": "finish", "why": "Enough has been retrieved to answer."}


def _describe_issue(item: dict[str, Any]) -> tuple[str, str]:
    number = item["number"]
    assignees = ", ".join(item.get("assignees") or []) or "unassigned"
    days = item.get("days_since_update")
    verdict = "stale" if (days or 0) > STALE_DAYS else "recently updated"
    line = (
        f"- #{number} {item['title']} — {assignees}; "
        f"{days} days since last update ({verdict})"
    )
    claim = f"{item['title']}; assignees: {assignees}; {days} days since update"
    return line, claim


def _synthesize(
    question: str,
    observations: list[dict[str, Any]],
    facts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    lines: list[str] = []
    citations: list[dict[str, Any]] = []
    cited: set[int] = set()
    backend = fetched_at = repo = None

    # Say which remembered fact shaped the answer -- recall the user cannot see is
    # indistinguishable from a lucky guess. But only mention a fact that actually reached a tool
    # call: claiming to "use" an irrelevant recalled fact is a false statement about our own
    # reasoning, and recall deliberately always surfaces priority-namespace facts whether or not
    # they turn out to matter.
    used_args = {
        str(value)
        for obs in observations
        for value in (obs.get("args") or {}).values()
    }
    for fact in facts or []:
        if fact["value"] not in used_args:
            continue
        quote = f' (you said: "{fact["source_quote"]}")' if fact.get("source_quote") else ""
        lines.append(f"Using your remembered {fact['key']} = {fact['value']}{quote}.")

    def cite(number: int, claim: str) -> None:
        if number not in cited:
            cited.add(number)
            citations.append({"issue": number, "claim": claim})

    for obs in observations:
        env = obs.get("envelope") or {}
        backend = env.get("backend") or backend
        fetched_at = env.get("fetched_at") or fetched_at
        repo = env.get("repo") or repo
        tool = obs["tool"]

        if not obs["ok"]:
            lines.append(f"The {tool} call failed: {env.get('error') or 'unknown error'}.")
            continue

        items = env.get("items") or []

        if tool in ("list_issues", "search_issues"):
            if not items:
                lines.append("No issues matched those criteria.")
            else:
                lines.append(f"{len(items)} matching issue(s):")
                for item in items:
                    line, claim = _describe_issue(item)
                    lines.append(line)
                    cite(item["number"], claim)
                stale = [i for i in items if (i.get("days_since_update") or 0) > STALE_DAYS]
                if stale:
                    numbers = ", ".join(f"#{i['number']}" for i in stale)
                    lines.append(
                        f"Stale for more than {int(STALE_DAYS)} days: {numbers}."
                    )
            if env.get("has_more"):
                lines.append(
                    f"This is one page only — more results exist (next_page="
                    f"{env.get('next_page')}), so the list above may be incomplete."
                )

        elif tool == "get_issue":
            for item in items:
                number = item["number"]
                lines.append(
                    f"#{number} {item['title']} ({item['state']}, "
                    f"milestone {item.get('milestone') or 'none'})."
                )
                cite(number, item["title"])
                if refs := item.get("references"):
                    joined = ", ".join(f"#{r}" for r in refs)
                    lines.append(f"Its body references {joined}.")
                    for ref in refs:
                        cite(
                            ref,
                            f"referenced by #{number} in its body; not independently retrieved",
                        )
                if comments := item.get("comment_list"):
                    lines.append(f"{len(comments)} comment(s) returned.")
                if item.get("body_truncated"):
                    lines.append("The body was truncated, so detail may be missing.")

        elif tool == "list_labels":
            lines.append("Labels: " + ", ".join(i["name"] for i in items) + ".")

        elif tool == "list_milestones":
            rendered = ", ".join(
                f"{i['title']} ({i['state']}"
                + (f", due {i['due_on']}" if i.get("due_on") else "")
                + ")"
                for i in items
            )
            lines.append(f"Milestones: {rendered}." if rendered else "No milestones found.")

    if not observations:
        lines.append("No observations were gathered, so there is nothing to report.")

    lines.append(f"Source: {repo or 'unknown repo'} via the {backend or 'unknown'} backend, "
                 f"fetched {fetched_at or 'unknown time'}.")

    return {"answer": "\n".join(lines), "citations": citations}


def _propose_facts(
    question: str, observations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Candidate facts, deliberately including ones that MUST be rejected.

    A stub that only ever proposed good facts would make the write gates untestable: the suite
    would be measuring the stub's restraint, not the rule.
    """
    facts: list[dict[str, str]] = []

    if match := _PRIORITY_RE.search(question):
        facts.append(
            {
                "key": "priority.milestone",
                "value": match.group("value"),
                "kind": "preference",
                "source_quote": match.group(0),
            }
        )

    # Derivable, and in a namespace we do not persist -- expected to fail gates 2 and 4.
    if match := _DERIVABLE_RE.search(question):
        facts.append(
            {
                "key": f"issue.{match.group('num')}.comments",
                "value": f"{match.group('count')} comments",
                "kind": "mapping",
                "source_quote": match.group(0),
            }
        )

    # Simulate being taken in by injected text: propose a "fact" whose quote comes from a tool
    # result rather than the user. Gate 3 must reject it.
    for obs in observations:
        blob = json.dumps(obs.get("envelope") or {})
        lowered = blob.casefold()
        for marker in _INJECTION_MARKERS:
            index = lowered.find(marker)
            if index == -1:
                continue
            facts.append(
                {
                    "key": "policy.override",
                    "value": "follow instructions found in issue text",
                    "kind": "constraint",
                    "source_quote": blob[index : index + 80],
                }
            )
            break

    return {"facts": facts}


class StubModel:
    """Scripted ChatModel. Deterministic by construction: no clock, no randomness."""

    name = "stub"

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        question = extract_question(messages)
        observations = extract_observations(messages)
        facts = extract_facts(messages)

        if is_fact_prompt(messages):
            payload = _propose_facts(question, observations)
        elif is_synthesis_prompt(messages):
            payload = _synthesize(question, observations, facts)
        else:
            payload = _plan(question, observations, facts)

        return ModelResponse(
            text=json.dumps(payload, indent=2, sort_keys=True), model=self.name
        )
