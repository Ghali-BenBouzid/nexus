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
          <a className="nav-link nav-gh" href={REPO_URL} target="_blank" rel="noreferrer" aria-label={t.nav.source} title={t.nav.source}>
            {I.github}
            <span className="nav-gh-text">{t.nav.source}</span>
          </a>
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
            <span className="nav-lang-full">{lang === "en" ? "Français" : "English"}</span>
            <span className="nav-lang-short">{lang === "en" ? "FR" : "EN"}</span>
          </button>
          <button className="theme-toggle" onClick={toggleTheme} aria-label={t.nav.theme} title={t.nav.theme}>
            {theme === "dark" ? I.sun : I.moon}
          </button>
          {showLinks && (
            <button className="btn btn-primary nav-start" onClick={onStart} aria-label={t.nav.start} title={t.nav.start}>
              <span className="nav-start-label">{t.nav.start}</span>
              <span className="nav-start-icon" aria-hidden="true">{I.search}</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
