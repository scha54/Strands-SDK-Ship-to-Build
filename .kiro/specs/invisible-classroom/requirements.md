# Requirements Document

## Introduction

The Invisible Classroom turns household objects into safe, age-appropriate, interactive learning adventures for underserved learners. An adult Facilitator enters an Age_Band, a Subject and the available Objects. Specialist agents built with the Strands Agents SDK identify learning opportunities, plan a curriculum objective, create a three-activity story, evaluate responses and adapt the next challenge. The MVP is text-first, adult-mediated and does not require child accounts.

Priorities: P0 is the MVP, P1 is stretch, P2 is future. Requirement IDs (R-xx) and non-functional IDs (NFR-xx) are carried over from the source requirements document and are used for traceability. The companion `design.md` in the workspace root is context for the later design phase.

**Users:** Facilitator, Learner (aged approximately 6 to 12), and Judge (a hackathon reviewer using synthetic demo mode).

**MVP scope:** English, arithmetic/counting and introductory measurement, manually entered objects, three activities, one baseline question and one end question.

**Out of scope:** direct child accounts, face recognition, live video, offline AI generation, educational diagnosis, formal certification, unrestricted web access.

## Glossary

- **System**: The Invisible Classroom application, including the web UI, API, agents and session store.
- **Web_UI**: The React/TypeScript frontend used by the Facilitator and Learner.
- **API**: The FastAPI backend exposing the `/api/v1` endpoints.
- **Facilitator**: The adult who configures sessions, supervises activities and may stop or delete a session.
- **Learner**: The child, aged approximately 6 to 12, who solves activities with adult mediation.
- **Judge**: A hackathon reviewer evaluating the System in demo mode.
- **Session**: A short-lived, pseudonymous record of one learning interaction, identified by a random opaque Session_ID.
- **Session_ID**: A random opaque identifier for a Session.
- **Age_Band**: One of 6-8, 9-10 or 11-12.
- **Subject**: A learning subject; in the MVP, arithmetic/counting or introductory measurement.
- **Object**: A household item entered by the Facilitator and available for use in activities.
- **Object_Inventory**: The normalized, deduplicated, bounded list of Objects with preserved original text.
- **Lesson**: A generated unit containing a title, learning objective, object list, setup, three ordered Activities, a baseline question, an end question, hints, rubrics and an estimated duration.
- **Activity**: One challenge with learner instructions, separate facilitator notes, expected answer, rubric, hint and difficulty.
- **Baseline_Question**: The objective-aligned question offered at the start of a Lesson.
- **End_Question**: The comparable, nonidentical question offered at the end of a Lesson.
- **Orchestrator**: The Strands orchestrator agent that coordinates specialist agents.
- **Environment_Specialist**: The specialist agent that identifies a safe object inventory and affordances.
- **Curriculum_Specialist**: The specialist agent that chooses the learning objective and challenge progression.
- **Storytelling_Specialist**: The specialist agent that composes the three-Activity adventure.
- **Assessment_Specialist**: The specialist agent that provides rubric-based feedback on answers.
- **Specialist_Contract**: A versioned, typed schema that a specialist agent output must satisfy.
- **Validation_Gates**: The deterministic schema, safety and object-grounding checks applied outside the language models.
- **Safe_Template**: A curated prebuilt Lesson or Activity clearly labeled as a template.
- **Assessment_Status**: One of `correct`, `partially_correct`, `needs_support` or `unassessable`.
- **Stage_Event**: A sanitized record of an agent stage status that excludes prompts, credentials and raw personal data.
- **Capability_Token**: A high-entropy bearer token returned at Session creation and required for Session-specific routes.
- **Idempotency_Key**: A client-supplied key that prevents duplicate mutations on repeated requests.
- **Session_Store**: The persistence layer for Sessions, using DynamoDB with TTL in deployment and an in-memory repository in local development.
- **Bedrock**: Amazon Bedrock, the model service used by the specialist agents.
- **Demo_Mode**: A mode that loads a fixed synthetic preset for demonstration.
- **Demo_Fallback**: A deterministic non-live path used when Bedrock is unavailable, labeled `Demo fallback — no live agent execution`.
- **PII**: Personally identifying information such as names, birthdays, addresses, school names, email addresses and phone numbers.
- **Repository**: The source code repository delivered with the System.

