import { useState } from "react";

export interface SessionControlsProps {
  stopped: boolean;
  ended: boolean;
  busy: boolean;
  onStop: () => void;
  onEnd: () => void;
  onDelete: () => void;
}

/**
 * Stop, End and Delete controls (R-08.3, R-10.4). Stop and End are hidden
 * once they no longer apply; Delete always asks for confirmation first.
 */
export function SessionControls({
  stopped,
  ended,
  busy,
  onStop,
  onEnd,
  onDelete,
}: SessionControlsProps): React.JSX.Element {
  const [confirming, setConfirming] = useState(false);

  return (
    <nav aria-label="Session controls" className="ic-session-controls">
      {!stopped && !ended && (
        <button type="button" disabled={busy} onClick={onStop}>
          Stop
        </button>
      )}
      {!stopped && !ended && (
        <button type="button" disabled={busy} onClick={onEnd}>
          End session
        </button>
      )}
      {!confirming ? (
        <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
          Delete session
        </button>
      ) : (
        <span role="group" aria-label="Confirm delete">
          <span>Delete this session and everything saved in it?</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setConfirming(false);
              onDelete();
            }}
          >
            Yes, delete
          </button>
          <button type="button" onClick={() => setConfirming(false)}>
            Keep session
          </button>
        </span>
      )}
    </nav>
  );
}
