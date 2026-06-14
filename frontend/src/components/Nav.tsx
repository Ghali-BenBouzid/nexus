import { I } from "../icons";
import { lang, setLang, t } from "../lib/i18n";
import type { Theme } from "../types";
import { NexusLockup } from "./NexusLogo";

const REPO_URL = "https://github.com/Ghali-BenBouzid/nexus";

type NavProps = {
  theme: Theme;
  toggleTheme: () => void;
  onLogo: () => void;
  scrolled: boolean;
  onStart: () => void;
  onHistory?: () => void;
  showLinks?: boolean;
};

export function Nav({ theme, toggleTheme, onLogo, scrolled, onStart, onHistory, showLinks = true }: NavProps) {
  return (
    <nav className={"nav" + (scrolled ? " scrolled" : "")}>
      <div className="wrap">
        <div className="nav-left">
          {onHistory && (
            <button className="nav-rail" onClick={onHistory} aria-label={t.nav.recent} title={t.nav.recent}>
              {I.sidebar}
            </button>
          )}
          <div className="brand" onClick={onLogo}>
            <NexusLockup size={20} />
          </div>
          <a className="nav-link nav-gh" href={REPO_URL} target="_blank" rel="noreferrer">{I.github}{t.nav.source}</a>
        </div>
        {showLinks && (
          <div className="nav-links">
            <a className="nav-link" href="#about">{t.nav.about}</a>
            <a className="nav-link" href="#how">{t.nav.how}</a>
            <a className="nav-link" href="#engineering">{t.nav.engineering}</a>
          </div>
        )}
        <div className="nav-right">
          <button
            className="nav-link nav-lang"
            onClick={() => setLang(lang === "en" ? "fr" : "en")}
            title={lang === "en" ? "Voir en français" : "View in English"}
          >
            {lang === "en" ? "Français" : "English"}
          </button>
          <button className="theme-toggle" onClick={toggleTheme} aria-label={t.nav.theme} title={t.nav.theme}>
            {theme === "dark" ? I.sun : I.moon}
          </button>
          {showLinks && (
            <button className="btn btn-primary" onClick={onStart}>{t.nav.start}</button>
          )}
        </div>
      </div>
    </nav>
  );
}
