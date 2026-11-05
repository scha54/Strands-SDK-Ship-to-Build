// Unit tests for the adult-supervision notice.
//
// Validates: Requirements R-08.4 (adult-supervision notice on Lesson screens),
// R-09.1 / NFR-03 (notice is an announced landmark with accessible labelling).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SupervisionNotice } from "./SupervisionNotice";

describe("SupervisionNotice (R-08.4)", () => {
  it("renders the default adult-supervision reminder", () => {
    render(<SupervisionNotice />);

    const notice = screen.getByTestId("supervision-notice");
    expect(notice).toBeInTheDocument();
    expect(notice).toHaveTextContent(/adult should supervise/i);
  });

  it("exposes an accessible note landmark for assistive technology", () => {
    render(<SupervisionNotice />);

    const notice = screen.getByRole("note", {
      name: /adult supervision notice/i,
    });
    expect(notice).toBeInTheDocument();
  });

  it("does not encourage secrecy or emotional dependency (R-08.4)", () => {
    render(<SupervisionNotice />);

    const notice = screen.getByTestId("supervision-notice");
    expect(notice.textContent ?? "").not.toMatch(/secret|don'?t tell|only you/i);
  });

  it("allows the message to be overridden while staying a labelled landmark", () => {
    render(<SupervisionNotice message="A grown-up should stay nearby." />);

    const notice = screen.getByRole("note", {
      name: /adult supervision notice/i,
    });
    expect(notice).toHaveTextContent("A grown-up should stay nearby.");
  });
});
