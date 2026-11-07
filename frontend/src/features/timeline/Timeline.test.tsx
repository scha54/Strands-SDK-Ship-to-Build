// Component tests for the five-stage timeline.
//
// Validates: Requirements R-12.2 (five ordered stages), R-12.3 (sanitized
// display), R-12.4 (fallback label on every stage), NFR-03 (labelled,
// text-conveyed state), NFR-09 (live vs fallback distinguishable, G5).
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Timeline } from "./Timeline";
import { DEMO_FALLBACK_LABEL } from "./stages";

const ORDER = [
  "Understand objects",
  "Choose objective",
  "Create story",
  "Assess answer",
  "Adapt next activity",
];

describe("Timeline", () => {
  it("shows the five stages in order, all pending with no events (R-12.2)", () => {
    render(<Timeline events={[]} source="live" />);
    const items = within(screen.getByRole("list", { name: /stages/i })).getAllByRole(
      "listitem",
    );
    expect(items).toHaveLength(5);
    items.forEach((li, i) => {
      expect(li).toHaveTextContent(ORDER[i] as string);
      expect(li).toHaveAttribute("data-state", "pending");
      expect(li).toHaveTextContent("Pending");
    });
  });

  it("maps events to pending, in progress and complete (R-12.2, NFR-03)", () => {
    render(
      <Timeline
        source="live"
        events={[
          { stage: "understand_objects", status: "started" },
          { stage: "understand_objects", status: "completed" },
          { stage: "choose_objective", status: "started" },
        ]}
      />,
    );
    expect(screen.getByTestId("stage-understand_objects")).toHaveTextContent("Complete");
    const active = screen.getByTestId("stage-choose_objective");
    expect(active).toHaveTextContent("In progress");
    expect(active).toHaveAttribute("aria-current", "step");
    expect(screen.getByTestId("stage-create_story")).toHaveTextContent("Pending");
  });

  it("shows the fallback label on every stage and the mode banner (R-12.4)", () => {
    render(<Timeline source="demo_fallback" events={[]} />);
    for (const id of [
      "understand_objects",
      "choose_objective",
      "create_story",
      "assess_answer",
      "adapt_next_activity",
    ]) {
      expect(screen.getByTestId(`stage-fallback-${id}`)).toHaveTextContent(
        DEMO_FALLBACK_LABEL,
      );
    }
    expect(screen.getByTestId("timeline-mode")).toHaveTextContent(DEMO_FALLBACK_LABEL);
  });

  it("distinguishes live from fallback and omits the label when live (NFR-09, G5)", () => {
    render(<Timeline source="live" events={[]} />);
    expect(screen.getByTestId("timeline-mode")).toHaveTextContent("Live agent execution");
    expect(screen.queryByText(DEMO_FALLBACK_LABEL)).not.toBeInTheDocument();
  });

  it("renders no sensitive or internal fields from events (R-12.3)", () => {
    const events = [
      {
        stage: "create_story",
        status: "completed",
        specialist: "storytelling",
        contract_version: "1.0",
        timestamp: "2024-01-01T00:00:00Z",
        prompt: "SECRET_PROMPT",
        reasoning: "SECRET_REASONING",
        api_key: "SECRET_KEY",
        session_id: "SECRET_ID",
      },
    ] as const;
    const { container } = render(<Timeline source="live" events={events} />);
    const html = container.innerHTML;
    expect(html).not.toMatch(/SECRET_|storytelling|2024-01-01|contract/i);
    expect(container.textContent ?? "").not.toMatch(/prompt|reasoning|credential|token/i);
  });
});
