# Deploying Kept

Three ways to host the public demo. **Option A (Render, free) is what we use.**

- **A: Render**, free plan, builds the root `Dockerfile` straight from GitHub. No card needed.
- **B: Nebius Serverless**, needs a funded AI Cloud billing account (hackathon promo credits apply to Token
  Factory only, so an AI Cloud project starts at a $0 balance and refuses to create resources).
- **C: Hugging Face Space** (`deploy/huggingface/`), but Docker Spaces became paid (PRO) in 2026.

The rules do not require hosting on Nebius: *"runs on Nebius Token Factory or Nebius AI Cloud"* is met by
making runtime calls to the Token Factory API, which Kept does on every request.

## Option A (free): Render

`render.yaml` in the repo root describes the service: Docker runtime, free plan, `/health` check, demo mode
on, and the three secrets left blank for you to enter.

1. Sign in at render.com with GitHub and let it read the `commitment-keeper` repo.
2. **New, Blueprint**, pick the repo and the `master` branch. Render reads `render.yaml`.
3. When asked, enter the secrets: `KEPT_NEBIUS_API_KEY`, `KEPT_TAVILY_API_KEY` and `KEPT_DEMO_ACCESS_CODE`
   (a code you choose). Create the service and watch **Logs** while the image builds (several minutes).
4. When it says Live, open `https://kept-xxxx.onrender.com` (shown at the top of the service page).
5. Check it: banner and sample promises, **Find promises**, **Research and draft**, the access code, and
   the Perimeter panel showing only Nebius and Tavily.

Good to know:
- A free service **sleeps after 15 minutes without traffic** and takes about a minute to wake. Open the
  link yourself shortly before judging, and say so in the testing notes.
- Free instances have 512 MB of RAM and restart from time to time. Demo workspaces are in memory and
  temporary by design, so that is fine.
- Render deploys on every push to the branch. **Before submitting, turn off auto-deploy** (Settings, Build
  and Deploy) once the judged version is live, so a later push cannot break it.
- Rate limits count visitors by client address. Leave `FORWARDED_ALLOW_IPS` unset: behind Render's proxy
  visitors then share one address for those limits, which is safe for a demo and cannot be spoofed.
- Never put a key in `render.yaml` or the Dockerfile. Only the secrets screen.

## Option B (needs paid AI Cloud billing): Nebius Serverless

Puts the **public demo** on a Nebius Serverless AI **endpoint**: one small CPU container (the models
run on Token Factory, so no GPU is needed). Every visitor gets a private temporary workspace.

Commands marked **(verified)** come straight from the Nebius docs. Anything marked **(check `--help`)** I
could not confirm, so run the command with `--help` first.

