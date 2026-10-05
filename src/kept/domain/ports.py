from typing import Any, Protocol

from pydantic import BaseModel

from kept.domain.models import AuditEvent, Commitment, CommitmentStatus, Tier


class StructuredLLM(Protocol):
    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: list[dict[str, str]],
        schema: type[T],
        **kwargs: Any,
    ) -> T: ...


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class CommitmentRepository(Protocol):
    def add(self, commitment: Commitment) -> Commitment: ...

    def get(self, commitment_id: int) -> Commitment | None: ...

    def list(self, status: CommitmentStatus | None = None) -> list[Commitment]: ...

    def set_status(self, commitment_id: int, status: CommitmentStatus) -> None: ...
