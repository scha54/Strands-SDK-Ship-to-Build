import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppLayout } from "./app/AppLayout";
import { SupervisionNotice } from "./components/SupervisionNotice";

// Entry point. Feature routes are wired in later tasks; the scaffold mounts the
// mobile-first layout (R-09.5 / NFR-04) with the shared supervision notice
// (R-08.4) so the shell is runnable end-to-end.
const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <AppLayout>
      <h1>The Invisible Classroom</h1>
      <SupervisionNotice />
      <p>Turn everyday objects into safe, hands-on learning adventures.</p>
    </AppLayout>
  </StrictMode>,
);