## Requirements

### Requirement 1: Session configuration (R-01, P0)

**User Story:** As a Facilitator, I want to start without registering a child, so that learning is accessible and private.

#### Acceptance Criteria

1. WHEN the start page loads, THE Web_UI SHALL show a single-select Age_Band control with exactly three options (6-8, 9-10 and 11-12) and none preselected, a Subject selector listing the supported subjects with none preselected, an Objects entry field accepting 1 to 20 objects of 1 to 50 characters each, and a Demo_Mode preset control.
2. WHEN valid fields are submitted, THE API SHALL create a Session and return a Session_ID within 2 seconds, where the Session_ID is random, contains at least 128 bits of randomness, and is not derived from any submitted field value.
3. IF the Age_Band or Subject is not selected, or the Objects field is empty, or any object is longer than 50 characters, or more than 20 objects are entered, THEN THE Web_UI SHALL show an error next to each invalid field while retaining all entered values, and THE API SHALL reject the request with an error identifying each invalid field, create no Session, and make zero Bedrock invocations.
4. THE System SHALL omit requests for, and SHALL NOT accept or store, a child's name, birthday, address, school or email.
5. WHEN the Facilitator selects the Demo_Mode preset, THE Web_UI SHALL fill the Age_Band, Subject and Objects fields with the preset values and keep every field editable before submission.
6. IF Session creation fails for a reason other than field validation, THEN THE Web_UI SHALL show an error indicating that the Session could not be started, retain all entered values, and allow resubmission, and THE API SHALL leave no partially created Session.

### Requirement 2: Grounding in local resources (R-02, P0)

**User Story:** As a Facilitator, I want lessons based only on objects we possess, so that no purchase is needed.

#### Acceptance Criteria

1. WHEN Objects are entered, THE System SHALL normalize each Object by trimming leading and trailing whitespace, collapsing internal whitespace and comparing case-insensitively, deduplicate Objects that match after normalization, store the original entered text of each Object unchanged, and limit the Object_Inventory to 1 to 20 unique Objects with each Object name at most 50 characters.
2. IF the entered Objects contain zero valid Objects, more than 20 unique Objects, or an Object name longer than 50 characters, THEN THE System SHALL reject the submission, display an error indicating which limit was violated, and retain the Facilitator's entered text.
3. IF an Object is ambiguous, THEN THE System SHALL either request clarification from the Facilitator before generating any Activity that uses that Object, or label the Object with a visible safe assumption stated in one sentence of at most 100 characters.
4. IF an Object is unsuitable or hazardous, THEN THE System SHALL exclude every hazardous use of that Object from all generated Activities and display at least one safe substitute Object or a safe alternative use, and SHALL inform the Facilitator of the exclusion.
5. THE System SHALL generate Activities that use only Objects in the Object_Inventory, without requiring purchased supplies or paid services.
6. IF a generated Activity references an item that is not in the Object_Inventory or requires purchased supplies or paid services, THEN THE System SHALL reject that Activity, not display it to the Learner, and apply the lesson generation retry and fallback behavior defined in Requirement 3.

### Requirement 3: Lesson generation (R-03, P0)

**User Story:** As a Learner, I want a short adventure with hands-on challenges, so that I learn by doing.

#### Acceptance Criteria

1. WHEN valid inputs are submitted, THE System SHALL generate a Lesson containing a title (1 to 80 characters), a learning objective (1 to 200 characters), an object list (1 to 10 objects, each present in the submitted inputs), a setup (1 to 500 characters), exactly three ordered Activities, an expected answer and rubric for each Activity, 1 to 3 hints for each Activity, and an estimated duration of 5 to 10 minutes.
2. THE System SHALL provide, for each Activity, learner instructions of 1 to 300 characters and facilitator notes held separately from the learner instructions.
3. THE System SHALL restrict the concepts and vocabulary of each generated Lesson to those defined for the selected Age_Band and Subject.
4. IF generated output fails schema, safety or object-grounding validation, THEN THE System SHALL discard the output and retry generation up to 2 times.
5. IF generated output still fails validation after 2 retries, THEN THE System SHALL return a Safe_Template Lesson labeled as a Safe_Template in the Learner view, or, if no Safe_Template exists for the selected Age_Band and Subject, return a failure indication to the Learner and create no Lesson.
6. WHILE an Activity has no submitted answer, THE API SHALL omit the expected answer and full rubric for that Activity from all Learner view responses.
7. WHEN the Learner submits an answer for an Activity, THE API SHALL include the expected answer and full rubric for that Activity, and only that Activity, in the Learner view.

