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
        self.last_system_prompt = ""
        self.plan_prompt = ""

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        self.tiers.append(tier)
        if schema is ResearchPlan:
            self.plan_prompt = messages[0]["content"]
            return schema.model_validate(self._plan.model_dump())
        self.last_system_prompt = messages[0]["content"]
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
    llm: FakeLLM,
    search: FakeSearch,
    direction: Direction = Direction.OWED_BY_ME,
    signature: str = "",
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
    service = KeeperService(llm, search, commitments, drafts, signature=lambda: signature)
    return service, commitments, drafts, saved.id


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
    assert draft.body == "Attached.\n\nBest,"
    assert search.queries == []
    assert llm.draft_calls == 1


async def test_drafting_without_research_forbids_claims_of_progress() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="Hi", body="Quick question."))
    service, _, _, cid = _setup(llm, FakeSearch())
    await service.prepare(cid, TODAY)
    assert "NO search results" in llm.last_system_prompt
    assert "Do not state or imply any progress" in llm.last_system_prompt


async def test_prompts_forbid_invented_details_commitments_and_placeholders() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert "Never add a location, date" in llm.plan_prompt
    assert "Never invent facts about me" in llm.last_system_prompt
    assert "Do not make new commitments" in llm.last_system_prompt
    assert "the signature is added automatically" in llm.last_system_prompt
    assert 'Start with "Hi Priya,"' in llm.last_system_prompt
    assert "Never send a bare follow-up" in llm.last_system_prompt


async def test_drafting_with_research_does_not_include_the_no_evidence_rule() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert "NO search results" not in llm.last_system_prompt


async def test_planner_is_told_to_research_finding_and_booking_tasks() -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="s", body="b"))
    service, _, _, cid = _setup(llm, FakeSearch())
    await service.prepare(cid, TODAY)
    assert "finding, comparing, choosing or booking" in llm.plan_prompt


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


async def test_signature_is_appended_after_best_and_before_sources() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]), signature="Kanisha Agarwal")
    draft = await service.prepare(cid, TODAY)
    assert draft.body == (
        "Acme sells widgets [1].\n\nBest,\nKanisha Agarwal\n\nSources:\n[1] https://acme.test"
    )


@pytest.mark.parametrize(
    "written",
    [
        "Hello.\n\nBest regards,\n[Your Name]",
        "Hello.\n\nBest,",
        "Hello.\n\nKind regards,\nJohn Smith\n",
        "Hello.\n\nThanks!",
    ],
)
async def test_model_written_closings_are_replaced_not_duplicated(written: str) -> None:
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="s", body=written))
    service, _, _, cid = _setup(llm, FakeSearch(), signature="Kanisha Agarwal")
    draft = await service.prepare(cid, TODAY)
    assert draft.body == "Hello.\n\nBest,\nKanisha Agarwal"


async def test_body_text_that_merely_contains_thanks_is_kept() -> None:
    body = "Thanks to the team we shipped early.\nMore details below."
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="s", body=body))
    service, _, _, cid = _setup(llm, FakeSearch(), signature="Kanisha Agarwal")
    draft = await service.prepare(cid, TODAY)
    assert draft.body.startswith(body)
    assert draft.body.endswith("Best,\nKanisha Agarwal")


async def test_signature_is_read_fresh_for_every_draft() -> None:
    names = iter(["First Person", "Second Person"])
    llm = FakeLLM(ResearchPlan(queries=[]), DraftContent(subject="s", body="Hello."))
    db = Database(":memory:")
    commitments, drafts = SqliteCommitmentRepository(db), SqliteDraftRepository(db)
    service = KeeperService(llm, FakeSearch(), commitments, drafts, signature=lambda: next(names))
    bodies = []
    for _ in range(2):
        saved = commitments.add(
            Commitment(
                direction=Direction.OWED_BY_ME,
                person="Priya",
                description="Send it",
                source_id="n",
                source_quote="q",
            )
        )
        bodies.append((await service.prepare(saved.id or 0, TODAY)).body)
    assert bodies[0].endswith("Best,\nFirst Person")
    assert bodies[1].endswith("Best,\nSecond Person")


async def test_a_draft_that_declares_no_use_of_results_needs_no_citations() -> None:
    body = "Which city and budget should I plan for?"
    llm = FakeLLM(
        PLAN, DraftContent(subject="Quick question", body=body, uses_search_results=False)
    )
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    draft = await service.prepare(cid, TODAY)
    assert llm.draft_calls == 1  # no repair round-trip
    assert draft.sources == []
    assert "Sources:" not in draft.body
    assert draft.body.startswith(body)


async def test_declaring_use_of_results_without_citing_them_is_still_refused() -> None:
    llm = FakeLLM(
        PLAN, DraftContent(subject="s", body="Acme sells widgets.", uses_search_results=True)
    )
    service, _, drafts, cid = _setup(llm, FakeSearch([ACME]))
    with pytest.raises(UngroundedDraftError):
        await service.prepare(cid, TODAY)
    assert drafts.list() == []


async def test_a_repair_may_conclude_that_no_results_were_used() -> None:
    llm = FakeLLM(
        PLAN,
        DraftContent(subject="s", body="Quick question?", uses_search_results=True),
        DraftContent(subject="s", body="Quick question?", uses_search_results=False),
    )
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    draft = await service.prepare(cid, TODAY)
    assert llm.draft_calls == 2
    assert draft.sources == []
