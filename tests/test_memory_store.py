"""The store: supersession, recall ranking, audit trail, and the DB-level constraints.

The schema constraints get their own tests because they are the layer that holds when our Python
is wrong -- which is the only reason to put a rule in the database at all.
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.memory import Candidate, MemoryStore, tokenize

FIXED_NOW = "2026-08-01T00:00:00+00:00"


@pytest.fixture
async def store():
    async with MemoryStore(":memory:", clock=lambda: FIXED_NOW) as s:
        yield s


def cand(key="priority.milestone", value="v2", **kw) -> Candidate:
    base = dict(
        key=key, value=value, kind="preference", source_quote=f"{value} is the priority",
        scope="global", source="user_asserted",
    )
    base.update(kw)
    return Candidate(**base)


class TestLifecycle:
    async def test_use_before_open_raises(self):
        with pytest.raises(RuntimeError, match="open\\(\\) must be awaited"):
            await MemoryStore(":memory:").count()

    async def test_foreign_keys_are_on(self, store):
        """Off is SQLite's default, and that default is what hides a dangling superseded_by."""
        async with store._conn.execute("PRAGMA foreign_keys") as cursor:
            assert (await cursor.fetchone())[0] == 1

    async def test_schema_is_idempotent(self):
        s = MemoryStore(":memory:")
        await s.open()
        await s.open()  # CREATE TABLE IF NOT EXISTS
        await s.close()


class TestWrite:
    async def test_write_then_read_back(self, store):
        new_id, superseded = await store.write(cand(), session_id="s1")
        assert superseded is None
        live = await store.get_live("priority.milestone")
        assert (live.id, live.value, live.session_id) == (new_id, "v2", "s1")
        assert live.created_at == FIXED_NOW
        assert live.active == 1

    async def test_provenance_is_stored(self, store):
        await store.write(cand(), session_id="s7")
        live = await store.get_live("priority.milestone")
        assert live.source == "user_asserted"
        assert live.source_quote == "v2 is the priority"
        assert live.session_id == "s7"


class TestSupersession:
    async def test_new_value_supersedes_the_old(self, store):
        first, _ = await store.write(cand(value="v2"), session_id="s1")
        second, superseded = await store.write(cand(value="v3"), session_id="s2")

        assert superseded == first
        live = await store.get_live("priority.milestone")
        assert (live.id, live.value) == (second, "v3")

    async def test_audit_trail_survives(self, store):
        first, _ = await store.write(cand(value="v2"), session_id="s1")
        second, _ = await store.write(cand(value="v3"), session_id="s2")

        history = await store.history("priority.milestone")
        assert [(f.id, f.value, f.active, f.superseded_by) for f in history] == [
            (first, "v2", 0, second),
            (second, "v3", 1, None),
        ]

    async def test_only_one_live_row_per_key_scope(self, store):
        await store.write(cand(value="v2"), session_id="s1")
        await store.write(cand(value="v3"), session_id="s2")
        await store.write(cand(value="v4"), session_id="s3")
        assert await store.count(active_only=True) == 1
        assert await store.count(active_only=False) == 3

    async def test_different_scopes_coexist(self, store):
        await store.write(cand(scope="global"), session_id="s1")
        await store.write(cand(scope="repo:o/r", value="v9"), session_id="s1")
        assert await store.count() == 2
        assert (await store.get_live("priority.milestone", "repo:o/r")).value == "v9"

    async def test_chain_of_three_links_correctly(self, store):
        ids = [
            (await store.write(cand(value=v), session_id=f"s{i}"))[0]
            for i, v in enumerate(["v1", "v2", "v3"])
        ]
        history = await store.history("priority.milestone")
        assert [f.superseded_by for f in history] == [ids[1], ids[2], None]


