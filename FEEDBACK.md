# Feedback on the tools

Built solo for the Nebius x NVIDIA Global AI Hackathon (Personal AI track). This is what I used, what
worked, and what got in the way, in the order I hit it. The dated log at the bottom has the raw notes.

## Nebius Token Factory

**Used for:** every runtime model call in Kept. Pulling promises out of notes and emails (Nano), planning
research and writing cited drafts (Super), and the weekly conflict check (Ultra). All of it goes through one
audited HTTP client, so the privacy log in the app shows each Token Factory request.

**Worked well**
- It is OpenAI-compatible. I changed the base URL and kept the standard client, and the first call worked.
- Three Nemotron sizes behind one key made it easy to match the model to the task instead of paying for the
  biggest model everywhere.
- Fast: a trivial prompt on Super came back in about 0.5 seconds. Structured JSON output was reliable once
  reasoning was turned off.
- The hackathon credits applied to Token Factory calls, which is what let me test freely.

**Needs work**
- Model IDs are case-sensitive and the docs and cookbook IDs did not match the live `/v1/models` list. My
  lowercase guess from the docs returned 404 "model does not exist", which does not hint at the real cause.
  I found the right IDs only by listing the models. A "did you mean" in the error, or docs generated from
  the live list, would save the first hour of every newcomer.
- The credits are Token Factory only, and that was not obvious. See the AI Cloud section below.

**Onboarding (zero to hello world):** quick. The only real hiccup was the model ID problem above.

**Would I build on it again?** Yes. The compatibility, speed and tiered models are the reasons Kept is
practical. The fixes I would ask for are the error message and the docs.

## Nebius AI Cloud (Serverless Endpoints / Jobs)

**Used for:** I tried, and it is not part of the shipped app. I prepared a Serverless endpoint deployment
and got as far as creating a registry, then stopped, so I cannot give feedback on running a workload there.
Kept is hosted on Render's free tier instead. The Nebius steps I prepared are in `docs/DEPLOY.md` (option B).

**What happened**
- The CLI sign-in worked once I chose browser federation over a service account. The prompts asked for a
  tenant ID and a project, and it took a while to find where to read the tenant ID. A "where do I find this"
  link in the prompt would help.
- Creating a container registry failed with a PermissionDenied error. The cause was a zero AI Cloud balance:
  I had promo credits, but they only apply to Token Factory. I read the error as a permissions problem and
  only found the zero balance on the billing page, and it was not clear to me from the hackathon materials
  that the credits excluded AI Cloud. A plain "insufficient balance" message would have saved me a detour.
- I checked the hackathon rules before paying anything. They say the app can run on Token Factory or AI
  Cloud and describe Serverless hosting as encouraged, not required, so I hosted elsewhere.

**Worked well (from the docs, not from running it)**
- The endpoint command's flags are clear: a CPU preset, a public port, no auth. A small CPU container is
  all Kept would need, since the models run on Token Factory.
- Per-second billing suits a demo that is idle most of the time.

**Needs work**
- Make it clear, in the rules and in the welcome material, that promo credits do not cover AI Cloud. Or let
  a small CPU endpoint run on them, so entrants can use the platform they are being asked to review.
- The docs say an endpoint cannot be updated in place, so each redeploy changes the public URL. For a
  hackathon submission that is a trap. A stable name would help. This is from the docs. I did not hit it.

**Would I build on it again?** Yes, if the credits covered it. A hosted demo on Serverless is the natural
home for this app.

## NVIDIA Nemotron (Nano / Super / Ultra)

**Used for:** Nano 30B for fast extraction and classification (notes and emails). Super 120B for planning
research and writing drafts. Ultra 550B for the week check, the one task that needs multi-step reasoning
across the whole list of promises.

**Worked well**
- Nano is accurate at finding promises and ignoring chatter. On my labeled test cases it found the right
  people and directions and copied exact quotes. Dates were its weak spot (below).
- With one short line of context ("this email was written to me by Priya, so 'I' means Priya"), Nano got
  the direction of every promise right across three live runs on a sample inbox, skipped quoted replies, and
  ignored requests and small talk.
