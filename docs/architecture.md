# Architecture

Full detail is in [design.md](../.kiro/specs/invisible-classroom/design.md). This page is the
short orientation.

## Shape

One deployable FastAPI backend (modular monolith) and a React/TypeScript SPA.

```
Web_UI (React) --HTTPS--> FastAPI
                           |- middleware: body size, concurrency, rate limit, correlation ID
                           |- routes: sessions, lessons/events, learning loop, demo
                           |- services: session, lesson, assessment, learning loop, demo
                           |- Validation_Gates (plain Python): schema, grounding, safety,
                           |    age vocabulary, readability, PII redaction
                           |- Orchestrator (Strands) --> Environment, Curriculum,
                           |    Storytelling, Assessment specialists --> Bedrock adapter
                           '- Session_Store: in-memory (local) or DynamoDB with TTL
```

## Key decisions

- **Gates are code, not models.** Model output is untrusted. Safety, grounding and arithmetic
  checks are deterministic and run after every generation; one failing Activity rejects the whole
  Lesson. Failures retry up to twice, then fall back to a labeled Safe_Template.
- **Typed handoffs.** Each specialist returns a versioned Pydantic Specialist_Contract. The
  Orchestrator validates it, records the contract version in a sanitized Stage_Event and
  persists nothing on failure.
- **Budgets.** `RequestBudget` bounds depth (2), specialist calls (8), tokens (20,000) and
  deadlines (45 s generation, 15 s assessment).
- **Deterministic grading first.** Integer, decimal and exact answers are graded without a
  model; the Assessment_Specialist is called only when no deterministic verdict exists.
- **Capability access, minimal data.** A random Session_ID and a Capability_Token (only its hash
  is stored). No child name, birthday, address, school or email is accepted. Sessions expire after
  24 hours and can be stopped, ended or deleted at any time.
- **Stub by default.** `IC_USE_STUB_MODEL=true` swaps Bedrock for a deterministic stub so all
  tests and the demo run offline.

## Demo_Mode

`POST /api/v1/demo/session` loads the seed, creates the Session with zero model calls and runs
the five stages after the response (`GET /sessions/{id}/events` reports progress). The stages
are mapped from Stage_Events: understand objects, choose objective, create story, assess answer,
adapt next activity. If the live run fails the gates, errors, or does not finish within 10 s,
the pre-recorded seed plays through the same five stages and the Lesson carries
`source="demo_fallback"` with the label `Demo fallback — no live agent execution`.

## Seed data

See [README: Seed data](../README.md#seed-data). The file is
`backend/app/templates/demo_seed/demo_seed.json`.

## Observability and privacy

Each request produces a redacted diagnostic record (correlation ID, stage statuses, latency in
ms, error category, usage estimate). Prompts, reasoning, credentials, personal data and learner
free text are excluded from logs and from the stage display.

## Not in the default build

Image analysis (R-13) and Hindi (R-14) are P1 and feature-flagged off. P2 items (R-15) are not
scheduled.
