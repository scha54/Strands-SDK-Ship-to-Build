import "./SupervisionNotice.css";

/**
 * Adult-supervision notice shown on every Lesson-content screen (R-08.4).
 *
 * The notice reminds the facilitator that an adult must supervise the activity
 * and never encourages secrecy or emotional dependency. It renders as a
 * landmark region so assistive technology can announce it (R-09.1 / NFR-03).
 */

const DEFAULT_MESSAGE =
  "An adult should supervise this activity. Stay together, keep it in the open, " +
  "and stop any time you want.";

export interface SupervisionNoticeProps {
  /** Optional override message. Defaults to the standard supervision reminder. */
  message?: string;
}

export function SupervisionNotice({
  message = DEFAULT_MESSAGE,
}: SupervisionNoticeProps): React.JSX.Element {
  return (
    <aside
      className="ic-supervision-notice"
      role="note"
      aria-label="Adult supervision notice"
      data-testid="supervision-notice"
    >
      <span className="ic-supervision-notice__icon" aria-hidden="true">
        &#9888;
      </span>
      <p className="ic-supervision-notice__text">{message}</p>
    </aside>
  );
}

export default SupervisionNotice;
