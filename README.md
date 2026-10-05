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
- FastAPI, SQLite, pydantic

## Architecture
```
domain  <-  services  <-  adapters (llm, tavily, sqlite, egress)  <-  api / cli
```
Every outbound request passes through one audited egress client (allowlist + persisted audit log).

## Setup
```bash
cp .env.example .env   # add your keys
make install
make check
make run
```

## Status
Work in progress. See `FEEDBACK.md` for tool notes.

## License
MIT
