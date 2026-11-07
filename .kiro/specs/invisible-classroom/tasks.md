# Implementation Plan: The Invisible Classroom

## Overview

Implementation follows the design's sequence: foundation, sessions, Strands specialists/orchestration/Bedrock adapter, safety/grounding/fallback, learning loop, demo hardening, then P1 stretch (image, Hindi) as optional work. The backend is Python (FastAPI, Pydantic v2, Strands Agents SDK, Hypothesis, pytest). The frontend is React/TypeScript (Vitest, fast-check, Playwright).

Conventions:
- Every task cites R-xx (Requirement numbers in `requirements.md`) and NFR-xx ids. Every automated test must also cite them in a docstring or comment (Traceability 1).
- Each task states a **Done when** condition that can be checked by a test or command.
- Property tests use Hypothesis (backend) or fast-check (frontend), run at least 100 iterations, use deterministic model stubs, and carry the tag `Feature: invisible-classroom, Property {n}: {text}`.
- P1 (R-13, R-14) tasks are in section 12, all optional, behind feature flags that default to off. P2 (R-15) items are not implemented. No P0 task depends on any P1 task.
- The Demo_Mode preset is Age_Band 6-8, mathematics (mapped to the `arithmetic_counting` Subject), and exactly seven Objects: five stones and two leaves (R-12.1). The seed file is the single source of truth.
- The `STOPPED` state and `POST /sessions/{id}/stop` are P0 (R-08.3).

## Tasks

- [x] 1. Foundation: repository, typed contracts, configuration, CI
  - [x] 1.1 Scaffold backend, repository layout and CI pipeline
    - Create `backend/app/` module layout from the design, `pyproject.toml` with pinned dependencies, lockfile, Ruff, mypy, pytest, Hypothesis
    - Create typed configuration for model ID, region, limits (depth 2, 8 calls, 45 s/15 s, 2 retries, 20,000 tokens, 1 MB, 50 concurrent, 60/min, 24 h) and budgets, loaded from environment with no secrets in code
    - Add CI workflow order: lint/typecheck, unit/property tests, secret scan, dependency vulnerability scan, SBOM generation, build
    - **Done when:** `pytest`, `ruff`, `mypy` pass on the empty scaffold; a config test shows every default limit is overridable by environment; CI file lists the scan and SBOM steps
    - _Requirements: R-11.4, R-04.4; NFR-01, NFR-02, NFR-06, NFR-07_

  - [x] 1.2 Implement domain models and Specialist_Contracts
    - Implement `AgeBand`, `Subject`, `AssessmentStatus`, `CreateSessionRequest` (`extra="forbid"`), `ObjectItem`, `ObjectInventory`, `Activity`, `Question`, `Lesson`, `Assessment`, `AnswerRequest`, `GateResult`, `Grade`, `AgentStageEvent`, `SessionSummary`, `ApiError` with the design's bounds
    - Add versioned `EnvironmentOutput`, `CurriculumPlan`, `StoryDraft`, `AssessmentOutput` each carrying `contract_version`
    - Add validators: three Activities, unique Activity IDs, `required_objects` subset of inventory, Lesson `objects` subset of submitted inputs
    - **Done when:** unit tests show bound violations and extra identity fields (name, birthday, address, school, email) fail validation and valid examples pass
    - _Requirements: R-01.4, R-03.1, R-03.2, R-04.3, R-06.1; NFR-02_

  - [x] 1.3 Scaffold frontend and typed API client
    - Create `frontend/src/{app,api,components,features,types}/` with Vite, TypeScript strict, ESLint, Vitest, fast-check
    - Generate TypeScript types from the FastAPI OpenAPI schema with an npm script; add a mobile-first base layout with a 320 px reflow-safe stylesheet and a shared supervision-notice component
    - **Done when:** `tsc`, ESLint and Vitest pass; the type generation script produces types from the backend schema; the notice component renders in a unit test
    - _Requirements: R-08.4, R-09.5; NFR-03, NFR-04_

  - [ ]* 1.4 Write property test for Lesson schema bounds
    - **Property 4: Lesson schema bounds are enforced**
    - **Validates: Requirements R-03.1, R-03.2**