### Requirement 4: Genuine Strands multi-agent execution (R-04, P0)

**User Story:** As a Judge, I want evidence that specialist agents actually collaborate, so that I can trust the multi-agent claim.

#### Acceptance Criteria

1. WHEN a Lesson is requested, THE Orchestrator SHALL invoke the Environment_Specialist, the Curriculum_Specialist and the Storytelling_Specialist at least once each before returning the Lesson.
2. WHEN an answer is submitted and deterministic grading returns no verdict for that answer, THE Orchestrator SHALL invoke the Assessment_Specialist to produce rubric-based feedback.
3. WHEN a specialist returns output, THE System SHALL validate the output against the versioned Specialist_Contract for that specialist and record the contract version used in the corresponding Stage_Event.
4. THE System SHALL enforce the following configurable limits per request, with these defaults: orchestration depth of 2, 8 specialist calls, 45 seconds total duration for generation (15 seconds for assessment), 2 retries per specialist call, and 20,000 model tokens.
5. WHEN an agent stage starts, completes or fails, THE API SHALL expose a Stage_Event within 1 second containing the stage name, the specialist name, the status (started, completed or failed) and a timestamp.
6. IF specialist output fails Specialist_Contract validation, THEN THE Orchestrator SHALL retry that specialist call up to the configured retry limit and, if validation still fails, SHALL return an error response identifying the failing specialist, without persisting a partial Lesson or assessment.
7. IF any limit in criterion 4 is reached, THEN THE Orchestrator SHALL stop invoking further specialists, return an error response identifying which limit was reached, and expose a failed Stage_Event for the interrupted stage.

### Requirement 5: Activity interaction (R-05, P0)

**User Story:** As a Learner, I want to solve one challenge at a time, so that I stay focused.

#### Acceptance Criteria

