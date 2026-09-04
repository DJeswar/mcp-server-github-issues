"""The provider seam.

Both implementations return identical model types with identical field semantics. That
invariant is what lets everything built against fixtures work unchanged on live data; break it
and the divergence is silent. `tests/test_parity.py` guards it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from ..models import (
    Backend,
    Envelope,
    GetIssueQuery,
    IssueDetail,
    IssueSummary,
    Label,
    ListIssuesQuery,
    ListLabelsQuery,
    ListMilestonesQuery,
    Milestone,
    SearchIssuesQuery,
)


class IssuesProvider(ABC):
    #: Recorded in every envelope, so a fixture-vs-live discrepancy is visible in eval traces.
    backend: Backend

    @property
    @abstractmethod
    def repo_label(self) -> str:
        """`owner/name` as reported to the client."""

    @abstractmethod
    def now(self) -> datetime:
        """Reference 'now'. Fixed for fixtures (determinism), wall clock for live."""

    async def aclose(self) -> None:
        """Release resources. No-op unless the provider holds a connection."""

    # ------------------------------------------------------------------ operations

    @abstractmethod
    async def list_issues(self, q: ListIssuesQuery) -> Envelope[IssueSummary]: ...

    @abstractmethod
    async def get_issue(self, q: GetIssueQuery) -> Envelope[IssueDetail]: ...

    @abstractmethod
    async def search_issues(self, q: SearchIssuesQuery) -> Envelope[IssueSummary]: ...

    @abstractmethod
    async def list_labels(self, q: ListLabelsQuery) -> Envelope[Label]: ...

    @abstractmethod
    async def list_milestones(self, q: ListMilestonesQuery) -> Envelope[Milestone]: ...

    # ------------------------------------------------------------------ helpers

    def envelope(
        self,
        cls: Any,
        items: Sequence[Any],
        *,
        page: int = 1,
        has_more: bool = False,
        notes: Iterable[str] | None = None,
    ) -> Any:
        """Build the shared envelope. `cls` is a parameterized Envelope[...] type."""
        return cls(
            repo=self.repo_label,
            backend=self.backend,
            fetched_at=self.now(),
            count=len(items),
            has_more=has_more,
            next_page=(page + 1) if has_more else None,
            items=list(items),
            notes=[n for n in (notes or []) if n],
        )
