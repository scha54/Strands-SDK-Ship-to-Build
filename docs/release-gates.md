# Release gates G1 to G5

Gates come from the requirements. "Status" says what this repository demonstrates today and
whether the evidence is **measured** (observed from a real run of the thing named) or
**illustrative** (stubbed, scripted or placeholder). Live and fallback execution are always
stated separately.

| Gate | Requirement | Evidence in the repository | Status |
|---|---|---|---|
| G1 | Real Strands specialist calls are visible in the sanitized trace | Four Strands specialists behind the Orchestrator; sanitized Stage_Events (`GET /sessions/{id}/events`) and the five-stage timeline | Trace structure is tested with the stub model (illustrative of live behavior). **Open until a live Bedrock run is recorded.** |
| G2 | Safety, schema and grounding gates pass | Validation_Gates in `backend/app/services/`; unit and property tests; evaluation harness | Measured over 69 synthetic cases on the stub model; adversarial gate bypasses = 0. Says nothing yet about live model output. |
| G3 | No unresolved critical or high security issues or secrets | CI: gitleaks, `pip-audit`, CycloneDX SBOM, pinned lockfiles | Enforced in CI. Review the latest CI run for the actual result. |
| G4 | Mobile, keyboard and error flows are tested | Playwright: 320 px reflow, keyboard-only, axe, model-failure, Stop and expired-session flows | Measured against the stub-backed stack. Manual assistive-technology testing has not been done. |
| G5 | Live vs fallback and measured vs illustrative are clearly distinguished | `source` field (`generated`, `safe_template`, `demo_fallback`), fallback label on every stage screen, `[STUBBED]`/`LIVE` labels in the evaluation output, this document | Implemented and tested. |

## Measured vs illustrative, at a glance

| Figure | Kind |
|---|---|
| Schema, grounding, safety pass rates; adversarial bypass count | Measured, on synthetic cases, stub model |
| Scaffold relevance for scripted misconceptions | Measured, on scripted cases, stub model |
| Latency p50/p95 from the stubbed suite | Illustrative (stub answers in about a millisecond) |
| Estimated cost per session from the stubbed suite | Illustrative (tokens times a placeholder rate) |
| Anything from `--live` | Measured against Bedrock, reported under its own `LIVE` label; none recorded in this repository |
| Learning outcomes, engagement, efficacy | Not measured; no claim made |

## Live vs fallback

| Execution | Meaning |
|---|---|
| Live | Specialists called Bedrock |
| Stub | Specialists ran against the deterministic offline stub; not Bedrock |
| Demo_Fallback | Pre-recorded seed data; label `Demo fallback — no live agent execution` |
| Safe_Template | Curated template after repeated gate failures; labeled in the UI |
