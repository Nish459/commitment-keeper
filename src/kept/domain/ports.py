from typing import Protocol

from kept.domain.models import AuditEvent, Commitment, CommitmentStatus


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class CommitmentRepository(Protocol):
    def add(self, commitment: Commitment) -> Commitment: ...

    def get(self, commitment_id: int) -> Commitment | None: ...

    def list(self, status: CommitmentStatus | None = None) -> list[Commitment]: ...

    def set_status(self, commitment_id: int, status: CommitmentStatus) -> None: ...
