// Component tests for the setup (start page) feature.
//
// Validates: Requirements R-01.1 (initial control state), R-01.3 / R-02.2
// (per-field errors retaining entered values), R-01.5 (Demo_Mode preset fill
// and editability), R-01.6 (non-validation failure message with resubmission),
// R-09.3 / NFR-03 (programmatically associated labels). No child-identity
// fields are present (R-01.4).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CreateSessionRequest } from "../../api/types";
import { DEMO_PRESET } from "./demoPreset";
import { SetupForm } from "./SetupForm";

function renderForm(
  onSubmit: (req: CreateSessionRequest) => Promise<void> = vi
    .fn()
    .mockResolvedValue(undefined),
) {
  render(<SetupForm onSubmit={onSubmit} />);
  return { onSubmit };
}

function selectAge(label: RegExp): void {
  fireEvent.click(screen.getByRole("radio", { name: label }));
}

function selectSubject(value: string): void {
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value } });
}

function setObjects(value: string): HTMLTextAreaElement {
  const objects = screen.getByLabelText("Objects") as HTMLTextAreaElement;
  fireEvent.change(objects, { target: { value } });
  return objects;
}

function clickStart(): void {
  fireEvent.click(screen.getByRole("button", { name: /start session/i }));
}

describe("SetupForm initial control state (R-01.1)", () => {
  it("shows exactly three Age_Band options with none preselected", () => {
    renderForm();

    const ageOptions = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(ageOptions).toHaveLength(3);
    expect(ageOptions.map((input) => input.value)).toEqual([
      "6-8",
      "9-10",
      "11-12",
    ]);
    for (const option of ageOptions) {
      expect(option).not.toBeChecked();
    }
  });

  it("shows a Subject selector listing supported subjects with none preselected", () => {
    renderForm();

    const select = screen.getByLabelText("Subject") as HTMLSelectElement;
    expect(select.value).toBe("");
    const values = Array.from(select.options).map((option) => option.value);
    expect(values).toContain("arithmetic_counting");
    expect(values).toContain("intro_measurement");
  });

  it("shows an empty Objects entry and a Demo_Mode preset control", () => {
    renderForm();

    const objects = screen.getByLabelText("Objects") as HTMLTextAreaElement;
    expect(objects.value).toBe("");
    expect(
      screen.getByRole("button", { name: /demo mode preset/i }),
    ).toBeInTheDocument();
  });

  it("exposes a programmatically associated label for every control (R-09.3)", () => {
    renderForm();

    expect(screen.getByLabelText("Subject")).toBeInstanceOf(HTMLSelectElement);
    expect(screen.getByLabelText("Objects")).toBeInstanceOf(HTMLTextAreaElement);
    expect(screen.getByRole("group", { name: /age band/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /start session/i }),
    ).toBeInTheDocument();
  });

  it("asks for no child-identity fields (R-01.4)", () => {
    renderForm();

    expect(screen.queryByLabelText(/name/i)).toBeNull();
    expect(screen.queryByLabelText(/birthday|birth date/i)).toBeNull();
    expect(screen.queryByLabelText(/address/i)).toBeNull();
    expect(screen.queryByLabelText(/school/i)).toBeNull();
    expect(screen.queryByLabelText(/email/i)).toBeNull();
  });
});

