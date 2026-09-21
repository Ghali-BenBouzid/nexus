// Lightweight, framework-free i18n. The language is resolved once at module load
// from the browser's default (French if the primary preference is French, English
// otherwise) and never changes during a session, so components import the already
// resolved `t` dictionary and re-render nothing. Backend-streamed agent text stays
// in whatever language the API returns; this only covers the static UI.

export type Lang = "fr" | "en";

const STORAGE_KEY = "nexus-lang";

function storedLang(): Lang | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "fr" || v === "en" ? v : null;
  } catch {
    return null;
  }
}

function detect(): Lang {
  // A ?lang=fr / ?lang=en query param wins (handy for previewing). Otherwise
  // English is the default for everyone; French is used only when the visitor
  // has explicitly chosen it via the language switch, never switched
  // automatically from the browser locale.
  if (typeof window !== "undefined") {
    const forced = new URLSearchParams(window.location.search).get("lang");
    if (forced === "fr" || forced === "en") return forced;
  }
  return storedLang() ?? "en";
}

export const lang: Lang = detect();

if (typeof document !== "undefined") document.documentElement.lang = lang;

// Persist the choice and reload so the resolved-once dictionary is rebuilt.
export function setLang(next: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined") window.location.reload();
}

const en = {
  docTitle: "Nexus, deep research, cited",
  nav: {
    about: "About",
    how: "How it works",
    source: "Source",
    start: "Start researching",
    recent: "Recent chats",
    theme: "Toggle theme",
    home: "Nexus home page",
  },
  hero: {
    headline: "Ask anything. Every claim, sourced.",
    sub: "Nexus plans your question, sends agents to research the live web, and returns one fully-cited report.\nEvery claim links back to its source, so you can check the work yourself.",
    placeholder: "Ask Nexus to research anything…",
    examplesLabel: "Try one of these examples",
    chips: [
      "What are the most promising approaches to grid-scale energy storage in 2026?",
      "How are small language models changing on-device AI in 2026?",
    ],
  },
  about: {
    title: "About",
    body: "Nexus is an agentic research platform. You ask a question, a team of agents plans it, researches the live web, and writes back a single report where every claim links to its source. I designed and built all of it: the backend, the agent orchestration, and the frontend.",
    proof: ["Open source", "Invite-only live demo"],
    builtWithLabel: "Built with",
    builtWith: [
      { label: "Backend", items: ["FastAPI", "Python", "LangGraph", "Postgres", "Redis"] },
      { label: "Frontend", items: ["React", "TypeScript", "three.js"] },
      { label: "Deployment", items: ["Railway", "Neon", "Cloudflare"] },
    ],
    sourceLink: "Source on GitHub",
  },
  hiw: {
    title: "How it works",
    default: "Hover or tap a step to see what it does, and why it's built that way.",
    parts: {
      supervisor: "The agent you actually talk to. It runs a small tool loop over the conversation, can pull up the full reports already gathered, and commits to one of three moves: answer straight from those reports, compose them into one new report, or start a fresh research run. A follow-up the existing sources already cover never pays for a new run.",
      compose: "When you ask to combine or deepen reports you already have, the supervisor merges them into one new report, reusing the same writer with no new web search. Code re-numbers the citations across the merged sources, so the references stay correct.",
      plan: "A forced function call returns the sub-questions as structured data, never prose. The plan is machine-checkable, so the rest of the pipeline can trust its shape instead of parsing free text.",
      review: "Before any web research runs, the plan is handed back to you. Approve it and the agents go; or send it back with a note and it loops to re-plan. Nothing spends quota until you say go.",
      researcher: "Each sub-question runs as its own tool-using agent, with web search and page-fetch and a capped iteration budget. The orchestrator runs them in parallel, with a cap on how many run at once.",
      documents: "Planned. The same agent loop pointed at your own uploaded documents, running alongside the web agents inside the same orchestrator.",
      consolidate: "Plain code, no model. It dedupes the sources by URL and assigns the citation numbers itself. Because no model ever chooses or writes a citation, the surface where one could be hallucinated is removed.",
      write: "A single model call turns the findings into prose. It only keeps the citation markers the code already assigned and is told to add no facts of its own, so the writing step can't invent a source either.",
    } as Record<string, string>,
    labels: {
      orchestrator: "Orchestrator",
      message: "message",
      citedReport: "cited report",
      directAnswer: "direct answer",
      fanout: "fan-out",
      supervisor: "Supervisor",
      supervisorRole: "the agent you talk to",
      compose: "Compose",
      composeRole: "merge, no search",
      routeCompose: "compose",
      routeResearch: "research",
      review: "Your review",
      reviewRole: "approve / revise",
      confirm: "confirm",
      revise: "revise",
      plan: "Plan",
      planRole: "decompose",
      researcher: "Researcher",
      documents: "Documents",
      docRole: "RAG · next",
      consolidate: "Consolidate",
      consolidateRole: "no LLM",
      write: "Write",
      writeRole: "cite [n]",
    },
    stack: [
      { lead: "Supervisor", rest: " reads your message and answers from the existing reports, merges them into one new report, or starts a research run." },
      { lead: "Plan", rest: " breaks the question into focused sub-questions, and you confirm the plan before any research runs." },
      { lead: "Research ×N", rest: " one tool-using agent per sub-question reads the live web, all in parallel." },
      { lead: "Documents", rest: " research your own files alongside the web (RAG, next)." },
      { lead: "Consolidate", rest: " plain code dedupes and numbers the sources, no model." },
      { lead: "Write", rest: " a grounded report; every claim points to a numbered source." },
    ],
    aria: "A supervisor agent reads each message and either answers directly, composes the existing reports into one new report, or starts a research run: the research subgraph plans the question, you confirm the plan, a fan-out of researcher agents gathers sources, then a consolidation step and a writer turn it into a cited report.",
  },
  footer: {
    builtBy: "Built by Ghali Ben Bouzid.",
    restPre: "The rest of my work is at ",
    restPost: ".",
    exploreTitle: "Explore",
    codeTitle: "Code",
    source: "Source on GitHub",
    agentOrch: "Agent orchestration",
    note: "Nexus, deep research, cited. FastAPI and Python on the back, React on the front, agent orchestration on LangGraph and OpenRouter.",
  },
  chat: {
    runningPlaceholder: "Researching… stop to ask something new",
    idlePlaceholder: "Ask a follow-up, or start a new search…",
    jumpLatest: "Jump to latest",
    showArtifacts: "Show outputs",
  },
  access: {
    credits: (percent: number) => `${percent}% of your demo credits left`,
    invalid: "This invite link is not valid.",
    none: "Live research needs an invite link.",
  },
  demo: {
    title: "Live research is invite-only",
    body: "Each run uses real models and live web searches, so access comes with a demo account. Message me on LinkedIn and I'll set one up for you.",
    cta: "Get a demo account",
    later: "Not now",
  },
  turn: {
    reportReady: "Report ready",
    viewInPanel: "View in panel",
    openReport: "Open report",
    sourcesUsed: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
    emptyNote: "No sources found for this question.",
    tryRewording: "Try rewording",
    stoppedNote: "You stopped this run.",
    rerun: "Re-run",
    runFailed: "Run failed",
    defaultError: "A system error stopped the research before it finished.",
    tryAgain: "Try again",
  },
  artifact: {
    back: "Back to artifacts",
    report: "Report",
    closePanel: "Close panel",
    copy: "Copy report",
    rerun: "Re-run",
    refresh: "Refresh report",
    sourcesHead: "Sources",
    cited: (n: number) => `${n} cited`,
    // The count is everything the run opened, cited or not, which is what
    // "consulted" means: the old label counted only the uncited leftovers.
    allConsulted: (n: number) => `All ${n} consulted`,
    onlyCited: (n: number) => `Only the ${n} cited`,
    unanswered: (n: number) => `Unanswered · ${n}`,
    emptyFailed: "This run didn't produce a report.",
    emptyNoCite: "No report: the agents found nothing to cite for this question.",
    emptyPending: "The report will appear here once the agents finish.",
    title: "Outputs",
    noReports: "No reports yet. Ask for deep research, or fact-check a document.",
    running: "Working…",
    failed: "Failed",
    deep_research: "Deep research",
    fact_check: "Fact check",
    openedElsewhere: "From another chat",
  },
  uploads: {
    title: "Uploads",
    empty: "No files attached.",
    add: "Attach a file",
    remove: "Remove",
    factCheck: "Fact-check",
    failed: "The file could not be uploaded.",
    ocr: "read by OCR",
    truncated: "shortened",
    pages: (n: number) => (n === 1 ? "1 page" : `${n} pages`),
    ready: (name: string) => `${name} is attached. Ask about it, or fact-check it.`,
  },
  outputs: {
    ready: (title: string) => `${title} is ready.`,
    open: "Open",
    dismiss: "Dismiss",
  },
  history: {
    recent: "Recent",
    loading: "Loading…",
    empty: "No conversations yet.",
    untitled: "Untitled chat",
    close: "Close history",
    collapse: "Collapse",
    expand: "Recent",
    newChat: "New chat",
    status: (s: string) => s,
  },
  // The run's progress bar (the backend emits event types; the UI words them).
  progress: {
    understanding: "Reading your request",
    planning: "Planning the research",
    planned: (n: number) => `Planned ${n} sub-question${n === 1 ? "" : "s"}`,
    answering: "Writing the answer",
    answered: "Answered",
    readingDocument: (name: string) => `reading ${name}`,
    deepStarted: (title: string) => `Started deep research${title ? `: ${title}` : ""}`,
    factCheckStarted: (name: string) => `Started a fact check${name ? `: ${name}` : ""}`,
    inOutputs: "in Outputs",
    researching: (active: number, total: number) =>
      `${active} of ${total} researcher${total === 1 ? "" : "s"} searching the web`,
    researchDone: "Research done",
    writing: "Writing the report",
    written: "Report written",
    ready: "Report ready",
    researched: (n: number) => `Researched ${n} question${n === 1 ? "" : "s"}`,
    thoughtFor: (time: string) => `Thought for ${time}`,
    stopped: "Stopped",
    failed: "Failed",
    thinking: "thinking",
    searching: (query: string) => `searching "${query}"`,
    readingPage: (domain: string) => `reading ${domain}`,
    starting: "starting",
    found: "found information",
    empty: "nothing relevant found",
    couldNot: "could not research",
    stoppedHere: "stopped",
    unfinished: "did not finish",
    stale: (time: string) => `no response for ${time}, the run may be stuck`,
  },
  count: {
    sources: (n: number) => `${n} source${n === 1 ? "" : "s"}`,
    gaps: (n: number) => `${n} gap${n === 1 ? "" : "s"}`,
  },
};

