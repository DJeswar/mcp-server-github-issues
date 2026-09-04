"""SQLite long-term memory store.

Recall is keyword/key match ranked by recency and use, capped small. `sqlite-vec` is installed
transitively and deliberately unused: semantic search over a store this size is the
"persist everything and hope retrieval sorts it out" design the runbook warns against, and
non-deterministic recall would make the Phase 5 eval gate meaningless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import aiosqlite

from .rules import Candidate

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_STOPWORDS = frozenset(
    """a an the is are was were be been being do does did what which who whom whose when where
    why how i me my we our you your it its this that these those of in on at to for with about
    should would could can will shall may might must have has had am and or but if then than
    so as by from up down out over under again further once here there all any both each few
    more most other some such no nor not only own same too very s t just don now on work"""
    .split()
)


@dataclass(frozen=True)
class StoredFact:
    id: int
    key: str
    value: str
    kind: str
    scope: str
    source: str
    source_quote: str
    session_id: str
    created_at: str
    last_used_at: str | None
    use_count: int
    confidence: float
    active: int
    superseded_by: int | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokenize(text: str) -> set[str]:
    """Content words, plus the parts of any dotted/hyphenated token.

    The expansion is load-bearing, not a nicety. Keys look like `convention.branch`, which the
    token pattern captures whole -- so without splitting, the question "what is our branch
    convention?" shares no token with its own key and the fact is never recalled. That bug hid
    behind the always-consider rule for `priority` facts, which surface regardless of overlap.
    """
    tokens = {
        token
        for token in _TOKEN_RE.findall((text or "").casefold())
        if token not in _STOPWORDS and len(token) > 1
    }
    parts = {
        part
        for token in tokens
        for part in re.split(r"[._-]", token)
        if len(part) > 1 and part not in _STOPWORDS
    }
    return tokens | parts


class MemoryStore:
    """Async SQLite store. Use as an async context manager."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._path = str(path)
        self._clock = clock
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------ lifecycle

    async def open(self) -> MemoryStore:
        # isolation_level=None: without it Python's sqlite3 opens an implicit transaction and an
        # explicit BEGIN raises, which the supersede sequence needs.
        self._db = await aiosqlite.connect(self._path, isolation_level=None)
        # foreign_keys is OFF by default, and that default is exactly what would hide a dangling
        # superseded_by reference.
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        return self

    async def __aenter__(self) -> MemoryStore:
        return await self.open()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MemoryStore.open() must be awaited before use")
        return self._db

    # ------------------------------------------------------------------ writes

    async def write(
        self,
        candidate: Candidate,
        *,
        session_id: str,
        confidence: float = 1.0,
        expires_at: str | None = None,
    ) -> tuple[int, int | None]:
        """Insert `candidate`, superseding any live row for the same (key, scope).

        Returns (new_id, superseded_id). The retired row is kept for audit.
        """
        now = self._clock()
        db = self._conn

        await db.execute("BEGIN")
        try:
            async with db.execute(
                "SELECT id FROM facts WHERE key = ? AND scope = ? AND active = 1",
                (candidate.key, candidate.scope),
            ) as cursor:
                row = await cursor.fetchone()
            superseded_id = int(row[0]) if row else None

            # Order matters: retire, insert, then link. Inserting first trips facts_live;
            # linking first has no id to point at.
            if superseded_id is not None:
                await db.execute(
                    "UPDATE facts SET active = 0 WHERE id = ?", (superseded_id,)
                )

            cursor = await db.execute(
                """INSERT INTO facts
                   (key, value, kind, scope, source, source_quote, session_id,
                    created_at, confidence, expires_at, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    candidate.key,
                    candidate.value,
                    candidate.kind,
                    candidate.scope,
                    candidate.source,
                    candidate.source_quote,
                    session_id,
                    now,
                    confidence,
                    expires_at,
                ),
            )
            new_id = int(cursor.lastrowid)

            if superseded_id is not None:
                await db.execute(
                    "UPDATE facts SET superseded_by = ? WHERE id = ?",
                    (new_id, superseded_id),
                )

            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise

        return new_id, superseded_id

    # ------------------------------------------------------------------ reads

    async def _live(self, scopes: Iterable[str]) -> list[StoredFact]:
        placeholders = ",".join("?" for _ in scopes)
        now = self._clock()
        async with self._conn.execute(
            f"""SELECT id, key, value, kind, scope, source, source_quote, session_id,
                       created_at, last_used_at, use_count, confidence, active, superseded_by
                FROM facts
                WHERE active = 1 AND scope IN ({placeholders})
                  AND (expires_at IS NULL OR expires_at > ?)""",
            (*scopes, now),
        ) as cursor:
            rows = await cursor.fetchall()
        return [StoredFact(*row) for row in rows]

    async def recall(
        self, *, question: str, scope: str = "global", limit: int = 5
    ) -> list[StoredFact]:
        """Keyword match on key/value, ranked by overlap, then use, then recency.

        A fact with no term overlap is still eligible if its namespace is one the agent should
        always consider (`priority`, `constraint`, `policy`) -- those change behaviour whether or
        not the user restates them, which is the whole point of persisting them.
        """
        scopes = {"global", scope}
        facts = await self._live(scopes)
        terms = tokenize(question)
        always = ("priority", "constraint", "policy")

        scored: list[tuple[int, StoredFact]] = []
        for fact in facts:
            haystack = tokenize(f"{fact.key} {fact.value}")
            score = len(terms & haystack)
            if score == 0 and fact.key.split(".")[0].lower() not in always:
                continue
            scored.append((score, fact))

        # deterministic: score desc, use_count desc, created_at desc, then key for ties
        scored.sort(key=lambda pair: (-pair[0], -pair[1].use_count, pair[1].created_at, pair[1].key))
        chosen = [fact for _, fact in scored[:limit]]

        if chosen:
            await self._touch([fact.id for fact in chosen])
        return chosen

    async def _touch(self, ids: list[int]) -> None:
        now = self._clock()
        await self._conn.executemany(
            "UPDATE facts SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
            [(now, fact_id) for fact_id in ids],
        )

    async def get_live(self, key: str, scope: str = "global") -> StoredFact | None:
        async with self._conn.execute(
            """SELECT id, key, value, kind, scope, source, source_quote, session_id,
                      created_at, last_used_at, use_count, confidence, active, superseded_by
               FROM facts WHERE key = ? AND scope = ? AND active = 1""",
            (key, scope),
        ) as cursor:
            row = await cursor.fetchone()
        return StoredFact(*row) if row else None

    async def history(self, key: str, scope: str = "global") -> list[StoredFact]:
        """Every row for a key, live and retired, oldest first. The audit trail."""
        async with self._conn.execute(
            """SELECT id, key, value, kind, scope, source, source_quote, session_id,
                      created_at, last_used_at, use_count, confidence, active, superseded_by
               FROM facts WHERE key = ? AND scope = ? ORDER BY id""",
            (key, scope),
        ) as cursor:
            rows = await cursor.fetchall()
        return [StoredFact(*row) for row in rows]

    async def count(self, *, active_only: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM facts" + (" WHERE active = 1" if active_only else "")
        async with self._conn.execute(sql) as cursor:
            return int((await cursor.fetchone())[0])

    # ------------------------------------------------------------------ guardrail events

    async def log_guardrail_events(
        self, events: Iterable[Any], *, session_id: str
    ) -> int:
        """Persist GuardrailEvent-shaped objects. Returns how many rows were written.

        Duck-typed on purpose: the guardrail modules must not import the memory layer, and the
        memory layer must not import agent state. The node that has both wires them together.
        """
        now = self._clock()
        rows = [
            (
                session_id,
                now,
                event.detector,
                event.direction,
                event.source,
                event.action,
                (event.span or (None, None))[0],
                (event.span or (None, None))[1],
                event.detail,
            )
            for event in events
        ]
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO guardrail_events
               (session_id, created_at, detector, direction, source, action,
                span_start, span_end, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return len(rows)

    async def guardrail_counts(self) -> dict[str, int]:
        """Per-detector totals -- the number the README leans on."""
        async with self._conn.execute(
            "SELECT detector, COUNT(*) FROM guardrail_events GROUP BY detector ORDER BY detector"
        ) as cursor:
            return {row[0]: int(row[1]) for row in await cursor.fetchall()}

    async def guardrail_event_count(self, *, direction: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM guardrail_events"
        params: tuple[Any, ...] = ()
        if direction:
            sql += " WHERE direction = ?"
            params = (direction,)
        async with self._conn.execute(sql, params) as cursor:
            return int((await cursor.fetchone())[0])

    async def raw_insert(self, **columns: Any) -> int:
        """Escape hatch for tests that need to exercise the DB constraints directly."""
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        cursor = await self._conn.execute(
            f"INSERT INTO facts ({names}) VALUES ({marks})", tuple(columns.values())
        )
        return int(cursor.lastrowid)