- [x] 2. Sessions: normalization, state, store, authorization, limits, setup UI
  - [x] 2.1 Implement object normalizer
    - Trim, collapse whitespace, case-insensitive dedupe, keep first original text, enforce 1 to 20 unique and 50 chars, return which limit was violated
    - **Done when:** unit tests cover whitespace, case duplicates, zero objects, 21 unique objects and 51-char names with the correct limit named
    - _Requirements: R-02.1, R-02.2; NFR-02_

  - [ ]* 2.2 Write property test for object normalization
    - **Property 3: Object normalization is canonical and lossless**
    - **Validates: Requirements R-02.1**

  - [x] 2.3 Implement session state machine
    - Implement legal transitions from the design including `STOPPED`, `FAILED`, `ENDED`, `COMPLETED`, `DELETED`; Stop reachable from every non-terminal state; after Stop only read and delete are permitted
    - **Done when:** unit tests assert every illegal transition raises an invalid-state error and writes after STOPPED return a stopped-session error code
    - _Requirements: R-08.3, R-10.4; NFR-05_

  - [ ]* 2.4 Write property test for state machine transitions
    - **Property 20: State machine permits only legal transitions**
    - **Validates: Requirements R-08.3**

  - [x] 2.5 Implement Session_Store (in-memory and DynamoDB)
    - Implement `create`, `get`, `put_if_version`, `delete` for both backends; store only permitted attributes (Age_Band, Subject, Objects, Lesson, answers, progress, timestamps, token hash, version, idempotency records); set `expires_at = updated_at + 24 h` on every persist; `get` raises NotFound or Expired using the injected clock before TTL removal; generate IDs with `secrets.token_urlsafe(32)`
    - **Done when:** contract tests run against the in-memory store and local DynamoDB; a stale `version` write fails; an expired record is rejected without TTL removal; the stored item has no attributes outside the allowed list
    - _Requirements: R-01.2, R-10.1, R-10.2, R-10.5, R-10.6, R-10.7, R-10.8; NFR-08_

  - [ ]* 2.6 Write property test for expiry enforcement
    - **Property 25: Expiry is enforced on read**
    - **Validates: Requirements R-10.7, R-10.8**

  - [x] 2.7 Implement idempotency service
    - Compute payload hash; same key and hash within 24 h returns the stored result; same key with a different hash returns `idempotency_key_conflict`; the record is written in the same conditional write as the state change
    - **Done when:** unit tests show repeat calls apply the mutation once, a conflicting payload returns 409 with stored results unchanged, and a key older than 24 h is treated as new
    - _Requirements: R-05.3, R-11.2, R-11.7; NFR-05_

  - [ ]* 2.8 Write property test for idempotency
    - **Property 12: Mutations are idempotent within the window**
    - **Validates: Requirements R-05.3, R-11.2, R-11.7**

  - [x] 2.9 Implement API middleware, error mapping and health endpoints
    - Body-size (1 MB), concurrency cap (50), per-client rate limit (60/min), correlation ID, `ApiError` mapping (404, 409, 410, 413, 422, 429, 503) that names the limit exceeded; reject in middleware before any handler
    - Add `/healthz` (no external calls, within 500 ms) and `/readyz` (within 2 s, names unavailable dependencies)
    - **Done when:** API tests show each limit returns the right status and names the limit, with no store writes; `/healthz` returns 200 when the store is down; `/readyz` returns 503 naming the dependency
    - _Requirements: R-11.4, R-11.5, R-11.6; NFR-02, NFR-05_

  - [ ]* 2.10 Write property test for request limits
    - **Property 26: Request limits reject without side effects**
    - **Validates: Requirements R-11.4**

  - [x] 2.11 Implement session service, capability auth and session routes
    - `POST /sessions` (validate, normalize, create, return Session_ID and Capability_Token within 2 s, store only the token hash, zero model calls, no partial Session on failure), `GET /sessions/{id}`, `POST /sessions/{id}/stop` (within 2 s, rejects later answers/hints/advance, keeps data readable), `POST /sessions/{id}/end`, `DELETE /sessions/{id}` (confirm within 2 s); constant-time token comparison; 422 lists every invalid field
    - **Done when:** API tests cover valid creation, each invalid field, extra identity fields, wrong token, read/delete after delete (404), read after expiry (410), Stop then answer (409 stopped-session), and failed creation leaving no record
    - _Requirements: R-01.2, R-01.3, R-01.4, R-01.6, R-08.3, R-10.4, R-10.5, R-10.6, R-10.8; NFR-01, NFR-02, NFR-08_

  - [ ]* 2.12 Write property test for Session_ID uniqueness
    - **Property 1: Session identifiers are unique and input-independent**
    - **Validates: Requirements R-01.2**

  - [ ]* 2.13 Write property test for invalid input rejection
    - **Property 2: Invalid input is rejected with no side effects**
    - **Validates: Requirements R-01.3, R-01.4, R-02.2**

  - [ ]* 2.14 Write property test for deletion
    - **Property 24: Deleted sessions are gone**
    - **Validates: Requirements R-10.5, R-10.6**

  - [x] 2.15 Build the setup feature in the Web_UI
    - Single-select Age_Band (6-8, 9-10, 11-12, none preselected), Subject selector (none preselected), Objects entry (1 to 20, 1 to 50 chars), Demo_Mode preset button that fills fields and keeps them editable, per-field errors that retain entered values, "Session could not be started" error with resubmit, no child identity fields
    - **Done when:** component tests assert the initial control state, per-field errors with retained values, preset fill and editability, and the failure message with resubmission
    - _Requirements: R-01.1, R-01.3, R-01.5, R-01.6, R-02.2, R-09.3; NFR-03, NFR-04_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Strands specialists, orchestrator and Bedrock adapter
  - [x] 4.1 Implement RequestBudget and Stage_Event emitter
    - `RequestBudget.consume()` tracks depth, calls, tokens and deadline and raises `LimitReached(limit_name)`; emitter writes sanitized `{stage, specialist, status, contract_version?, timestamp}` events available within 1 second and never includes prompts, reasoning, credentials or internal IDs
    - **Done when:** unit tests show each limit raises with its name, and an event serialization test finds no prompt or identifier fields
    - _Requirements: R-04.4, R-04.5, R-04.7, R-12.3; NFR-05, NFR-07_

  - [ ]* 4.2 Write property test for request budgets
    - **Property 10: Request budgets are never exceeded**
    - **Validates: Requirements R-04.4, R-04.7**

  - [ ]* 4.3 Write property test for Stage_Event well-formedness
    - **Property 11: Stage events are well-formed and sanitized**
    - **Validates: Requirements R-04.5, R-12.3**

  - [x] 4.4 Implement Bedrock adapter and the four Strands specialists
    - Bedrock client wrapper with model ID and region from config, timeouts, bounded retries and circuit breaker; deterministic stub model for tests and local mode; Environment, Curriculum, Storytelling and Assessment specialists using Strands structured output into their Specialist_Contracts; specialists receive no shell, browser or write tools; object text and answers are passed as data in narrow prompts
    - **Done when:** each specialist returns its contract type from the stub model; a malformed stub response raises a contract error; the circuit breaker opens after repeated stub failures
    - _Requirements: R-04.1, R-04.3; NFR-05, NFR-07, NFR-10_

  - [x] 4.5 Implement the Orchestrator
    - `generate_lesson` invokes Environment, Curriculum and Storytelling in order; `assess` invokes the Assessment_Specialist; validate each output against its contract and record the contract version in the Stage_Event; retry a failing specialist up to the retry limit, then return an error naming the specialist and persist nothing; on `LimitReached` stop, emit a failed Stage_Event and return an error naming the limit; cancel pending model calls on Stop
    - **Done when:** orchestration tests with stubs assert invocation order and at least one call per specialist, retry counts, the named-specialist error with an empty store, the named-limit error, and cancellation on Stop
    - _Requirements: R-04.1, R-04.2, R-04.3, R-04.5, R-04.6, R-04.7, R-08.3; NFR-05, NFR-10_

  - [ ]* 4.6 Write property test for invalid specialist output
    - **Property 9: Invalid specialist output is never persisted**
    - **Validates: Requirements R-04.3, R-04.6**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Safety, grounding, fallback and lesson generation
  - [x] 6.1 Implement PII detection and redaction
    - Detect names, phone numbers, emails, street addresses, school names and birth dates; redact before any model call and return a warning; when redaction cannot complete, make no model call and return an error asking the Facilitator to remove the PII while leaving other session data unchanged
    - **Done when:** unit tests per PII type show redacted model input plus a warning, and the unredactable case shows zero model calls and unchanged session data
    - _Requirements: R-08.6, R-08.7; NFR-08, NFR-10_

  - [ ]* 6.2 Write property test for PII handling
    - **Property 21: PII never reaches a model**
    - **Validates: Requirements R-08.6, R-08.7**

  - [x] 6.3 Implement grounding gate and ambiguity/hazard handling for Objects
    - Every Activity and Lesson object must be in the inventory with no purchased supplies or paid services; ambiguous Objects get a clarification request or a visible one-sentence assumption of at most 100 characters; hazardous Objects are excluded from all Activities with a safe substitute or alternative use and a Facilitator notice
    - **Done when:** unit tests show an off-inventory item fails the gate, an ambiguous Object carries an assumption of at most 100 characters, and an excluded hazardous Object appears in no Activity and produces a notice
    - _Requirements: R-02.3, R-02.4, R-02.5, R-02.6, R-08.1; NFR-10_

  - [ ]* 6.4 Write property test for grounding
    - **Property 5: Grounding gate matches the inventory**
    - **Validates: Requirements R-02.5, R-02.6, R-03.1**

  - [x] 6.5 Implement safety, age vocabulary, readability and composite Validation_Gates
    - Hazard taxonomy (ingestion, sharp, fire, electricity, hazardous chemicals, heights, strangers, dangerous water), secrecy and emotional-dependence checks, Age_Band/Subject vocabulary rules, readability check (at most 3 sentences, at most 25 words each, grade 6 or lower), schema check; one failing Activity rejects the whole Lesson as a failed attempt; compose into `check_lesson` and `check_activity`
    - **Done when:** unit tests show each hazard category and a secrecy phrase reject the whole Lesson, over-long instructions fail readability, and a clean Lesson passes all gates
    - _Requirements: R-03.3, R-08.1, R-08.2, R-08.5, R-09.6; NFR-02, NFR-10_

  - [ ]* 6.6 Write property test for the safety gate
    - **Property 6: Safety gate rejects the whole Lesson**
    - **Validates: Requirements R-02.4, R-08.1, R-08.2, R-08.5**

  - [ ]* 6.7 Write property test for readability limits
    - **Property 22: Instruction text respects readability limits**
    - **Validates: Requirements R-09.6**

  - [x] 6.8 Implement lesson service, Safe_Templates and lesson/event routes
    - Up to 1 initial attempt plus 2 retries on gate failure; on exhaustion return the labeled Safe_Template for the Age_Band and Subject, or a failure with no Lesson persisted; persist the Lesson with a conditional write (state `GENERATING` to `READY`, `FAILED` on failure); on model error or timeout cancel the call and within 2 s return an error with retry and Safe_Template options while keeping inputs; add curated Safe_Template Lessons for every Age_Band and Subject; add `POST /sessions/{id}/lessons` (idempotent, 202, per-session generation cap) and `GET /sessions/{id}/events`
    - **Done when:** service tests with stubs show at most 3 attempts, template fallback with a visible label, a failure with no stored Lesson when no template exists, a timeout response within 2 s with both options, and a repeated idempotency key not regenerating
    - _Requirements: R-03.1, R-03.4, R-03.5, R-04.5, R-11.1, R-11.2; NFR-05, NFR-10_

  - [ ]* 6.9 Write property test for bounded retry and fallback
    - **Property 7: Bounded retry then safe fallback**
    - **Validates: Requirements R-03.4, R-03.5**

  - [x] 6.10 Implement learner view projector
    - Remove `expected_answer`, `rubric` and `facilitator_note` from learner responses while an Activity has no submitted answer; after an answer, include the expected answer and rubric for that Activity only; serve facilitator notes only via the facilitator view of the same authenticated session; show exactly one Activity and "n of N" progress
    - **Done when:** serialization tests show no leaked fields before an answer and exactly one Activity's answer and rubric afterward
    - _Requirements: R-03.2, R-03.6, R-03.7, R-05.1; NFR-02_

  - [ ]* 6.11 Write property test for learner view projection
    - **Property 8: Learner view never leaks answers early**
    - **Validates: Requirements R-03.2, R-03.6, R-03.7**

  - [x] 6.12 Implement redacted observability
    - Per-request diagnostic record with redacted correlation ID, agent-stage statuses, latency in ms, error category and usage estimate; exclude credentials, personal data and learner free text; add OpenTelemetry spans and metrics for p50/p95 latency and estimated cost per Session
    - **Done when:** log-capture tests find no answer text or credentials in any record and each record has the required fields
    - _Requirements: R-10.3, R-11.3; NFR-01, NFR-08_

  - [ ]* 6.13 Write property test for log privacy
    - **Property 23: Learner free text never appears in logs**
    - **Validates: Requirements R-10.3, R-11.3**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Learning loop: grading, assessment, adaptation, baseline/end checks
  - [x] 8.1 Implement deterministic grader
    - Parse integer/decimal answers and compare deterministically with no model call; text answers use word-level edit distance of at most 2 per word when `spelling_matters` is false; return `None` only when no deterministic verdict exists; return `unassessable` for ambiguous answers
    - **Done when:** unit tests show equal results for repeated inputs, correct marking of 2-edit misspellings, no tolerance when spelling matters, and `None` only for free-form answers
    - _Requirements: R-05.2, R-06.3, R-06.5, R-09.9; NFR-02_

  - [ ]* 8.2 Write property test for deterministic grading
    - **Property 14: Exact answers are graded deterministically**
    - **Validates: Requirements R-05.2, R-06.5**

  - [ ]* 8.3 Write property test for spelling tolerance
    - **Property 18: Spelling tolerance applies only when spelling is not the objective**
    - **Validates: Requirements R-09.9**

  - [x] 8.4 Implement assessment service, clarification and adaptation
    - Grade deterministically first and invoke the Assessment_Specialist only when no verdict exists; return exactly one Assessment_Status with an explanation of at most 300 characters suited to the Age_Band; on misconception keep the objective, change scaffold level or difficulty, pass the adapted Activity through all gates and report the adjustment to the Facilitator; for unassessable answers request clarification, withhold an incorrect mark, and after 2 failed clarifications keep unassessable, offer skip or hint and exclude the answer from mastery estimates; label every mastery estimate "provisional" with no diagnostic language
    - **Done when:** tests show the specialist is not called for deterministically graded answers, explanations are at most 300 characters, adaptation preserves the objective and is reported, the third unclear answer is excluded from estimates, and no output contains diagnostic wording
    - _Requirements: R-04.2, R-06.1, R-06.2, R-06.3, R-06.4, R-06.6; NFR-09, NFR-10_

  - [ ]* 8.5 Write property test for assessment output
    - **Property 15: Assessment output is well-formed**
    - **Validates: Requirements R-06.1, R-06.6**

  - [ ]* 8.6 Write property test for adaptation
    - **Property 16: Adaptation preserves the objective**
    - **Validates: Requirements R-06.2**

  - [ ]* 8.7 Write property test for unclear answers
    - **Property 17: Unclear answers are never marked wrong and are eventually excluded**
    - **Validates: Requirements R-06.3, R-06.4**

  - [x] 8.8 Implement learning-loop routes
    - `POST /baseline` (answer or skip, shown before other content), `POST /answers` (idempotent, rejects empty, over 2,000 chars or wrong format with progress unchanged, result within 2 s for deterministic grading), `POST /hint` (scaffold with no expected-answer text, status unchanged), `POST /advance` (persist completed/skipped then advance; on persist failure keep the current Activity and allow retry), `POST /end-check` (same topic and answer scale, different wording), `GET /summary` (concepts practiced, at least one next step, provisional estimate); all writes rejected after Stop; observed difference only from both answered values
    - **Done when:** API tests cover each route, invalid answers leaving state unchanged, hints without answer text, persist-failure retry, stopped-session rejection, and summary content
    - _Requirements: R-05.2, R-05.3, R-05.4, R-05.5, R-05.6, R-05.7, R-05.8, R-07.1, R-07.2, R-07.6, R-08.3, R-10.9; NFR-02, NFR-05_

  - [ ]* 8.9 Write property test for invalid answers and hints
    - **Property 13: Invalid answers and hints leave progress unchanged**
    - **Validates: Requirements R-05.4, R-05.5**

  - [x] 8.10 Build the learning-loop UI
    - Baseline screen (answer or skip, displayed first), one-Activity view with "n of N", hint, answer, feedback and clarification prompts, no timed input, end-check screen, summary with concepts, next steps and the baseline/end difference rule (shown only when both answered, always with the not-validated warning, never an improvement statement for skipped, zero or negative), Stop, End and Delete controls, supervision notice on every Lesson screen, save-failure message within 2 s with retry and retained on-screen state
    - **Done when:** component tests assert the rules above, including the skipped-baseline flow continuing without data loss, and no timeout on answers
    - _Requirements: R-05.1, R-05.6, R-05.7, R-05.8, R-07.1 to R-07.6, R-08.3, R-08.4, R-09.7, R-10.4, R-10.9; NFR-03, NFR-09_

  - [ ]* 8.11 Write property test for the observed difference display
    - **Property 19: Observed difference is shown only when valid**
    - **Validates: Requirements R-07.3, R-07.4, R-07.5**

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Demo hardening: seed data, fallback, accessibility, evaluation, docs
  - [ ] 10.1 Implement Demo_Mode, seed data and Demo_Fallback
    - Seed file with Age_Band 6-8, mathematics (`arithmetic_counting`), exactly seven Objects (five stones, two leaves); `POST /demo/session` loads it within 3 s with no user input or image; if Bedrock is unavailable or silent for 10 s, play pre-recorded seed data through the same five stages with `source="demo_fallback"` and the label `Demo fallback — no live agent execution`; map Stage_Events onto the five stages (understand objects, choose objective, create story, assess answer, adapt next activity)
    - **Done when:** tests show the preset values, a seven-Object inventory, completion in 3 s with a stub, fallback after a 10 s stub timeout completing all five stages in order with the label, and identical stage order across two runs
    - _Requirements: R-12.1, R-12.2, R-12.4, R-12.6; NFR-05, NFR-09_

  - [ ] 10.2 Build the five-stage timeline UI
    - Show the five sanitized stages in order, each pending, in progress or complete; show the fallback label on every stage screen when in fallback; exclude prompts, reasoning, credentials and internal identifiers; distinguish live from fallback execution (G5)
    - **Done when:** component tests show stage order and states, the label on each stage screen in fallback, and no sensitive fields in the rendered DOM
    - _Requirements: R-12.2, R-12.3, R-12.4; NFR-03, NFR-09_

  - [ ] 10.3 Accessibility pass and alternative paths
    - Keyboard order matching visual order, visible focus indicator with 3:1 contrast, programmatic labels, 4.5:1 / 3:1 text contrast, no horizontal scroll from 320 px; per-Activity alternatives for color, sound or fine-motor dependence with equal scoring; message, progress preservation and Facilitator notice when no alternative exists
    - **Done when:** axe checks show no violations on setup, timeline, activity and summary screens; keyboard-only and 320 px Playwright runs pass; a test shows equivalent answers via an alternative receive the same score and status, and the no-alternative case preserves progress and notifies the Facilitator
    - _Requirements: R-09.1 to R-09.5, R-09.8, R-09.10; NFR-03, NFR-04_

  - [ ] 10.4 Add end-to-end tests and the evaluation harness
    - Playwright flow: demo preset, baseline, wrong answer, hint, adapted challenge, end check, summary, delete; error-flow tests (model failure, Stop, expired session); evaluation script over at least 30 synthetic cases (schema, grounding, safety pass rates, scaffold relevance for scripted misconceptions), recording p50/p95 latency and estimated cost per Session; adversarial prompt-injection cases; live-model run is opt-in and its results are labeled separately from stubbed results
    - **Done when:** the E2E suite passes against the stub backend; the harness outputs pass rates and latency/cost figures; adversarial cases produce no gate bypass
    - _Requirements: R-12.2, R-12.6; NFR-03, NFR-04, NFR-05, NFR-09, NFR-10_

  - [ ] 10.5 Write repository documentation and demo script
    - README setup instructions, architecture documentation, seed data description, test instructions, and a demo script whose timed walkthrough is at most 180 seconds; document the release gates G1 to G5 and clearly mark measured versus illustrative outcomes and live versus fallback execution; no unsubstantiated efficacy claims
    - **Done when:** a docs check test confirms the files exist, the script lists timed steps totalling at most 180 seconds, and following the setup on a clean checkout starts Demo_Mode through all five stages
    - _Requirements: R-12.5, R-12.6; NFR-06, NFR-09_

