"""Turn raw notes into persisted commitments, rejecting anything the text does not support."""

import re
from datetime import date, timedelta

from pydantic import BaseModel

from kept.domain.models import Commitment, Direction, Tier
from kept.domain.ports import CommitmentRepository, StructuredLLM

_SYSTEM_PROMPT = """You extract commitments (promises) from meeting notes, transcripts and emails.

The user is "me". A commitment is a concrete promise to do something, made by me to someone
(direction "owed_by_me") or by someone to me (direction "owed_to_me"). Ignore vague intentions,
questions, and facts. Resolve relative dates ("Friday", "next week") by looking them up in this
calendar (never calculate them), as an ISO date (YYYY-MM-DD), or null if no deadline is stated.
A weekday on its own means its next occurrence on or after today.
{calendar}

Reply with JSON only:
{{"commitments": [{{"direction": "owed_by_me" | "owed_to_me", "person": "<the other person>",
"description": "<what was promised, imperative>", "due": "YYYY-MM-DD" | null,
"source_quote": "<exact words copied from the text>"}}]}}
Use an empty list when there are none."""


class ExtractedCommitment(BaseModel):
    direction: Direction
    person: str
    description: str
    due: date | None = None
    source_quote: str


class ExtractionResult(BaseModel):
    commitments: list[ExtractedCommitment]


def _calendar(today: date, days: int = 21) -> str:
    return "\n".join(
        f"{d:%a} {d.isoformat()}" + (" (today)" if d == today else "")
        for d in (today + timedelta(n) for n in range(days))
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class ExtractionService:
    def __init__(self, llm: StructuredLLM, repo: CommitmentRepository) -> None:
        self._llm = llm
        self._repo = repo

    async def extract(self, source_id: str, text: str, today: date) -> list[Commitment]:
        result = await self._llm.complete_json(
            Tier.NANO,
            [
                {"role": "system", "content": _SYSTEM_PROMPT.format(calendar=_calendar(today))},
                {"role": "user", "content": text},
            ],
            ExtractionResult,
            temperature=0.0,
            thinking=False,
        )
        haystack = _normalize(text)
        existing = {(c.source_id, _normalize(c.source_quote)) for c in self._repo.list()}
        saved: list[Commitment] = []
        for item in result.commitments:
            quote = _normalize(item.source_quote)
            if not quote or quote not in haystack or (source_id, quote) in existing:
                continue
            existing.add((source_id, quote))
            saved.append(
                self._repo.add(
                    Commitment(
                        direction=item.direction,
                        person=item.person.strip(),
                        description=item.description.strip(),
                        due=item.due,
                        source_id=source_id,
                        source_quote=item.source_quote.strip(),
                    )
                )
            )
        return saved
