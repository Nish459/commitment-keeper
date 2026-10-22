"""Compare Nemotron with other Token Factory models on Kept's own tasks.

Run: .venv/bin/python -m scripts.compare_models [model-id ...]
Three tasks, each scored by code rather than by opinion:
  1. extraction: the labeled cases from scripts/eval_extraction.py
  2. dates: can the model turn "by Friday" into an ISO date? (Kept resolves dates in code instead)
  3. drafts: a cited comparison email from fixed search results, three runs each; counts drafts
     that ask the recipient questions, drafts with no citations, and numbers not in the evidence
Costs a few cents. Caveat: Kept's prompts were tuned on Nemotron, which favors it a little.
"""

import asyncio
import json
import re
import sys
import time
from datetime import date
from typing import Any

from pydantic import BaseModel

from kept.adapters.egress import build_http_client
from kept.adapters.llm import LLMClient
from kept.adapters.sqlite import Database, SqliteCommitmentRepository, SqliteDraftRepository
from kept.config import Settings, get_settings
from kept.domain.models import (
    AuditEvent,
    Commitment,
    Direction,
    SearchResult,
    Tier,
)
from kept.services.dates import resolve_due
from kept.services.extraction import ExtractionService
from kept.services.keeper import KeeperService, asks_questions
from scripts.eval_extraction import CASES, TODAY

NEMOTRON = "nvidia/"
DEFAULT_MODELS = [
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "google/gemma-3-27b-it",
    "nvidia/nemotron-3-super-120b-a12b",
    "openai/gpt-oss-120b",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
]
# Other models get more room to think than Kept gives Nemotron, so a hidden-reasoning model is not
# marked down for running out of tokens.
OTHER_MAX_TOKENS = 8192

PHRASES = [
    "by Friday", "next Monday", "tomorrow", "by Wednesday", "in 3 days", "in 2 weeks",
    "Oct 20", "the 15th of December", "end of the month", "end of this week", "this Friday",
]  # fmt: skip

EVIDENCE = [
    SearchResult(
        title="Tavily",
        url="https://tavily.example/docs",
        snippet="Tavily is a search API built for AI agents. Free tier: 1,000 credits per month. "
        "Pay-as-you-go costs $0.008 per credit. Basic search uses 1 credit, advanced search 2.",
    ),
    SearchResult(
        title="Exa",
        url="https://exa.example/pricing",
        snippet="Exa offers neural search with full page content. Deep search costs $12 per 1,000 "
        "requests. Exa supports structured outputs and similarity search.",
    ),
    SearchResult(
        title="Perplexity",
        url="https://perplexity.example/api",
        snippet="Perplexity's Search API returns ranked web results with domain and region "
        "filters. Its Agent API returns LLM answers with citations.",
    ),
    SearchResult(
        title="Comparison notes",
        url="https://notes.example/compare",
        snippet="For agents that need raw results, Tavily and Exa are lighter. For ready answers, "
        "Perplexity's Agent API saves a step.",
    ),
]


class NullSink:
    def record(self, event: AuditEvent) -> None:
        pass


class FixedSearch:
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return EVIDENCE


class DateGuess(BaseModel):
    phrase: str
    iso: str


class DateGuesses(BaseModel):
    dates: list[DateGuess]


class Roomy:
    """Gives non-Nemotron models what they need: no chat_template flag, and room to think."""

    def __init__(self, llm: LLMClient, nemotron: bool) -> None:
        self._llm = llm
        self._nemotron = nemotron

    async def complete_json[T: BaseModel](
        self, tier: Tier, messages: list[dict[str, str]], schema: type[T], **kwargs: Any
    ) -> T:
        if not self._nemotron:
            kwargs["thinking"] = None
            kwargs["max_tokens"] = max(kwargs.get("max_tokens", 0), OTHER_MAX_TOKENS)
        return await self._llm.complete_json(tier, messages, schema, **kwargs)


def _person(name: str) -> str:
    """ "The vendor" and "vendor" are the same person: ignore a leading article when scoring."""
    return re.sub(r"^(the|a|an)\s+", "", name.strip().lower())


async def extraction(llm: Roomy, nemotron: bool) -> dict[str, Any]:
    correct = total = errors = 0
    started = time.monotonic()
    for case in CASES:
        repo = SqliteCommitmentRepository(Database(":memory:"))
        service = ExtractionService(llm, repo, tier=Tier.NANO, thinking=False if nemotron else None)
        try:
            got = await service.extract("eval", case.text, TODAY)
        except Exception:
            errors += 1
            got = []
        found = {(c.direction, _person(c.person), c.due) for c in got}
        hits = sum((d, _person(p), due) in found for d, p, due in case.expected)
        correct += hits
        total += len(case.expected) + max(0, len(found) - hits)
    return {
        "correct": correct,
        "total": total,
        "errors": errors,
        "seconds": time.monotonic() - started,
    }


