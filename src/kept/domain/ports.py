from typing import Protocol

from kept.domain.models import AuditEvent


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...
