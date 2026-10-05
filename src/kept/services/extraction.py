"""Turn raw notes into persisted commitments, rejecting anything the text does not support."""

import re
from datetime import date

from pydantic import BaseModel

from kept.domain.models import Commitment, Direction, Tier
from kept.domain.ports import CommitmentRepository, StructuredLLM
from kept.services.dates import resolve_due

_SYSTEM_PROMPT = """You extract commitments (promises) from meeting notes, transcripts and emails.

The user is "me". A commitment is a concrete promise to do something.
- direction "owed_by_me": I (the speaker, "I", "we") promised to do something for someone else.
- direction "owed_to_me": someone else (named) promised to do something for me.
"person" is always the OTHER party's name, never "me". If the other party is a role or company
(e.g. "the vendor"), use that. Ignore vague intentions ("maybe", "someday"), questions, and facts.

"due_phrase" is the deadline wording copied exactly from the text (e.g. "by Friday", "next Monday",
"end of this week", "tomorrow"), or null if the text states no deadline. Never compute dates.
"source_quote" is the exact sentence or clause copied from the text.

Reply with JSON only:
{"commitments": [{"direction": "owed_by_me" | "owed_to_me", "person": "...",
"description": "<what was promised, short imperative>", "due_phrase": "..." | null,
"source_quote": "..."}]}
Use an empty list when there are none."""


class ExtractedCommitment(BaseModel):
    direction: Direction
    person: str
    description: str
    due_phrase: str | None = None
    source_quote: str


class ExtractionResult(BaseModel):
    commitments: list[ExtractedCommitment]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class ExtractionService:
    def __init__(
        self,
        llm: StructuredLLM,
        repo: CommitmentRepository,
        *,
        tier: Tier = Tier.NANO,
        thinking: bool | None = False,
    ) -> None:
        self._llm = llm
        self._repo = repo
        self._tier = tier
        self._thinking = thinking

    async def extract(self, source_id: str, text: str, today: date) -> list[Commitment]:
        result = await self._llm.complete_json(
            self._tier,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            ExtractionResult,
            temperature=0.0,
            thinking=self._thinking,
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
                        due=resolve_due(item.due_phrase, today),
                        source_id=source_id,
                        source_quote=item.source_quote.strip(),
                    )
                )
            )
        return saved
