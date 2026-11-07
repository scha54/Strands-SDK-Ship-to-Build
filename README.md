# The Invisible Classroom

A Facilitator (parent, caregiver, community teacher) lists everyday objects, and a team of
Strands Agents SDK specialists turns them into a short, safe, supervised, hands-on lesson for a
child aged 6 to 12. Deterministic Validation_Gates written in plain Python (not in a model)
check every lesson for schema, grounding in the listed objects, safety and readability before a
child sees it.

This is a hackathon prototype. It makes **no claim that it improves learning**. See
[Claims and limits](#claims-and-limits).

Documents:

- [Architecture](docs/architecture.md) - components, flow, data, seed data
- [Demo script](docs/demo-script.md) - timed walkthrough, at most 180 seconds
- [Release gates G1 to G5](docs/release-gates.md) - what each gate means and its evidence
- Specification: [requirements.md](.kiro/specs/invisible-classroom/requirements.md),
  [design.md](.kiro/specs/invisible-classroom/design.md),
  [tasks.md](.kiro/specs/invisible-classroom/tasks.md)

## Repository layout

```
backend/    FastAPI modular monolith, Strands specialists, gates, tests, evaluation harness
frontend/   React + TypeScript SPA (Vite), Vitest unit tests, Playwright E2E and accessibility
docs/       Architecture, demo script, release gates
.github/    CI workflow (lint, typecheck, tests, secret scan, dependency scan, SBOM, build)
```

## Prerequisites

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer and npm
- No AWS account is needed for any step below. Everything here runs on the deterministic stub
  model. Live Bedrock is opt-in (see [Live mode](#live-mode-bedrock)).

## Setup (clean checkout)

```powershell
# Backend
cd backend
uv sync --frozen

# Frontend (second terminal)
cd frontend
npm ci
npx playwright install chromium   # only needed for the E2E and accessibility suites
```

## Start Demo_Mode (all five stages)

Demo_Mode loads the seed preset with no input and no image, then runs five stages: understand
objects, choose objective, create story, assess answer, adapt next activity.

1. Start the API on the stub model:

   ```powershell
   cd backend
   $env:IC_USE_STUB_MODEL = "true"
   uv run uvicorn app.main:create_app --factory --port 8000
   ```

2. Create the Demo_Mode session and read its stages (second terminal):

   ```powershell
   $s = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/demo/session
   $h = @{ Authorization = "Bearer $($s.capability_token)" }
   Invoke-RestMethod -Headers $h "http://127.0.0.1:8000$($s.events_url)" | ConvertTo-Json -Depth 5
   ```

   The response `state` is `ready` and `events` lists a `started` and `completed` event for each
   of the five stages, in order. The run is identical on every start because the inputs come from
   the seed file and the stub model is deterministic. If the first read still shows `generating`,
   repeat the second command.

3. Optional, to see the screens (the stub-backed screen used by the E2E suite). In two more
   terminals:

   ```powershell
   cd backend;  uv run uvicorn tests.e2e_server:app --port 8765      # stub API
   cd frontend; npm run dev                                          # Vite on :5173
   ```

   Open `http://localhost:5173/harness.html?screen=live&backend=ok`, press **Fill Demo Mode
   preset**, then **Start session**. The five-stage timeline and the learning loop run against the stub
   API. `backend=fail` uses an API whose model always fails, to show the error flow. The
   production entry point `index.html` is still a minimal shell; the full screens are wired in
   this harness page.

### Live vs fallback execution

| Mode | How it is triggered | What the UI and API show |
|---|---|---|
| Stub (default here) | `IC_USE_STUB_MODEL=true` | Stages run the real Orchestrator and gates against a deterministic stub model. This is **not** a Bedrock call. |
| Live | `IC_USE_STUB_MODEL` unset, AWS credentials available | Stages run against Bedrock. Only this mode supports a "real model" statement. |
| Demo_Fallback | Bedrock unavailable, gate failure, or no completion within 10 s | Pre-recorded seed data plays through the same five stages with `source="demo_fallback"` and the label `Demo fallback — no live agent execution`. |

### Live mode (Bedrock)

Unset `IC_USE_STUB_MODEL` and provide AWS credentials through the normal AWS credential chain
(an IAM role in deployment). Set `IC_MODEL_ID` and `IC_AWS_REGION` for your account. No secrets
are stored in the repository. The live path was not exercised in this repository's automated
tests and has no measured results here.

## Configuration

All settings come from environment variables prefixed `IC_` (see `backend/app/config.py`):
model ID and region, orchestration depth (2), specialist calls (8), deadlines (45 s generation,
15 s assessment), retries, token budget (20,000), request size (1 MB), concurrency (50), rate
limit (60 per minute), session TTL (24 h), and the Demo_Fallback trigger (10 s).

## Seed data

`backend/app/templates/demo_seed/demo_seed.json` is the single source of truth for Demo_Mode:

- Age_Band `6-8`, Subject `arithmetic_counting` (shown as "mathematics")
- Exactly seven Objects: `Stone 1` to `Stone 5` and `Leaf 1`, `Leaf 2`. The names are numbered
  because the normalizer removes case-insensitive duplicates, so five identical "stone" lines
  would collapse to one.
- A scripted learner answer, the five pre-recorded stages, a recorded Assessment, and a
  pre-recorded three-Activity Lesson used by Demo_Fallback

The frontend preset in `frontend/src/features/setup/demoPreset.ts` mirrors it, and a test reads
the seed file and fails on any drift. All seed content is synthetic and contains no learner data.

## Tests

```powershell
# Backend: unit, property (Hypothesis), API, docs check
cd backend
uv run pytest
uv run ruff check . ; uv run ruff format --check . ; uv run mypy

# Frontend: unit and property (Vitest, fast-check)
cd frontend
npm test
npm run typecheck ; npm run lint

# Browser: Playwright E2E and accessibility (axe, keyboard-only, 320 px)
npm run test:e2e
```

`npm run test:e2e` starts the Vite server and two stub API servers itself. It covers the full
flow (demo preset, baseline, wrong answer, hint, adapted challenge, end check, summary, delete)
and the model-failure, Stop and expired-session flows. It never calls AWS.

### Evaluation harness

```powershell
cd backend
uv run python -m app.evaluation                 # stubbed suite, prints a summary
uv run python -m app.evaluation --out report.json
$env:IC_EVAL_LIVE = "1"; uv run python -m app.evaluation --live   # opt-in live run
```

The stubbed suite runs 69 synthetic cases (36 lessons, 10 scripted-misconception scaffold cases,
23 adversarial prompt-injection and compromised-output cases) through the real Orchestrator and
gates. It reports schema, grounding and safety pass rates, scaffold relevance, adversarial gate
bypasses (must be 0), and latency and cost.

**Measured vs illustrative.** Pass rates and the bypass count are measured over the synthetic
cases against the stub model, so they show the gates behave as coded, not that a real model
produces safe lessons. **Latency (p50/p95) and the estimated cost per session from the stubbed
run are illustrative**: the stub answers in about a millisecond, and cost is tokens multiplied by
a configurable placeholder rate. They are not Bedrock measurements. Live results, when run, are
reported under a separate `LIVE` label.

## Security and supply chain

CI (`.github/workflows/ci.yml`) runs, in order: Ruff and mypy, tests, gitleaks secret scan,
`pip-audit`, CycloneDX SBOM generation, and build. Dependencies are pinned and locked
(`uv.lock`, `package-lock.json`).

## Claims and limits

- The system is a facilitator-supervised aid. It is not a diagnostic or validated assessment
  tool, and mastery figures are labeled "provisional".
- The baseline and end-of-lesson confidence check is for observation only and is shown with a
  not-validated warning. No educational efficacy is claimed or evidenced.
- Image upload and Hindi (P1) and P2 items are not implemented in the default build.
