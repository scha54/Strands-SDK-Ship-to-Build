import type { QuestionView } from "../../api/learning";
import { ScaleQuestion } from "./ScaleQuestion";

export interface EndCheckScreenProps {
  question: QuestionView;
  busy: boolean;
  onSubmit: (answer: number | null) => void;
}

/** End-check screen: same topic and scale as the baseline (R-07.2). */
export function EndCheckScreen(props: EndCheckScreenProps): React.JSX.Element {
  return <ScaleQuestion heading="One last check" {...props} />;
}
