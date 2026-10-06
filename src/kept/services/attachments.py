"""Files a user adds to a draft so an email that says "attached" really has the file."""

import mimetypes
import re
from pathlib import PurePosixPath

from kept.domain.errors import InvalidAttachmentError
from kept.domain.models import Attachment, DraftStatus
from kept.domain.ports import AttachmentRepository, DraftRepository
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_NAME_CHARS = 120
# Mail providers reject these outright, so refuse early with a clear reason.
BLOCKED_EXTENSIONS = frozenset(
    {".exe", ".bat", ".cmd", ".com", ".scr", ".js", ".vbs", ".msi", ".jar", ".ps1", ".sh", ".lnk"}
)
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_MAX_SUFFIX_CHARS = 10


def clean_filename(name: str) -> str:
    """A safe name for display and the email header: no path, control chars, bounded length."""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if len(base) > MAX_NAME_CHARS:
        suffix = PurePosixPath(base).suffix
        suffix = suffix if len(suffix) <= _MAX_SUFFIX_CHARS else ""
        base = base[: MAX_NAME_CHARS - len(suffix)] + suffix
    return base or "attachment"


def _megabytes(size: int) -> int:
    return size // (1024 * 1024)


class AttachmentService:
    def __init__(self, drafts: DraftRepository, attachments: AttachmentRepository) -> None:
        self._drafts = drafts
        self._attachments = attachments

    def _require_pending(self, draft_id: int) -> None:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise DraftNotFoundError(f"Draft {draft_id} not found")
        if draft.status is not DraftStatus.PENDING:
            raise DraftAlreadyReviewedError(f"Draft {draft_id} is already {draft.status.value}")

    def list(self, draft_id: int) -> list[Attachment]:
        if self._drafts.get(draft_id) is None:
            raise DraftNotFoundError(f"Draft {draft_id} not found")
        return self._attachments.for_draft(draft_id)

    def add(
        self, draft_id: int, filename: str, content_type: str | None, data: bytes
    ) -> Attachment:
        self._require_pending(draft_id)
        name = clean_filename(filename)
        if PurePosixPath(name).suffix.lower() in BLOCKED_EXTENSIONS:
            raise InvalidAttachmentError(f"{name} is a file type email providers block.")
        if not data:
            raise InvalidAttachmentError(f"{name} is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise InvalidAttachmentError(f"{name} is over {_megabytes(MAX_FILE_BYTES)} MB.")
        existing = self._attachments.for_draft(draft_id)
        if len(existing) >= MAX_FILES:
            raise InvalidAttachmentError(f"A draft can have at most {MAX_FILES} attachments.")
        if sum(a.size for a in existing) + len(data) > MAX_TOTAL_BYTES:
            raise InvalidAttachmentError(
                f"Attachments together are limited to {_megabytes(MAX_TOTAL_BYTES)} MB."
            )
        kind = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return self._attachments.add(
            Attachment(
                draft_id=draft_id, filename=name, content_type=kind, size=len(data), data=data
            )
        )

    def remove(self, draft_id: int, attachment_id: int) -> bool:
        self._require_pending(draft_id)
        return self._attachments.remove(draft_id, attachment_id)
