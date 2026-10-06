from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from kept.domain.models import (
    Attachment,
    AuditEvent,
    Commitment,
    CommitmentStatus,
    Draft,
    DraftStatus,
    SearchResult,
    Tier,
)


class StructuredLLM(Protocol):
    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T: ...


class WebSearch(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


class EmailSender(Protocol):
    async def send(
        self, to: str, subject: str, body: str, attachments: Sequence[Attachment] = ()
    ) -> None: ...


class AttachmentRepository(Protocol):
    def add(self, attachment: Attachment) -> Attachment: ...

    def for_draft(self, draft_id: int) -> list[Attachment]: ...

    def remove(self, draft_id: int, attachment_id: int) -> bool: ...


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class CommitmentRepository(Protocol):
    def add(self, commitment: Commitment) -> Commitment: ...

    def get(self, commitment_id: int) -> Commitment | None: ...

    def list(self, status: CommitmentStatus | None = None) -> list[Commitment]: ...

    def set_status(self, commitment_id: int, status: CommitmentStatus) -> None: ...


class DraftRepository(Protocol):
    def add(self, draft: Draft) -> Draft: ...

    def get(self, draft_id: int) -> Draft | None: ...

    def list(self, status: DraftStatus | None = None) -> list[Draft]: ...

    def for_commitment(self, commitment_id: int) -> Draft | None: ...

    def set_status(self, draft_id: int, status: DraftStatus) -> None: ...

    def set_sent(self, draft_id: int, to: str, at: datetime) -> None: ...

    def update_content(self, draft_id: int, subject: str, body: str) -> None: ...


class ProfileRepository(Protocol):
    def get_name(self) -> str | None: ...

    def set_name(self, name: str) -> None: ...


class ContactRepository(Protocol):
    def get(self, person: str) -> str | None: ...

    def set(self, person: str, email: str) -> None: ...

    def all(self) -> dict[str, str]: ...
