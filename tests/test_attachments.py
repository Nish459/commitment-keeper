import httpx
import pytest

from kept.adapters.sqlite import (
    Database,
    SqliteAttachmentRepository,
    SqliteCommitmentRepository,
    SqliteDraftRepository,
)
from kept.domain.errors import InvalidAttachmentError
from kept.domain.models import Attachment, Commitment, Direction, Draft, DraftStatus
from kept.services.attachments import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_NAME_CHARS,
    MAX_TOTAL_BYTES,
    AttachmentService,
    clean_filename,
)
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError
from tests.fakes import NOTE, FakeSearch, FakeSender, ScriptedLLM


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("roadmap.pdf", "roadmap.pdf"),
        ("Q4 roadmap (final).pdf", "Q4 roadmap (final).pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\deck.pptx", "deck.pptx"),
        ("a/b/c.txt", "c.txt"),
        ("bad\x00na\nme\t.txt", "bad_na_me_.txt"),
        ('we"ird:na*me?.csv', "we_ird_na_me_.csv"),
        ("  .hidden  ", "hidden"),
        ("", "attachment"),
        ("...", "attachment"),
        ("///", "attachment"),
    ],
)
def test_filenames_are_made_safe_for_display_and_email_headers(raw: str, expected: str) -> None:
    assert clean_filename(raw) == expected


def test_long_filenames_are_shortened_but_keep_their_extension() -> None:
    name = clean_filename("x" * 300 + ".pdf")
    assert len(name) == MAX_NAME_CHARS and name.endswith(".pdf")
    assert len(clean_filename("y" * 300)) == MAX_NAME_CHARS


class Env:
    def __init__(self) -> None:
        db = Database(":memory:")
        self.drafts = SqliteDraftRepository(db)
        self.files = SqliteAttachmentRepository(db)
        self.service = AttachmentService(self.drafts, self.files)
        commitments = SqliteCommitmentRepository(db)
        commitment = commitments.add(
            Commitment(
                direction=Direction.OWED_BY_ME,
                person="Zoe",
                description="Send it",
                source_id="n",
                source_quote="q",
            )
        )
        self.draft_id = (
            self.drafts.add(Draft(commitment_id=commitment.id or 0, subject="s", body="b")).id or 0
        )


def test_the_repository_keeps_the_bytes_in_order_and_scopes_removal_to_the_draft() -> None:
    env = Env()
    first = env.files.add(
        Attachment(
            draft_id=env.draft_id,
            filename="a.bin",
            content_type="x/y",
            size=3,
            data=b"\x00\x01\xff",
        )
    )
    env.files.add(
        Attachment(draft_id=env.draft_id, filename="b.bin", content_type="x/y", size=1, data=b"b")
    )
    stored = env.files.for_draft(env.draft_id)
    assert [a.filename for a in stored] == ["a.bin", "b.bin"]
    assert stored[0].data == b"\x00\x01\xff"

    assert env.files.remove(env.draft_id + 1, first.id or 0) is False  # wrong draft
    assert env.files.remove(env.draft_id, first.id or 0) is True
    assert [a.filename for a in env.files.for_draft(env.draft_id)] == ["b.bin"]


def test_a_valid_file_is_stored_with_a_guessed_type_and_never_dumped_in_json() -> None:
    env = Env()
    saved = env.service.add(env.draft_id, "../roadmap.pdf", None, b"%PDF-1.4")
    assert (saved.filename, saved.content_type, saved.size) == ("roadmap.pdf", "application/pdf", 8)
    assert "data" not in saved.model_dump()
    assert saved.model_dump_json().find("PDF") == -1


@pytest.mark.parametrize("name", ["virus.exe", "run.BAT", "x.js", "a.ps1", "link.lnk"])
def test_file_types_that_email_providers_block_are_refused(name: str) -> None:
    env = Env()
    with pytest.raises(InvalidAttachmentError, match="block"):
        env.service.add(env.draft_id, name, None, b"data")


