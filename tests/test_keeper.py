from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel

from kept.adapters.sqlite import (
    Database,
    SqliteCommitmentRepository,
    SqliteDraftRepository,
)
from kept.domain.errors import SearchError
from kept.domain.models import Commitment, CommitmentStatus, Direction, SearchResult, Tier
from kept.services.keeper import (
    CommitmentNotFoundError,
    DraftContent,
    KeeperService,
    NotPreparableError,
    ResearchPlan,
)

TODAY = date(2026, 10, 7)


class FakeLLM:
    def __init__(self, plan: ResearchPlan, content: DraftContent) -> None:
        self._by_schema: dict[type[BaseModel], BaseModel] = {
            ResearchPlan: plan,
            DraftContent: content,
        }
        self.tiers: list[Tier] = []
        self.prompts: list[str] = []

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        self.tiers.append(tier)
        self.prompts.append(messages[-1]["content"])
        return schema.model_validate(self._by_schema[schema].model_dump())


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


RESULT = SearchResult(title="Acme", url="https://acme.test", snippet="Acme sells widgets.")


async def test_prepare_drafts_with_only_fetched_sources_and_marks_ready() -> None:
    llm = FakeLLM(
        ResearchPlan(queries=["acme widgets"]),
        DraftContent(
            subject="Comparison",
            body="Acme sells widgets.",
            source_urls=["https://acme.test", "https://made-up.test", "https://acme.test"],
        ),
    )
    search = FakeSearch([RESULT])
    service, commitments, _, cid = _setup(llm, search)

    draft = await service.prepare(cid, TODAY)

    assert draft.sources == ["https://acme.test"]
    assert search.queries == ["acme widgets"]
    assert llm.tiers == [Tier.SUPER, Tier.SUPER]
    assert "Acme sells widgets." in llm.prompts[1]
    stored = commitments.get(cid)
    assert stored is not None
    assert stored.status is CommitmentStatus.READY_FOR_REVIEW


async def test_prepare_without_research_needed_skips_search() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="Hi", body="Attached."))
    search = FakeSearch()
    service, _, _, cid = _setup(llm, search)
    draft = await service.prepare(cid, TODAY)
    assert draft.sources == []
    assert search.queries == []


async def test_prepare_is_idempotent_while_draft_pending() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="Hi", body="B"))
    service, _, drafts, cid = _setup(llm, FakeSearch())
    first = await service.prepare(cid, TODAY)
    second = await service.prepare(cid, TODAY)
    assert second.id == first.id
    assert len(drafts.list()) == 1


async def test_prepare_raises_when_all_searches_fail_and_leaves_status() -> None:
    llm = FakeLLM(ResearchPlan(queries=["q"]), DraftContent(subject="s", body="b"))
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
