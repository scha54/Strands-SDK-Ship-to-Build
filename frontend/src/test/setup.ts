// Vitest global setup: adds jest-dom matchers (e.g. toBeInTheDocument) and
// cleans up the rendered React tree between tests.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
