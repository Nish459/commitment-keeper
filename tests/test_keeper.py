from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.domain.errors import SearchError
from kept.domain.models import (
    Commitment,
    CommitmentStatus,
    Direction,
    Draft,
    DraftKind,
    SearchResult,
    Tier,
)
from kept.services.keeper import (
    CommitmentNotFoundError,
    DraftContent,
    KeeperService,
    NeedsDetailsError,
    NotPreparableError,
    ResearchPlan,
    UngroundedDraftError,
    asks_questions,
    tidy_body,
)
from kept.services.people import PeopleService

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
    assert "asked for, requested or is waiting for" in " ".join(llm.last_system_prompt.split())
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


SEND_FILE_PLAN = ResearchPlan(kind="send_file", queries=["ignored: nothing on the web helps"])


async def test_sending_something_you_already_have_gets_a_cover_note_not_questions() -> None:
    cover = DraftContent(
        subject="Q4 roadmap",
        body="Hi Zoe,\n\nAs promised, the Q4 roadmap is attached.",
        uses_search_results=False,
    )
    llm = FakeLLM(SEND_FILE_PLAN, cover)
    search = FakeSearch([ACME])
    service, _, _, cid = _setup(llm, search, signature="Ada Lovelace")

    draft = await service.prepare(cid, TODAY)

    assert search.queries == []  # the web cannot produce the user's own file
    assert draft.needs_attachment is True
    assert draft.sources == []
    assert (
        draft.body == "Hi Zoe,\n\nAs promised, the Q4 roadmap is attached.\n\nBest,\nAda Lovelace"
    )
    prompt = llm.last_system_prompt
    assert "cover email" in prompt and "You do not know its contents" in prompt
    assert "do not ask" in prompt and "ask for each" not in prompt
    assert llm.draft_calls == 1  # no citation repair for a cover note


async def test_research_and_other_promises_do_not_need_an_attachment() -> None:
    for kind in ("research", "other"):
        llm = FakeLLM(
            ResearchPlan(kind=kind, queries=[]),
            DraftContent(subject="s", body="Hello.", uses_search_results=False),
        )
        service, _, _, cid = _setup(llm, FakeSearch())
        draft = await service.prepare(cid, TODAY, details="Austin, 12 people")
        assert draft.needs_attachment is False


async def test_a_promise_kept_cannot_do_alone_asks_the_user_not_the_other_person() -> None:
    plan = ResearchPlan(kind="other", queries=[], needs=["city", " headcount ", "", "dates"])
    llm = FakeLLM(plan, DraftContent(subject="s", body="never used"))
    search = FakeSearch([ACME])
    service, commitments, drafts, cid = _setup(llm, search)
    with pytest.raises(NeedsDetailsError) as caught:
        await service.prepare(cid, TODAY)
    assert caught.value.needs == ["city", "headcount", "dates"]
    assert llm.draft_calls == 0 and search.queries == []
    assert drafts.for_commitment(cid) is None
    assert commitments.get(cid).status is CommitmentStatus.OPEN  # type: ignore[union-attr]


async def test_with_the_users_details_that_promise_is_researched_and_written_up() -> None:
    plan = ResearchPlan(kind="other", queries=["venues in Austin"])
    llm = FakeLLM(plan, DraftContent(subject="Venues", body="Option A [1]."))
    search = FakeSearch([ACME])
    service, _, _, cid = _setup(llm, search)
    draft = await service.prepare(cid, TODAY, details="Austin, 12 people, Nov 4")
    assert search.queries == ["venues in Austin"]
    assert "Austin, 12 people, Nov 4" in llm.last_user_prompt
    assert "do not ask about them" in llm.last_user_prompt
    assert "not from Priya" in llm.last_user_prompt
    assert draft.sources == ["https://acme.test"]


async def test_the_planner_is_asked_what_only_the_user_can_supply() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert '"needs"' in llm.plan_prompt and "only I can supply" in llm.plan_prompt


@pytest.mark.parametrize(
    "body",
    [
        "To complete this, could you please clarify which aspects to focus on?",
        "Can you confirm the budget?",
        "Please specify the format you want.",
        "I need the following details: city, dates.",
        "Which cities? What dates?",
    ],
)
def test_drafts_that_hand_the_work_back_are_detected(body: str) -> None:
    assert asks_questions(body)