describe("SetupForm per-field validation (R-01.3, R-02.2)", () => {
  it("shows per-field errors and makes no submit call when nothing is entered", () => {
    const { onSubmit } = renderForm();

    clickStart();

    expect(screen.getByText(/select an age band/i)).toBeInTheDocument();
    expect(screen.getByText(/select a subject/i)).toBeInTheDocument();
    expect(screen.getByText(/enter at least one object/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("names the too-long limit and retains entered values (R-02.2)", () => {
    const { onSubmit } = renderForm();

    selectAge(/9 to 10/i);
    selectSubject("arithmetic_counting");
    const longName = "x".repeat(51);
    const objects = setObjects(longName);

    clickStart();

    expect(screen.getByText(/50 characters or fewer/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /9 to 10/i })).toBeChecked();
    expect((screen.getByLabelText("Subject") as HTMLSelectElement).value).toBe(
      "arithmetic_counting",
    );
    expect(objects.value).toBe(longName);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("names the too-many-objects limit when more than 20 are entered (R-02.2)", () => {
    const { onSubmit } = renderForm();

    selectAge(/6 to 8/i);
    selectSubject("intro_measurement");
    const text = Array.from({ length: 21 }, (_, i) => `object ${i}`).join("\n");
    const objects = setObjects(text);

    clickStart();

    expect(screen.getByText(/at most 20 objects/i)).toBeInTheDocument();
    expect(objects.value).toBe(text);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits a valid request with trimmed, non-empty object lines", async () => {
    const captured: CreateSessionRequest[] = [];
    const onSubmit = vi.fn(async (req: CreateSessionRequest) => {
      captured.push(req);
    });
    renderForm(onSubmit);

    selectAge(/6 to 8/i);
    selectSubject("arithmetic_counting");
    setObjects("  stone  \n\n leaf \n");

    clickStart();

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(captured[0]).toEqual({
      age_band: "6-8",
      subject: "arithmetic_counting",
      objects: ["stone", "leaf"],
      language: "en",
    });
  });
});

describe("SetupForm Demo_Mode preset (R-01.5)", () => {
  it("fills every field with preset values and keeps them editable", () => {
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: /demo mode preset/i }));

    expect(screen.getByRole("radio", { name: /6 to 8/i })).toBeChecked();
    expect((screen.getByLabelText("Subject") as HTMLSelectElement).value).toBe(
      DEMO_PRESET.subject,
    );
    const objects = screen.getByLabelText("Objects") as HTMLTextAreaElement;
    const lines = objects.value.split("\n").filter((l) => l.length > 0);
    expect(lines).toHaveLength(7);
    expect(lines.filter((l) => l === "stone")).toHaveLength(5);
    expect(lines.filter((l) => l === "leaf")).toHaveLength(2);

    // Fields remain editable after the preset fill.
    selectAge(/11 to 12/i);
    expect(screen.getByRole("radio", { name: /11 to 12/i })).toBeChecked();
    selectSubject("intro_measurement");
    expect((screen.getByLabelText("Subject") as HTMLSelectElement).value).toBe(
      "intro_measurement",
    );
    fireEvent.change(objects, { target: { value: `${objects.value}\npebble` } });
    expect(objects.value).toContain("pebble");
  });
});

describe("SetupForm session-creation failure (R-01.6)", () => {
  it("shows the failure message, retains values and allows resubmission", async () => {
    const onSubmit = vi
      .fn<(req: CreateSessionRequest) => Promise<void>>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(undefined);
    renderForm(onSubmit);

    selectAge(/6 to 8/i);
    selectSubject("arithmetic_counting");
    const objects = setObjects("stone\nleaf");

    clickStart();

    const alert = await screen.findByText(/session could not be started/i);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /6 to 8/i })).toBeChecked();
    expect(objects.value).toBe("stone\nleaf");

    clickStart();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText(/session could not be started/i)).toBeNull(),
    );
  });

  it("hides the generic failure message once validation fails instead", async () => {
    const onSubmit = vi
      .fn<(req: CreateSessionRequest) => Promise<void>>()
      .mockRejectedValue(new Error("boom"));
    renderForm(onSubmit);

    selectAge(/6 to 8/i);
    selectSubject("arithmetic_counting");
    setObjects("stone");

    clickStart();
    expect(
      await screen.findByText(/session could not be started/i),
    ).toBeInTheDocument();

    setObjects("");
    clickStart();

    expect(screen.queryByText(/session could not be started/i)).toBeNull();
    expect(screen.getByText(/enter at least one object/i)).toBeInTheDocument();
  });

  it("associates the age-band error with the radiogroup (R-09.3)", () => {
    renderForm();

    clickStart();

    const group = screen.getByRole("radiogroup");
    const describedBy = group.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const error = document.getElementById(describedBy as string);
    expect(error).not.toBeNull();
    expect(
      within(error as HTMLElement).getByText(/select an age band/i),
    ).toBeInTheDocument();
  });
});
