# Kept

**A private personal AI that tracks the promises you make, then does the work behind them.**

Built for the Nebius x NVIDIA Global AI Hackathon, **Personal AI** track.

People forget what they promised. Kept reads your notes, finds the commitments in them (both the ones
you made and the ones made to you), and keeps them: it researches, drafts the email, reminds you before
the deadline, and shows you exactly what left your machine. Nothing is sent without your approval.

> **Live demo:** _link added after deployment_ (see [Trying the demo](#trying-the-demo))

## What it does

| You do | Kept does |
|---|---|
| Paste meeting notes, or type a promise by hand | Finds each promise, who owes whom, and a due date, with the exact quote it came from |
| Click **Research and draft** (or **Draft all due soon**) | Searches the web, writes a **cited** email, and flags it if it says "attached" |
| Click **Check my week** | Reads every open promise and flags conflicts, late dependencies and risks, then suggests an order |
| Review a draft | Edit it, attach files, and approve. Only then is anything sent. |
| Open the **Perimeter** panel | See every request that left the machine: host, path and size, never content |

Also: ledger search, an `.ics` calendar download for any deadline, per-person history that shapes follow-ups
(including a reminder P.S. for what they still owe you), a light and a dark theme, and a `kept sweep`
command that drafts everything due soon, built to run as a scheduled job.

## How NVIDIA Nemotron and Nebius are used

All model calls go to **Nebius Token Factory** through its OpenAI-compatible API. The work is split
across three Nemotron sizes by how hard each task is:

| Task | Model | Why this size |
|---|---|---|
| Finding promises in notes | **Nemotron 3 Nano** | A fast, cheap pattern-extraction job |
| Planning research, writing cited drafts | **Nemotron 3 Super** | Needs good writing and grounding, not deep reasoning |
| **Check my week** (conflicts, dependencies, order) | **Nemotron 3 Ultra** | The one place that genuinely needs multi-step reasoning |

- **Tavily** supplies the web research behind every draft (runtime calls, always cited).
- **Nebius Serverless** hosts the demo endpoint (see [`docs/DEPLOY.md`](docs/DEPLOY.md)).
- Nemotron reasons by default and can use its whole token budget "thinking", so Kept turns reasoning off
  for extraction and drafting and leaves it on for Ultra. Details are in [`FEEDBACK.md`](FEEDBACK.md).

## Built to be trusted

- **Models never do date math or write facts about you.** The model copies a deadline *phrase* ("by
  Friday") and code computes the date. Names, signatures, reminders and sources are added by code.
- **Drafts are grounded.** Claims must cite the search results they came from, uncited drafts are
  rejected, and invented places, dates and commitments are forbidden by rule.
- **One audited way out.** Every outbound request goes through a single client with an exact-host
  allowlist and a metadata-only audit log, shown live in the Perimeter panel.
- **Email is off by default,** can only go to addresses you list, and an email that says "attached"
  cannot be sent without a file.

We measured extraction on labeled cases rather than guessing:
`scripts/eval_extraction.py`. Asking the model for ISO dates scored as low as 5/13. Copying phrases and
resolving them in code scored 9/9.

## Trying the demo

The hosted demo gives every visitor a **private, temporary workspace** with sample promises. No sign-in.
It resets after a couple of hours, email sending is off, and usage is capped to protect shared credits.
Judges can enter the **access code** from the submission notes (banner, "Have an access code?") to lift
the limits.

## Run it yourself

Requires Python 3.12+ and Node 20+.

```bash
cp .env.example .env     # add KEPT_NEBIUS_API_KEY and KEPT_TAVILY_API_KEY
make install
make check               # lint, types, backend and frontend tests
make run                 # builds the UI, serves everything at http://127.0.0.1:8000
```

Check your keys and model access: `.venv/bin/python scripts/check_live.py`.

Draft everything due soon from the command line (what a scheduled job runs): `.venv/bin/kept sweep`.

**Docker:** `docker buildx build --platform linux/amd64 -t kept .` then
`docker run -p 8000:8000 --env-file .env kept`. Deploying to Nebius: [`docs/DEPLOY.md`](docs/DEPLOY.md).

### Configuration

Defaults live in `src/kept/config.py`. Only the two keys are required; everything else is optional and
listed in [`.env.example`](.env.example): model IDs, outbound email (SMTP), demo mode and its limits,
the sweep window, and the egress allowlist.

## Architecture

```
domain  <-  services  <-  adapters (llm, tavily, sqlite, smtp, egress)  <-  api / cli
```

- `domain`: plain models, ports and errors, no I/O.
- `services`: extraction, keeper (research and drafting), review, sweep, planner (week check), people
  (history), attachments, calendar, manual entry.
- `adapters`: Token Factory client, Tavily, SQLite, SMTP, and the audited egress client.
- `container.py` is the only place adapters are wired to services. `demo.py` builds one private
  workspace per visitor.
- `frontend/`: React 19, TypeScript and Vite, with self-hosted fonts and no third-party requests.

## What it does not do (yet)

- It cannot create your files or act in the world: "send the Q4 roadmap" produces a cover note and
  asks you to attach the file; "book the venue" asks for the missing details.
- It does not read your mailbox or calendar. Promises come from notes you paste or type.
- The hosted demo is ephemeral by design, so cross-session memory is shown on a local install.
- NVIDIA NemoClaw, OpenShell and Hermes Agent were evaluated but not used (alpha, aimed at DGX/WSL).
  Kept implements its own audited egress allowlist instead.

## License

MIT. See [`LICENSE`](LICENSE).
