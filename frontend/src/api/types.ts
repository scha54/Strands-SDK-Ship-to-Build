// Convenience aliases over the generated OpenAPI component schemas, so feature
// code imports stable names instead of reaching into `components["schemas"]`.
// The underlying types are generated from the backend contract by
// `npm run gen:api` (R-04.3; NFR-02) and must not be edited by hand.
import type { components } from "../types/api";

type Schemas = components["schemas"];

export type AgeBand = Schemas["AgeBand"];
export type Subject = Schemas["Subject"];
export type AssessmentStatus = Schemas["AssessmentStatus"];
export type CreateSessionRequest = Schemas["CreateSessionRequest"];
export type ObjectItem = Schemas["ObjectItem"];
export type ObjectInventory = Schemas["ObjectInventory"];
export type Activity = Schemas["Activity"];
export type Question = Schemas["Question"];
export type Lesson = Schemas["Lesson"];
export type Assessment = Schemas["Assessment"];
export type AnswerRequest = Schemas["AnswerRequest"];
export type GateResult = Schemas["GateResult"];
export type Grade = Schemas["Grade"];
export type AgentStageEvent = Schemas["AgentStageEvent"];
export type SessionSummary = Schemas["SessionSummary"];
export type ApiError = Schemas["ApiError"];