- [ ] 11. Checkpoint - Ensure all tests pass (P0 complete)
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. P1 stretch (optional, feature-flagged off by default, off the P0 critical path)
  - [ ]* 12.1 Implement the image analysis adapter
    - Validate JPEG or PNG at most 5 MB before analysis; reject bad images with a reason and leave data unchanged; return at most 20 detected Objects within 15 s; on none, failure or timeout show a message and offer manual entry; never infer identity or sensitive traits of any person; block lesson generation until at least one Object is confirmed; delete the image on confirmation, session end, or 24 h, whichever is first
    - **Done when:** tests show validation outcomes, the 15 s timeout fallback, no generation without a confirmed Object, and image deletion on each trigger
    - _Requirements: R-13.1 to R-13.8; NFR-08, NFR-10_

  - [ ]* 12.2 Write property test for image validation
    - **Property 27: Image validation (P1)**
    - **Validates: Requirements R-13.1, R-13.2**

  - [ ]* 12.3 Implement the Hindi adapter and language check
    - Generate Devanagari learner instructions within the English length limits; language check (script, preserved numbers, units and Object names, no empty instruction) within 5 s; on failure or timeout show the English Lesson with a notice, keep the Session and progress, never show unchecked Hindi, and allow retry without a new Session
    - **Done when:** tests show a passing and a failing check, the 5 s timeout path, identical expected answers in both languages, and a repeatable retry
    - _Requirements: R-14.1 to R-14.6; NFR-02_

  - [ ]* 12.4 Write property test for the Hindi language check
    - **Property 28: Hindi language check (P1)**
    - **Validates: Requirements R-14.3, R-14.4, R-14.5**

  - [ ]* 12.5 Add flagged image and Hindi controls to the Web_UI
    - Upload control with per-Object confirm, edit and remove, a language selector, the Hindi-unavailable notice and retry action; controls hidden when the flags are off
    - **Done when:** component tests show the controls absent with flags off and the P0 test suite passing unchanged with flags on
    - _Requirements: R-13.5, R-13.6, R-14.5, R-14.6, R-15.3; NFR-03_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. All P1 tasks (section 12) are optional.