@pytest.mark.parametrize(
    "body",
    [
        "Tavily is hosted only [1]. Exa is semantic-first [2]. Let me know if you have questions.",
        "Here is the comparison. Does Friday work for a call?",
        "Please let me know if anything is unclear.",
        "Body.\n\nSources:\n[1] https://a.test/page?x=1&y=2?z",
    ],
)
def test_ordinary_courtesy_and_urls_are_not_mistaken_for_questions(body: str) -> None:
    assert not asks_questions(body)


async def test_a_research_draft_that_asks_questions_gets_one_firm_retry() -> None:
    asking = DraftContent(subject="s", body="Could you please clarify what to compare? [1]")
    delivered = DraftContent(subject="s", body="Acme sells widgets [1].")
    llm = FakeLLM(PLAN, asking, delivered)
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    draft = await service.prepare(cid, TODAY)
    assert llm.draft_calls == 2
    assert "Acme sells widgets" in draft.body and "clarify" not in draft.body


async def test_a_second_attempt_that_still_asks_is_kept_rather_than_looping() -> None:
    asking = DraftContent(subject="s", body="Could you please clarify? [1]")
    llm = FakeLLM(PLAN, asking)
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert llm.draft_calls == 2


async def test_a_delivered_draft_is_not_retried_and_no_results_means_no_retry() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert llm.draft_calls == 1

    no_results = FakeLLM(
        ResearchPlan(queries=[]),
        DraftContent(subject="s", body="Could you please clarify?", uses_search_results=False),
    )
    service, _, _, cid = _setup(no_results, FakeSearch())
    await service.prepare(cid, TODAY)
    assert no_results.draft_calls == 1


async def test_the_draft_prompt_says_deliver_instead_of_ask() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    prompt = " ".join(llm.last_system_prompt.split())
    assert "Deliver the work" in prompt and "Do not ask Priya what they want" in prompt
    assert "ask for each one" not in prompt


async def test_the_planner_is_taught_the_three_kinds_with_examples() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    for needle in ('"send_file"', '"research"', '"other"', "send the Q4 roadmap"):
        assert needle in llm.plan_prompt


def test_an_unknown_kind_is_rejected_by_validation_so_the_model_gets_a_repair_round() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate({"kind": "banana", "queries": []})


def _service_with_memory(
    llm: FakeLLM, search: FakeSearch, owed_due: date | None = None
) -> tuple[KeeperService, SqliteCommitmentRepository, SqliteDraftRepository, int, int]:
    """A keeper that remembers: Priya already has a kept promise, an email, and an open one."""
    db = Database(":memory:")
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)

    def promise(
        description: str,
        status: CommitmentStatus,
        direction: Direction,
        due: date | None = None,
    ) -> int:
        saved = commitments.add(
            Commitment(
                direction=direction,
                person="Priya",
                description=description,
                status=status,
                due=due,
                source_id="n",
                source_quote="q",
            )
        )
        return saved.id or 0

    current = promise("Send competitor comparison", CommitmentStatus.OPEN, Direction.OWED_BY_ME)
    earlier = promise("Review pricing page", CommitmentStatus.DONE, Direction.OWED_BY_ME)
    promise("Share the Q3 deck", CommitmentStatus.OPEN, Direction.OWED_TO_ME, owed_due)
    old = drafts.add(Draft(commitment_id=earlier, subject="Pricing review", body="b"))
    drafts.set_sent(old.id or 0, "p@acme.com", datetime(2026, 10, 3, tzinfo=UTC))
    service = KeeperService(
        llm, search, commitments, drafts, people=PeopleService(commitments, drafts)
    )
    return service, commitments, drafts, current, earlier


async def test_the_draft_prompt_carries_history_with_the_person_and_rules_for_using_it() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, current, _ = _service_with_memory(llm, FakeSearch([ACME]))

    await service.prepare(current, TODAY)

    assert "History with Priya:" in llm.last_user_prompt
    assert '"Pricing review" (3 Oct 2026)' in llm.last_user_prompt
    assert 'Priya owes you "Share the Q3 deck"' in llm.last_user_prompt
    assert "Send competitor comparison" not in llm.last_user_prompt.split("History with")[1]
    system = " ".join(llm.last_system_prompt.split())  # prompts are wrapped; compare ignoring that
    assert "A short history with Priya is included" in system
    assert "this follows that email" in system
    assert "never turn it into a new commitment" in system


async def test_a_cover_note_gets_no_history_it_is_just_a_cover_note() -> None:
    llm = FakeLLM(
        SEND_FILE_PLAN, DraftContent(subject="s", body="Attached.", uses_search_results=False)
    )
    service, _, _, current, _ = _service_with_memory(llm, FakeSearch())
    await service.prepare(current, TODAY)
    assert "History with" not in llm.last_user_prompt
    assert "history" not in llm.last_system_prompt.lower()


