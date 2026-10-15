"""Rehearse the demo video's flow against the real models, so surprises show up before recording.

Run: .venv/bin/python scripts/rehearse_demo.py [--smtp]
Uses an in-memory database and your keys from .env. Costs a few cents. Sends no email: --smtp only
checks that the mail login works. Prints how long each step takes, so you know what to speed up.
"""

import asyncio
import smtplib
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from kept.adapters.sqlite import Database
from kept.api.app import create_app
from kept.config import Settings, get_settings
from kept.container import build_container
from kept.services.keeper import asks_questions
from kept.services.sample_inbox import write_sample_mbox

# Kept in step with the "Try a sample note" text in frontend/src/components/Composer.tsx.
SAMPLE_NOTE = (
    "Standup with Priya (Acme Corp). I will send her a competitor comparison of Tavily vs Exa vs "
    "Perplexity API for search by Friday. Priya said she will share the Q3 pricing deck by "
    "Wednesday. I also promised Marcus I'd review his onboarding doc by next Monday."
)

Json = dict[str, Any]


class Rehearsal:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.failures = 0
        self.timings: list[tuple[str, float]] = []

    def report(self, ok: bool, label: str, detail: str = "") -> None:
        if not ok:
            self.failures += 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")

    async def step(self, name: str, method: str, path: str, **kwargs: Any) -> Any:
        print(f"\n{name}")
        started = time.monotonic()
        response = await self.client.request(method, path, timeout=180, **kwargs)
        elapsed = time.monotonic() - started
        self.timings.append((name, elapsed))
        self.report(response.status_code < 400, f"{method} {path}", f"{elapsed:.1f}s")
        return response.json() if response.status_code < 400 else None


async def run(settings: Settings, mbox: Path) -> int:
    container = build_container(
        settings.model_copy(update={"smtp_host": "", "email_from": ""}), db=Database(":memory:")
    )
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://rehearsal") as client:
        r = Rehearsal(client)

        found: list[Json] = (
            await r.step(
                "1. Paste the sample note",
                "POST",
                "/api/notes",
                json={"source_id": "Sample standup", "text": SAMPLE_NOTE},
            )
        ) or []
        by_me = [c for c in found if c["direction"] == "owed_by_me"]
        r.report(
            len(found) == 3 and len(by_me) == 2,
            "three promises, two made by me",
            f"{len(found)} found",
        )
        r.report(all(c["source_quote"] for c in found), "each has its exact quote")

        comparison = next((c for c in by_me if "compar" in c["description"].lower()), None)
        if comparison:
            draft: Json = (
                await r.step(
                    "2. Research and draft the comparison",
                    "POST",
                    f"/api/commitments/{comparison['id']}/prepare",
                )
            ) or {}
            body = str(draft.get("body", ""))
            r.report(
                len(draft.get("sources", [])) >= 1,
                "cited sources",
                f"{len(draft.get('sources', []))}",
            )
            r.report(not asks_questions(body), "delivers instead of asking the recipient questions")
            r.report("Best," in body, "signed")
        else:
            r.report(False, "found the comparison promise")

        scan: Json = (
            await r.step(
                "3. Scan the sample inbox (uploaded as a real .mbox file)",
                "POST",
                "/api/inbox/scan",
                files=[("files", ("sample-inbox.mbox", mbox.read_bytes(), "application/mbox"))],
            )
        ) or {"suggestions": [], "completions": []}
        names = {c["description"].lower() for c in scan["completions"]}
        r.report(
            len(scan["suggestions"]) >= 4, "new promises suggested", f"{len(scan['suggestions'])}"
        )
        r.report(any("q3" in n for n in names), "Priya's deck noticed as done")
        r.report(any("onboarding" in n for n in names), "the Marcus review noticed as done")

        ids = [c["commitment_id"] for c in scan["completions"]]
        await r.step(
            "4. Apply the ticked changes",
            "POST",
            "/api/inbox/accept",
            json={"suggestions": scan["suggestions"]},
        )
        if ids:
            await r.step(
                "   ...and mark the finished ones kept",
                "POST",
                "/api/inbox/complete",
                json={"commitment_ids": ids},
            )

        ledger: list[Json] = await r.step("5. Read the ledger", "GET", "/api/commitments") or []
        theirs = next(
            (c for c in ledger if c["direction"] == "owed_to_me" and c["status"] == "open"), None
        )
        if theirs:
            reminder: Json = (
                await r.step(
                    "6. Draft a reminder for something owed to me",
                    "POST",
                    f"/api/commitments/{theirs['id']}/remind",
                )
            ) or {}
            r.report(
                reminder.get("kind") == "reminder",
                "a reminder draft",
                str(theirs["description"])[:40],
            )
        else:
            r.report(False, "something open that someone owes me")

        week: Json = (
            await r.step("7. Check my week (Nemotron Ultra)", "POST", "/api/week-check")
        ) or {}
        r.report(bool(week.get("summary")), "a summary came back")
        r.report(
            bool(week.get("suggested_order")),
            "a suggested order",
            f"{len(week.get('suggested_order', []))} items",
        )

        audit: list[Json] = await r.step("8. Privacy log", "GET", "/api/audit?limit=500") or []
        hosts = sorted({str(e["host"]) for e in audit})
        r.report(
            all(("nebius" in h or "tavily" in h) for h in hosts),
            "only Nebius and Tavily were contacted",
            ", ".join(hosts),
        )
        r.report(not any(e["blocked"] for e in audit), "nothing was blocked")

        print("\nTimings (record live, then speed up anything over about 8 s):")
        for name, seconds in r.timings:
            print(f"  {seconds:5.1f}s  {name.strip()}")
        print(f"  {sum(s for _, s in r.timings):5.1f}s  total")
        await container.aclose()
        return r.failures


def check_smtp(settings: Settings) -> bool:
    print("\nMail login check (nothing is sent)")
    if not settings.email_enabled:
        print(
            "  SKIP email is not configured: add KEPT_SMTP_HOST, KEPT_SMTP_USERNAME, "
            "KEPT_SMTP_PASSWORD and KEPT_EMAIL_FROM to .env"
        )
        return False
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
    except (smtplib.SMTPException, OSError) as exc:
        print(f"  FAIL could not log in to {settings.smtp_host}: {type(exc).__name__}")
        return False
    print(f"  ok   logged in to {settings.smtp_host} as {settings.smtp_username}")
    return True


def main() -> None:
    settings = get_settings()
    if (
        not settings.nebius_api_key.get_secret_value()
        or not settings.tavily_api_key.get_secret_value()
    ):
        raise SystemExit("Set KEPT_NEBIUS_API_KEY and KEPT_TAVILY_API_KEY in .env first.")
    with tempfile.TemporaryDirectory() as directory:
        mbox = Path(directory) / "sample-inbox.mbox"
        write_sample_mbox(mbox, date.today())
        failures = asyncio.run(run(settings, mbox))
    smtp_ok = check_smtp(settings) if "--smtp" in sys.argv else True
    verdict = "READY to record" if failures == 0 and smtp_ok else "NOT ready"
    print(f"\n{verdict}: {failures} check(s) failed")
    raise SystemExit(0 if failures == 0 and smtp_ok else 1)


if __name__ == "__main__":
    main()
