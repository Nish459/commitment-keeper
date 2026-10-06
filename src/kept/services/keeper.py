"""Does the work behind a promise: plan research, search, draft. Never sends anything."""

import re
from collections.abc import Callable
from datetime import date
from typing import Literal

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

_PLAN_PROMPT = """You help me keep a promise I made. First decide what kind of promise it is, then
what web research it needs. Reply with JSON only:
{"kind": "research" | "send_file" | "other", "queries": ["<search query>", ...]}

kind:
- "send_file": I promised to send, share or forward something I already have or own: a document,
  deck, roadmap, report, file or link ("send the Q4 roadmap", "share the contract"). No queries.
- "research": I promised information, analysis, a comparison or options that can be gathered from
  the web ("compare vendors", "find venues", "summarize the new release").
- "other": anything else (book, call, review, decide, pay, follow up).

queries: at most {max_queries} focused queries for "research" and "other" promises that involve
finding, comparing, choosing or booking something. Empty for "send_file".
Use only details that appear in the promise or my original words. Never add a location, date,
name, budget or headcount of your own. If a key detail is missing, search generically."""

_SEND_FILE_PROMPT = """You write a short cover email for a promise I made to send something I
already have: {description}. Write it as a ready-to-send email from me to {person}.
Today is {today}.

Rules:
- Two to four short sentences. Start with "Hi {person},". Say the item is attached.
- Do not describe what the file contains, do not invent details, dates or numbers, and do not ask
  {person} any questions about it. You do not know its contents.
- Do not make new commitments or set new dates.
- Do not write a closing, sign-off or my name; the signature is added automatically.

Reply with JSON only: {{"subject": "...", "body": "...", "uses_search_results": false}}"""

_DRAFT_PROMPT = """You prepare the deliverable for a promise I made, as a ready-to-send email
from me to {person}. Today is {today}. Use ONLY facts from the provided search results; if they
are insufficient, say what is missing instead of inventing details. Every fact taken from a
result must end with that result's number in square brackets, like [2].

Rules:
- Never invent facts about me or my plans: no locations, budgets, headcounts, names or deadlines
  that are not in the promise, my original words, or the search results.
- Do not make new commitments or set new dates. Only restate the existing promise and its
  original deadline.
- Start with "Hi {person}," and say plainly what this email is about.
- If the promise needs details you do not have (location, budget, headcount, dates), ask for each
  one in a short bulleted list. Never send a bare follow-up with no content or questions.
- Keep it under 200 words, concise and professional.
- Do not write a closing, sign-off or my name; the signature is added automatically.

Reply with JSON only:
{{"subject": "...", "body": "...", "uses_search_results": true | false}}
Set "uses_search_results" to true only if the email states facts taken from the results. An email
that just asks questions or restates the promise uses none, and then needs no citations."""

_NO_EVIDENCE_RULE = """
You have NO search results. Do not state or imply any progress, findings, options, availability,
prices or decisions. You may only restate the promise, say it is still being worked on only if
that is explicitly in the promise text, and ask for any information needed to proceed."""

_REPAIR_PROMPT = (
    "Your draft cites no sources. Rewrite it so every fact taken from the search results ends "
    "with that result's number in square brackets, like [2]. Reply with the same JSON format."
)

_CITATION = re.compile(r"\[(\d+)\]")
# A trailing sign-off the model wrote anyway ("Best regards,", optionally followed by a name line).
_SIGNOFF = re.compile(
    r"(?:\s*\n)+\s*(?:best(?: regards)?|kind regards|regards|thanks|thank you|sincerely|cheers)"
    r"[,!.]?[ \t]*(?:\n[^\n]{0,60})?\s*$",
    re.IGNORECASE,
)


def _sign(body: str, name: str) -> str:
    """Replace any model-written closing with a deterministic one, so the name is never invented."""
    closing = f"Best,\n{name}" if name else "Best,"
    return f"{_SIGNOFF.sub('', body.strip())}\n\n{closing}"


