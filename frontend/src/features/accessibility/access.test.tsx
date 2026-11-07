/**
 * Alternative-path tests.
 *
 * Validates: Requirements R-09.8 (alternative path, same answer submitted so the
 * same score and status result), R-09.10 (no alternative: message, progress
 * preserved, Facilitator notified), R-09.3 (labeled access controls); NFR-03.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";

import type { LearnerView } from "../../api/learning";
import { ActivityView } from "../activity/ActivityView";
import {
  CAPABILITIES,
  type ActivityAccess,
  type Capability,
  resolveActivityAccess,
} from "./access";

const access: ActivityAccess = {
  needs: ["color"],
  alternatives: { color: "Sort big stones from small stones." },
};

function viewWith(a: ActivityAccess | null): LearnerView {
  return {
    session_id: "s",
    title: "Stones",
    setup: "",
    source: "generated",
    progress: { current: 1, total: 3, label: "1 of 3" },
    activity: {
      id: "a1",
      instruction: "Sort red from blue stones.",
      required_objects: ["stones"],
      answer_kind: "integer",
      difficulty: 1,
      answered: false,
      access: a,
    },
  };
}

function renderActivity(a: ActivityAccess | null, avoid: Capability[]) {
  const onSubmitAnswer = vi.fn();
  const onAdvance = vi.fn();
  render(
    <ActivityView
      view={viewWith(a)}
      result={null}
      hint={null}
      busy={false}
      onSubmitAnswer={onSubmitAnswer}
      onHint={() => undefined}
      onAdvance={onAdvance}
      avoid={avoid}
    />,
  );
  return { onSubmitAnswer, onAdvance };
}

describe("resolveActivityAccess", () => {
  it("is standard when nothing is avoided or nothing is needed (R-09.8)", () => {
    expect(resolveActivityAccess(access, [])).toEqual({ kind: "standard" });
    expect(resolveActivityAccess(null, ["color"])).toEqual({ kind: "standard" });
    expect(resolveActivityAccess(access, ["sound"])).toEqual({ kind: "standard" });
  });

  it("uses the alternative when one exists (R-09.8)", () => {
    expect(resolveActivityAccess(access, ["color"])).toEqual({
      kind: "alternative",
      instructions: ["Sort big stones from small stones."],
    });
  });

  it("reports unavailable when any blocked need has no alternative (R-09.10)", () => {
    const partial: ActivityAccess = { needs: ["color", "sound"], alternatives: { color: "x" } };
    expect(resolveActivityAccess(partial, ["color", "sound"])).toEqual({
      kind: "unavailable",
      unmet: ["sound"],
    });
  });

  it("property: unavailable exactly when a blocked need lacks an alternative (R-09.8, R-09.10)", () => {
    const cap = fc.constantFrom<Capability>(...CAPABILITIES);
    fc.assert(
      fc.property(
        fc.uniqueArray(cap),
        fc.uniqueArray(cap),
        fc.uniqueArray(cap),
        (needs, haveAlt, avoid) => {
          const alternatives: ActivityAccess["alternatives"] = {};
          for (const c of haveAlt) alternatives[c] = `alt-${c}`;
          const r = resolveActivityAccess({ needs, alternatives }, avoid);
          const blocked = needs.filter((c) => avoid.includes(c));
          const unmet = blocked.filter((c) => !haveAlt.includes(c));
          if (blocked.length === 0) expect(r.kind).toBe("standard");
          else if (unmet.length > 0) expect(r).toEqual({ kind: "unavailable", unmet });
          else expect(r.kind).toBe("alternative");
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("ActivityView alternative paths", () => {
  it("submits the identical answer payload via the alternative as via the standard path (R-09.8)", () => {
    const std = renderActivity(access, []);
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    expect(std.onSubmitAnswer).toHaveBeenCalledWith("4");
    expect(screen.queryByTestId("alternative-instruction")).toBeNull();
  });

  it("shows the alternative instruction and submits the same answer (R-09.8)", () => {
    const alt = renderActivity(access, ["color"]);
    expect(screen.getByTestId("alternative-instruction")).toHaveTextContent("big stones");
    expect(screen.queryByText(/red from blue/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    expect(alt.onSubmitAnswer).toHaveBeenCalledWith("4");
  });

  it("with no alternative: tells the Learner, notifies the Facilitator, keeps progress (R-09.10)", () => {
    const { onSubmitAnswer, onAdvance } = renderActivity({ needs: ["color"], alternatives: {} }, [
      "color",
    ]);
    expect(screen.getByTestId("no-alternative")).toHaveTextContent(
      "can't be done in the current mode",
    );
    expect(screen.getByTestId("no-alternative")).toHaveTextContent("progress is saved");
    expect(screen.getByTestId("facilitator-access-notice")).toHaveTextContent(
      /Facilitator.*color/,
    );
    // Progress indicator stays; nothing was submitted or advanced automatically.
    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 3");
    expect(onSubmitAnswer).not.toHaveBeenCalled();
    expect(onAdvance).not.toHaveBeenCalled();
    // The Facilitator can still skip.
    fireEvent.click(screen.getByRole("button", { name: "Skip this activity" }));
    expect(onAdvance).toHaveBeenCalledWith("skipped");
  });
});