async def dates(llm: Roomy) -> dict[str, Any]:
    prompt = (
        f"Today is Tuesday {TODAY.isoformat()}. Convert each phrase to the date it means, as "
        'YYYY-MM-DD. Reply with JSON only: {"dates": [{"phrase": "...", "iso": "..."}]}\n'
        + "\n".join(PHRASES)
    )
    started = time.monotonic()
    try:
        out = await llm.complete_json(
            Tier.NANO,
            [{"role": "user", "content": prompt}],
            DateGuesses,
            temperature=0.0,
            thinking=False,
        )
    except Exception:
        return {
            "correct": 0,
            "total": len(PHRASES),
            "errors": 1,
            "seconds": time.monotonic() - started,
        }
    guessed = {g.phrase.strip().lower(): g.iso.strip() for g in out.dates}
    correct = sum(
        guessed.get(p.lower()) == (resolve_due(p, TODAY) or date.min).isoformat() for p in PHRASES
    )
    return {
        "correct": correct,
        "total": len(PHRASES),
        "errors": 0,
        "seconds": time.monotonic() - started,
    }


def unsupported_numbers(body: str) -> int:
    """Numbers in a draft that appear nowhere in the evidence: a cheap hallucination signal."""
    text = body.split("\n\nSources:")[0]
    text = re.sub(r"\[\d+\]", "", text)
    evidence = " ".join(r.snippet for r in EVIDENCE)
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
    return sum(1 for n in numbers if n.strip(",") and n not in evidence)


async def drafts(settings: Settings, llm: Roomy, runs: int = 3) -> dict[str, Any]:
    questions = uncited = unsupported = errors = 0
    started = time.monotonic()
    for _ in range(runs):
        db = Database(":memory:")
        commitments, store = SqliteCommitmentRepository(db), SqliteDraftRepository(db)
        saved = commitments.add(
            Commitment(
                direction=Direction.OWED_BY_ME,
                person="Priya",
                description="Send competitor comparison of Tavily vs Exa vs Perplexity",
                source_id="eval",
                source_quote="I will send her a competitor comparison by Friday.",
            )
        )
        keeper = KeeperService(llm, FixedSearch(), commitments, store)
        try:
            draft = await keeper.prepare(saved.id or 0, TODAY)
        except Exception:
            errors += 1
            continue
        questions += asks_questions(draft.body)
        uncited += not draft.sources
        unsupported += unsupported_numbers(draft.body)
    done = max(1, runs - errors)
    return {
        "runs": runs,
        "errors": errors,
        "asked_questions": questions,
        "uncited": uncited,
        "unsupported_numbers_per_draft": round(unsupported / done, 1),
        "seconds_per_draft": round((time.monotonic() - started) / runs, 1),
    }


async def evaluate(base: Settings, http: Any, model: str) -> dict[str, Any]:
    nemotron = model.startswith(NEMOTRON)
    settings = base.model_copy(
        update={"model_nano": model, "model_super": model, "model_ultra": model}
    )
    llm = Roomy(LLMClient(settings, http), nemotron)
    print(f"  running {model}")
    result: dict[str, Any] = {"model": model}
    result["extraction"] = await extraction(llm, nemotron)
    result["dates"] = await dates(llm)
    result["drafts"] = await drafts(settings, llm)
    return result


def table(results: list[dict[str, Any]]) -> str:
    header = "| Model | Extraction | ISO dates | Asked questions | Uncited | Unsupported numbers |"
    rows = [header, "|---|---|---|---|---|---|"]
    for r in results:
        e, d, k = r["extraction"], r["dates"], r["drafts"]
        rows.append(
            f"| {r['model']} | {e['correct']}/{e['total']} ({e['errors']} errors) | "
            f"{d['correct']}/{d['total']} | {k['asked_questions']}/{k['runs']} | "
            f"{k['uncited']}/{k['runs']} | {k['unsupported_numbers_per_draft']} |"
        )
    return "\n".join(rows)


async def main() -> None:
    models = sys.argv[1:] or DEFAULT_MODELS
    settings = get_settings()
    http = build_http_client(settings.egress_allowlist, NullSink())
    print(f"Comparing {len(models)} models (in parallel)")
    results = await asyncio.gather(*(evaluate(settings, http, m) for m in models))
    await http.aclose()
    print("\n" + table(list(results)))
    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
