from pathlib import Path

import httpx

from kept.adapters.llm import LLMOutputError
from kept.adapters.sqlite import Database
from kept.api.app import create_app
from kept.config import Settings
from kept.container import build_container
from tests.fakes import NOTE, FakeSearch, FakeSender, ScriptedLLM


async def test_full_flow_ingest_prepare_approve(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    created = (await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})).json()
    assert [c["person"] for c in created] == ["Priya"]
    cid = created[0]["id"]

    draft = (await client.post(f"/api/commitments/{cid}/prepare")).json()
    assert draft["sources"] == ["https://a.test"]
    assert draft["status"] == "pending"
    ready = (await client.get("/api/commitments", params={"status": "ready_for_review"})).json()
    assert [c["id"] for c in ready] == [cid]

    approved = (await client.post(f"/api/drafts/{draft['id']}/approve")).json()
    assert approved["status"] == "approved"
    done = (await client.get("/api/commitments", params={"status": "done"})).json()
    assert [c["id"] for c in done] == [cid]


async def test_not_found_and_conflict_statuses(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    assert (await client.post("/api/commitments/99/prepare")).status_code == 404
    assert (await client.post("/api/drafts/99/approve")).status_code == 404

    cid = (await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})).json()[0]["id"]
    did = (await client.post(f"/api/commitments/{cid}/prepare")).json()["id"]
    await client.post(f"/api/drafts/{did}/reject")
    assert (await client.post(f"/api/drafts/{did}/approve")).status_code == 409


async def test_upstream_failures_map_to_502(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, llm, search = env
    cid = (await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})).json()[0]["id"]

    search.fail = True
    assert (await client.post(f"/api/commitments/{cid}/prepare")).status_code == 502

    search.fail = False
    llm.error = LLMOutputError("bad json")
    response = await client.post("/api/notes", json={"source_id": "n2", "text": NOTE})
    assert response.status_code == 502


async def test_validation_and_health(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    assert (await client.post("/api/notes", json={"source_id": "", "text": "x"})).status_code == 422
    health = (await client.get("/health")).json()
    assert health["status"] == "ok"
    assert health["nebius_key_set"] is False
    assert set(health) == {"status", "version", "nebius_key_set", "tavily_key_set"}
    assert (await client.get("/api/audit")).json() == []


async def test_allowlist_endpoint_lists_permitted_hosts(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    hosts = (await client.get("/api/allowlist")).json()
    assert "api.tavily.com" in hosts


async def test_web_ui_is_served_from_web_dir(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Kept</h1>")
    container = build_container(
        Settings(_env_file=None, web_dir=tmp_path),
        llm=ScriptedLLM(),
        search=FakeSearch(),
        db=Database(":memory:"),
    )
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert "<h1>Kept</h1>" in (await client.get("/")).text
        assert (await client.get("/health")).status_code == 200
    await container.aclose()


async def _prepared_draft(client: httpx.AsyncClient) -> int:
    note = {"source_id": "n1", "text": NOTE}
    cid = (await client.post("/api/notes", json=note)).json()[0]["id"]
    return int((await client.post(f"/api/commitments/{cid}/prepare")).json()["id"])


async def test_capabilities_and_allowlist_reflect_email_setup(
    email_env: tuple[httpx.AsyncClient, FakeSender],
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _ = email_env
    email = (await client.get("/api/capabilities")).json()["email"]
    assert email == {"enabled": True, "sender": "me@example.com", "recipients": ["priya@acme.com"]}
    assert "smtp.example.com" in (await client.get("/api/allowlist")).json()

    plain, _, _ = env
    assert (await plain.get("/api/capabilities")).json()["email"]["enabled"] is False


async def test_approve_with_recipient_sends_and_exposes_contact(
    email_env: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    client, sender = email_env
    draft_id = await _prepared_draft(client)

    response = await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "priya@acme.com"})
    assert response.status_code == 200
    assert response.json()["sent_to"] == "priya@acme.com"
    assert sender.sent == ["priya@acme.com"]
    assert (await client.get("/api/contacts")).json() == {"priya": "priya@acme.com"}


async def test_approve_email_errors_map_to_http_statuses(
    email_env: tuple[httpx.AsyncClient, FakeSender],
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, sender = email_env
    draft_id = await _prepared_draft(client)
    refused = await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "x@evil.com"})
    assert refused.status_code == 403

    sender.fail = True
    failed = await client.post(f"/api/drafts/{draft_id}/approve", json={"to": "priya@acme.com"})
    assert failed.status_code == 502

    plain, _, _ = env
    plain_draft = await _prepared_draft(plain)
    unconfigured = await plain.post(f"/api/drafts/{plain_draft}/approve", json={"to": "a@b.com"})
    assert unconfigured.status_code == 409


async def test_edit_draft_updates_text_and_validates_input(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    draft_id = await _prepared_draft(client)

    ok = await client.put(
        f"/api/drafts/{draft_id}", json={"subject": "  Better subject ", "body": " Better body "}
    )
    assert ok.status_code == 200
    assert (ok.json()["subject"], ok.json()["body"]) == ("Better subject", "Better body")
    stored = (await client.get("/api/drafts")).json()[0]
    assert stored["subject"] == "Better subject"

    bad_subject = await client.put(
        f"/api/drafts/{draft_id}", json={"subject": "a\nBcc: x@y.com", "body": "b"}
    )
    assert bad_subject.status_code == 422
    blank_body = await client.put(f"/api/drafts/{draft_id}", json={"subject": "s", "body": "   "})
    assert blank_body.status_code == 422
    missing = await client.put("/api/drafts/999", json={"subject": "s", "body": "b"})
    assert missing.status_code == 404

    await client.post(f"/api/drafts/{draft_id}/reject")
    reviewed = await client.put(f"/api/drafts/{draft_id}", json={"subject": "s", "body": "b"})
    assert reviewed.status_code == 409


async def test_profile_name_is_saved_trimmed_and_falls_back_to_the_setting(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    assert (await client.get("/api/profile")).json() == {"name": ""}

    saved = await client.put("/api/profile", json={"name": "  Ada Lovelace "})
    assert saved.json() == {"name": "Ada Lovelace"}
    assert (await client.get("/api/profile")).json() == {"name": "Ada Lovelace"}

    assert (await client.put("/api/profile", json={"name": ""})).json() == {"name": ""}
    assert (await client.put("/api/profile", json={"name": "A\nBcc: x@y.com"})).status_code == 422


async def test_drafts_are_signed_with_the_saved_profile_name(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    await client.put("/api/profile", json={"name": "Ada Lovelace"})
    draft_id = await _prepared_draft(client)
    draft = next(d for d in (await client.get("/api/drafts")).json() if d["id"] == draft_id)
    assert "Best,\nAda Lovelace" in draft["body"]


async def test_sweep_endpoint_drafts_everything_due_soon_and_reports_it(
    env: tuple[httpx.AsyncClient, ScriptedLLM, FakeSearch],
) -> None:
    client, _, _ = env
    await client.post("/api/notes", json={"source_id": "n1", "text": NOTE})  # due Friday

    swept = (await client.post("/api/sweep")).json()
    assert [d["status"] for d in swept["prepared"]] == ["pending"]
    assert (swept["failed"], swept["skipped"], swept["stopped"]) == ([], 0, None)

    again = (await client.post("/api/sweep")).json()
    assert again["prepared"] == []
