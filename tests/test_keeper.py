from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel

from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.domain.errors import SearchError
from kept.domain.models import Commitment, CommitmentStatus, Direction, SearchResult, Tier
from kept.services.keeper import (
    CommitmentNotFoundError,
    DraftContent,
    KeeperService,
    NotPreparableError,
    ResearchPlan,
    UngroundedDraftError,
)

TODAY = date(2026, 10, 7)


class FakeLLM:
    """Returns the plan once, then each scripted draft in turn."""

    def __init__(self, plan: ResearchPlan, *drafts: DraftContent) -> None:
        self._plan = plan
        self._drafts = list(drafts)
        self.tiers: list[Tier] = []
        self.draft_calls = 0
        self.last_user_prompt = ""

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        self.tiers.append(tier)
        if schema is ResearchPlan:
            return schema.model_validate(self._plan.model_dump())
        self.last_user_prompt = next(m["content"] for m in messages if m["role"] == "user")
        content = self._drafts[min(self.draft_calls, len(self._drafts) - 1)]
        self.draft_calls += 1
        return schema.model_validate(content.model_dump())


class FakeSearch:
    def __init__(self, results: list[SearchResult] | None = None, fail: bool = False) -> None:
        self._results = results or []
        self._fail = fail
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if self._fail:
            raise SearchError("down")
        return self._results


def _setup(
    llm: FakeLLM, search: FakeSearch, direction: Direction = Direction.OWED_BY_ME
) -> tuple[KeeperService, SqliteCommitmentRepository, SqliteDraftRepository, int]:
    db = Database(":memory:")
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    saved = commitments.add(
        Commitment(
            direction=direction,
            person="Priya",
            description="Send competitor comparison",
            source_id="n1",
            source_quote="I'll send it Friday",
        )
    )
    assert saved.id is not None
    return KeeperService(llm, search, commitments, drafts), commitments, drafts, saved.id


ACME = SearchResult(title="Acme", url="https://acme.test", snippet="Acme sells widgets.")
BETA = SearchResult(title="Beta", url="https://beta.test", snippet="Beta sells gadgets.")
PLAN = ResearchPlan(queries=["widgets"])


async def test_prepare_lists_only_cited_sources_and_marks_ready() -> None:
    llm = FakeLLM(
        PLAN, DraftContent(subject="Comparison", body="Acme sells widgets [1]. Also [9].")
    )
    search = FakeSearch([ACME, BETA])
    service, commitments, _, cid = _setup(llm, search)

    draft = await service.prepare(cid, TODAY)

    assert draft.sources == ["https://acme.test"]
    assert draft.body.endswith("Sources:\n[1] https://acme.test")
    assert "[2]" not in draft.body.split("Sources:")[1]
    assert search.queries == ["widgets"]
    assert llm.tiers == [Tier.SUPER, Tier.SUPER]
    assert "Acme sells widgets." in llm.last_user_prompt
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.READY_FOR_REVIEW


async def test_prepare_repairs_a_draft_that_cites_nothing() -> None:
    llm = FakeLLM(
        PLAN,
        DraftContent(subject="s", body="Acme sells widgets."),
        DraftContent(subject="s", body="Acme sells widgets [1]."),
    )
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    draft = await service.prepare(cid, TODAY)
    assert llm.draft_calls == 2
    assert draft.sources == ["https://acme.test"]


async def test_prepare_fails_when_draft_stays_uncited_and_saves_nothing() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="No citations here."))
    service, commitments, drafts, cid = _setup(llm, FakeSearch([ACME]))
    with pytest.raises(UngroundedDraftError):
        await service.prepare(cid, TODAY)
    assert drafts.list() == []
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.OPEN


async def test_prepare_without_research_needed_skips_search_and_citations() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="Hi", body="Attached."))
    search = FakeSearch()
    service, _, _, cid = _setup(llm, search)
    draft = await service.prepare(cid, TODAY)
    assert draft.sources == []
    assert draft.body == "Attached."
    assert search.queries == []
    assert llm.draft_calls == 1


async def test_prepare_is_idempotent_while_draft_pending() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="Hi", body="B"))
    service, _, drafts, cid = _setup(llm, FakeSearch())
    first = await service.prepare(cid, TODAY)
    second = await service.prepare(cid, TODAY)
    assert second.id == first.id
    assert len(drafts.list()) == 1


async def test_prepare_raises_when_all_searches_fail_and_leaves_status() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="b"))
    service, commitments, drafts, cid = _setup(llm, FakeSearch(fail=True))
    with pytest.raises(SearchError):
        await service.prepare(cid, TODAY)
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.OPEN
    assert drafts.list() == []


async def test_prepare_rejects_missing_and_inbound_commitments() -> None:
    llm = FakeLLM(ResearchPlan(), DraftContent(subject="s", body="b"))
    service, _, _, cid = _setup(llm, FakeSearch(), Direction.OWED_TO_ME)
    with pytest.raises(NotPreparableError):
        await service.prepare(cid, TODAY)
    with pytest.raises(CommitmentNotFoundError):
        await service.prepare(999, TODAY)