- Property tests cover Properties 1 to 28 from the design, one task per property.
- P2 items (R-15: downloadable packs, speech accessibility, curriculum mappings, group activities) are intentionally not scheduled.
- Release gates G1 to G5 are verified by tasks 6.12, 6.5, 10.3, 10.4 and 10.1/10.2 respectively and by the final checkpoint.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "2.1", "2.3", "2.9", "4.1"] },
    { "id": 3, "tasks": ["2.2", "2.4", "2.5", "2.7", "2.10", "4.2", "4.3", "4.4", "6.1", "6.3", "6.5", "8.1"] },
    { "id": 4, "tasks": ["2.6", "2.8", "2.11", "4.5", "6.2", "6.4", "6.6", "6.7", "6.10", "6.12", "8.2", "8.3"] },
    { "id": 5, "tasks": ["2.12", "2.13", "2.14", "2.15", "4.6", "6.8", "6.11", "6.13", "8.4"] },
    { "id": 6, "tasks": ["6.9", "8.5", "8.6", "8.7", "8.8", "10.1"] },
    { "id": 7, "tasks": ["8.9", "8.10"] },
    { "id": 8, "tasks": ["8.11", "10.2", "12.1", "12.3"] },
    { "id": 9, "tasks": ["10.3", "10.4", "12.2", "12.4"] },
    { "id": 10, "tasks": ["10.5", "12.5"] }
  ]
}
```
