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
    engineering: "Engineering challenges",
    source: "Source",
    start: "Start researching",
    recent: "Recent chats",
    theme: "Toggle theme",
  },
  hero: {
    headline: "Ask anything. Every claim, sourced.",
    sub: "Nexus plans your question, sends agents to research the live web, and returns one fully-cited report.\nEvery claim links back to its source, so you can check the work yourself.",
    placeholder: "Ask Nexus to research anything…",
    chips: [
      "What are the most promising approaches to grid-scale energy storage in 2026?",
      "How are small language models changing on-device AI in 2026?",
    ],
  },
  about: {
    title: "About",
    body: "Nexus is an agentic research platform. You ask a question, a team of agents plans it, researches the live web, and writes back a single report where every claim links to its source. I designed and built all of it: the backend, the agent orchestration, and the frontend.",
    proof: ["Open source", "Live on a free LLM tier", "A real run takes ~1min"],
    builtWithLabel: "Built with",
    builtWith: [
      { label: "Backend", items: ["FastAPI", "Python", "Postgres"] },
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
      researcher: "Each sub-question runs as its own tool-using agent, with web search and page-fetch and a capped iteration budget. The orchestrator runs them as concurrent tasks but bounds how many execute at once: for now just one, to stay well under the free-tier limits. Lifting it is a one-line change.",
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
      { lead: "Research ×N", rest: " one tool-using agent per sub-question reads the live web (concurrent tasks, currently gated to one at a time)." },
      { lead: "Documents", rest: " research your own files alongside the web (RAG, next)." },
      { lead: "Consolidate", rest: " plain code dedupes and numbers the sources, no model." },
      { lead: "Write", rest: " a grounded report; every claim points to a numbered source." },
    ],
    aria: "A supervisor agent reads each message and either answers directly, composes the existing reports into one new report, or starts a research run: the research subgraph plans the question, you confirm the plan, a fan-out of researcher agents gathers sources, then a consolidation step and a writer turn it into a cited report.",
  },
  eng: {
    title: "Engineering challenges",
    why: "Impact",
    challenges: [
      {
        problem: "Free-tier LLM limits, on three axes at once.",
        how: "Free tiers cap requests, tokens, and daily totals, and one run can trip any of them. A token-aware rate limiter with a per-model profile paces the orchestrator's own calls under every ceiling.",
        why: "A real run never dies on a rate-limit error in front of someone.",
      },
      {
        problem: "Keeping the model from inventing citations.",
        how: "Hand citations to the model and it eventually cites a source it never read. So a deterministic step dedupes and numbers the sources, and the writer only keeps the markers it's given.",
        why: "The room for a hallucinated citation shrinks to almost nothing, so every claim links to a source that was actually read.",
      },
      {
        problem: "Knowing whether a change actually helps.",
        how: "Prompt and pipeline tweaks feel better without being better. An eval harness with a fixed set of graded questions and an LLM-as-a-judge pass scores each change before it ships.",
        why: "Measure before you tune: 'seems nicer' becomes a number I can compare across runs.",
      },
      {
        problem: "One core, four different providers.",
        how: "Free LLM backends each speak a slightly different dialect, and Groq's Llama models kept breaking the tool-call parser. One OpenAI-compatible adapter fronts them all, Gemini by default, the rest swappable.",
        why: "The agents never know which backend they run on, so switching provider is a config change, not a rewrite.",
      },
      {
        problem: "Built for concurrency.",
        how: "The orchestrator dispatches researchers as concurrent, non-blocking tasks, down through the providers and the database. The concurrency cap is set to one for now, to stay under free-tier limits.",
        why: "The fan-out is real; lifting the cap is a single knob, so it scales with the budget instead of a rewrite.",
      },
    ],
    nextTitle: "What's next",
    nextIntro: "A few of these are already in progress.",
    next: [
      "Researching your own documents alongside the web.",
      "An opt-in deep-research mode that trades speed for coverage: it plans the question from as many angles as it can, then works through them with a stronger model.",
    ],
  },
  footer: {
    builtBy: "Built by Ghali Ben Bouzid.",
    restPre: "The rest of my work is at ",
    restPost: ".",
    exploreTitle: "Explore",
    codeTitle: "Code",
    source: "Source on GitHub",
    agentOrch: "Agent orchestration",
    note: "Nexus, deep research, cited. FastAPI and Python on the back, React on the front, agent orchestration on a free LLM tier.",
  },
  chat: {
    runningPlaceholder: "Researching… stop to ask something new",
    idlePlaceholder: "Ask a follow-up, or start a new search…",
    jumpLatest: "Jump to latest",
    showArtifacts: "Show artifacts",
    historyHint: "↑↓ history",
  },
  turn: {
    brand: "Nexus",
    planning: "Planning the research…",
    researching: "Researching",
    stopped: "Stopped",
    done: "Done",
    planTitle: "Here's the plan. Confirm to research, or revise it.",
    confirmPlan: "Confirm & research",
    revisePlan: "Revise",
    discardPlan: "Discard",
    revisePlaceholder: "What should change? (optional)",
    sendRevision: "Send revision",
    cancelRevision: "Cancel",
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
    showConsulted: (n: number) => `Show everything consulted · ${n}`,
    unanswered: (n: number) => `Unanswered · ${n}`,
    emptyFailed: "This run didn't produce a report.",
    emptyNoCite: "No report: the agents found nothing to cite for this question.",
    emptyPending: "The report will appear here once the agents finish.",
    title: "Artifacts",
    noReports: "No reports yet.",
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
    status: (s: string) => (s === "awaiting_plan" ? "awaiting plan" : s),
  },
  feed: {
    activity: "Agent activity",
    planner: "PLANNER",
    researcher: "RESEARCHER",
    writer: "WRITER",
    plan: (n: number) => `Research plan · ${n} sub-questions`,
    researcherDone: (i: number) => `Researcher ${i} done`,
    search: "search",
    read: "read",
    steps: (n: number) => `${n} step${n === 1 ? "" : "s"}`,
    liveTag: "Live run · streaming-ready",
    simTag: "Simulated run · streaming-ready",
    // Agent-feed phrases (the backend emits English; the UI renders these).
    planning: "Planning your research",
    planningSub: "Breaking down your question",
    writing: "Writing report",
    writingSub: "Turning the findings into prose",
    reportReady: "Report ready",
    citationsLinked: "Citations linked to sources.",
    findings: "Findings gathered.",
    noInfo: "No information found.",
    couldNotResearch: "Could not research this area.",
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
    engineering: "Défis techniques",
    source: "Source",
    start: "Lancer une recherche",
    recent: "Conversations récentes",
    theme: "Changer de thème",
  },
  hero: {
    headline: "Posez une question. Chaque affirmation est sourcée.",
    sub: "Nexus décompose votre question, envoie des agents chercher sur le web en direct, et produit un seul rapport référencé. Chaque affirmation renvoie à sa source, vous pouvez donc vérifier le travail vous-même.",
    placeholder: "Demandez une recherche à Nexus…",
    chips: [
      "Quelles sont les approches les plus prometteuses pour le stockage d'énergie à l'échelle du réseau en 2026 ?",
      "Comment les petits modèles de langage transforment-ils l'IA embarquée en 2026 ?",
    ],
  },
  about: {
    title: "À propos",
    body: "Nexus est une plateforme de recherche agentique. Vous posez une question, une équipe d'agents la décompose, cherche sur le web en direct, et vous remet un seul rapport dont chaque affirmation renvoie à sa source. J'ai tout conçu et construit : la partie serveur, l'orchestration des agents et l'interface.",
    proof: ["Open source", "Fonctionne sur une offre LLM gratuite", "Une vraie recherche prend ~1min"],
    builtWithLabel: "Construit avec",
    builtWith: [
      { label: "Partie serveur", items: ["FastAPI", "Python", "Postgres"] },
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
      researcher: "Chaque sous-question est confiée à un agent doté d'outils de recherche web et de lecture de pages, avec un budget d'itérations plafonné. L'orchestrateur les lance comme des tâches concurrentes, mais borne le nombre exécuté en même temps : pour l'instant une seule, pour rester sous les quotas de l'offre gratuite. La relever est un réglage d'une ligne.",
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
      { lead: "Recherche ×N", rest: " un agent outillé par sous-question lit le web en direct (tâches concurrentes, actuellement limitées à une à la fois)." },
      { lead: "Documents", rest: " cherchent dans vos propres fichiers en parallèle du web (RAG, à venir)." },
      { lead: "Consolider", rest: " du code simple dédoublonne et numérote les sources, sans modèle." },
      { lead: "Rédiger", rest: " un rapport fondé ; chaque affirmation pointe vers une source numérotée." },
    ],
    aria: "Un superviseur lit chaque message, puis répond directement, fusionne les rapports déjà produits en un nouveau rapport, ou lance une recherche : le sous-graphe de recherche planifie la question, vous confirmez le plan, plusieurs agents chercheurs rassemblent les sources en parallèle, puis une étape de consolidation et un rédacteur en font un rapport sourcé.",
  },
  eng: {
    title: "Défis techniques",
    why: "Impact",
    challenges: [
      {
        problem: "Les limites des offres LLM gratuites, sur trois axes à la fois.",
        how: "Les offres gratuites plafonnent requêtes, tokens et total quotidien, et une seule recherche peut faire sauter n'importe lequel. Un limiteur de débit par modèle, conscient des tokens, rythme les appels sous chaque plafond.",
        why: "Une vraie recherche ne plante jamais sur une erreur de quota devant quelqu'un.",
      },
      {
        problem: "Empêcher le modèle d'inventer des citations.",
        how: "Laissé au modèle, il finit par citer une source qu'il n'a jamais lue. Une étape déterministe dédoublonne et numérote les sources, et le rédacteur ne garde que les marqueurs qu'on lui donne.",
        why: "La place pour une citation hallucinée se réduit à presque rien, donc chaque affirmation renvoie à une source réellement lue.",
      },
      {
        problem: "Savoir si un changement aide vraiment.",
        how: "Les retouches de prompt semblent meilleures sans l'être. Un protocole d'évaluation, questions notées et passe de LLM-as-a-judge, note chaque changement avant sa livraison.",
        why: "Mesurer avant d'ajuster : « ça a l'air mieux » devient un chiffre comparable d'une recherche à l'autre.",
      },
      {
        problem: "Un seul noyau, quatre fournisseurs différents.",
        how: "Chaque fournisseur LLM gratuit parle un dialecte un peu différent, et les Llama de Groq cassaient le parseur d'appels d'outils. Un adaptateur compatible OpenAI les couvre tous, Gemini par défaut, le reste interchangeable.",
        why: "Les agents ignorent sur quel fournisseur ils tournent : en changer est une question de config, pas une réécriture.",
      },
      {
        problem: "Conçu pour l'exécution concurrente.",
        how: "L'orchestrateur lance les chercheurs en tâches concurrentes et non bloquantes, jusqu'aux fournisseurs et à la base de données. La limite de concurrence est fixée à un pour l'instant, pour rester sous les quotas gratuits.",
        why: "Le fan-out est réel ; relever la limite est un seul réglage, donc ça monte en charge avec le budget au lieu d'une réécriture.",
      },
    ],
    nextTitle: "La suite",
    nextIntro: "Certaines de ces fonctionnalités sont déjà en cours de développement.",
    next: [
      "Chercher dans vos propres documents en parallèle du web.",
      "Un mode recherche approfondie optionnel, qui troque la vitesse contre la couverture : il aborde la question sous le plus d'angles possible, puis les traite avec un modèle plus puissant.",
    ],
  },
  footer: {
    builtBy: "Construit par Ghali Ben Bouzid.",
    restPre: "Le reste de mon travail est sur ",
    restPost: ".",
    exploreTitle: "Explorer",
    codeTitle: "Code",
    source: "Code sur GitHub",
    agentOrch: "Orchestration des agents",
    note: "Nexus, recherche approfondie, sourcée. FastAPI et Python côté serveur, React côté interface, orchestration d'agents sur une offre LLM gratuite.",
  },
  chat: {
    runningPlaceholder: "Recherche en cours… arrêtez pour poser autre chose",
    idlePlaceholder: "Posez une question de suivi, ou lancez une nouvelle recherche…",
    jumpLatest: "Aller au plus récent",
    showArtifacts: "Afficher les rapports",
    historyHint: "↑↓ historique",
  },
  turn: {
    brand: "Nexus",
    planning: "Planification de la recherche…",
    researching: "Recherche",
    stopped: "Arrêté",
    done: "Terminé",
    planTitle: "Voici le plan. Confirmez pour lancer la recherche, ou révisez-le.",
    confirmPlan: "Confirmer et rechercher",
    revisePlan: "Réviser",
    discardPlan: "Abandonner",
    revisePlaceholder: "Que faut-il changer ? (facultatif)",
    sendRevision: "Envoyer la révision",
    cancelRevision: "Annuler",
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
    showConsulted: (n: number) => `Tout ce qui a été consulté · ${n}`,
    unanswered: (n: number) => `Sans réponse · ${n}`,
    emptyFailed: "Cette recherche n'a pas produit de rapport.",
    emptyNoCite: "Pas de rapport : les agents n'ont rien trouvé à citer pour cette question.",
    emptyPending: "Le rapport apparaîtra ici une fois les agents terminés.",
    title: "Rapports",
    noReports: "Aucun rapport pour l'instant.",
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
        awaiting_plan: "plan à valider",
        complete: "terminé",
        failed: "échec",
      })[s] ?? s,
  },
  feed: {
    activity: "Activité des agents",
    planner: "PLANIFICATEUR",
    researcher: "CHERCHEUR",
    writer: "RÉDACTEUR",
    plan: (n: number) => `Plan de recherche · ${n} sous-questions`,
    researcherDone: (i: number) => `Chercheur ${i} terminé`,
    search: "recherche",
    read: "lecture",
    steps: (n: number) => `${n} étape${n > 1 ? "s" : ""}`,
    liveTag: "Recherche en direct · prêt pour le streaming",
    simTag: "Recherche simulée · prêt pour le streaming",
    planning: "Planification de votre recherche",
    planningSub: "Décomposition de votre question",
    writing: "Rédaction du rapport",
    writingSub: "Mise en forme des résultats",
    reportReady: "Rapport prêt",
    citationsLinked: "Citations reliées aux sources.",
    findings: "Résultats rassemblés.",
    noInfo: "Aucune information trouvée.",
    couldNotResearch: "Recherche impossible sur cet aspect.",
  },
  count: {
    sources: (n: number) => `${n} source${n > 1 ? "s" : ""}`,
    gaps: (n: number) => `${n} lacune${n > 1 ? "s" : ""}`,
  },
};

export const t: Dict = lang === "fr" ? fr : en;
if (typeof document !== "undefined") document.title = t.docTitle;