def test_size_count_and_total_limits_are_enforced() -> None:
    env = Env()
    with pytest.raises(InvalidAttachmentError, match="empty"):
        env.service.add(env.draft_id, "a.txt", None, b"")
    with pytest.raises(InvalidAttachmentError, match="over"):
        env.service.add(env.draft_id, "big.bin", None, b"x" * (MAX_FILE_BYTES + 1))

    chunk = b"x" * (MAX_TOTAL_BYTES // 3 + 1)
    for i in range(2):
        env.service.add(env.draft_id, f"part{i}.bin", None, chunk[:MAX_FILE_BYTES])
    env.service.add(env.draft_id, "part2.bin", None, chunk[:MAX_FILE_BYTES])
    with pytest.raises(InvalidAttachmentError, match="together"):
        env.service.add(env.draft_id, "part3.bin", None, chunk[:MAX_FILE_BYTES])

    small = Env()
    for i in range(MAX_FILES):
        small.service.add(small.draft_id, f"f{i}.txt", None, b"x")
    with pytest.raises(InvalidAttachmentError, match="at most"):
        small.service.add(small.draft_id, "one-too-many.txt", None, b"x")


def test_only_pending_drafts_can_change_and_unknown_drafts_are_reported() -> None:
    env = Env()
    attachment = env.service.add(env.draft_id, "a.txt", None, b"x")
    env.drafts.set_status(env.draft_id, DraftStatus.APPROVED)
    with pytest.raises(DraftAlreadyReviewedError):
        env.service.add(env.draft_id, "b.txt", None, b"x")
    with pytest.raises(DraftAlreadyReviewedError):
        env.service.remove(env.draft_id, attachment.id or 0)
    assert [a.filename for a in env.service.list(env.draft_id)] == [
        "a.txt"
    ]  # history stays readable
    with pytest.raises(DraftNotFoundError):
        env.service.add(999, "a.txt", None, b"x")
    with pytest.raises(DraftNotFoundError):
        env.service.list(999)


async def _prepared_draft(client: httpx.AsyncClient) -> int:
    cid = (await client.post("/api/notes", json={"source_id": "n", "text": NOTE})).json()[0]["id"]
    draft = (await client.post(f"/api/commitments/{cid}/prepare")).json()
    assert draft["needs_attachment"] is True
    return int(draft["id"])


def _pdf(name: str = "roadmap.pdf", size: int = 12) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, b"%" * size, "application/pdf")}


async def test_the_whole_flow_upload_list_send_with_the_file(
    attach_env: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    client, sender = attach_env
    draft_id = await _prepared_draft(client)

    blocked = await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "zoe@acme.com"})
    assert blocked.status_code == 409
    assert "file is attached" in blocked.json()["detail"]
    assert sender.sent == []

    uploaded = await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf())
    assert uploaded.status_code == 201
    assert uploaded.json() == {
        "id": 1,
        "draft_id": draft_id,
        "filename": "roadmap.pdf",
        "content_type": "application/pdf",
        "size": 12,
    }
    listed = (await client.get(f"/api/drafts/{draft_id}/attachments")).json()
    assert [a["filename"] for a in listed] == ["roadmap.pdf"]

    sent = await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "zoe@acme.com"})
    assert sent.status_code == 200
    assert sender.files == [["roadmap.pdf"]]


async def test_removing_a_file_and_sending_several(
    attach_env: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    client, sender = attach_env
    draft_id = await _prepared_draft(client)
    first = (await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf("a.pdf"))).json()
    await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf("b.pdf"))
    await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf("c.pdf"))

    assert (
        await client.delete(f"/api/drafts/{draft_id}/attachments/{first['id']}")
    ).status_code == 204
    assert (
        await client.delete(f"/api/drafts/{draft_id}/attachments/{first['id']}")
    ).status_code == 404

    await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "zoe@acme.com"})
    assert sender.files == [["b.pdf", "c.pdf"]]


async def test_bad_uploads_are_refused_with_a_reason(
    attach_env: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    client, _ = attach_env
    draft_id = await _prepared_draft(client)
    url = f"/api/drafts/{draft_id}/attachments"

    exe = await client.post(url, files=_pdf("setup.exe"))
    assert exe.status_code == 422 and "block" in exe.json()["detail"]
    big = await client.post(url, files=_pdf("big.pdf", MAX_FILE_BYTES + 1))
    assert big.status_code == 422 and "over" in big.json()["detail"]
    assert (await client.post("/api/drafts/999/attachments", files=_pdf())).status_code == 404
    assert (await client.get(url)).json() == []


async def test_files_cannot_be_added_after_the_draft_was_decided(
    attach_env: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    client, _ = attach_env
    draft_id = await _prepared_draft(client)
    await client.post(f"/api/drafts/{draft_id}/reject")
    late = await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf())
    assert late.status_code == 409


async def test_attachments_are_unavailable_when_email_is_not_set_up(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    cid = (await client.post("/api/notes", json={"source_id": "n", "text": NOTE})).json()[0]["id"]
    draft_id = (await client.post(f"/api/commitments/{cid}/prepare")).json()["id"]
    refused = await client.post(f"/api/drafts/{draft_id}/attachments", files=_pdf())
    assert refused.status_code == 409
    assert "isn't set up" in refused.json()["detail"]
