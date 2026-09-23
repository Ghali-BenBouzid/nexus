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
    body: "Nexus is a general purpose agent that happens to be very good at research. You talk to it in a chat and it works out what your message needs, then does it: answering outright, running a search, sending out researcher sub-agents, starting a deep run that takes minutes, or checking a document you gave it against its sources. Whatever it tells you, every claim links to the page it came from. I designed and built all of it: the backend, the agent orchestration, and the frontend.",
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
    body: "Underneath, Nexus is one agent holding a set of tools, not a research pipeline with a chat bolted on top. The deep dive draws two things: how that agent decides whether your message needs a search, a team of researcher sub-agents, a deep run or a document checked, and the machinery it runs on, where a queue, a worker and a checkpoint are what let a run outlive a deploy.",
    cta: "Read the technical deep dive",
    ctaSub: "Two diagrams, the decisions behind them, and where I got it wrong",
  },
  deep: {
    title: "How I built Nexus",
    lede: "Nexus is a chat with a team of agents behind it. The models are the easy part, and nearly all of the engineering sits in what surrounds them. One agent works out how much effort your message deserves instead of a classifier guessing at it. Citations are handed out by code, so nothing can cite a page it never opened. Runs live on a queue with their own worker, so a deploy does not kill one, and the long ones checkpoint and resume rather than starting over. Every model call is priced and written to a ledger, because the live demo spends real money.",
    back: "Back to Nexus",
    source: "Read the source on GitHub",

    agentTitle: "What happens to a message",
    agentBody: "My first version routed each message: a classifier read it and sent it down one of three paths. It was wrong often enough to be annoying, usually on follow-ups, where it would start a fresh research run over something it had already answered. So I removed the router. One agent now reads your message, decides for itself what answering it takes, does that work with its tools and writes the reply. Deciding how much work a question deserves turns out to be a judgement, and a model makes it well where a classifier made it badly.",
    agentAria: "A supervisor agent receives each message and reaches for tools as it needs them: web search and page fetch, reading an uploaded document, a research run that plans sub-questions and fans out to parallel researchers, and two background runs, deep research and fact check, that write their own reports into Outputs.",
    agentNotes: [
      { lead: "The dashed arrows are tools.", rest: " The supervisor picks which to use and how many times. Three of them answer back; the two background runs take the work away and write their own report, so the chat is not blocked waiting for something that takes minutes." },
      { lead: "The plan decides its own size.", rest: " I capped it rather than fixing it: a plain fact gets one sub-question, a comparison across three options gets six. A deep run plans up to twelve. Forcing a number either wasted researchers or starved the answer." },
      { lead: "Researchers run in parallel, on a shared clock.", rest: " Each sub-question is its own agent. They share a time budget, and when it runs out they submit what they have. I added that after a slower model made whole runs time out and lose everything they had found." },
      { lead: "Code assigns the citations, not the model.", rest: " Left to cite on their own, models sometimes cite a page they never opened. So a registry numbers each source as a tool returns it, and an agent can only cite a number it was handed. Anything else is stripped before it reaches you. The trade is real: nothing in an answer can go past what was actually retrieved." },
    ],

    sysTitle: "What runs underneath",
    sysBody: "A run takes anywhere from two seconds to a few minutes. At first I ran the agents inside the API request, which worked until I deployed during one and killed it. Now the API saves your message, drops a job on a queue and returns straight away, and a separate worker does the work. The browser keeps one stream open, so you watch the thinking and the answer arrive instead of watching a spinner.",
    sysAria: "The browser loads the frontend from Cloudflare and calls a FastAPI service on Railway. The API writes to Neon Postgres and pushes jobs onto a Redis queue. A worker on Railway runs the agents, calling OpenRouter for models and Tavily for search, publishes each frame back through Redis, and the API forwards them to the browser as server-sent events.",
    sysNotes: [
      { lead: "The queue costs me a service.", rest: " Redis and a second process are both things that can break at three in the morning, and I would not add them to a smaller project. Here a run outliving a deploy was worth it." },
      { lead: "A heartbeat, and something to collect the dead.", rest: " The worker writes a heartbeat every few seconds. A scheduled check fails any run whose heartbeat stopped, because a crashed job sitting at \"running\" forever is worse than one that admits it failed." },
      { lead: "Deep runs are checkpointed.", rest: " A deep run takes minutes, which is long enough that a deploy will land in the middle of one. It is a LangGraph graph over a Postgres checkpointer, so a worker picking it up resumes from the last finished step rather than paying a second time for researchers that already came back." },
      { lead: "Progress survives a reload.", rest: " Stages are written to Postgres and replayed when a stream opens, so a dropped connection costs you a redraw and not the answer. Tokens are never stored: the reply is saved whole at the end of the turn." },
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
    idlePlaceholder: "Ask anything",
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
  tour: {
    title: "A quick tour of Nexus",
    start: "Take the tour",
    skip: "Skip",
    back: "Back",
    next: "Next",
    done: "Start asking",
    deep: {
      title: "Deep research",
      body: "Nexus sends out a small team of agents and comes back with a full cited report. It runs in the background, so you can carry on while it works.",
    },
    attach: {
      title: "Fact check a document",
      body: "Attach a PDF and switch to Fact check. Nexus pulls out what the document claims and checks each one against the web.",
    },
    outputs: {
      title: "Reports show up here",
      body: "Anything Nexus runs in the background lands in this panel, and you get a nudge wherever you are once it is ready.",
    },
    history: {
      title: "Recent chats",
      body: "Every chat is kept here. Reopen one and pick up where you stopped.",
    },
  },
  modes: {
    pick: "Mode",
    off: "Back to a normal answer",
    answer: {
      label: "Answer",
      note: "Searches if it needs to. Seconds.",
    },
    deep: {
      label: "Deep research",
      note: "A full cited report. Minutes.",
    },
    factcheck: {
      label: "Fact check",
      note: "Tests a document's claims against the web.",
      needsFile: "Attach a document first",
      request: (file: string) => `Fact-check ${file}`,
    },
  },
  // What the bar asks for once a mode changes what sending means.
  modePlaceholder: {
    answer: "",
    deep: "What should the report cover?",
    factcheck: "Which document, and what should the check focus on?",
  } as Record<string, string>,
  cites: {
    label: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
    missing: "This source is no longer listed.",
    prev: "Previous source",
    next: "Next source",
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
    steering: "passing your change to the running research",
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
    body: "Nexus est un agent généraliste qui se trouve être très bon en recherche. Vous lui parlez dans une conversation, il détermine ce que votre message demande, puis le fait : répondre directement, lancer une recherche, envoyer des sous-agents chercheurs, démarrer un traitement approfondi de plusieurs minutes, ou vérifier un document que vous lui avez donné face à ses sources. Quoi qu'il vous dise, chaque affirmation renvoie à la page dont elle vient. J'ai tout conçu et construit : la partie serveur, l'orchestration des agents et l'interface.",
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
    body: "Sous le capot, Nexus est un agent muni d'outils, pas une chaîne de recherche sur laquelle on a posé une conversation. Le détail technique dessine deux choses : comment cet agent décide si votre message demande une recherche, une équipe de sous-agents chercheurs, un traitement approfondi ou la vérification d'un document, et la mécanique sur laquelle il tourne, où une file, un worker et un jalon sont ce qui permet à un traitement de survivre à un déploiement.",
    cta: "Lire le détail technique",
    ctaSub: "Deux schémas, les décisions derrière, et là où je me suis trompé",
  },
  deep: {
    title: "Comment j'ai construit Nexus",
    lede: "Nexus est une conversation avec une équipe d'agents derrière. Les modèles sont la partie facile, et presque toute l'ingénierie se trouve dans ce qui les entoure. Un agent détermine l'effort que mérite votre message, au lieu d'un classifieur qui le devine. Les citations sont attribuées par le code, donc rien ne peut citer une page jamais ouverte. Les recherches vivent sur une file avec leur propre worker, pour qu'un déploiement n'en tue aucune, et les plus longues sont jalonnées : elles reprennent au lieu de repartir de zéro. Chaque appel de modèle est facturé et inscrit dans un registre, parce que la démo en ligne dépense de l'argent réel.",
    back: "Retour à Nexus",
    source: "Voir le code sur GitHub",

    agentTitle: "Ce qui arrive à un message",
    agentBody: "Ma première version aiguillait chaque message : un classifieur le lisait et l'envoyait sur l'une des trois voies. Il se trompait assez souvent pour que ce soit pénible, surtout sur les questions de suivi, où il relançait une recherche complète sur un point déjà traité. J'ai donc retiré l'aiguillage. Un seul agent lit votre message, détermine lui-même ce qu'il faut pour y répondre, fait ce travail avec ses outils et rédige la réponse. Juger la quantité de travail qu'une question mérite est justement un jugement : un modèle le fait bien là où mon classifieur le faisait mal.",
    agentAria: "Un agent superviseur reçoit chaque message et mobilise les outils dont il a besoin : recherche web et lecture de page, lecture d'un document déposé, une recherche qui planifie des sous-questions et les répartit entre des chercheurs parallèles, et deux traitements en arrière-plan, la recherche approfondie et la vérification de document, qui écrivent leurs propres rapports dans Sorties.",
    agentNotes: [
      { lead: "Les flèches en pointillés sont des outils.", rest: " Le superviseur choisit lesquels et combien de fois. Trois d'entre eux lui répondent ; les deux traitements en arrière-plan emportent le travail et écrivent leur propre rapport, pour que la conversation ne reste pas bloquée sur quelque chose qui prend des minutes." },
      { lead: "Le plan décide de sa propre taille.", rest: " Je l'ai plafonné plutôt que fixé : un fait simple donne une sous-question, une comparaison à trois options en donne six. Une recherche approfondie va jusqu'à douze. Imposer un nombre gaspillait des chercheurs ou affamait la réponse." },
      { lead: "Les chercheurs travaillent en parallèle, sur une horloge commune.", rest: " Chaque sous-question est un agent. Ils partagent un budget de temps et, à son terme, rendent ce qu'ils ont. Je l'ai ajouté après qu'un modèle plus lent a fait dépasser des recherches entières, qui perdaient tout ce qu'elles avaient trouvé." },
      { lead: "C'est le code qui attribue les citations, pas le modèle.", rest: " Laissés à eux-mêmes, les modèles citent parfois une page qu'ils n'ont jamais ouverte. Un registre numérote donc chaque source à mesure qu'un outil la renvoie, et un agent ne peut citer qu'un numéro qu'on lui a donné. Le reste est retiré avant que ça vous parvienne. La contrepartie est réelle : rien dans une réponse ne peut dépasser ce qui a été réellement récupéré." },
    ],

    sysTitle: "Ce qui tourne en dessous",
    sysBody: "Une recherche dure de deux secondes à quelques minutes. Au début, j'exécutais les agents dans la requête API, ce qui a marché jusqu'au jour où j'ai déployé pendant l'une d'elles et où je l'ai tuée. Maintenant l'API enregistre votre message, dépose un travail dans une file et répond aussitôt, et un processus séparé fait le travail. Le navigateur garde un flux ouvert : vous voyez la réflexion et la réponse arriver au lieu de regarder tourner un indicateur.",
    sysAria: "Le navigateur charge l'interface depuis Cloudflare et appelle un service FastAPI sur Railway. L'API écrit dans Postgres chez Neon et dépose les travaux dans une file Redis. Un worker sur Railway exécute les agents, appelle OpenRouter pour les modèles et Tavily pour la recherche, republie chaque trame via Redis, et l'API les transmet au navigateur en server-sent events.",
    sysNotes: [
      { lead: "La file me coûte un service.", rest: " Redis et un second processus sont deux choses qui peuvent tomber à trois heures du matin, et je ne les ajouterais pas à un projet plus petit. Ici, qu'une recherche survive à un déploiement le valait." },
      { lead: "Un battement, et de quoi ramasser les morts.", rest: " Le worker écrit un battement toutes les quelques secondes. Une vérification planifiée échoue toute recherche dont le battement s'est arrêté, parce qu'un travail planté qui reste « en cours » indéfiniment est pire qu'un travail qui admet son échec." },
      { lead: "Les recherches approfondies sont jalonnées.", rest: " Une recherche approfondie dure des minutes, assez pour qu'un déploiement tombe au milieu. C'est un graphe LangGraph sur un checkpointer Postgres : un worker qui la reprend repart de la dernière étape terminée au lieu de repayer des chercheurs déjà revenus." },
      { lead: "La progression survit à un rechargement.", rest: " Les étapes sont écrites dans Postgres et rejouées à l'ouverture d'un flux : une connexion coupée vous coûte un réaffichage, pas la réponse. Les tokens ne sont jamais stockés, la réponse est enregistrée en entier à la fin du tour." },
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
    idlePlaceholder: "Posez une question",
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
  tour: {
    title: "Nexus en bref",
    start: "Faire le tour",
    skip: "Passer",
    back: "Retour",
    next: "Suivant",
    done: "Poser une question",
    deep: {
      title: "Recherche approfondie",
      body: "Nexus envoie une petite équipe d'agents et vous rend un rapport complet et sourcé. Il travaille en arrière-plan, vous pouvez donc passer à autre chose pendant ce temps.",
    },
    attach: {
      title: "Vérifier un document",
      body: "Joignez un PDF et passez en mode Vérification. Nexus en extrait les affirmations et va confronter chacune au web.",
    },
    outputs: {
      title: "Vos rapports arrivent ici",
      body: "Tout ce que Nexus lance en arrière-plan atterrit dans ce panneau, et vous êtes prévenu où que vous soyez dès que c'est prêt.",
    },
    history: {
      title: "Conversations récentes",
      body: "Toutes vos conversations restent ici. Rouvrez-en une et reprenez où vous vous étiez arrêté.",
    },
  },
  modes: {
    pick: "Mode",
    off: "Revenir à une réponse normale",
    answer: {
      label: "Réponse",
      note: "Cherche si besoin. Quelques secondes.",
    },
    deep: {
      label: "Recherche approfondie",
      note: "Un rapport complet et sourcé. Plusieurs minutes.",
    },
    factcheck: {
      label: "Vérification",
      note: "Confronte au web ce qu'affirme un document.",
      needsFile: "Joignez d'abord un document",
      request: (file: string) => `Vérifie ${file}`,
    },
  },
  modePlaceholder: {
    answer: "",
    deep: "Que doit couvrir le rapport ?",
    factcheck: "Quel document, et sur quoi concentrer la vérification ?",
  } as Record<string, string>,
  cites: {
    label: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
    missing: "Cette source n'est plus répertoriée.",
    prev: "Source précédente",
    next: "Source suivante",
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
    steering: "transmission de votre changement à la recherche en cours",
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
