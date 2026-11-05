# The Invisible Classroom — Requirements

**Version:** 1.0 | **Status:** Kiro implementation specification | **Priority:** P0 MVP, P1 stretch, P2 future

## Vision and scope
Turn household objects into safe, age-appropriate, interactive learning adventures for underserved learners. An adult facilitator enters an age band, learning subject and available objects. Strands SDK specialists identify learning opportunities, plan a curriculum objective, create a three-activity story, evaluate responses and adapt the next challenge. The MVP is text-first, adult-mediated and does not require child accounts.

**Users:** adult facilitator, learner aged approximately 6–12, hackathon judge in synthetic demo mode. **MVP:** English, arithmetic/counting and introductory measurement, manually entered objects, three activities, one baseline and one end check. **Out of scope:** direct child accounts, face recognition, live video, offline AI generation, educational diagnosis, formal certification, unrestricted web access.

## Requirements (EARS acceptance criteria)

### R-01 Session configuration [P0]
**User story:** As a facilitator, I want to start without registering a child, so learning is accessible and private.
1. WHEN the start page loads, THE SYSTEM SHALL show age band (6–8, 9–10, 11–12), subject, objects, and a demo preset.
2. WHEN valid fields are submitted, THE SYSTEM SHALL create a random opaque session ID.
3. IF required fields are invalid, THE SYSTEM SHALL show field-level errors and SHALL NOT invoke the model.
4. THE SYSTEM SHALL NOT request a child's name, birthday, address, school or email.

### R-02 Grounding in local resources [P0]
**User story:** As a facilitator, I want lessons based only on objects we possess.
1. WHEN objects are entered, THE SYSTEM SHALL normalize and deduplicate a bounded list while preserving the original text.
2. IF an object is ambiguous, THE SYSTEM SHALL request clarification or visibly label a safe assumption.
3. WHEN an object is unsuitable or hazardous, THE SYSTEM SHALL exclude hazardous uses and suggest a safe substitute.
4. THE SYSTEM SHALL NOT require purchased supplies or paid services.

### R-03 Lesson generation [P0]
**User story:** As a learner, I want a short adventure with hands-on challenges.
1. WHEN inputs are valid, THE SYSTEM SHALL generate a lesson title, learning objective, object list, setup, three ordered activities, expected answers/rubrics, hints and estimated duration of 5–10 minutes.
2. EACH activity SHALL contain short learner instructions and separate facilitator notes.
3. THE SYSTEM SHALL restrict concepts and vocabulary to the selected age band and subject.
4. IF the output fails typed schema, safety, or object-grounding validation, THE SYSTEM SHALL retry at most twice and then use a clearly labeled safe template or report failure.

### R-04 Genuine Strands multi-agent execution [P0]
**User story:** As a judge, I want evidence that specialist agents actually collaborate.
1. WHEN a lesson is requested, THE SYSTEM SHALL invoke Environment, Curriculum and Storytelling specialists under a Strands orchestrator.
2. WHEN an answer is submitted, THE SYSTEM SHALL invoke an Assessment specialist for rubric-based feedback where deterministic grading is insufficient.
3. THE SYSTEM SHALL validate each specialist output against a versioned typed contract.
4. THE SYSTEM SHALL cap orchestration depth, specialist calls, duration, retries and model usage.
5. THE SYSTEM SHALL expose sanitized agent-stage status without exposing prompts, credentials, or raw personal data.

### R-05 Activity interaction [P0]
**User story:** As a learner, I want to solve one challenge at a time.
1. WHEN a lesson is ready, THE SYSTEM SHALL show the first activity and progress indicator.
2. WHEN an answer is submitted, THE SYSTEM SHALL validate it and prevent duplicate mutations.
3. WHEN a hint is requested, THE SYSTEM SHALL offer a scaffold rather than immediately reveal the answer.
4. WHEN an activity is completed or skipped, THE SYSTEM SHALL advance and persist its status.
5. WHEN the final activity ends, THE SYSTEM SHALL show practiced concepts and suggested next steps.

### R-06 Assessment and adaptation [P0]
**User story:** As a facilitator, I want helpful feedback that adjusts to the learner.
1. WHEN an answer arrives, THE SYSTEM SHALL return `correct`, `partially_correct`, `needs_support` or `unassessable`, with a short explanation.
2. WHEN a misconception is detected, THE SYSTEM SHALL adjust the next activity's scaffolding or difficulty while preserving the objective.
3. IF an answer is ambiguous, THE SYSTEM SHALL request clarification instead of confidently marking it incorrect.
4. THE SYSTEM SHALL use deterministic checks for exact arithmetic and model-assisted assessment only where needed.
5. THE SYSTEM SHALL describe mastery estimates as provisional and SHALL NOT diagnose learning difficulties.

### R-07 Baseline and end checks [P0]
**User story:** As a facilitator, I want a simple indicator of progress.
1. WHEN a lesson begins, THE SYSTEM SHALL offer a short objective-aligned baseline question.
2. WHEN the lesson ends, THE SYSTEM SHALL offer a comparable, nonidentical end question.
3. WHEN both are answered, THE SYSTEM SHALL show the observed difference and a warning that this is not a validated educational assessment.
4. IF either is skipped, THE SYSTEM SHALL NOT claim improvement.