async def test_first_contact_has_no_history_block_and_no_history_rule() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    db = Database(":memory:")
    commitments, drafts = SqliteCommitmentRepository(db), SqliteDraftRepository(db)
    only = commitments.add(
        Commitment(
            direction=Direction.OWED_BY_ME,
            person="Newcomer",
            description="Send intro",
            source_id="n",
            source_quote="q",
        )
    )
    service = KeeperService(
        llm, FakeSearch([ACME]), commitments, drafts, people=PeopleService(commitments, drafts)
    )
    await service.prepare(only.id or 0, TODAY)
    assert "History with" not in llm.last_user_prompt
    assert "A short history" not in llm.last_system_prompt


async def test_without_a_people_service_drafting_still_works() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    await service.prepare(cid, TODAY)
    assert "History with" not in llm.last_user_prompt


async def test_a_postscript_reminds_about_what_they_still_owe_using_real_data() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, current, _ = _service_with_memory(
        llm, FakeSearch([ACME]), owed_due=date(2026, 10, 9)
    )
    body = (await service.prepare(current, TODAY)).body
    assert '\n\nBest,\n\nP.S. A gentle reminder: "Share the Q3 deck" is due 9 Oct.' in body
    assert body.index("P.S.") < body.index("Sources:")  # after the signature, before the sources


async def test_an_overdue_promise_is_called_overdue_and_a_far_off_one_is_left_alone() -> None:
    late = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, current, _ = _service_with_memory(
        late, FakeSearch([ACME]), owed_due=date(2026, 10, 5)
    )
    assert '"Share the Q3 deck" was due 5 Oct.' in (await service.prepare(current, TODAY)).body

    far = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    other, _, _, current2, _ = _service_with_memory(
        far, FakeSearch([ACME]), owed_due=date(2026, 11, 30)
    )
    assert "P.S." not in (await other.prepare(current2, TODAY)).body


async def test_without_anything_owed_there_is_no_postscript() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Acme sells widgets [1]."))
    service, _, _, current, _ = _service_with_memory(
        llm, FakeSearch([ACME])
    )  # owed, but no due date
    assert "P.S." not in (await service.prepare(current, TODAY)).body


def _chase_setup(
    llm: FakeLLM, due: date | None, *, status: CommitmentStatus = CommitmentStatus.OPEN
) -> tuple[KeeperService, SqliteCommitmentRepository, SqliteDraftRepository, int]:
    db = Database(":memory:")
    commitments = SqliteCommitmentRepository(db)
    drafts = SqliteDraftRepository(db)
    saved = commitments.add(
        Commitment(
            direction=Direction.OWED_TO_ME,
            person="Priya",
            description="Share the Q3 pricing deck",
            due=due,
            status=status,
            source_id="n1",
            source_quote="Priya said she will share the Q3 pricing deck by Wednesday.",
        )
    )
    search = FakeSearch([ACME])
    service = KeeperService(llm, search, commitments, drafts, signature=lambda: "Ada")
    return service, commitments, drafts, saved.id or 0


async def test_a_reminder_is_a_signed_unsearched_nudge_marked_as_a_reminder() -> None:
    llm = FakeLLM(
        PLAN,
        DraftContent(
            subject="Quick nudge", body="Hi Priya,\n\nChecking in.", uses_search_results=False
        ),
    )
    service, commitments, _, cid = _chase_setup(llm, date(2026, 10, 5))
    draft = await service.remind(cid, TODAY)
    assert draft.kind is DraftKind.REMINDER
    assert draft.subject == "Quick nudge"
    assert draft.body.endswith("Best,\nAda") and draft.sources == []
    stored = commitments.get(cid)
    assert stored is not None and stored.status is CommitmentStatus.READY_FOR_REVIEW
    assert llm.tiers == [Tier.SUPER]  # one writing call: no plan, no search


