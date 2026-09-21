import { I } from "../icons";
import { t } from "../lib/i18n";
import { NexusLockup } from "./NexusLogo";

const REPO_URL = "https://github.com/Ghali-BenBouzid/nexus";
const PORTFOLIO_URL = "https://ghalibenbouzid.com";

// ---- What it is: plain intro, proof row, and a quiet "built with" strip ----
export function About() {
  return (
    <section className="section" id="about">
      <div className="wrap">
        <div className="section-head">
          <h2>{t.about.title}</h2>
          <p>{t.about.body}</p>
        </div>
        <ul className="proof-row">
          {t.about.proof.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
        <div className="built-with">
          <span className="built-with-label">{t.about.builtWithLabel}</span>
          <div className="stack-grid">
            {t.about.builtWith.map((group) => (
              <div className="stack-col" key={group.label}>
                <h3 className="stack-col-head">{group.label}</h3>
                <ul className="stack-col-list">
                  {group.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="about-links">
          <a className="btn btn-ghost" href={REPO_URL} target="_blank" rel="noreferrer">
            {t.about.sourceLink}
          </a>
        </div>
      </div>
    </section>
  );
}

// ---- How it works: the short version, and the way to the long one ----
export function HowItWorks({ onDeepDive }: { onDeepDive: () => void }) {
  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="section-head">
          <h2>{t.hiw.title}</h2>
          <p>{t.hiw.body}</p>
        </div>
        {/* The way through to the long version. A pill would read as one more
            link in a page full of them, so it is a card that shows what it
            opens: a document, its subject, and somewhere to go. */}
        <button className="hiw-cta" onClick={onDeepDive}>
          <span className="hiw-cta-ic" aria-hidden="true">{I.doc}</span>
          <span className="hiw-cta-main">
            <span className="hiw-cta-title">{t.hiw.cta}</span>
            <span className="hiw-cta-sub">{t.hiw.ctaSub}</span>
          </span>
          <span className="hiw-cta-go" aria-hidden="true">{I.arrowRight}</span>
        </button>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer-brand">
          <div className="brand">
            <NexusLockup size={24} />
          </div>
          <p>
            {t.footer.builtBy}
            <br />
            {t.footer.restPre}
            <a className="footer-loop" href={PORTFOLIO_URL} target="_blank" rel="noreferrer">
              ghalibenbouzid.com
            </a>
            {t.footer.restPost}
          </p>
        </div>
        <div className="footer-cols">
          <div className="footer-col">
            <h3>{t.footer.exploreTitle}</h3>
            <a href="#about">{t.nav.about}</a>
            <a href="#how">{t.nav.how}</a>
            <a href="/how">{t.nav.deepDive}</a>
          </div>
          <div className="footer-col">
            <h3>{t.footer.codeTitle}</h3>
            <a href={REPO_URL} target="_blank" rel="noreferrer">{t.footer.source}</a>
            <a href={`${REPO_URL}/tree/main/app`} target="_blank" rel="noreferrer">{t.footer.agentOrch}</a>
          </div>
        </div>
      </div>
      <div className="wrap">
        <div className="footer-note">{t.footer.note}</div>
      </div>
    </footer>
  );
}
