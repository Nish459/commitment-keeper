"""Does the work behind a promise: plan research, search, draft. Never sends anything."""

import re
from datetime import date

from pydantic import BaseModel, Field

from kept.domain.errors import SearchError
from kept.domain.models import (
    Commitment,
    CommitmentStatus,
    Direction,
    Draft,
    DraftStatus,
    SearchResult,
    Tier,
)
from kept.domain.ports import CommitmentRepository, DraftRepository, StructuredLLM, WebSearch

_SNIPPET_LIMIT = 1200

_PLAN_PROMPT = """You help me keep a promise I made. Decide what web research, if any, is needed
to fulfil it. Reply with JSON only: {"queries": ["<search query>", ...]}.
Use at most {max_queries} focused queries, or an empty list if no research is needed."""

_DRAFT_PROMPT = """You prepare the deliverable for a promise I made, as a ready-to-send email
from me to {person}. Today is {today}. Use ONLY facts from the provided search results; if they
are insufficient, say what is missing instead of inventing details. Every fact taken from a
result must end with that result's number in square brackets, like [2]. Keep it under 200 words,
concise and professional. Reply with JSON only: {{"subject": "...", "body": "..."}}"""

_REPAIR_PROMPT = (
    "Your draft cites no sources. Rewrite it so every fact taken from the search results ends "
    "with that result's number in square brackets, like [2]. Reply with the same JSON format."
)

_CITATION = re.compile(r"\[(\d+)\]")


class KeeperError(Exception):
    """The commitment cannot be prepared."""


class CommitmentNotFoundError(KeeperError):
    pass


class NotPreparableError(KeeperError):
    pass


class UngroundedDraftError(KeeperError):
    """The model would not ground its draft in the search results."""


class ResearchPlan(BaseModel):
    queries: list[str] = Field(default_factory=list)


class DraftContent(BaseModel):
    subject: str
    body: str


def _format_evidence(results: list[SearchResult]) -> str:
    if not results:
        return "(no search results)"
    return "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\n{r.snippet[:_SNIPPET_LIMIT]}"
        for i, r in enumerate(results, start=1)
    )


class KeeperService:
    def __init__(
        self,
        llm: StructuredLLM,
        search: WebSearch,
        commitments: CommitmentRepository,
        drafts: DraftRepository,
        *,
        max_queries: int = 3,
        max_results: int = 5,
    ) -> None:
        self._llm = llm
        self._search = search
        self._commitments = commitments
        self._drafts = drafts
        self._max_queries = max_queries
        self._max_results = max_results

    async def prepare(self, commitment_id: int, today: date) -> Draft:
        commitment = self._commitments.get(commitment_id)
        if commitment is None:
            raise CommitmentNotFoundError(f"Commitment {commitment_id} not found")
        if commitment.direction is not Direction.OWED_BY_ME:
            raise NotPreparableError("Only promises I made can be prepared")
        existing = self._drafts.for_commitment(commitment_id)
        if existing is not None and existing.status is DraftStatus.PENDING:
            return existing

        evidence = await self._gather(commitment)
        content = await self._write(commitment, evidence, today)

        numbered = {i: r.url for i, r in enumerate(evidence, start=1)}
        cited = sorted({int(n) for n in _CITATION.findall(content.body)} & numbered.keys())
        sources = [numbered[n] for n in cited]
        body = content.body.strip()
        if sources:
            listing = "\n".join(f"[{n}] {numbered[n]}" for n in cited)
            body = f"{body}\n\nSources:\n{listing}"
        draft = self._drafts.add(
            Draft(
                commitment_id=commitment_id,
                subject=content.subject.strip(),
                body=body,
                sources=sources,
            )
        )
        self._commitments.set_status(commitment_id, CommitmentStatus.READY_FOR_REVIEW)
        return draft

    async def _gather(self, commitment: Commitment) -> list[SearchResult]:
        plan = await self._llm.complete_json(
            Tier.SUPER,
            [
                {
                    "role": "system",
                    "content": _PLAN_PROMPT.replace("{max_queries}", str(self._max_queries)),
                },
                {"role": "user", "content": f"{commitment.description} (for {commitment.person})"},
            ],
            ResearchPlan,
            temperature=0.0,
            thinking=False,
        )
        queries = [q.strip() for q in plan.queries if q.strip()][: self._max_queries]
        results: list[SearchResult] = []
        failure: SearchError | None = None
        for query in queries:
            try:
                results.extend(await self._search.search(query, self._max_results))
            except SearchError as exc:
                failure = exc
        if queries and not results and failure is not None:
            raise failure
        return list({r.url: r for r in results}.values())

    async def _write(
        self, commitment: Commitment, evidence: list[SearchResult], today: date
    ) -> DraftContent:
        messages = [
            {
                "role": "system",
                "content": _DRAFT_PROMPT.format(person=commitment.person, today=today.isoformat()),
            },
            {
                "role": "user",
                "content": f"Promise: {commitment.description}\n"
                f'Original words: "{commitment.source_quote}"\n\n'
                f"Search results:\n{_format_evidence(evidence)}",
            },
        ]
        content = await self._complete(messages)
        if evidence and not _CITATION.search(content.body):
            repair = [
                *messages,
                {"role": "assistant", "content": content.model_dump_json()},
                {"role": "user", "content": _REPAIR_PROMPT},
            ]
            content = await self._complete(repair)
            if not _CITATION.search(content.body):
                raise UngroundedDraftError("The draft cited no sources, so it was not saved")
        return content

    async def _complete(self, messages: list[dict[str, str]]) -> DraftContent:
        return await self._llm.complete_json(
            Tier.SUPER,
            messages,
            DraftContent,
            temperature=0.3,
            max_tokens=4096,
            thinking=False,
        )