class TestSchemaConstraints:
    """These must be enforced by SQLite, not by our Python."""

    BASE = dict(
        key="policy.x", value="y", kind="preference", scope="global",
        source_quote="q", session_id="s1", created_at=FIXED_NOW,
    )

    async def test_tool_result_source_is_rejected_by_the_database(self, store):
        """Rule 3 made structural: a careless future caller gets an error, not a silent write."""
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            await store.raw_insert(**self.BASE, source="tool_result")

    async def test_unknown_kind_is_rejected_by_the_database(self, store):
        row = dict(self.BASE, kind="vibes", source="user_asserted")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            await store.raw_insert(**row)

    async def test_two_live_rows_for_one_key_scope_are_rejected(self, store):
        await store.raw_insert(**self.BASE, source="user_asserted")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            await store.raw_insert(**self.BASE, source="user_asserted")

    async def test_retired_rows_do_not_trip_the_unique_index(self, store):
        await store.raw_insert(**self.BASE, source="user_asserted", active=0)
        await store.raw_insert(**self.BASE, source="user_asserted", active=0)
        await store.raw_insert(**self.BASE, source="user_asserted", active=1)
        assert await store.count(active_only=False) == 3


class TestRecall:
    async def test_term_overlap_matches(self, store):
        await store.write(cand(key="convention.branch", value="trunk-based"), session_id="s1")
        facts = await store.recall(question="what is our branch convention?")
        assert [f.key for f in facts] == ["convention.branch"]

    async def test_priority_facts_surface_without_term_overlap(self, store):
        """The whole point of persisting a priority is that it applies when unmentioned."""
        await store.write(cand(), session_id="s1")
        facts = await store.recall(question="what should I work on?")
        assert [f.value for f in facts] == ["v2"]

    async def test_unrelated_non_priority_fact_is_not_recalled(self, store):
        await store.write(cand(key="convention.branch", value="trunk-based"), session_id="s1")
        assert await store.recall(question="who owns issue triage?") == []

    async def test_retired_facts_are_never_recalled(self, store):
        await store.write(cand(value="v2"), session_id="s1")
        await store.write(cand(value="v3"), session_id="s2")
        facts = await store.recall(question="what should I work on?")
        assert [f.value for f in facts] == ["v3"]

    async def test_scope_filtering(self, store):
        await store.write(cand(scope="repo:other/repo", value="v9"), session_id="s1")
        assert await store.recall(question="priority", scope="repo:mine/repo") == []
        assert len(await store.recall(question="priority", scope="repo:other/repo")) == 1

    async def test_limit_is_respected(self, store):
        for i in range(6):
            await store.write(cand(key=f"priority.p{i}", value=f"x{i}"), session_id="s1")
        assert len(await store.recall(question="anything", limit=3)) == 3

    async def test_recall_bumps_use_count_and_last_used(self, store):
        await store.write(cand(), session_id="s1")
        assert (await store.get_live("priority.milestone")).use_count == 0
        await store.recall(question="what should I work on?")
        live = await store.get_live("priority.milestone")
        assert live.use_count == 1
        assert live.last_used_at == FIXED_NOW

    async def test_expired_facts_are_excluded(self, store):
        await store.write(cand(), session_id="s1", expires_at="2020-01-01T00:00:00+00:00")
        assert await store.recall(question="what should I work on?") == []

    async def test_recall_is_deterministic(self, store):
        for i in range(4):
            await store.write(cand(key=f"priority.p{i}", value=f"x{i}"), session_id="s1")
        first = [f.key for f in await store.recall(question="anything")]
        second = [f.key for f in await store.recall(question="anything")]
        assert first == second


class TestTokenize:
    def test_drops_stopwords_and_single_chars(self):
        assert tokenize("What should I work on?") == set()

    def test_keeps_meaningful_terms(self):
        assert "milestone" in tokenize("which milestone is next")

    def test_keeps_dotted_keys(self):
        assert "priority.milestone" in tokenize("priority.milestone = v2")

    def test_also_yields_the_parts_of_a_dotted_key(self):
        """Without this a question's plain words can never match a namespaced key."""
        assert {"priority", "milestone"} <= tokenize("priority.milestone = v2")

    def test_splits_hyphenated_values(self):
        assert {"trunk", "based"} <= tokenize("trunk-based")
