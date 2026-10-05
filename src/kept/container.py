"""Composition root: the only place concrete adapters are wired to services."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import httpx

from kept.adapters.egress import build_http_client
from kept.adapters.llm import LLMClient
from kept.adapters.smtp import SmtpEmailSender
from kept.adapters.sqlite import (
    Database,
    SqliteAuditSink,
    SqliteCommitmentRepository,
    SqliteContactRepository,
    SqliteDraftRepository,
)
from kept.adapters.tavily import TavilySearch
from kept.config import Settings
from kept.domain.ports import EmailSender, StructuredLLM, WebSearch
from kept.services.extraction import ExtractionService
from kept.services.keeper import KeeperService
from kept.services.review import ReviewService


@dataclass
class Container:
    settings: Settings
    db: Database
    audit: SqliteAuditSink
    http: httpx.AsyncClient
    commitments: SqliteCommitmentRepository
    drafts: SqliteDraftRepository
    contacts: SqliteContactRepository
    extraction: ExtractionService
    keeper: KeeperService
    review: ReviewService
    today: Callable[[], date]

    async def aclose(self) -> None:
        await self.http.aclose()
        self.db.close()


def build_container(
    settings: Settings,
    *,
    llm: StructuredLLM | None = None,
    search: WebSearch | None = None,
    db: Database | None = None,
    email: EmailSender | None = None,
    inner_transport: httpx.AsyncBaseTransport | None = None,
    today: Callable[[], date] = date.today,
) -> Container:
    """Overrides exist so tests can swap the model, search and network without patching."""
    database = db or Database(settings.db_path)
    audit = SqliteAuditSink(database)
    http = build_http_client(settings.egress_allowlist, audit, inner=inner_transport)
    commitments = SqliteCommitmentRepository(database)
    drafts = SqliteDraftRepository(database)
    contacts = SqliteContactRepository(database)
    structured_llm = llm or LLMClient(settings, http)
    web_search = search or TavilySearch(settings.tavily_api_key.get_secret_value(), http)
    sender = email
    if sender is None and settings.email_enabled:
        sender = SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value(),
            sender=settings.email_from,
            sink=audit,
        )
    return Container(
        settings=settings,
        db=database,
        audit=audit,
        http=http,
        commitments=commitments,
        drafts=drafts,
        contacts=contacts,
        extraction=ExtractionService(structured_llm, commitments),
        keeper=KeeperService(structured_llm, web_search, commitments, drafts),
        review=ReviewService(
            commitments,
            drafts,
            contacts,
            sender=sender,
            sender_address=settings.email_from,
            allowed_recipients=settings.email_allowed_recipients,
        ),
        today=today,
    )
