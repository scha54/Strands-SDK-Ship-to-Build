import "./base.css";

/**
 * Mobile-first application shell.
 *
 * Provides the single-column, reflow-safe frame (R-09.5 / NFR-04) that feature
 * screens render into. A skip link and semantic landmarks support keyboard and
 * assistive-technology users (R-09.1 / NFR-03).
 */
export interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps): React.JSX.Element {
  return (
    <div className="ic-app">
      <a className="ic-skip-link" href="#ic-main">
        Skip to main content
      </a>
      <main id="ic-main" className="ic-app__main ic-stack" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}

export default AppLayout;
