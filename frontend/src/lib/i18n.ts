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
  docTitle: "Nexus, answers you can check",
  nav: {
    about: "About",
    how: "How it works",
    deepDive: "Technical deep dive",
    source: "Source",
    start: "Start researching",
    recent: "Recent chats",
    theme: "Toggle theme",
    home: "Nexus home page",
  },
  hero: {
    headline: "Ask a question. See where the answer came from.",
    sub: "Nexus reads the web and answers you in the chat, with every claim linked to the page it came from.\nAsk it to go deeper and it writes a full report. Give it a document and it checks what the document claims.",
    placeholder: "Ask anything, or attach a document",
    examplesLabel: "Try one of these examples",
    chips: [
      "What are the most promising approaches to grid-scale energy storage in 2026?",
      "How are small language models changing on-device AI in 2026?",
    ],
  },
  about: {
    title: "About",
    body: "Nexus is a research assistant. You ask a question in a chat and it answers, doing whatever work the question turns out to need: nothing, one search, or a team of agents reading the web in parallel. Every claim links to the page it came from. It also runs longer jobs in the background: a full report on a question, or a fact check of a document you upload. I designed and built all of it: the backend, the agent orchestration, and the frontend.",
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
    body: "You send a message. One agent decides what answering it actually takes: nothing, a single search, or a team of researchers reading the web in parallel. Citations are assigned by code as each page comes back, so the model can only cite something that was really read.",
    cta: "Read the technical deep dive",
  },
  deep: {
    title: "How Nexus works",
    lede: "Two diagrams and the reasoning behind them: what happens to a message inside the system, and where that system runs. Written to be readable whether or not you write code.",
    back: "Back to Nexus",
    source: "Read the source on GitHub",

    agentTitle: "What happens to a message",
    agentBody: "There is no menu of modes and no classifier deciding which one you meant. A single supervisor agent reads your message and works out what answering it takes, then does that work and writes the reply itself. \"Does this need research?\" is a judgement, and a model makes it well where a classifier makes it badly.",
    agentAria: "A supervisor agent receives each message and reaches for tools as it needs them: web search and page fetch, reading an uploaded document, a research run that plans sub-questions and fans out to parallel researchers, and two background runs, deep research and fact check, that write their own reports into Outputs.",
    agentNotes: [
      { lead: "Tools, not routes.", rest: " The dotted arrows are tools the supervisor may reach for, as many times as it needs. A follow-up its existing sources already cover costs nothing." },
      { lead: "The plan sizes itself.", rest: " A plain fact gets one sub-question, a three-way comparison gets six. A deep run plans up to twelve." },
      { lead: "Researchers run in parallel.", rest: " Each sub-question is its own agent with its own search budget. They share a time budget: when it runs out they submit what they have rather than losing the run to a timeout." },
      { lead: "Code assigns the citations.", rest: " A registry numbers each source as a tool returns it, and an agent can only cite a number it was handed. Anything else is stripped before you see it, so nothing in an answer can go beyond what was retrieved." },
    ],

    sysTitle: "Where it runs",
    sysBody: "The browser never waits on a model. The API saves your message, puts a job on a queue and returns; a separate worker runs the agents. The browser holds one stream open, so the thinking and the answer appear as they are written.",
    sysAria: "The browser loads the frontend from Cloudflare and calls a FastAPI service on Railway. The API writes to Neon Postgres and pushes jobs onto a Redis queue. A worker on Railway runs the agents, calling OpenRouter for models and Tavily for search, publishes each frame back through Redis, and the API forwards them to the browser as server-sent events.",
    sysNotes: [
      { lead: "A queue and a worker.", rest: " A run takes seconds to minutes. Running it inside the API meant a redeploy killed it. Now it outlives one, at the cost of a second process and Redis to keep alive." },
      { lead: "A heartbeat and a reaper.", rest: " The worker writes a heartbeat every few seconds; a scheduled check fails any run whose heartbeat stops, so a crashed job does not sit as \"running\" forever." },
      { lead: "Deep runs are checkpointed.", rest: " A deep run takes minutes, which is long enough for a deploy to land mid-run, so it is a LangGraph graph over a Postgres checkpointer. A worker picking it back up resumes from the last finished step instead of re-paying for researchers that already came back." },
      { lead: "Progress survives a reload.", rest: " Stages are written to Postgres and replayed when a stream opens, so a dropped connection costs a redraw rather than the answer. Tokens are never stored: the reply is saved whole when the turn ends." },
    ],

    sysLabels: {
      browser: "Browser",
      frontend: "React app",
      cdn: "Cloudflare",
      api: "FastAPI",
      apiRole: "accounts, runs, the feed",
      host: "Railway",
      queue: "Redis",
      queueRole: "queue + stream bus",
      worker: "Worker",
      workerRole: "runs the agents",
      db: "Postgres",
      dbRole: "Neon",
      models: "OpenRouter",
      search: "Tavily",
      stream: "server-sent events",
      job: "job",
      frames: "frames",
    },
    agentLabels: {
      message: "your message",
      supervisor: "Supervisor",
      supervisorRole: "decides and answers",
      answer: "cited answer",
      tools: "tools",
      search: "Web search + fetch",
      doc: "Read document",
      research: "Research",
      plan: "Plan",
      researchers: "Researchers ×N",
      parallel: "in parallel",
      deep: "Deep research",
      deepRole: "checkpointed, minutes",
      factCheck: "Fact check",
      factRole: "claims from a file",
      outputs: "Outputs",
      background: "background",
    },
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
    runningPlaceholder: "Working… stop to ask something else",
    idlePlaceholder: "Ask a follow-up, or something new…",
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
  docTitle: "Nexus, des réponses vérifiables",
  nav: {
    about: "À propos",
    how: "Fonctionnement",
    deepDive: "Le détail technique",
    source: "Source",
    start: "Lancer une recherche",
    recent: "Conversations récentes",
    theme: "Changer de thème",
    home: "Accueil de Nexus",
  },
  hero: {
    headline: "Posez une question. Voyez d'où vient la réponse.",
    sub: "Nexus lit le web et vous répond dans la conversation, chaque affirmation renvoyant à la page dont elle vient.\nDemandez-lui d'aller plus loin et il rédige un rapport complet. Donnez-lui un document et il vérifie ce qu'il affirme.",
    placeholder: "Posez une question, ou joignez un document",
    examplesLabel: "Essayez l'un de ces exemples",
    chips: [
      "Quelles sont les approches les plus prometteuses pour le stockage d'énergie à l'échelle du réseau en 2026 ?",
      "Comment les petits modèles de langage transforment-ils l'IA embarquée en 2026 ?",
    ],
  },
  about: {
    title: "À propos",
    body: "Nexus est un assistant de recherche. Vous posez une question dans une conversation et il y répond, en faisant le travail que la question demande vraiment : rien, une recherche, ou une équipe d'agents qui lisent le web en parallèle. Chaque affirmation renvoie à la page dont elle vient. Il lance aussi des travaux plus longs en arrière-plan : un rapport complet sur une question, ou la vérification d'un document que vous déposez. J'ai tout conçu et construit : la partie serveur, l'orchestration des agents et l'interface.",
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
    body: "Vous envoyez un message. Un agent détermine ce qu'il faut vraiment pour y répondre : rien, une seule recherche, ou une équipe de chercheurs qui lisent le web en parallèle. Les citations sont attribuées par le code à mesure que les pages reviennent : le modèle ne peut donc citer que ce qui a réellement été lu.",
    cta: "Lire le détail technique",
  },
  deep: {
    title: "Comment fonctionne Nexus",
    lede: "Deux schémas et le raisonnement derrière : ce qui arrive à un message dans le système, et où ce système tourne. Écrit pour être lisible que vous codiez ou non.",
    back: "Retour à Nexus",
    source: "Voir le code sur GitHub",

    agentTitle: "Ce qui arrive à un message",
    agentBody: "Il n'y a ni menu de modes ni classifieur qui devine ce que vous vouliez dire. Un seul agent superviseur lit votre message et détermine ce qu'il faut pour y répondre, puis fait ce travail et rédige lui-même la réponse. « Est-ce que ceci demande une recherche ? » est un jugement : un modèle le fait bien là où un classifieur le fait mal.",
    agentAria: "Un agent superviseur reçoit chaque message et mobilise les outils dont il a besoin : recherche web et lecture de page, lecture d'un document déposé, une recherche qui planifie des sous-questions et les répartit entre des chercheurs parallèles, et deux traitements en arrière-plan, la recherche approfondie et la vérification de document, qui écrivent leurs propres rapports dans Sorties.",
    agentNotes: [
      { lead: "Des outils, pas des aiguillages.", rest: " Les flèches en pointillés sont des outils que le superviseur mobilise, autant de fois qu'il le faut. Une question de suivi déjà couverte par ses sources ne coûte rien." },
      { lead: "Le plan se dimensionne seul.", rest: " Un fait simple donne une sous-question, une comparaison à trois en donne six. Une recherche approfondie va jusqu'à douze." },
      { lead: "Les chercheurs travaillent en parallèle.", rest: " Chaque sous-question est un agent avec son propre budget de recherche. Ils partagent un budget de temps : à son terme, ils rendent ce qu'ils ont plutôt que de perdre la recherche sur un dépassement." },
      { lead: "Le code attribue les citations.", rest: " Un registre numérote chaque source à mesure qu'un outil la renvoie, et un agent ne peut citer qu'un numéro qu'on lui a donné. Le reste est retiré avant affichage : rien dans une réponse ne peut dépasser ce qui a été réellement récupéré." },
    ],

    sysTitle: "Où ça tourne",
    sysBody: "Le navigateur n'attend jamais un modèle. L'API enregistre votre message, dépose un travail dans une file et répond ; un processus séparé exécute les agents. Le navigateur garde un flux ouvert, et la réflexion comme la réponse apparaissent à mesure qu'elles s'écrivent.",
    sysAria: "Le navigateur charge l'interface depuis Cloudflare et appelle un service FastAPI sur Railway. L'API écrit dans Postgres chez Neon et dépose les travaux dans une file Redis. Un worker sur Railway exécute les agents, appelle OpenRouter pour les modèles et Tavily pour la recherche, republie chaque trame via Redis, et l'API les transmet au navigateur en server-sent events.",
    sysNotes: [
      { lead: "Une file et un worker.", rest: " Une recherche dure de quelques secondes à quelques minutes. Exécutée dans l'API, un redéploiement la tuait. Elle y survit désormais, au prix d'un second processus et de Redis à maintenir." },
      { lead: "Un battement et un ramasseur.", rest: " Le worker écrit un battement toutes les quelques secondes ; une vérification planifiée échoue toute recherche dont le battement s'arrête, pour qu'un travail planté ne reste pas « en cours » indéfiniment." },
      { lead: "Les recherches approfondies sont jalonnées.", rest: " Une recherche approfondie dure des minutes, assez pour qu'un déploiement tombe au milieu : c'est donc un graphe LangGraph sur un checkpointer Postgres. Un worker qui la reprend repart de la dernière étape terminée au lieu de repayer des chercheurs déjà revenus." },
      { lead: "La progression survit à un rechargement.", rest: " Les étapes sont écrites dans Postgres et rejouées à l'ouverture d'un flux : une connexion coupée coûte un réaffichage, pas la réponse. Les tokens ne sont jamais stockés, la réponse est enregistrée en entier à la fin du tour." },
    ],

    sysLabels: {
      browser: "Navigateur",
      frontend: "App React",
      cdn: "Cloudflare",
      api: "FastAPI",
      apiRole: "comptes, runs, le flux",
      host: "Railway",
      queue: "Redis",
      queueRole: "file + bus de flux",
      worker: "Worker",
      workerRole: "exécute les agents",
      db: "Postgres",
      dbRole: "Neon",
      models: "OpenRouter",
      search: "Tavily",
      stream: "server-sent events",
      job: "travail",
      frames: "trames",
    },
    agentLabels: {
      message: "votre message",
      supervisor: "Superviseur",
      supervisorRole: "décide et répond",
      answer: "réponse sourcée",
      tools: "outils",
      search: "Recherche web + page",
      doc: "Lire un document",
      research: "Recherche",
      plan: "Plan",
      researchers: "Chercheurs ×N",
      parallel: "en parallèle",
      deep: "Recherche approfondie",
      deepRole: "jalonnée, des minutes",
      factCheck: "Vérification",
      factRole: "affirmations d'un fichier",
      outputs: "Sorties",
      background: "arrière-plan",
    },
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
    runningPlaceholder: "Travail en cours… arrêtez pour demander autre chose",
    idlePlaceholder: "Posez une question de suivi, ou autre chose…",
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
