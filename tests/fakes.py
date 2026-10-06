"""Shared test doubles: a scripted model, a fake web search and a fake mailer."""

from typing import Any

from pydantic import BaseModel

from kept.domain.errors import EmailError, SearchError
from kept.domain.models import Direction, SearchResult, Tier
from kept.services.extraction import ExtractedCommitment, ExtractionResult
from kept.services.keeper import DraftContent, ResearchPlan

NOTE = "I'll send Priya the competitor comparison by Friday."


class ScriptedLLM:
    def __init__(self) -> None:
        self.responses: dict[type[BaseModel], BaseModel] = {
            ExtractionResult: ExtractionResult(
                commitments=[
                    ExtractedCommitment(
                        direction=Direction.OWED_BY_ME,
                        person="Priya",
                        description="Send competitor comparison",
                        due_phrase="by Friday",
                        source_quote="I'll send Priya the competitor comparison by Friday",
                    )
                ]
            ),
            ResearchPlan: ResearchPlan(queries=["competitors"]),
            DraftContent: DraftContent(subject="Comparison", body="Here it is [1]."),
        }
        self.error: Exception | None = None

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        if self.error is not None:
            raise self.error
        return schema.model_validate(self.responses[schema].model_dump())


class FakeSearch:
    fail = False

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if self.fail:
            raise SearchError("down")
        return [SearchResult(title="A", url="https://a.test", snippet="facts")]


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise EmailError("Sending failed: refused")
        self.sent.append(to)