async def test_the_deadline_in_a_reminder_is_worked_out_by_code_not_the_model() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Hi Priya.", uses_search_results=False))
    service, _, _, cid = _chase_setup(llm, date(2026, 10, 5))  # Monday, two days before TODAY
    await service.remind(cid, TODAY)
    assert "It was due Monday 5 October." in llm.last_system_prompt
    assert 'Their original words: "Priya said she will share' in llm.last_system_prompt

    later = FakeLLM(PLAN, DraftContent(subject="s", body="Hi.", uses_search_results=False))
    service, _, _, cid = _chase_setup(later, date(2026, 10, 9))
    await service.remind(cid, TODAY)
    assert "It is due Friday 9 October." in later.last_system_prompt

    for due, expected in (
        (date(2026, 10, 7), "It is due today (Wednesday 7 October)."),
        (date(2026, 10, 8), "It is due tomorrow (Thursday 8 October)."),
        (date(2026, 10, 6), "It was due yesterday (Tuesday 6 October)."),
    ):
        relative = FakeLLM(PLAN, DraftContent(subject="s", body="Hi.", uses_search_results=False))
        service, _, _, cid = _chase_setup(relative, due)
        await service.remind(cid, TODAY)
        assert expected in relative.last_system_prompt

    none = FakeLLM(PLAN, DraftContent(subject="s", body="Hi.", uses_search_results=False))
    service, _, _, cid = _chase_setup(none, None)
    await service.remind(cid, TODAY)
    assert "They gave no deadline." in none.last_system_prompt


async def test_the_reminder_prompt_is_kind_and_forbids_inventing_things() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Hi.", uses_search_results=False))
    service, _, _, cid = _chase_setup(llm, date(2026, 10, 5))
    await service.remind(cid, TODAY)
    prompt = " ".join(llm.last_system_prompt.split())
    assert "Never accuse, scold or pressure" in prompt
    assert "Do not invent reasons, details, dates or new commitments" in prompt
    assert "the signature is added automatically" in prompt


async def test_only_open_promises_made_to_me_can_be_chased() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="b", uses_search_results=False))
    service, _, _, mine = _setup(llm, FakeSearch())  # a promise I made
    with pytest.raises(NotPreparableError, match="made to me"):
        await service.remind(mine, TODAY)
    with pytest.raises(CommitmentNotFoundError):
        await service.remind(999, TODAY)

    closed, _, _, done = _chase_setup(llm, None, status=CommitmentStatus.DONE)
    with pytest.raises(NotPreparableError, match="already closed"):
        await closed.remind(done, TODAY)


async def test_chasing_twice_while_a_reminder_is_pending_returns_the_same_draft() -> None:
    llm = FakeLLM(PLAN, DraftContent(subject="s", body="Hi.", uses_search_results=False))
    service, _, _, cid = _chase_setup(llm, None)
    first = await service.remind(cid, TODAY)
    second = await service.remind(cid, TODAY)
    assert first.id == second.id and llm.draft_calls == 1


async def test_a_model_written_subject_is_one_tidy_line() -> None:
    messy = "  Competitor\r\nBcc: evil@example.com   comparison  " + "x" * 400
    llm = FakeLLM(PLAN, DraftContent(subject=messy, body="Acme sells widgets [1]."))
    service, _, _, cid = _setup(llm, FakeSearch([ACME]))
    subject = (await service.prepare(cid, TODAY)).subject
    assert "\n" not in subject and "\r" not in subject and len(subject) <= 200
    assert subject.startswith("Competitor Bcc: evil@example.com comparison")

    reminder = FakeLLM(
        PLAN, DraftContent(subject="Nudge\nBcc: x", body="Hi.", uses_search_results=False)
    )
    service, _, _, cid = _chase_setup(reminder, None)
    assert (await service.remind(cid, TODAY)).subject == "Nudge Bcc: x"


@pytest.mark.parametrize(
    ("raw", "tidy"),
    [
        ("Free tier [1, 2].", "Free tier [1][2]."),
        ("Use cases [6, 7, 8] and more [3;4].", "Use cases [6][7][8] and more [3][4]."),
        ("Already fine [1][2] and [3].", "Already fine [1][2] and [3]."),
        ("The `deep` tier is slow.", "The deep tier is slow."),
        ("Sources:\n[1] https://a.test/x?y=[2,3]", "Sources:\n[1] https://a.test/x?y=[2][3]"),
    ],
)
def test_grouped_citations_become_one_marker_each_and_backticks_go(raw: str, tidy: str) -> None:
    assert tidy_body(raw) == tidy


async def test_sources_cited_only_in_a_group_still_appear_in_the_list() -> None:
    body = "Tavily is cheap [1, 2]. Exa is semantic `deep` search [2]."
    llm = FakeLLM(PLAN, DraftContent(subject="s", body=body))
    service, _, _, cid = _setup(llm, FakeSearch([ACME, BETA]))
    draft = await service.prepare(cid, TODAY)
    assert draft.sources == ["https://acme.test", "https://beta.test"]
    assert "[1][2]" in draft.body and "`" not in draft.body and "[1, 2]" not in draft.body
    assert "Sources:\n[1] https://acme.test\n[2] https://beta.test" in draft.body
