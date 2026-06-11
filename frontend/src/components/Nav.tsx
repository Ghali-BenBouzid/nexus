import { I } from "../icons";
import type { Theme } from "../types";

type NavProps = {
  theme: Theme;
  toggleTheme: () => void;
  onLogo: () => void;
  scrolled: boolean;
  onStart: () => void;
};

export function Nav({ theme, toggleTheme, onLogo, scrolled, onStart }: NavProps) {
  return (
    <nav className={"nav" + (scrolled ? " scrolled" : "")}>
      <div className="wrap">
        <div className="brand" onClick={onLogo}>
          <div className="brand-mark">≈</div>
          <span className="brand-name">Nexus</span>
        </div>
        <div className="nav-links">
          <a className="nav-link" href="#how">How it works</a>
          <a className="nav-link" href="#feed">Live agents</a>
          <a className="nav-link" href="#sources">Citations</a>
          <a className="nav-link" href="#soon">Documents</a>
        </div>
        <div className="nav-right">
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme" title="Toggle theme">
            {theme === "dark" ? I.sun : I.moon}
          </button>
          <a className="nav-link" href="#">Sign in</a>
          <button className="btn btn-primary" onClick={onStart}>Start researching</button>
        </div>
      </div>
    </nav>
  );
}
