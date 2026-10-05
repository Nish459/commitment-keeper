from datetime import date
from typing import Any

from pydantic import BaseModel

from kept.adapters.sqlite import Database, SqliteCommitmentRepository
from kept.domain.models import Direction, Tier
from kept.services.extraction import ExtractedCommitment, ExtractionResult, ExtractionService

NOTE = (
    "Met Priya. I'll send her the competitor comparison by Friday.\nPriya will share the Q3 deck."
)


class FakeLLM:
    def __init__(self, result: ExtractionResult) -> None:
        self._result = result
        self.tiers: list[Tier] = []
        self.system_prompts: list[str] = []

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        self.tiers.append(tier)
        self.system_prompts.append(messages[0]["content"])
        return schema.model_validate(self._result.model_dump())


def _item(quote: str, direction: Direction = Direction.OWED_BY_ME) -> ExtractedCommitment:
    return ExtractedCommitment(
        direction=direction,
        person="Priya",
        description="Do the thing",
        due_phrase="by Friday",
        source_quote=quote,
    )


async def test_extract_saves_supported_commitments_using_nano() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    llm = FakeLLM(
        ExtractionResult(
            commitments=[
                _item("I'll send her the competitor comparison by Friday"),
                _item("Priya will share the Q3 deck", Direction.OWED_TO_ME),
            ]
        )
    )
    saved = await ExtractionService(llm, repo).extract("note-1", NOTE, date(2026, 10, 5))
    assert [c.direction for c in saved] == [Direction.OWED_BY_ME, Direction.OWED_TO_ME]
    assert all(c.id is not None for c in saved)
    assert llm.tiers == [Tier.NANO]
    assert len(repo.list()) == 2


async def test_extract_drops_quotes_not_found_in_source() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    llm = FakeLLM(ExtractionResult(commitments=[_item("I promised to fly to the moon")]))
    assert await ExtractionService(llm, repo).extract("note-1", NOTE, date(2026, 10, 5)) == []
    assert repo.list() == []


async def test_extract_is_idempotent_per_source() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    llm = FakeLLM(ExtractionResult(commitments=[_item("Priya will share the Q3 deck")]))
    service = ExtractionService(llm, repo)
    await service.extract("note-1", NOTE, date(2026, 10, 5))
    again = await service.extract("note-1", NOTE, date(2026, 10, 5))
    assert again == []
    assert len(repo.list()) == 1


async def test_due_phrase_is_resolved_deterministically() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    llm = FakeLLM(
        ExtractionResult(commitments=[_item("I'll send her the competitor comparison by Friday")])
    )
    (saved,) = await ExtractionService(llm, repo).extract("note-1", NOTE, date(2026, 10, 6))
    assert saved.due == date(2026, 10, 9)


async def test_description_is_saved_in_sentence_case() -> None:
    repo = SqliteCommitmentRepository(Database(":memory:"))
    item = _item("Priya will share the Q3 deck").model_copy(
        update={"description": " share the deck"}
    )
    llm = FakeLLM(ExtractionResult(commitments=[item]))
    (saved,) = await ExtractionService(llm, repo).extract("note-1", NOTE, date(2026, 10, 6))
    assert saved.description == "Share the deck"