## What you need
- A Nebius AI Cloud account and project, with credits (the Builder Program credits apply).
- Docker running on your machine.
- Your `KEPT_NEBIUS_API_KEY` and `KEPT_TAVILY_API_KEY` (already in your `.env`).
- A demo access code you choose (it goes in the submission's testing notes).

## 1. Install and sign in to the Nebius CLI (verified)
```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
exec -l $SHELL
nebius version
nebius profile create      # opens a browser to sign in; choose your tenant and project
```

## 2. Create a registry and let Docker use it (verified)
Use your project's region for `REGION_ID` (for example `eu-north1` or `us-central1`).
```bash
export REGION_ID=<your-region>
export REGISTRY_PATH=$(nebius registry create --name kept --format json | jq -r ".metadata.id" | cut -d- -f 2)
nebius registry configure-helper
```

## 3. Build for amd64 and push (verified pattern)
Nebius runs `amd64`. On an Apple Silicon Mac you must say so, or the container fails with
`exec format error`.
```bash
export IMAGE=cr.$REGION_ID.nebius.cloud/$REGISTRY_PATH/kept:v1
docker buildx build --platform linux/amd64 -t $IMAGE --push .
```
An image in a registry in the **same project** needs no pull credentials.

## 4. Create the endpoint (flags verified)
```bash
export DEMO_CODE=<choose-an-access-code>

nebius ai endpoint create \
  --name kept-demo \
  --image $IMAGE \
  --platform cpu-d3 \
  --preset 2vcpu-8gb \
  --public \
  --container-port 8000 \
  --auth none \
  --env KEPT_DEMO_MODE=true \
  --env KEPT_DEMO_ACCESS_CODE=$DEMO_CODE \
  --env KEPT_NEBIUS_API_KEY=<your key> \
  --env KEPT_TAVILY_API_KEY=<your key>
```
Why these choices:
- `--auth none`: judges open the app in a browser, which cannot send a token header. The app protects
  itself with its demo limits and the access code.
- `--platform cpu-d3 --preset 2vcpu-8gb`: a CPU-only machine; the app is light (about 100 MB of memory).
- One endpoint is one instance, which is what demo mode needs (workspaces live in memory).
- Do **not** set `FORWARDED_ALLOW_IPS` until you have checked what the proxy sends (see the end).

**About secrets.** `--env` stores the keys in the endpoint's definition, visible to people with access to
the project. The safer route is `--env-secret KEPT_NEBIUS_API_KEY=<secret>` with a MysteryBox secret
whose payload key has the same name as the variable (verified for `--env-secret`; **check
`nebius mysterybox secret create --help`** for creating the secret). Also, never paste the keys into
chat or commit them.

## 5. Find the URL and check it (verified)
```bash
nebius ai endpoint list
export ENDPOINT_ID=<the id of kept-demo>
nebius ai endpoint get $ENDPOINT_ID --format json | jq -r '.status.state'
export URL=$(nebius ai endpoint get $ENDPOINT_ID --format json | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1)
echo $URL
curl -s $URL/health
```
Wait for the state to be `Running`. `/health` should show `"nebius_key_set": true` and
`"tavily_key_set": true`. Then open `$URL` in a browser, in a private window, and:
1. See the demo banner and the sample promises.
2. Paste a note and click **Find promises** (this proves it can reach Token Factory).
3. Click **Research and draft** (this proves Tavily works).
4. Click **Have an access code?** and enter your code.
5. Open the **Perimeter** panel and confirm only Nebius and Tavily appear.

## Cost and housekeeping (verified)
- You are billed while it runs; a stopped endpoint is not billed for compute.
  ```bash
  nebius ai endpoint stop --id $ENDPOINT_ID
  nebius ai endpoint start --id $ENDPOINT_ID
  ```
- **There is no documented in-place update.** To ship a new version: push a new image tag, create a new
  endpoint, check it, then delete the old one with `nebius ai endpoint delete --id <id>`. The URL
  belongs to the endpoint, so **it will change**. Decide your final URL before putting it in the
  submission, and don't recreate the endpoint afterwards.
- Logs: the docs I read don't show a log command (**check `nebius ai endpoint --help`**).

## Judge testing notes (paste into the submission)
> Open the demo URL. No sign-in. Each visitor gets a private workspace with sample promises, and
> email sending is turned off. Usage is capped; to lift the limits click "Have an access code?" in the
> banner and enter: `<your code>`. To see Kept send real email and remember people across sessions,
> run it locally (README, "Run it yourself").

## If something goes wrong
| Symptom | Likely cause |
|---|---|
| Endpoint restarts or shows an `exec format error` | The image was built for ARM. Rebuild with `--platform linux/amd64` |
| `/health` shows `nebius_key_set: false` | The `--env` keys were missing or misspelled |
| Page loads but "Find promises" errors | Check the Token Factory key and credits |
| "The demo is busy right now" | Workspace creation is rate limited. If every visitor looks like one address (the proxy's), raise the limit or set `FORWARDED_ALLOW_IPS` after confirming the proxy overwrites client-supplied `X-Forwarded-For` |

## Optional: the nightly sweep as a Serverless Job
`kept sweep` is built for this (`--container-command` / `--args` on `nebius ai job create`, **check
`--help`**). A Job's disk is temporary, so it can only act on a database it can reach (a mounted volume),
not on the demo's in-memory workspaces. Treat this as an extra for a personal, persistent install.

## Option C: Hugging Face Space (paid)

`deploy/huggingface/Dockerfile` and `README.md` make a two-file Space that clones this repo and starts in
demo mode. Hugging Face now requires PRO for Docker Spaces, so it is kept only as a fallback. Upload both
files, add the same three secrets, and open the direct `https://<user>-kept.hf.space` address (the
huggingface.co page iframes the app and blocks the session cookie).
