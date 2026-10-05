# Kept

A private personal AI that tracks the promises you make and **keeps them**: it extracts commitments
from your notes, remembers people and history across sessions, does the research and drafting behind
each promise before the deadline, and shows exactly what left your machine.

Built for the Nebius x NVIDIA Global AI Hackathon (Personal AI track).

## Stack
- **Nebius Token Factory** for all inference (OpenAI-compatible API)
- **NVIDIA Nemotron** tiered by task: Nano (extraction), Super (drafting), Ultra (hard reasoning)
- **Tavily** for cited web research
- **Nebius Serverless** for hosting and nightly sweeps
- FastAPI, SQLite, pydantic (backend)
- React 19, TypeScript, Vite (frontend, self-hosted fonts, no third-party requests)

## Architecture
```
domain  <-  services  <-  adapters (llm, tavily, sqlite, egress)  <-  api / cli
```
Every outbound request passes through one audited egress client (allowlist + persisted audit log).
The UI shows that log live in its Perimeter panel.

## Setup
Requires Python 3.12+ and Node 20+.
```bash
cp .env.example .env   # add KEPT_NEBIUS_API_KEY and KEPT_TAVILY_API_KEY
make install
make check             # lint, types, backend and frontend tests
make run               # builds the UI, serves everything at http://127.0.0.1:8000
```
Verify your keys and model access with `.venv/bin/python scripts/check_live.py`.
Measure extraction quality with `.venv/bin/python scripts/eval_extraction.py`.

## Status
Work in progress. See `FEEDBACK.md` for tool notes.

## License
MIT
