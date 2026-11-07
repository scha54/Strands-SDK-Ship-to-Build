import {
  CAPABILITIES,
  CAPABILITY_LABELS,
  type Capability,
} from "./access";

export interface AccessModeSelectorProps {
  avoid: readonly Capability[];
  onChange: (next: Capability[]) => void;
}

/** Facilitator choice of capabilities to avoid; each box is labeled (R-09.3, R-09.8). */
export function AccessModeSelector({
  avoid,
  onChange,
}: AccessModeSelectorProps): React.JSX.Element {
  return (
    <fieldset>
      <legend>Access options</legend>
      {CAPABILITIES.map((c) => (
        <label key={c} style={{ display: "block" }}>
          <input
            type="checkbox"
            checked={avoid.includes(c)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...avoid, c]
                  : avoid.filter((x) => x !== c),
              )
            }
          />{" "}
          {CAPABILITY_LABELS[c]}
        </label>
      ))}
    </fieldset>
  );
}