class KeeperError(Exception):
    """The commitment cannot be prepared."""


class CommitmentNotFoundError(KeeperError):
    pass


class NotPreparableError(KeeperError):
    pass


class UngroundedDraftError(KeeperError):
    """The model would not ground its draft in the search results."""


class ResearchPlan(BaseModel):
    kind: Literal["research", "send_file", "other"] = "research"
    queries: list[str] = Field(default_factory=list)


class DraftContent(BaseModel):
    subject: str
    body: str
    # Strict by default: unless the model says it used no facts from the results, it must cite.
    uses_search_results: bool = True


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
        signature: Callable[[], str] = lambda: "",
    ) -> None:
        self._llm = llm
        self._search = search
        self._commitments = commitments
        self._drafts = drafts
        self._max_queries = max_queries
        self._max_results = max_results
        self._signature = signature

    async def prepare(self, commitment_id: int, today: date) -> Draft:
        commitment = self._commitments.get(commitment_id)
        if commitment is None:
            raise CommitmentNotFoundError(f"Commitment {commitment_id} not found")
        if commitment.direction is not Direction.OWED_BY_ME:
            raise NotPreparableError("Only promises I made can be prepared")
        existing = self._drafts.for_commitment(commitment_id)
        if existing is not None and existing.status is DraftStatus.PENDING:
            return existing

        plan = await self._plan(commitment)
        evidence = await self._search_for(plan)
        content = await self._write(commitment, evidence, today, plan.kind)

        numbered = {i: r.url for i, r in enumerate(evidence, start=1)}
        cited = sorted({int(n) for n in _CITATION.findall(content.body)} & numbered.keys())
        sources = [numbered[n] for n in cited]
        body = _sign(content.body, self._signature().strip())
        if sources:
            listing = "\n".join(f"[{n}] {numbered[n]}" for n in cited)
            body = f"{body}\n\nSources:\n{listing}"
        draft = self._drafts.add(
            Draft(
                commitment_id=commitment_id,
                subject=content.subject.strip(),
                body=body,
                sources=sources,
                needs_attachment=plan.kind == "send_file",
            )
        )
        self._commitments.set_status(commitment_id, CommitmentStatus.READY_FOR_REVIEW)
        return draft

    async def _plan(self, commitment: Commitment) -> ResearchPlan:
        return await self._llm.complete_json(
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

    async def _search_for(self, plan: ResearchPlan) -> list[SearchResult]:
        if plan.kind == "send_file":
            return []  # the thing to send is the user's own; the web cannot help
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
        self, commitment: Commitment, evidence: list[SearchResult], today: date, kind: str
    ) -> DraftContent:
        if kind == "send_file":
            return await self._complete(
                [
                    {
                        "role": "system",
                        "content": _SEND_FILE_PROMPT.format(
                            description=commitment.description,
                            person=commitment.person,
                            today=today.isoformat(),
                        ),
                    },
                    {"role": "user", "content": f'Original words: "{commitment.source_quote}"'},
                ]
            )
        system = _DRAFT_PROMPT.format(person=commitment.person, today=today.isoformat())
        messages = [
            {
                "role": "system",
                "content": system if evidence else system + _NO_EVIDENCE_RULE,
            },
            {
                "role": "user",
                "content": f"Promise: {commitment.description}\n"
                f'Original words: "{commitment.source_quote}"\n\n'
                f"Search results:\n{_format_evidence(evidence)}",
            },
        ]
        content = await self._complete(messages)
        if evidence and content.uses_search_results and not _CITATION.search(content.body):
            repair = [
                *messages,
                {"role": "assistant", "content": content.model_dump_json()},
                {"role": "user", "content": _REPAIR_PROMPT},
            ]
            content = await self._complete(repair)
            if content.uses_search_results and not _CITATION.search(content.body):
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