type Dict = typeof en;

const fr: Dict = {
  docTitle: "Nexus, recherche approfondie et sourcée",
  nav: {
    about: "À propos",
    how: "Fonctionnement",
    source: "Source",
    start: "Lancer une recherche",
    recent: "Conversations récentes",
    theme: "Changer de thème",
    home: "Accueil de Nexus",
  },
  hero: {
    headline: "Posez une question. Chaque affirmation est sourcée.",
    sub: "Nexus décompose votre question, envoie des agents chercher sur le web en direct, et produit un seul rapport référencé. Chaque affirmation renvoie à sa source, vous pouvez donc vérifier le travail vous-même.",
    placeholder: "Demandez une recherche à Nexus…",
    examplesLabel: "Essayez l'un de ces exemples",
    chips: [
      "Quelles sont les approches les plus prometteuses pour le stockage d'énergie à l'échelle du réseau en 2026 ?",
      "Comment les petits modèles de langage transforment-ils l'IA embarquée en 2026 ?",
    ],
  },
  about: {
    title: "À propos",
    body: "Nexus est une plateforme de recherche agentique. Vous posez une question, une équipe d'agents la décompose, cherche sur le web en direct, et vous remet un seul rapport dont chaque affirmation renvoie à sa source. J'ai tout conçu et construit : la partie serveur, l'orchestration des agents et l'interface.",
    proof: ["Open source", "Démo en direct sur invitation"],
    builtWithLabel: "Construit avec",
    builtWith: [
      { label: "Partie serveur", items: ["FastAPI", "Python", "LangGraph", "Postgres", "Redis"] },
      { label: "Interface", items: ["React", "TypeScript", "three.js"] },
      { label: "Déploiement", items: ["Railway", "Neon", "Cloudflare"] },
    ],
    sourceLink: "Code sur GitHub",
  },
  hiw: {
    title: "Fonctionnement",
    default: "Survolez ou touchez une étape pour voir ce qu'elle fait, et pourquoi elle est construite ainsi.",
    parts: {
      supervisor: "L'agent à qui vous parlez vraiment. Il lit votre message dans le contexte de la conversation, peut rouvrir les rapports déjà produits ou faire une vérification web rapide, puis tranche entre trois options : répondre directement à partir de ces rapports, les fusionner en un nouveau rapport, ou lancer une recherche. Une question de suivi déjà couverte par les sources existantes ne relance jamais de recherche.",
      compose: "Quand vous demandez de combiner ou d'approfondir des rapports déjà produits, le superviseur les fusionne en un nouveau rapport, avec le même rédacteur et sans nouvelle recherche web. Le code renumérote ensuite les citations sur l'ensemble des sources fusionnées, pour que les références restent justes.",
      plan: "Un appel de fonction forcé renvoie les sous-questions sous forme de données structurées, jamais en texte libre. Le plan est vérifiable par la machine, donc le reste de la chaîne peut y faire confiance sans avoir à analyser du texte.",
      review: "Avant toute recherche web, le plan vous est rendu. Vous l'approuvez et les agents partent ; ou vous le renvoyez avec une note et il repart en planification. Rien ne consomme de quota tant que vous n'avez pas dit go.",
      researcher: "Chaque sous-question est confiée à un agent doté d'outils de recherche web et de lecture de pages, avec un budget d'itérations plafonné. L'orchestrateur les lance en parallèle, avec un plafond sur le nombre exécuté en même temps.",
      documents: "Prévu. La même boucle d'agent pointée sur vos propres documents, tournant aux côtés des agents web dans le même orchestrateur.",
      consolidate: "Du code simple, sans modèle. Il dédoublonne les sources par URL et attribue lui-même les numéros de citation. Comme aucun modèle ne choisit ni n'écrit de citation, la surface où elle pourrait être inventée disparaît.",
      write: "Un seul appel au modèle transforme les résultats en prose. Il ne garde que les marqueurs de citation déjà attribués par le code et reçoit la consigne de n'ajouter aucun fait, donc l'étape de rédaction ne peut pas inventer de source non plus.",
    } as Record<string, string>,
    labels: {
      orchestrator: "Orchestrateur",
      message: "message",
      citedReport: "rapport sourcé",
      directAnswer: "réponse directe",
      fanout: "fan-out",
      supervisor: "Superviseur",
      supervisorRole: "l'agent à qui vous parlez",
      compose: "Composer",
      composeRole: "sans recherche",
      routeCompose: "composer",
      routeResearch: "rechercher",
      review: "Vous validez",
      reviewRole: "valider / réviser",
      confirm: "confirmer",
      revise: "réviser",
      plan: "Planifier",
      planRole: "décomposer",
      researcher: "Chercheur",
      documents: "Documents",
      docRole: "RAG · à venir",
      consolidate: "Consolider",
      consolidateRole: "sans LLM",
      write: "Rédiger",
      writeRole: "citer [n]",
    },
    stack: [
      { lead: "Superviseur", rest: " lit votre message, puis répond à partir des rapports existants, les fusionne en un nouveau, ou lance une recherche." },
      { lead: "Planifier", rest: " découpe la question en sous-questions ciblées, et vous confirmez le plan avant toute recherche." },
      { lead: "Recherche ×N", rest: " un agent outillé par sous-question lit le web en direct, tous en parallèle." },
      { lead: "Documents", rest: " cherchent dans vos propres fichiers en parallèle du web (RAG, à venir)." },
      { lead: "Consolider", rest: " du code simple dédoublonne et numérote les sources, sans modèle." },
      { lead: "Rédiger", rest: " un rapport fondé ; chaque affirmation pointe vers une source numérotée." },
    ],
    aria: "Un superviseur lit chaque message, puis répond directement, fusionne les rapports déjà produits en un nouveau rapport, ou lance une recherche : le sous-graphe de recherche planifie la question, vous confirmez le plan, plusieurs agents chercheurs rassemblent les sources en parallèle, puis une étape de consolidation et un rédacteur en font un rapport sourcé.",
  },
  footer: {
    builtBy: "Construit par Ghali Ben Bouzid.",
    restPre: "Le reste de mon travail est sur ",
    restPost: ".",
    exploreTitle: "Explorer",
    codeTitle: "Code",
    source: "Code sur GitHub",
    agentOrch: "Orchestration des agents",
    note: "Nexus, recherche approfondie, sourcée. FastAPI et Python côté serveur, React côté interface, orchestration d'agents avec LangGraph sur OpenRouter.",
  },
  chat: {
    runningPlaceholder: "Recherche en cours… arrêtez pour poser autre chose",
    idlePlaceholder: "Posez une question de suivi, ou lancez une nouvelle recherche…",
    jumpLatest: "Aller au plus récent",
    showArtifacts: "Afficher les résultats",
  },
  access: {
    credits: (percent: number) => `Il vous reste ${percent} % de vos crédits de démo`,
    invalid: "Ce lien d'invitation n'est pas valide.",
    none: "La recherche en direct nécessite un lien d'invitation.",
  },
  demo: {
    title: "La recherche en direct est sur invitation",
    body: "Chaque recherche utilise de vrais modèles et des recherches web en direct, l'accès passe donc par un compte de démo. Écrivez-moi sur LinkedIn et je vous en crée un.",
    cta: "Obtenir un compte de démo",
    later: "Plus tard",
  },
  turn: {
    reportReady: "Rapport prêt",
    viewInPanel: "Voir dans le panneau",
    openReport: "Ouvrir le rapport",
    sourcesUsed: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
    emptyNote: "Aucune source trouvée pour cette question.",
    tryRewording: "Reformuler",
    stoppedNote: "Vous avez arrêté cette recherche.",
    rerun: "Relancer",
    runFailed: "Échec de la recherche",
    defaultError: "Une erreur système a interrompu la recherche avant la fin.",
    tryAgain: "Réessayer",
  },
  artifact: {
    back: "Retour aux rapports",
    report: "Rapport",
    closePanel: "Fermer le panneau",
    copy: "Copier le rapport",
    rerun: "Relancer",
    refresh: "Actualiser le rapport",
    sourcesHead: "Sources",
    cited: (n: number) => `${n} citée${n > 1 ? "s" : ""}`,
    allConsulted: (n: number) => `Les ${n} consultées`,
    onlyCited: (n: number) => `Les ${n} citées seulement`,
    unanswered: (n: number) => `Sans réponse · ${n}`,
    emptyFailed: "Cette recherche n'a pas produit de rapport.",
    emptyNoCite: "Pas de rapport : les agents n'ont rien trouvé à citer pour cette question.",
    emptyPending: "Le rapport apparaîtra ici une fois les agents terminés.",
    title: "Résultats",
    noReports: "Aucun rapport pour l'instant. Demandez une recherche approfondie, ou vérifiez un document.",
    running: "En cours…",
    failed: "Échec",
    deep_research: "Recherche approfondie",
    fact_check: "Vérification",
    openedElsewhere: "Depuis une autre conversation",
  },
  uploads: {
    title: "Fichiers",
    empty: "Aucun fichier joint.",
    add: "Joindre un fichier",
    remove: "Retirer",
    factCheck: "Vérifier",
    failed: "Le fichier n'a pas pu être envoyé.",
    ocr: "lu par OCR",
    truncated: "tronqué",
    pages: (n: number) => (n === 1 ? "1 page" : `${n} pages`),
    ready: (name: string) =>
      `${name} est joint. Posez une question dessus, ou faites-le vérifier.`,
  },
  outputs: {
    ready: (title: string) => `${title} est prêt.`,
    open: "Ouvrir",
    dismiss: "Ignorer",
  },
  history: {
    recent: "Récent",
    loading: "Chargement…",
    empty: "Aucune conversation pour l'instant.",
    untitled: "Discussion sans titre",
    close: "Fermer l'historique",
    collapse: "Réduire",
    expand: "Récent",
    newChat: "Nouvelle conversation",
    status: (s: string) =>
      ({
        pending: "en attente",
        running: "en cours",
        complete: "terminé",
        failed: "échec",
      })[s] ?? s,
  },
  progress: {
    understanding: "Lecture de votre demande",
    planning: "Planification de la recherche",
    planned: (n: number) => `${n} sous-question${n > 1 ? "s" : ""} planifiée${n > 1 ? "s" : ""}`,
    answering: "Rédaction de la réponse",
    answered: "Répondu",
    readingDocument: (name: string) => `lecture de ${name}`,
    deepStarted: (title: string) =>
      `Recherche approfondie lancée${title ? ` : ${title}` : ""}`,
    factCheckStarted: (name: string) => `Vérification lancée${name ? ` : ${name}` : ""}`,
    inOutputs: "dans Résultats",
    researching: (active: number, total: number) =>
      `${active} chercheur${active > 1 ? "s" : ""} sur ${total} en recherche sur le web`,
    researchDone: "Recherche terminée",
    writing: "Rédaction du rapport",
    written: "Rapport rédigé",
    ready: "Rapport prêt",
    researched: (n: number) => `${n} question${n > 1 ? "s" : ""} étudiée${n > 1 ? "s" : ""}`,
    thoughtFor: (time: string) => `A réfléchi pendant ${time}`,
    stopped: "Arrêté",
    failed: "Échec",
    thinking: "réflexion",
    searching: (query: string) => `recherche « ${query} »`,
    readingPage: (domain: string) => `lecture de ${domain}`,
    starting: "démarrage",
    found: "informations trouvées",
    empty: "rien de pertinent",
    couldNot: "recherche impossible",
    stoppedHere: "arrêté",
    unfinished: "non terminé",
    stale: (time: string) => `aucune réponse depuis ${time}, la recherche est peut-être bloquée`,
  },
  count: {
    sources: (n: number) => `${n} source${n > 1 ? "s" : ""}`,
    gaps: (n: number) => `${n} lacune${n > 1 ? "s" : ""}`,
  },
};

export const t: Dict = lang === "fr" ? fr : en;
if (typeof document !== "undefined") document.title = t.docTitle;