- Super follows rules stated plainly. "Never invent a place, date or commitment" and "cite the search
  result you used" worked, and I enforce both in code as well.
- Right-sizing paid off: a cheap, fast model for the many small reads, the big one only where reasoning
  matters.

- Ultra: I left reasoning on for the week check and did not benchmark it separately from the other models,
  so I have no numbers for it beyond it returning usable conflict and ordering advice in the app.

**Needs work**
- **Reasoning is on by default and can use the whole token budget.** On Nano, a 64-token limit
  intermittently returned empty content, because the answer was hidden in the reasoning field. On Super, a
  20 KB drafting prompt spent all 3,000 tokens thinking (16 seconds, empty content). Passing
  `chat_template_kwargs.enable_thinking=false` fixed it, and a trivial call went from 2.6 s to 1.0 s. This
  deserves a prominent place in the cookbook and the model cards.
- **Weekday arithmetic is unreliable.** Asking for ISO dates scored 5/13 on Nano with thinking off, 8/10 with
  thinking on (50 seconds), and 7/10 on Super. Having the model copy the phrase ("by Friday") and resolving
  the date in code scored 9/9 on all three. Let Nemotron read and classify, and do date math in code.
- **Hallucination under thin context.** With no search results, Super wrote "no suitable venues found" (false).
  With vague input it invented a city and a new deadline. Explicit rules fixed it.
- **Drafts are not always consistent.** For the same promise, Super sometimes delivers a cited comparison and
  sometimes writes an email asking the recipient what they want compared. I have this logged as known work.

**Would I build on it again?** Yes. The tiering story is real and the models are good at the reading and
classifying work. I would turn reasoning off by default for anything short and structured.

## NemoClaw / OpenShell / Hermes Agent

**Used for:** evaluated from the documentation only. I did not install them, so this is not hands-on feedback.

**Why not used:** NemoClaw was alpha and its prerequisites pointed at DGX or WSL, and I develop on macOS. I
wanted every outbound request to be provable, so I built that directly: one HTTP client with an exact-host
allowlist and a metadata-only audit log, shown in the app's Privacy log. It covers the same need for this app.

**What would have made me use them:** a macOS or plain Docker path, and a small example of an egress policy
and approval flow I could run in ten minutes.

**Would I build on them again?** Yes, on a Linux box with a few days to spare. The sandboxed, policy-driven
egress idea is the right one for personal agents.

## Tavily

**Used for:** web research behind every cited draft, called at runtime through the same audited client.

**Worked well:** basic search returned in 1.3 to 2.3 seconds, and results were rich enough for a
multi-source comparison.
**Needs work:** results can lean on a single blog, so Kept cites claims inline and the reader can judge.

## What I would tell the organizers

1. Say clearly that hackathon credits are Token Factory only, and what an AI Cloud hosted demo costs.
2. Put the model ID list and the reasoning default in the first page of the Token Factory docs.
3. Give newcomers a "hello world" for a CPU Serverless endpoint that runs on the credits.

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
| 2026-10-07 | AI Cloud | Registry creation failed with PermissionDenied. Cause: AI Cloud billing balance was $0. Hackathon promo credits apply to Token Factory only. I read the error as a permissions problem; the billing page showed the zero balance. |
| 2026-10-09 | Hosting | Checked the rules: Token Factory runtime calls satisfy "runs on Token Factory or AI Cloud", so hosting the demo elsewhere is allowed. Hosted on Render's free tier (Docker). |
| 2026-10-09 | Nemotron 3 Nano | Mail scan: with a one-line "who is speaking" context, direction was right for every promise across 3 live runs on a sample inbox (5 promises from 6 emails, newsletter and small talk ignored). An email I wrote vs an email to me needed different context lines; without them "I'll send it" would be filed as my promise. |
| 2026-10-09 | Nemotron 3 Super | Same research promise ("competitor comparison") produced a clean cited draft once and a draft asking the recipient to clarify on another run. Non-deterministic; logged as a known issue. |