1. WHEN a Lesson is ready, THE Web_UI SHALL display exactly one Activity (the first in the Lesson sequence) and a progress indicator showing the current Activity position and total Activity count (for example, "1 of N").
2. WHEN an answer is submitted, THE API SHALL validate the answer against the Activity's expected answer format and return an Assessment_Status result within 2 seconds for deterministically graded answers.
3. WHEN an answer is submitted with an Idempotency_Key, THE API SHALL apply the resulting mutation exactly once per Idempotency_Key and return the original result for any repeat submission using the same key.
4. IF an answer is submitted that fails validation (empty, exceeds 2,000 characters, or does not match the Activity's expected answer format), THEN THE API SHALL reject the submission, return an error indication identifying the validation failure, and leave the Activity status and Learner progress unchanged.
5. WHEN a hint is requested, THE System SHALL return a scaffold that does not contain the expected answer text or a verbatim transformation of it, and SHALL keep the Activity status unchanged.
6. WHEN an Activity is completed or skipped, THE System SHALL persist the Activity status (completed or skipped) and advance the Web_UI to the next Activity within 1 second of persistence, updating the progress indicator.
7. IF persisting the Activity status fails, THEN THE System SHALL display an error indication to the Learner, keep the Learner on the current Activity, and allow the action to be retried.
8. WHEN the final Activity is completed or skipped, THE Web_UI SHALL display the list of concepts practiced in the Lesson and at least one suggested next step.

### Requirement 6: Assessment and adaptation (R-06, P0)

**User Story:** As a Facilitator, I want helpful feedback that adjusts to the Learner, so that each challenge fits their needs.

#### Acceptance Criteria

1. WHEN an answer arrives, THE System SHALL return exactly one Assessment_Status from {correct, partially_correct, needs_support, unassessable} and an explanation of at most 300 characters in plain language suited to the selected Age_Band.
2. WHEN a misconception is detected in an answer, THE System SHALL adjust the scaffolding level or difficulty of the next Activity, keep the same learning objective, and identify the adjustment to the Facilitator.
3. IF an answer is ambiguous, THEN THE System SHALL set Assessment_Status to unassessable, request clarification from the Learner or Facilitator, and withhold an incorrect mark until a clarified answer is received.
4. IF a clarification request goes unanswered or the clarified answer is still ambiguous after 2 attempts, THEN THE System SHALL keep Assessment_Status as unassessable, offer the Facilitator the options to skip the Activity or provide a hint, and exclude the answer from mastery estimates.
5. WHERE an answer requires exact arithmetic, THE System SHALL determine correctness with a deterministic check that returns the same result for the same input, and SHALL NOT use a model to decide correctness.
6. THE System SHALL label every mastery estimate as "provisional" and SHALL NOT state, imply, or suggest a diagnosis of a learning difficulty or disability.

### Requirement 7: Baseline and end checks (R-07, P0)

**User Story:** As a Facilitator, I want a simple indicator of progress, so that I can see what changed during the Lesson.

#### Acceptance Criteria

1. WHEN a Lesson begins, THE Web_UI SHALL display the Baseline_Question within 2 seconds, before any other Lesson content is shown, with a control to answer it and a control to skip it.
2. WHEN a Lesson ends, THE Web_UI SHALL display the End_Question within 2 seconds, with a control to answer it and a control to skip it, WHERE the End_Question covers the same topic and uses the same answer scale as the Baseline_Question and its wording differs from the Baseline_Question wording.
3. WHEN both the Baseline_Question and the End_Question are answered, THE Web_UI SHALL show on one screen the Baseline_Question answer, the End_Question answer, and the observed difference (End_Question answer minus Baseline_Question answer), together with a visible warning that the result is not a validated educational assessment.
4. IF either the Baseline_Question or the End_Question is skipped, THEN THE Web_UI SHALL NOT display an observed difference or any statement of improvement, and SHALL indicate which question was skipped.
5. IF the observed difference is zero or negative, THEN THE Web_UI SHALL display the difference value and the not-validated warning, and SHALL NOT display any statement of improvement.
6. IF the Facilitator skips the Baseline_Question, THEN THE Web_UI SHALL continue the Lesson without delay or loss of previously entered data.

### Requirement 8: Safety and adult control (R-08, P0)

**User Story:** As a Facilitator, I need to supervise and stop any activity, so that the Learner stays safe.

#### Acceptance Criteria

1. WHEN a Lesson has been generated and before it is displayed, THE System SHALL apply Validation_Gates for safety, age-appropriateness for the selected Age_Band, and grounding in the Facilitator-entered Objects, and SHALL display the Lesson only if all three gates pass.
2. IF any Activity in a generated Lesson involves ingestion, sharp objects, fire, electricity, hazardous chemicals, heights, strangers or dangerous water, THEN THE Validation_Gates SHALL reject the whole Lesson, THE System SHALL NOT display any part of it, and THE System SHALL treat the rejection as a failed validation attempt.
3. WHEN the Facilitator selects Stop, THE System SHALL within 2 seconds reject every further answer, hint and Activity submission for that Session with an error indicating the Session is stopped, cancel pending model calls where supported, and keep the Session's existing data available for review and deletion.
4. THE Web_UI SHALL display an adult-supervision notice on every screen that shows Lesson content.
5. IF a generated Lesson contains content that encourages the Learner to keep secrets from an adult or to depend emotionally on the System, THEN THE Validation_Gates SHALL reject the Lesson and THE System SHALL NOT display it.
6. IF input includes PII (a person's name, phone number, email address, street address, school name or birth date), THEN THE System SHALL redact the PII before any model call and display a warning to the Facilitator that PII was detected and redacted.
7. IF the System cannot redact PII from an input, THEN THE System SHALL NOT send that input to any model, SHALL display an error asking the Facilitator to remove the PII, and SHALL keep the Session's other data unchanged.

### Requirement 9: Accessibility (R-09, P0)

**User Story:** As a Facilitator, I want inclusive, easy-to-use learning experiences, so that every Learner can take part.

#### Acceptance Criteria

1. THE Web_UI SHALL allow every interactive element to be reached and operated using only the keyboard, in an order that matches the visual reading order.
2. WHILE an interactive element has keyboard focus, THE Web_UI SHALL display a visible focus indicator with a contrast ratio of at least 3:1 against adjacent colors.
3. THE Web_UI SHALL provide a programmatically associated text label for every form control, button, and image that conveys information.
4. THE Web_UI SHALL render text with a contrast ratio of at least 4.5:1 for normal text and at least 3:1 for large text (18 pt or 14 pt bold and larger), consistent with WCAG 2.2 AA.
5. THE Web_UI SHALL display all content and functionality without horizontal scrolling and without loss of information at viewport widths from 320 CSS px upward.
6. THE Web_UI SHALL present each instruction in no more than 25 words per sentence and no more than 3 sentences, written at a reading level no higher than grade 6.
7. THE Web_UI SHALL accept Learner answers for an unlimited duration without expiring the Activity, locking input, or discarding entered answers.
8. WHERE an Activity depends on color, sound, or fine motor skills, THE System SHALL offer at least one alternative way to complete the Activity that does not require that capability, and SHALL award the same score and completion status for equivalent answers.
9. WHERE spelling is not the learning objective of an Activity, THE System SHALL assess answers as correct if they differ from an accepted answer only by spelling errors of up to 2 character edits per word, and SHALL NOT reduce the score because of those errors.
10. IF an Activity has no available alternative for a required capability, THEN THE System SHALL show a message to the Learner indicating the Activity cannot be completed in the current mode, SHALL preserve the Learner's progress, and SHALL notify the Facilitator.

### Requirement 10: Session privacy (R-10, P0)

**User Story:** As a Facilitator, I want short-term progress without permanent child profiling, so that privacy is protected.

#### Acceptance Criteria

1. THE Session_Store SHALL store only Age_Band, Subject, Object list, Lesson, answers, progress and operational metadata limited to creation timestamp, last-updated timestamp and expiry timestamp under the Session_ID (plus the Capability_Token hash, state version and idempotency records needed for authorization and concurrency).
2. THE System SHALL omit cross-session child profiles, meaning no record that links two or more distinct Session_IDs to the same child.
3. THE System SHALL omit raw child answer text from all logs by default.
4. WHEN the Facilitator ends a Session, THE Web_UI SHALL display a delete action.
5. WHEN the API receives a delete request for an existing Session_ID, THE API SHALL permanently delete all data stored under that Session_ID from the Session_Store and confirm the deletion to the caller within 2 seconds.
6. IF the API receives a read or delete request for a deleted or non-existent Session_ID, THEN THE API SHALL return an error indicating the Session was not found and SHALL return no Session data.
7. THE Session_Store SHALL set a TTL of 24 hours from the last-updated timestamp on each persisted Session, and SHALL remove expired Sessions.
8. IF the API receives a read request for a Session whose expiry timestamp has passed, THEN THE API SHALL reject the request with an error indicating the Session has expired, without waiting for TTL removal, and SHALL return no Session data.
9. IF persistence of a Session fails, THEN THE Web_UI SHALL display a message indicating that progress could not be saved within 2 seconds of the failure, SHALL keep the Facilitator's current on-screen state, and SHALL offer a retry action.

### Requirement 11: Reliability and observability (R-11, P0)

**User Story:** As a user, I want graceful errors, and as a maintainer, I need safe diagnostics, so that the System stays usable and operable.

#### Acceptance Criteria

1. IF a model call fails or does not respond within its configured deadline, THEN THE System SHALL cancel the call, retain the user's entered inputs, and, within 2 seconds of the failure or timeout, present an error indication with a retry option and a Safe_Template Activity option.
2. WHEN a request reuses an Idempotency_Key within 24 hours of its first use with an identical payload, THE API SHALL return the original result without duplicating lesson generation or answer submission.
3. THE System SHALL emit, for each request, a diagnostic record containing a redacted correlation ID, agent-stage statuses, latency in milliseconds, an error category when an error occurs, and a usage estimate where available, and SHALL exclude credentials, personal data and learner free-text content from the record.
4. IF a request body exceeds 1 MB, OR concurrent in-flight requests exceed a configurable cap (default 50), OR a single client exceeds a configurable rate (default 60 requests per minute), THEN THE API SHALL reject the request without side effects and return an error indication identifying which limit was exceeded.
5. WHEN /healthz is requested while the API process is running, THE API SHALL return a success indication within 500 milliseconds without depending on external services.
6. WHEN /readyz is requested, THE API SHALL return a ready indication within 2 seconds only if all required dependencies are available, and otherwise a not-ready indication naming the unavailable dependencies.
7. IF a request reuses an Idempotency_Key within 24 hours with a payload different from the original, THEN THE API SHALL reject the request with an error indicating a key conflict and leave stored results unchanged.

### Requirement 12: Reproducible demo (R-12, P0)

**User Story:** As a Judge, I want to understand the solution in under three minutes, so that I can evaluate it quickly.

#### Acceptance Criteria

1. WHEN Demo_Mode is selected, THE System SHALL load a session with Age_Band 6-8, subject mathematics, and exactly seven objects (five stones and two leaves) within 3 seconds, without requiring user-supplied input or an image upload.
2. WHEN a Demo_Mode session runs, THE Web_UI SHALL display five sanitized stages in this order: understand objects, choose objective, create story, assess answer, adapt next activity, and SHALL mark each stage as pending, in progress, or complete.
3. THE Web_UI SHALL exclude raw prompts, model reasoning, credentials, and internal identifiers from the stage display.
4. IF Bedrock is unavailable or does not respond within 10 seconds, THEN THE System SHALL run the Demo_Fallback using pre-recorded seed data, display the visible label `Demo fallback — no live agent execution` on every stage screen, and complete all five stages.
5. THE Repository SHALL include setup instructions, architecture documentation, seed data, automated tests, and a demo script whose timed walkthrough lasts no more than 180 seconds.
6. WHEN a user follows the setup instructions on a clean checkout, THE System SHALL start Demo_Mode and complete all five stages with identical seed inputs and the same stage order on every run.

### Requirement 13: Image-based object identification (R-13, P1)

**User Story:** As a Facilitator, I want to identify objects from a photo, so that I can enter them faster.

#### Acceptance Criteria

1. WHEN an image is uploaded, THE System SHALL validate that the file is JPEG or PNG and no larger than 5 MB before any image analysis begins.
2. IF an uploaded image has an unsupported file type, exceeds 5 MB, or fails the safety check, THEN THE System SHALL reject the image, display an error indicating the reason for rejection, discard the image, and keep any previously entered session data and Objects unchanged.
3. WHEN an image passes validation, THE System SHALL return a list of detected Objects, with at most 20 Objects, within 15 seconds.
4. IF no Objects are detected or the analysis fails or exceeds 15 seconds, THEN THE System SHALL display a message indicating that no Objects were identified and SHALL offer manual Object entry.
5. WHEN detected Objects are returned, THE Web_UI SHALL display each detected Object and let the Facilitator confirm, edit, or remove each one before lesson generation.
6. IF the Facilitator has not confirmed at least one Object, THEN THE System SHALL NOT start lesson generation.
7. THE System SHALL NOT infer or output the identity, or any sensitive trait (including race, ethnicity, religion, health, age, or gender), of any person appearing in an image.
8. THE System SHALL delete each uploaded image within 24 hours of upload, and immediately once its Objects are confirmed or the session ends, whichever occurs first.

### Requirement 14: Hindi-language lessons (R-14, P1)

**User Story:** As a Facilitator, I want Lessons in Hindi, so that Learners can work in their own language.

#### Acceptance Criteria

1. WHEN the Facilitator selects Hindi and submits valid fields, THE System SHALL generate a Lesson whose learner instructions for all three Activities are written in Devanagari-script Hindi.
2. THE System SHALL restrict Hindi learner instructions to the vocabulary and concepts of the selected Age_Band and Subject, with each instruction no longer than the English instruction limit.
3. THE System SHALL preserve in the Hindi Lesson every number, quantity, unit and Object name used in the English-equivalent Lesson, so that expected answers are identical in both languages.
4. WHEN a Hindi Lesson is generated, THE System SHALL run a language check that verifies the Devanagari script, the preserved numbers and units, and that no Activity instruction is empty, and SHALL complete the check within 5 seconds.
5. IF the language check fails or does not complete within 5 seconds, THEN THE Web_UI SHALL display the English version of the affected Lesson together with a visible notice that Hindi is unavailable, SHALL retain the Session and its progress, and SHALL NOT display unchecked Hindi text to the Learner.
6. IF the language check fails, THEN THE Web_UI SHALL offer the Facilitator a retry action for Hindi that can be repeated without creating a new Session.

### Requirement 15: Future enhancements (R-15, P2)

**User Story:** As a product owner, I want a record of future enhancements, so that the MVP stays focused.

#### Acceptance Criteria

1. THE System SHALL treat the following as post-MVP enhancements: downloadable lesson packs, speech accessibility, facilitator-curated curriculum mappings, and group activities without individual tracking.
2. WHEN the MVP release is built, THE System SHALL ship with none of the four post-MVP enhancements required for release, and the MVP release SHALL NOT be blocked by any of them being absent or incomplete.
3. WHERE a post-MVP enhancement listed in criterion 1 is implemented, THE System SHALL make it available only after the MVP release and without changing the behavior of any MVP requirement (Requirements 1 to 14), as verified by all MVP acceptance criteria passing before and after the enhancement is enabled.
4. WHERE group activities without individual tracking are implemented, THE System SHALL store zero per-individual identifiers or per-individual progress records for participants of those activities.

## Non-Functional Requirements

| ID | Requirement | Validation |
|---|---|---|
| NFR-01 | THE System SHALL use TLS, least-privilege IAM and keep secrets out of code. | IaC review, secret scan |
| NFR-02 | THE System SHALL apply typed inputs and outputs, bounds and output sanitization. | Unit and fuzz tests |
| NFR-03 | THE Web_UI SHALL follow WCAG 2.2 AA-oriented design. | axe and keyboard audit |
| NFR-04 | THE Web_UI SHALL be mobile-first and responsive. | E2E viewport tests |
| NFR-05 | THE System SHALL apply timeouts, retries, circuit breaking and graceful fallback. | Fault-injection tests |
| NFR-06 | THE Repository SHALL pin dependencies, produce an SBOM and run vulnerability scans. | CI checks |
| NFR-07 | THE System SHALL make model, region, limits and budgets configurable. | Configuration tests |
| NFR-08 | THE System SHALL minimize data and provide explicit delete and TTL. | Privacy integration tests |
| NFR-09 | THE System SHALL omit unsubstantiated educational efficacy claims. | Demo and content review |
| NFR-10 | THE System SHALL defend against prompt injection and treat model output as untrusted. | Adversarial tests |

## Measurable MVP Acceptance Goals

1. WHEN 30 curated object, age and subject cases are run, THE System SHALL pass schema, grounding and safety checks for at least 90% of the cases.
2. WHEN scripted misconception cases are run, THE System SHALL produce a relevant scaffolded follow-up for at least 90% of the cases.
3. WHEN 20 controlled end-to-end tests are run with configured model access, THE System SHALL complete at least 95% of the tests successfully.
4. THE System SHALL record p50 and p95 latency and estimated cost per Session, and thresholds SHALL be tuned after baseline measurement.
5. THE System SHALL pass all P0 scenarios and release gates, including live multi-agent evidence and the labeled Demo_Fallback.

## Release Gates

- **G1**: Real Strands specialist calls are visible in the sanitized trace.
- **G2**: Safety, schema and grounding gates pass.
- **G3**: No unresolved critical or high security issues or secrets remain.
- **G4**: Mobile, keyboard and error flows are tested.
- **G5**: Live versus fallback execution and measured versus illustrative outcomes are clearly distinguished.

## Traceability

1. THE Repository SHALL cite the applicable R-xx and NFR-xx identifiers in every implementation task and automated test.
2. THE Repository SHALL generate `tasks.md` only after `requirements.md` and `design.md` are reconciled.
3. THE Repository SHALL keep P1 and P2 work off the P0 critical path.