### R-08 Safety and adult control [P0]
**User story:** As a facilitator, I need to supervise and stop any activity.
1. BEFORE a generated lesson is displayed, THE SYSTEM SHALL enforce safety, age-appropriateness and object-grounding checks.
2. THE SYSTEM SHALL reject activities involving ingestion, sharp objects, fire, electricity, hazardous chemicals, heights, strangers or dangerous water.
3. WHEN Stop is selected, THE SYSTEM SHALL prevent further submissions and cancel pending work where supported.
4. THE SYSTEM SHALL display an adult-supervision notice and SHALL NOT encourage secrecy or emotional dependency.
5. IF input includes identifying personal information, THE SYSTEM SHALL minimize/redact it before model calls where feasible and warn the facilitator.

### R-09 Accessibility [P0]
**User story:** As a facilitator, I want inclusive, easy-to-use learning experiences.
1. THE SYSTEM SHALL support keyboard navigation, visible focus, semantic labels, adequate contrast and mobile screens at least 320px wide.
2. THE SYSTEM SHALL use concise plain-language instructions and no timed answers.
3. WHEN activities depend on color, sound or fine motor skills, THE SYSTEM SHALL offer an alternative.
4. THE SYSTEM SHALL NOT penalize spelling when spelling is not the learning objective.

### R-10 Session privacy [P0]
**User story:** As a facilitator, I want short-term progress without permanent child profiling.
1. THE SYSTEM SHALL store only age band, subject, object list, lesson, answers, progress and necessary operational metadata under a pseudonymous session ID.
2. THE SYSTEM SHALL NOT create cross-session child profiles or log raw child answers by default.
3. WHEN a session is ended, THE SYSTEM SHALL provide a delete action; persisted sessions SHALL expire within 24 hours using TTL plus an explicit deletion path.
4. IF persistence fails, THE SYSTEM SHALL state that progress could not be saved.

### R-11 Reliability and observability [P0]
**User story:** As a user, I want graceful errors; as a maintainer, I need safe diagnostics.
1. WHEN an AI call fails or times out, THE SYSTEM SHALL offer retry or a safe prebuilt activity.
2. WHEN the same idempotency key is reused, THE SYSTEM SHALL not duplicate lesson generation or answer submission.
3. THE SYSTEM SHALL emit redacted correlation IDs, agent-stage statuses, latency, error categories and usage estimates where available.
4. THE SYSTEM SHALL enforce request-size limits, concurrency caps and rate limits and expose health/readiness endpoints.

### R-12 Reproducible demo [P0]
**User story:** As a judge, I want to understand the solution in under three minutes.
1. WHEN demo mode is selected, THE SYSTEM SHALL load age 6–8, mathematics, five stones, two leaves, a bottle and a bucket.
2. THE SYSTEM SHALL show sanitized stages: understand objects, choose objective, create story, assess answer, adapt next activity.
3. IF Bedrock is unavailable, THE SYSTEM SHALL run a deterministic fallback explicitly labeled `Demo fallback — no live agent execution`.
4. THE REPOSITORY SHALL include setup, architecture, seed data, tests and a sub-three-minute demo script.

### R-13 Image-based object identification [P1]
1. WHEN an image is uploaded, THE SYSTEM SHALL check size, file type and safety before processing.
2. BEFORE generation, THE SYSTEM SHALL ask the facilitator to confirm detected objects.
3. THE SYSTEM SHALL NOT perform identity or sensitive-trait inference and SHALL delete temporary images per retention policy.

### R-14 Hindi-language lessons [P1]
1. WHEN Hindi is selected, THE SYSTEM SHALL produce age-appropriate Hindi instructions with preserved mathematical meaning.
2. IF language checks fail, THE SYSTEM SHALL show a clear English fallback.

### R-15 Future enhancements [P2]
Optional downloadable lesson packs, speech accessibility, facilitator-curated curriculum mappings and group activities without individual tracking. These SHALL NOT block MVP release.

## Nonfunctional requirements
| ID | Requirement | Validation |
|---|---|---|
| NFR-01 | TLS, least-privilege IAM, no secrets in code | IaC review, secret scan |
| NFR-02 | Typed inputs/outputs, bounds and output sanitization | Unit/fuzz tests |
| NFR-03 | WCAG 2.2 AA-oriented UI | axe and keyboard audit |
| NFR-04 | Mobile-first responsive interface | E2E viewport tests |
| NFR-05 | Timeouts, retries, circuit breaking and graceful fallback | Fault-injection tests |
| NFR-06 | Pinned dependencies, SBOM and vulnerability scan | CI checks |
| NFR-07 | Configurable model/region/limits/budgets | Configuration tests |
| NFR-08 | Data minimization, explicit delete and TTL | Privacy integration tests |
| NFR-09 | No unsubstantiated educational efficacy claims | Demo/content review |
| NFR-10 | Prompt-injection defense; model output treated as untrusted | Adversarial tests |

## Measurable MVP acceptance goals
- At least 90% of 30 curated object/age/subject cases pass schema, grounding and safety checks.
- At least 90% of scripted misconception cases lead to relevant scaffolded follow-up.
- At least 95% successful end-to-end completion across 20 controlled tests with configured model access.
- Record p50/p95 latency and estimated cost per session; tune thresholds after baseline measurement rather than inventing guarantees.
- All P0 scenarios and release gates pass, including live multi-agent evidence and labeled fallback.

## Release gates
**G1** Real Strands specialist calls visible in sanitized trace. **G2** Safety, schema and grounding gates pass. **G3** No unresolved critical/high security issues or secrets. **G4** Mobile/keyboard/error flows tested. **G5** Live vs fallback and measured vs illustrative outcomes clearly distinguished.

## Traceability
All implementation tasks and automated tests must cite `R-xx` and applicable `NFR-xx` identifiers. Generate `tasks.md` only after reconciling this file with `design.md`.
