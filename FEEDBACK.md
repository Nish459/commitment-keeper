# Hackathon feedback log

Running notes for the required feedback section. Add entries as we build; be specific.

## Nebius Token Factory
- Used for:
- Worked well:
- Needs work:
- Onboarding (zero to hello world):
- Would build again? Why:

## Nebius AI Cloud (Serverless Jobs / Endpoints)
- Used for:
- Worked well:
- Needs work:
- Onboarding:
- Would build again? Why:

## NVIDIA Nemotron (Nano / Super / Ultra)
- Used for:
- Worked well:
- Needs work:
- Would build again? Why:

## NemoClaw / OpenShell / Hermes Agent
- Used for:
- Worked well:
- Needs work:
- Would build again? Why:

## Log
| Date | Tool | Note |
|---|---|---|
| 2026-10-06 | Token Factory | `/v1/models` lists IDs with mixed case (`NVIDIA-Nemotron-3-Nano-30B-A3B`); lowercase guess from docs returned 404 "model does not exist". Docs/cookbook IDs differ from the live list. |
| 2026-10-06 | Token Factory | Super (`nemotron-3-super-120b-a12b`) answered a trivial prompt in 0.5s through the OpenAI SDK with only a base_url change. |
| 2026-10-06 | Nemotron 3 Nano | Reasoning is on by default: ~50 hidden tokens before the answer, so `max_tokens=64` intermittently returns empty content (finish_reason stop, text only in `reasoning`). `chat_template_kwargs.enable_thinking=false` via extra_body fixes it (2 tokens). Worth documenting prominently in the cookbook. |
| 2026-10-06 | Nemotron 3 Nano | Weekday-to-date arithmetic was wrong (Fri -> Sat, 1 of 2 dates off). Fixed by putting a 21-day weekday calendar in the prompt for lookup; 3/3 correct afterwards. Extraction otherwise accurate and ignored non-commitment chatter. |
| 2026-10-06 | Nemotron 3 Super | Same default-on reasoning as Nano: on a ~20 KB drafting prompt it burned the whole 3000-token budget (finish_reason=length, 16 s, empty content). With `enable_thinking=false`: ~10 s end to end for plan + 3 searches + draft. Trivial prompt: 2.6 s -> 1.0 s. |
| 2026-10-06 | Tavily | Basic search returned 200 in 1.3-2.3 s per query; results were rich enough for a cited multi-source comparison. Snippets can be single-blog-heavy, so we attribute claims inline. |
| 2026-10-06 | Nemotron 3 Nano / Super | Labeled extraction eval (8 cases): asking the model for ISO dates scored 5/13 (Nano, thinking off), 8/10 (Nano, thinking on, 50 s), 7/10 (Super, thinking off). Models are unreliable at weekday arithmetic. Having them copy the deadline phrase and resolving dates in code gave 9/9 for all three variants. Takeaway: let Nemotron extract and classify; do date math deterministically. |
| 2026-10-06 | Nemotron 3 Super | Hallucination under thin context: with no search results it wrote "no suitable venues found due to limited availability" (false). With results but a vague promise it invented a city ("Chicago") and a new deadline ("by Thursday EOD"). Fixed with explicit prompt rules (no invented locations/dates/commitments, ask for missing details, no name placeholder). Result: it now asks the recipient for location, budget and team size. Models follow negative constraints well when they are stated as rules. |
