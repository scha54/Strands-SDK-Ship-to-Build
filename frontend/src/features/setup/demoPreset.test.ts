// Guards the Demo_Mode preset (R-01.5, R-12.1): seven Objects must stay distinct after the
// backend's case-insensitive dedupe. Drift from the seed file is checked in the backend test
// suite (backend/tests/test_docs.py), which can read both files.
import { describe, expect, it } from "vitest";

import { DEMO_PRESET } from "./demoPreset";

describe("DEMO_PRESET", () => {
  it("keeps exactly seven objects after case-insensitive dedupe", () => {
    const unique = new Set(DEMO_PRESET.objects.map((o) => o.trim().toLowerCase()));
    expect(DEMO_PRESET.objects).toHaveLength(7);
    expect(unique.size).toBe(7);
  });
});
