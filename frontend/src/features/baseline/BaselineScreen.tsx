import type { QuestionView } from "../../api/learning";
import { ScaleQuestion } from "./ScaleQuestion";

export interface BaselineScreenProps {
  question: QuestionView;
  busy: boolean;
  onSubmit: (answer: number | null) => void;
}

/** Baseline screen, displayed before any other Lesson content (R-07.1). */
export function BaselineScreen(props: BaselineScreenProps): React.JSX.Element {
  return <ScaleQuestion heading="Before we start" {...props} />;
}
