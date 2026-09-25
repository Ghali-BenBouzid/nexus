// Lightweight, framework-free i18n. Components import `t` and `lang`, which are
// live bindings: switching language swaps them and tells the app to re-render,
// so every `t.x` read at render picks up the new language. Nothing may copy a
// string out of `t` at module load, or it stays in the old language. Switching
// used to reload the page, which threw away everything not yet saved: files
// attached but not sent, the draft, an upload on its way. Backend-streamed agent
// text stays in whatever language the API returns; this only covers the static UI.

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

export let lang: Lang = detect();

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
    body: "Nexus is a general purpose agent that happens to be very good at research. You talk to it in a chat and it works out what your message needs, then does it: answering outright, running a search, sending out researcher sub-agents, writing a full deep research report when you ask for one, or checking a document you gave it against independent sources. Whatever it tells you, every claim links to the page it came from. I designed and built all of it: the backend, the agent orchestration, and the frontend.",
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
    body: "Underneath, Nexus is one agent holding a set of tools, not a research pipeline with a chat bolted on top. The deep dive shows how that agent decides whether your message needs a search, a team of researcher sub-agents or a document checked, the machinery it runs on, where a queue, a worker and checkpoints let a run outlive a deploy, and what broke along the way.",
    cta: "Read the technical deep dive",
    ctaSub: "Two diagrams, the decisions behind them, and where I got it wrong",
  },
  deep: {
    title: "How I built Nexus",
    lede: "Nexus is a chat with a team of agents behind it. The models are the easy part, and nearly all of the engineering sits in what surrounds them. One agent works out how much effort your message deserves instead of a classifier guessing at it. Citations are handed out by code, so nothing can cite a page it never opened. Runs live on a queue with their own worker, so a deploy does not kill one, and the long ones checkpoint and resume rather than starting over. Every model call is priced and written to a ledger, because the live demo spends real money. Below: what happens to a message, what runs underneath, the trade-offs I chose, what broke on the way, and how I measure it.",
    back: "Back to Nexus",
    source: "Read the source on GitHub",

    agentTitle: "What happens to a message",
    agentBody: "My first version routed each message: a classifier read it and sent it down one of three paths. It was wrong often enough to be annoying, usually on follow-ups, where it would start a fresh research run over something it had already answered. So I removed the router. One agent now reads your message, decides for itself what answering it takes, does that work with its tools and writes the reply. Deciding how much work a question deserves turns out to be a judgement, and a model makes it well where a classifier made it badly.",
    agentAria: "A supervisor agent receives each message and reaches for tools as it needs them: web search and page fetch, reading an uploaded document, a research run that plans sub-questions and fans out to parallel researchers, and two background runs, deep research and fact check, that write their own reports into the Reports panel.",
    agentNotes: [
      { lead: "The dashed arrows are tools.", rest: " The supervisor picks which to use and how many times. Three of them answer back; the two background runs take the work away and write their own report, so the chat is not blocked waiting for something that takes minutes. Deep research is only on offer when you switch its mode on: it costs minutes and real money, so the supervisor suggests it rather than starting it." },
      { lead: "The plan decides its own size.", rest: " I capped it rather than fixing it: a plain fact gets one sub-question, a comparison across three options gets six. Forcing a number either wasted researchers or starved the answer. A deep run has no fixed plan at all: a lead agent sends up to six researchers a round, reads what they found and decides whether to go back, for three rounds and fifteen researchers at most." },
      { lead: "Researchers run in parallel, on a shared clock.", rest: " Each sub-question is its own agent. They share a time budget, and when it runs out they submit what they have. Each also gets three web searches (five in a deep run) and is told to read pages in full rather than search again. The clock came after a slow model made whole runs time out; the search budget came after the search engines started blocking whole rounds." },
      { lead: "It asks when a choice would help.", rest: " A question panel docks above the composer with numbered options, a free answer and Skip. Before a deep run, that panel is how the supervisor works out the brief with you: what the report is for, then only what would change the research, and a go-ahead that cannot be skipped, because a skipped confirmation once read as a yes and launched a run." },
      { lead: "Code assigns the citations, not the model.", rest: " Left to cite on their own, models sometimes cite a page they never opened. So a registry numbers each source as a tool returns it, and an agent can only cite a number it was handed. Anything else is stripped before it reaches you. The trade is real: nothing in an answer can go past what was actually retrieved." },
    ],

    sysTitle: "What runs underneath",
    sysBody: "A run takes anywhere from two seconds to a few minutes. At first I ran the agents inside the API request, which worked until I deployed during one and killed it. Now the API saves your message, drops a job on a queue and returns straight away, and a separate worker does the work. The browser keeps one stream open, so you watch each step and then the answer arrive instead of watching a spinner.",
    sysAria: "The browser loads the frontend from Cloudflare and calls a FastAPI service on Railway. The API writes to Neon Postgres and pushes jobs onto a Redis queue. A worker on Railway runs the agents, calling OpenRouter for models and our own SearXNG and Crawl4AI services for search and page reading, publishes each frame back through Redis, and the API forwards them to the browser as server-sent events.",
    sysNotes: [
      { lead: "The queue costs me a service.", rest: " Redis and a second process are both things that can break at three in the morning, and I would not add them to a smaller project. Here a run outliving a deploy was worth it." },
      { lead: "A heartbeat, and something to collect the dead.", rest: " The worker writes a heartbeat every few seconds. A scheduled check fails any run whose heartbeat stopped, because a crashed job sitting at \"running\" forever is worse than one that admits it failed." },
      { lead: "Deep runs are checkpointed.", rest: " A deep run takes minutes, which is long enough that a deploy will land in the middle of one. It is a LangGraph graph over a Postgres checkpointer, so a worker picking it up resumes from the last finished step rather than paying a second time for rounds that already came back." },
      { lead: "The thinking is named, not streamed.", rest: " The supervisor's reasoning used to scroll past as it was written, far too fast to read. Now a small, cheap model gives each stretch of it a short title, and the feed lists those alongside every search, every page read and every research team, in the order they happened." },
      { lead: "Progress survives a reload.", rest: " Stages are written to Postgres and replayed when a stream opens, so a dropped connection costs you a redraw and not the answer. Tokens are never stored: the reply is saved whole at the end of the turn." },
      { lead: "Search runs on our own services.", rest: " SearXNG queries the search engines and Crawl4AI reads each page in a real browser, both next to the worker. That made searching free, which is what let a deep run afford several rounds. The price is that the engines behind SearXNG block a burst of searches for minutes, so every search the worker sends is paced at 40 a minute." },
    ],

    tradeTitle: "The trade-offs",
    tradeBody: "Most of Nexus comes down to a handful of decisions, and each one has a price. These are the ones I would make again.",
    tradeNotes: [
      { lead: "The agents run on LangChain's loop.", rest: " Writing a tool loop is a day's work; keeping it correct is not. What the app cannot hand over rides alongside as middleware. Billing and pacing sit on the model itself, because two of the agents call the model directly and middleware would never see them: the first version billed only what agents spent." },
      { lead: "Prompts are versioned.", rest: " Each prompt carries a version, and a lock file pins it to a hash of its text, so a test fails if the wording changes without a bump. Every evaluation run records the versions it used, which is what makes \"did this change help?\" a question with an answer. It costs a little ceremony on every edit." },
      { lead: "The conversation reaches the model as real messages.", rest: " It used to be one long user message where your words, the app's labels and past reports all looked alike. Now anything retrieved (a report, search results, a page) arrives inside a tag the prompts define as data, so a page that says \"ignore your instructions\" reads as page content." },
      { lead: "There is no plan to approve.", rest: " Nexus used to propose a plan and wait for a click. That put a form in front of you before a single search, and made a simple follow-up as heavy as a full run. The supervisor now does the work. The exception is a deep run, which costs half an hour: it starts only after a short brainstorm of the brief and your go-ahead." },
      { lead: "A run is one row with a kind.", rest: " A chat turn, a deep run and a fact check all need an owner, a status, a heartbeat, a live feed, a stop button and a bill. Keeping them in one table means everything built around a run works for all three." },
      { lead: "Each account has a dollar budget.", rest: " The demo runs on paid models, so there is no public signup. I create each account with a budget, every model call is priced into a ledger, and new work is refused once it is spent. The catch is that I hand the accounts out myself." },
    ],

    wrongTitle: "What went wrong",
    wrongBody: "A good part of the code exists because something broke first. These are the failures that taught me the most.",
    wrongNotes: [
      { lead: "Every report said nothing was found.", rest: " The first evaluation run put researcher success at 0% over 41 runs. The tool schemas used JSON Schema references the model never followed, so it sent its claims as plain strings and every one failed validation. Writing the schemas out in full took it to 100% on the next run." },
      { lead: "A question about me came back in German.", rest: " Language detection read \"Who is Ghali Ben Bouzid?\" as Dutch and the French version as German, and every agent followed it. Detection now needs a minimum confidence, and on a one-line query the small words (to, and, de, qu') decide, since names had also passed \"compare morroco's economy to algeria's\" off as Italian." },
      { lead: "Stopping a run did not stop the model.", rest: " The run was marked stopped, but the writer's call kept going, got billed, and its report was thrown away. The worker now cancels whatever is running, a model call included, within one heartbeat of the stop." },
      { lead: "Deep research was thin, then a course, then a summary.", rest: " One pass at a subject was not deep. Letting the lead loop gave a 32-minute run and 22,822 words. Reining it in gave six sections of one paragraph each. What held: a few areas, mapped in one round and deepened in the next, with several paragraphs each. The run that settled it took three rounds and cited 69 sources." },
      { lead: "The search engines blocked a whole round.", rest: " Six researchers searching at once reached the engines behind SearXNG as one burst. They answered with a CAPTCHA, an access denied and a 429 for minutes, while SearXNG reported an empty success. Researchers now have a small search budget, every search is paced, and an empty result is an error the agent sees." },
      { lead: "The same run started twice.", rest: " A CV was being fact-checked, the user asked for jokes while they waited, and the supervisor checked the same file again. A fact check now records its document and refuses one already being checked, and only one deep run works at a time in a conversation." },
      { lead: "One slow upstream made every call take a minute.", rest: " OpenRouter serves a model from several providers, and ranking them by throughput kept picking a degraded one. Calls now go to the cheapest provider that clears a speed floor, and the same 700-token call dropped from over a minute to 4 to 11 seconds." },
      { lead: "Deep runs were shallow in production.", rest: " Four real runs took under a minute, read one to four pages and wrote under a thousand words, on a budget of twelve minutes. A fast model took the minimum at every depth decision. The floors now live in the tools: a deep researcher cannot submit before reading two pages, the lead cannot write after one round, and the writer scales its length to what was found." },
      { lead: "Two fact checks of one document checked different things.", rest: " The checker chose its claims silently, somewhere inside its search loop. It now commits to them first, each tied to the passage it comes from, and nothing is searched until a review confirms the list covers the document." },
    ],

    evalTitle: "How I measure it",
    evalBody: "The repository holds 150 realistic first messages, from questions about me to false premises, prompt injections and typos, each with a note on what a good answer does. The harness runs them through the real turn and records the tools, the plan, every search, the answer, the cost and the time. A prompt change of one sentence moves the averages less than the judge's own noise, so changes are compared head to head: a separate model judges both answers to the same question without knowing which version wrote which, twice, and a split counts as a tie.",
    evalHead: ["Change", "Measured on", "Result"],
    evalRows: [
      ["Tell the agents today's date", "8 time-sensitive questions", "Won 3-2 on answers and 2-0 on plans"],
      ["Tell the supervisor what Nexus is and who built it", "24 questions about the app and me", "Routing from 15/24 to 24/24 correct, web searches from 12 to 0, 35% cheaper"],
      ["Send the conversation as real messages", "The same 24", "13 wins, 6 losses, 5 ties, and an injected instruction did not take over"],
      ["Let the planner size its plan", "8 broad questions", "Wider plans that the judge scores lower, so still open"],
    ],
    evalNote: "The judge is not neutral. It tends to prefer the shorter of two correct answers, and it counts extra angles in a plan as drift, which is why the last row is still an open question.",

    limitsTitle: "What it does not do yet",
    limits: [
      "Accounts are invite-only, and I create them by hand.",
      "Research covers the web. Searching your own documents alongside it is not built.",
      "Only a deep run resumes after a worker crash. A chat turn or a fact check is marked failed.",
      "A deep run takes about 20 to 30 minutes, and much of that is waiting on the slowest researcher.",
      "A PDF over 12 pages is refused.",
      "The evaluation leans on a model as judge, and the scored runs are still small.",
      "The prompt injection defences are in place but not yet measured on full research runs.",
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
      search: "SearXNG + Crawl4AI",
      searchRole: "self-hosted",
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
      outputs: "Reports",
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
    showArtifacts: "Show reports",
  },
  // The question panel the supervisor opens above the composer.
  ask: {
    position: (n: number, of: number) => `${n} of ${of}`,
    previous: "Previous question",
    next: "Next question",
    close: "Close",
    other: "Something else",
    skip: "Skip",
    placeholder: "Or reply directly…",
    navigate: "to navigate",
    select: "to select",
    typeBelow: "or type below",
    skipped: "Skipped",
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
  // When something happened: relative while recent, then the time of day,
  // then the date (lib/when.ts decides which).
  when: {
    justNow: "just now",
    minutesAgo: (n: number) => (n === 1 ? "a minute ago" : `${n} minutes ago`),
    hoursAgo: (n: number) => (n === 1 ? "an hour ago" : `${n} hours ago`),
    today: (time: string) => `Today at ${time}`,
    yesterday: (time: string) => `Yesterday at ${time}`,
    on: (date: string, time: string) => `${date}, ${time}`,
  },
  artifact: {
    back: "Back to artifacts",
    report: "Report",
    closePanel: "Close panel",
    copy: "Copy report",
    copied: "Copied",
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
    title: "Reports",
    noReports: "No reports yet. Ask for deep research, or fact-check a document.",
    running: "Working…",
    // A background run still going: how long it has been at it, ticking.
    workingFor: (clock: string) => `Working for ${clock}`,
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
    truncated: "shortened",
    pages: (n: number) => (n === 1 ? "1 page" : `${n} pages`),
    ready: (name: string) => `${name} is attached. Ask about it, or fact-check it.`,
    // A file goes up, then is read, and a long PDF takes a while. The tile says
    // so from the first frame rather than sitting there looking finished.
    uploading: "Uploading",
    reading: "Reading",
    // A refused upload, or a file that could not be read: the reason is on
    // hover and in the Uploads list.
    failedFile: "Failed",
    retry: "Try again",
    drop: "Drop to attach",
    dropHint: "PDF, Word or text",
    unsupported: "This file format is not supported. Try another one.",
  },
  account: {
    // What kind of account this is, beside its name: every account is an invite.
    plan: "Demo",
    menu: "Account",
    kind: "Demo account",
    credits: "Credits",
    left: (percent: number) => `${percent}% left`,
    until: (date: string) => `Access until ${date}`,
    stays: "You stay signed in on this browser until you sign out.",
    signOut: "Sign out",
    // Said before signing out, not after: the link is the only way back in.
    confirm: "To sign back in, you will need to open your invite link again. Keep it somewhere you can find it.",
    cancel: "Cancel",
  },
  preview: {
    open: (name: string) => `Open ${name}`,
    close: "Close",
    download: "Download",
    newTab: "Open in a new tab",
    loading: "Opening the file",
    failed: "The file could not be opened.",
    none: "There is no preview for this kind of file. Download it to read it.",
  },
  outputs: {
    ready: (title: string) => `${title} is ready.`,
    open: "Open",
    dismiss: "Dismiss",
  },
  // The browser notification when a report finishes in a tab nobody is looking at.
  notify: {
    title: "Your report is ready",
    // The tab's title while finished reports wait for the user to come back.
    tab: (n: number) => (n === 1 ? "Report ready" : `${n} reports ready`),
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
      body: "For complex questions that need real digging. You get a full report with its sources. It takes up to around 25 minutes, depending on the task, and you can keep chatting in the meantime.",
    },
    attach: {
      title: "Fact-check a document",
      body: "Attach a document, then choose Fact check. Nexus checks it against independent sources on the web and gives you a detailed report.",
    },
    outputs: {
      title: "Your reports arrive here",
      body: "When a report is finished, it appears here and you get a notification, even if you are in another tab.",
    },
    history: {
      title: "Your chats",
      body: "Every chat is saved here. Open one to pick up where you left off.",
    },
  },
  tips: {
    gotIt: "Got it",
    deep: {
      title: "Your deep research has started",
      body: "It takes up to around 25 minutes, depending on the task. Your report will appear here, and you will get a notification when it is ready. Feel free to keep chatting or switch tabs.",
    },
    factcheck: {
      title: "Your fact check has started",
      body: "Nexus is checking your document against independent sources. It takes a few minutes. Your report will appear here, and you will get a notification when it is ready.",
    },
    attach: {
      title: "Your document is attached",
      body: "Ask anything about it, or choose Fact check here to have it checked against independent sources.",
    },
  },
  modes: {
    pick: "Mode",
    off: "Back to a normal answer",
    answer: {
      label: "Answer",
      note: "A quick answer, in seconds.",
    },
    deep: {
      label: "Deep research",
      note: "For complex questions. Up to around 25 minutes, depending on the task.",
    },
    factcheck: {
      label: "Fact check",
      note: "Checks a document against independent sources.",
      needsFile: "Attach a document first",
      request: (file: string) => `Fact-check ${file}`,
    },
  },
  // How hard the supervisor thinks before replying. Relative times on purpose:
  // seconds depend on the question as much as on the setting.
  effort: {
    pick: "Effort",
    head: "How long it thinks before replying",
    high: {
      label: "High",
      note: "Thinks it through and cites its sources. Right for most questions.",
    },
    max: {
      label: "Max",
      note: "Its most careful reasoning, for hard problems. Slower: a reply can take a minute or two.",
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
    unread: "Unread report",
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
    listingClaims: "listing the claims to check",
    deepStarted: (title: string) => `Started deep research${title ? `: ${title}` : ""}`,
    factCheckStarted: (name: string) => `Started a fact check${name ? `: ${name}` : ""}`,
    inOutputs: "in Reports",
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
    // Steps in the feed, named for what they do, like the titles the model's
    // thinking gets ("Weighing the running costs").
    think: "Thinking",
    searchStep: (query: string) => `Searching "${query}"`,
    readStep: (domain: string) => `Reading ${domain}`,
    documentStep: (name: string) => `Reading ${name}`,
    steerStep: "Passing your change to the running research",
    researchStep: (question: string) => `Research team: ${question}`,
    stepCount: (n: number) => `${n} step${n === 1 ? "" : "s"}`,
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
    sub: "Nexus lit le web et vous répond dans la conversation, chaque affirmation renvoyant à la page dont elle vient.\nDemandez-lui d'aller plus loin et il rédige un rapport complet. Donnez-lui un document et il en vérifie les affirmations.",
    placeholder: "Posez une question, ou joignez un document",
    examplesLabel: "Essayez l'un de ces exemples",
    chips: [
      "Quelles sont les approches les plus prometteuses pour le stockage d'énergie à l'échelle du réseau en 2026 ?",
      "Comment les petits modèles de langage transforment-ils l'IA embarquée en 2026 ?",
    ],
  },
  about: {
    title: "À propos",
    body: "Nexus est un agent généraliste qui excelle en recherche. Vous échangez avec lui dans une conversation ; il détermine ce que demande votre message, puis s'en charge : répondre directement, lancer une recherche, envoyer des sous-agents chercheurs, rédiger un rapport de recherche approfondie quand vous le demandez, ou confronter à des sources indépendantes un document que vous lui avez confié. Quoi qu'il vous dise, chaque affirmation renvoie à la page dont elle vient. J'ai tout conçu et construit : la partie serveur, l'orchestration des agents et l'interface.",
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
    body: "Sous le capot, Nexus est un agent muni d'outils, pas une chaîne de recherche à laquelle on aurait greffé une conversation. Le détail technique montre comment cet agent décide si votre message demande une recherche, une équipe de sous-agents chercheurs ou la vérification d'un document, décrit la mécanique sur laquelle il repose, où une file d'attente, un worker et des points de reprise permettent à un traitement de survivre à un déploiement, et revient sur ce qui a cassé en route.",
    cta: "Lire le détail technique",
    ctaSub: "Deux schémas, les décisions derrière, et là où je me suis trompé",
  },
  deep: {
    title: "Comment j'ai construit Nexus",
    lede: "Nexus est une conversation avec une équipe d'agents derrière. Les modèles sont la partie facile, et presque toute l'ingénierie se trouve dans ce qui les entoure. Un agent détermine l'effort que mérite votre message, au lieu d'un classifieur qui le devine. Les citations sont attribuées par le code, donc rien ne peut citer une page jamais ouverte. Les recherches passent par une file d'attente et un worker dédié, pour qu'un déploiement n'en interrompe aucune, et les plus longues sont sauvegardées étape par étape : elles reprennent au lieu de repartir de zéro. Chaque appel de modèle est facturé et inscrit dans un registre, parce que la démo en ligne dépense de l'argent réel. Plus bas : ce qui arrive à un message, ce qui tourne en dessous, les compromis que j'ai choisis, ce qui a cassé en route, et comment je le mesure.",
    back: "Retour à Nexus",
    source: "Voir le code sur GitHub",

    agentTitle: "Ce qui arrive à un message",
    agentBody: "Ma première version aiguillait chaque message : un classifieur le lisait et l'envoyait sur l'une des trois voies. Il se trompait assez souvent pour que ce soit pénible, surtout sur les questions de suivi, où il relançait une recherche complète sur un point déjà traité. J'ai donc retiré l'aiguillage. Un seul agent lit votre message, détermine lui-même ce qu'il faut pour y répondre, fait ce travail avec ses outils et rédige la réponse. Estimer le travail que mérite une question relève du jugement : un modèle s'en acquitte bien, là où mon classifieur s'y prenait mal.",
    agentAria: "Un agent superviseur reçoit chaque message et mobilise les outils dont il a besoin : recherche web et lecture de page, lecture d'un document déposé, une recherche qui planifie des sous-questions et les répartit entre des chercheurs parallèles, et deux traitements en arrière-plan, la recherche approfondie et la vérification de document, qui rédigent leurs propres rapports dans le panneau Rapports.",
    agentNotes: [
      { lead: "Les flèches en pointillés sont des outils.", rest: " Le superviseur choisit lesquels et combien de fois. Trois d'entre eux lui répondent ; les deux traitements en arrière-plan emportent le travail et écrivent leur propre rapport, pour que la conversation ne reste pas bloquée sur une tâche de plusieurs minutes. La recherche approfondie n'est proposée que si vous activez son mode : elle coûte du temps et de l'argent, alors le superviseur la suggère au lieu de la lancer." },
      { lead: "Le plan décide de sa propre taille.", rest: " Je l'ai plafonné plutôt que fixé : un fait simple donne une sous-question, une comparaison à trois options en donne six. Imposer un nombre gaspillait des chercheurs ou appauvrissait la réponse. Une recherche approfondie n'a pas de plan fixe : un agent pilote envoie jusqu'à six chercheurs par tour, lit ce qu'ils rapportent et décide s'il faut y retourner, en trois tours et quinze chercheurs au plus." },
      { lead: "Les chercheurs travaillent en parallèle, sur une horloge commune.", rest: " Chaque sous-question est un agent. Ils partagent un budget de temps et, à son terme, rendent ce qu'ils ont. Chacun a aussi droit à trois recherches web (cinq en recherche approfondie), avec la consigne de lire les pages en entier plutôt que de chercher à nouveau. L'horloge est arrivée après qu'un modèle lent a fait expirer des recherches entières ; le budget de recherches, après que les moteurs ont commencé à bloquer des tours complets." },
      { lead: "Il pose des questions quand c'est utile.", rest: " Un panneau de questions s'ouvre au-dessus de la zone de saisie, avec des options numérotées, une réponse libre et un bouton pour passer. Avant une recherche approfondie, c'est ainsi que le superviseur établit le cahier des charges avec vous : à quoi servira le rapport, puis seulement ce qui changerait la recherche, et enfin un feu vert impossible à passer, car une confirmation ignorée a déjà été prise pour un accord et a lancé une recherche." },
      { lead: "C'est le code qui attribue les citations, pas le modèle.", rest: " Laissés à eux-mêmes, les modèles citent parfois une page qu'ils n'ont jamais ouverte. Un registre numérote donc chaque source à mesure qu'un outil la renvoie, et un agent ne peut citer qu'un numéro qu'on lui a donné. Le reste est retiré avant de vous parvenir. La contrepartie est réelle : rien dans une réponse ne peut dépasser ce qui a été réellement récupéré." },
    ],

    sysTitle: "Ce qui tourne en dessous",
    sysBody: "Une recherche dure de deux secondes à quelques minutes. Au début, j'exécutais les agents dans la requête API, ce qui a fonctionné jusqu'au jour où un déploiement en a interrompu une en plein milieu. Désormais, l'API enregistre votre message, dépose une tâche dans une file d'attente et répond aussitôt, et un processus séparé s'en charge. Le navigateur garde un flux ouvert : vous voyez chaque étape, puis la réponse, arriver au lieu de regarder tourner un indicateur.",
    sysAria: "Le navigateur charge l'interface depuis Cloudflare et appelle un service FastAPI sur Railway. L'API écrit dans Postgres chez Neon et dépose les tâches dans une file d'attente Redis. Un worker sur Railway exécute les agents, appelle OpenRouter pour les modèles et nos propres services SearXNG et Crawl4AI pour chercher et lire les pages, republie chaque trame via Redis, et l'API les transmet au navigateur en server-sent events.",
    sysNotes: [
      { lead: "La file me coûte un service.", rest: " Redis et un second processus sont deux choses qui peuvent tomber à trois heures du matin, et je ne les ajouterais pas à un projet plus petit. Ici, qu'une recherche survive à un déploiement le valait." },
      { lead: "Un signal de vie, et de quoi ramasser les morts.", rest: " Le worker émet un signal de vie à quelques secondes d'intervalle. Une vérification planifiée fait passer en échec toute recherche dont le signal s'est tu, parce qu'une tâche plantée qui reste « en cours » indéfiniment est pire qu'une tâche qui reconnaît son échec." },
      { lead: "Les recherches approfondies reprennent là où elles s'arrêtent.", rest: " Une recherche approfondie dure plusieurs minutes, assez pour qu'un déploiement tombe en plein milieu. C'est un graphe LangGraph adossé à un checkpointer Postgres : le worker qui la reprend repart de la dernière étape terminée au lieu de payer une seconde fois des tours déjà achevés." },
      { lead: "La réflexion est résumée, pas diffusée.", rest: " Le raisonnement du superviseur défilait à mesure qu'il s'écrivait, bien trop vite pour être lu. Un petit modèle peu coûteux donne désormais un titre court à chacune de ses étapes, et le flux les affiche aux côtés de chaque recherche, de chaque page lue et de chaque équipe de chercheurs, dans l'ordre où elles ont eu lieu." },
      { lead: "La progression survit à un rechargement.", rest: " Les étapes sont écrites dans Postgres et rejouées à l'ouverture d'un flux : une connexion coupée vous coûte un réaffichage, pas la réponse. Les tokens ne sont jamais stockés : la réponse est enregistrée en entier à la fin du tour." },
      { lead: "La recherche passe par nos propres services.", rest: " SearXNG interroge les moteurs de recherche et Crawl4AI lit chaque page dans un vrai navigateur, tous deux à côté du worker. Chercher est devenu gratuit, et c'est ce qui permet à une recherche approfondie de s'offrir plusieurs tours. La contrepartie : les moteurs derrière SearXNG bloquent une rafale de recherches pendant des minutes, donc chaque recherche envoyée par le worker est cadencée à 40 par minute." },
    ],

    tradeTitle: "Les compromis",
    tradeBody: "L'essentiel de Nexus tient en une poignée de décisions, et chacune a un prix. Ce sont celles que je reprendrais.",
    tradeNotes: [
      { lead: "Les agents tournent sur la boucle de LangChain.", rest: " Écrire une boucle d'outils prend une journée ; la garder correcte, non. Ce que l'application ne peut pas déléguer s'y greffe en middleware. La facturation et le cadencement se font au niveau du modèle lui-même, parce que deux des agents appellent le modèle directement et qu'un middleware ne les verrait jamais : la première version ne facturait que ce que dépensaient les agents." },
      { lead: "Les prompts sont versionnés.", rest: " Chaque prompt porte une version, et un fichier de verrouillage la lie à une empreinte de son texte : un test échoue si la formulation change sans que la version bouge. Chaque évaluation enregistre les versions utilisées, et c'est ce qui permet de répondre à « est-ce que ce changement a aidé ? ». Le prix : un peu de cérémonie à chaque modification." },
      { lead: "La conversation arrive au modèle sous forme de vrais messages.", rest: " C'était un long message unique où vos mots, les libellés de l'application et les anciens rapports se ressemblaient tous. Désormais tout ce qui est récupéré (un rapport, des résultats de recherche, une page) arrive dans une balise que les prompts définissent comme des données, et une page qui dit « ignore tes instructions » se lit comme le contenu d'une page." },
      { lead: "Il n'y a pas de plan à valider.", rest: " Nexus proposait un plan et attendait un clic. Cela mettait un formulaire devant vous avant la moindre recherche, et rendait une simple question de suivi aussi lourde qu'une recherche complète. Le superviseur fait maintenant le travail. Seule exception : la recherche approfondie, qui prend une demi-heure, ne démarre qu'après un bref échange sur le cahier des charges et votre feu vert." },
      { lead: "Un traitement est une ligne avec un type.", rest: " Un tour de conversation, une recherche approfondie et une vérification ont tous besoin d'un propriétaire, d'un statut, d'un battement, d'un flux en direct, d'un bouton d'arrêt et d'une facture. Les garder dans une seule table permet à tout ce qui est construit autour d'un traitement de servir aux trois." },
      { lead: "Chaque compte a un budget en dollars.", rest: " La démo tourne sur des modèles payants, donc pas d'inscription publique. Je crée chaque compte avec un budget, chaque appel de modèle est chiffré dans un registre, et tout nouveau travail est refusé une fois le budget dépensé. La limite : c'est moi qui distribue les comptes." },
    ],

    wrongTitle: "Ce qui a mal tourné",
    wrongBody: "Une bonne partie du code existe parce que quelque chose a d'abord cassé. Voici les échecs qui m'ont le plus appris.",
    wrongNotes: [
      { lead: "Chaque rapport disait n'avoir rien trouvé.", rest: " La première évaluation a mesuré 0 % de chercheurs réussis sur 41 recherches. Les schémas des outils utilisaient des références JSON Schema que le modèle ne suivait pas : il envoyait ses affirmations en simples chaînes, et aucune ne passait la validation. Écrire les schémas en entier a fait monter le taux à 100 % dès l'évaluation suivante." },
      { lead: "Une question sur moi est revenue en allemand.", rest: " La détection de langue lisait « Who is Ghali Ben Bouzid? » comme du néerlandais et la version française comme de l'allemand, et tous les agents suivaient. Elle exige désormais un seuil de confiance et, sur une requête d'une ligne, ce sont les petits mots (to, and, de, qu') qui tranchent : les noms propres lui avaient aussi fait prendre « compare morroco's economy to algeria's » pour de l'italien." },
      { lead: "Arrêter une recherche n'arrêtait pas le modèle.", rest: " La recherche était marquée arrêtée, mais l'appel du rédacteur continuait, était facturé, et son rapport était jeté. Le worker annule maintenant tout ce qui tourne, appel de modèle compris, dans les secondes qui suivent l'arrêt." },
      { lead: "La recherche approfondie a été trop mince, puis un cours, puis un résumé.", rest: " Un seul passage sur un sujet n'avait rien d'approfondi. Laisser l'agent pilote boucler a donné 32 minutes de recherche et 22 822 mots. Le brider a donné six sections d'un paragraphe chacune. Ce qui a tenu : quelques axes, défrichés en un tour puis creusés au suivant, avec plusieurs paragraphes chacun. La recherche qui a tranché a pris trois tours et cité 69 sources." },
      { lead: "Les moteurs de recherche ont bloqué un tour entier.", rest: " Six chercheurs lancés en même temps arrivaient sur les moteurs derrière SearXNG comme une seule rafale. Ils répondaient par un CAPTCHA, un accès refusé et une erreur 429 pendant des minutes, pendant que SearXNG annonçait un succès vide. Les chercheurs ont maintenant un petit budget de recherches, chaque recherche est cadencée, et un résultat vide est une erreur que l'agent voit." },
      { lead: "La même tâche lancée deux fois.", rest: " Pendant qu'un CV était en cours de vérification, l'utilisateur a demandé des blagues pour patienter, et le superviseur a relancé la vérification du même fichier. Une vérification enregistre désormais son document et refuse celui qui est déjà en cours, et une seule recherche approfondie peut tourner à la fois dans une conversation." },
      { lead: "Un fournisseur lent faisait durer chaque appel plus d'une minute.", rest: " OpenRouter sert un même modèle par plusieurs fournisseurs, et les classer par débit revenait sans cesse à un fournisseur dégradé. Les appels vont maintenant au moins cher parmi ceux qui atteignent un seuil de vitesse, et un même appel de 700 tokens est passé de plus d'une minute à 4 à 11 secondes." },
      { lead: "En production, les recherches approfondies restaient superficielles.", rest: " Quatre recherches réelles ont duré moins d'une minute, lu une à quatre pages et produit moins de mille mots, pour un budget de douze minutes. À chaque décision de profondeur, un modèle rapide choisissait le minimum. Les seuils sont désormais inscrits dans les outils : un chercheur ne peut rien soumettre avant d'avoir lu deux pages, l'agent pilote ne peut pas rédiger après un seul tour, et le rédacteur ajuste la longueur du rapport à ce qui a été trouvé." },
      { lead: "Deux vérifications du même document ne vérifiaient pas la même chose.", rest: " Le vérificateur choisissait ses affirmations en silence, quelque part dans sa boucle de recherche. Il s'engage maintenant sur sa liste d'abord, chaque affirmation liée au passage d'où elle vient, et rien n'est cherché tant qu'une relecture n'a pas confirmé que la liste couvre le document." },
    ],

    evalTitle: "Comment je le mesure",
    evalBody: "Le dépôt contient 150 premiers messages réalistes, des questions sur moi aux prémisses fausses, en passant par des injections de prompt et des fautes de frappe, chacun accompagné de ce qu'une bonne réponse doit faire. Le banc d'essai les fait passer par le vrai tour de conversation et enregistre les outils, le plan, chaque recherche, la réponse, le coût et le temps. Un changement de prompt d'une phrase fait moins bouger les moyennes que le bruit du juge lui-même, donc les changements sont comparés face à face : un autre modèle juge les deux réponses à la même question sans savoir quelle version a écrit laquelle, deux fois, et un désaccord compte comme une égalité.",
    evalHead: ["Changement", "Mesuré sur", "Résultat"],
    evalRows: [
      ["Donner la date du jour aux agents", "8 questions liées à l'actualité", "Gagne 3-2 sur les réponses et 2-0 sur les plans"],
      ["Dire au superviseur ce qu'est Nexus et qui l'a construit", "24 questions sur l'application et sur moi", "Aiguillage de 15/24 à 24/24 corrects, recherches web de 12 à 0, 35 % moins cher"],
      ["Envoyer la conversation en vrais messages", "Les mêmes 24", "13 victoires, 6 défaites, 5 égalités, et une instruction injectée n'a pas pris la main"],
      ["Laisser le planificateur dimensionner son plan", "8 questions larges", "Des plans plus larges, que le juge note moins bien : question encore ouverte"],
    ],
    evalNote: "Le juge n'est pas neutre. Il préfère souvent la plus courte de deux réponses justes, et il compte les angles supplémentaires d'un plan comme une dérive, ce qui explique que la dernière ligne reste une question ouverte.",

    limitsTitle: "Ce qu'il ne fait pas encore",
    limits: [
      "Les comptes sont sur invitation, et je les crée à la main.",
      "La recherche porte sur le web. Chercher en parallèle dans vos propres documents n'existe pas encore.",
      "Seule une recherche approfondie reprend après un plantage du worker. Un tour de conversation ou une vérification passe en échec.",
      "Une recherche approfondie prend environ 20 à 30 minutes, dont une bonne partie à attendre le chercheur le plus lent.",
      "Un PDF de plus de 12 pages est refusé.",
      "L'évaluation s'appuie sur un modèle comme juge, et les séries notées restent petites.",
      "Les défenses contre l'injection de prompt sont en place mais pas encore mesurées sur des recherches complètes.",
    ],

    sysLabels: {
      browser: "Navigateur",
      frontend: "App React",
      cdn: "Cloudflare",
      api: "FastAPI",
      apiRole: "comptes, tâches, flux",
      host: "Railway",
      queue: "Redis",
      queueRole: "file + bus de diffusion",
      worker: "Worker",
      workerRole: "exécute les agents",
      db: "Postgres",
      dbRole: "Neon",
      models: "OpenRouter",
      search: "SearXNG + Crawl4AI",
      searchRole: "auto-hébergés",
      stream: "server-sent events",
      job: "tâche",
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
      deepRole: "par étapes, des minutes",
      factCheck: "Vérification",
      factRole: "affirmations d'un fichier",
      outputs: "Rapports",
      background: "arrière-plan",
    },
  },
  footer: {
    builtBy: "Construit par Ghali Ben Bouzid.",
    restPre: "Le reste de mon travail se trouve sur ",
    restPost: ".",
    exploreTitle: "Explorer",
    codeTitle: "Code",
    source: "Code sur GitHub",
    agentOrch: "Orchestration des agents",
    note: "Nexus : recherche approfondie et sourcée. FastAPI et Python côté serveur, React côté interface, orchestration d'agents avec LangGraph sur OpenRouter.",
  },
  chat: {
    runningPlaceholder: "Travail en cours… arrêtez pour demander autre chose",
    idlePlaceholder: "Posez une question",
    jumpLatest: "Aller au plus récent",
    showArtifacts: "Afficher les rapports",
  },
  ask: {
    position: (n: number, of: number) => `${n} sur ${of}`,
    previous: "Question précédente",
    next: "Question suivante",
    close: "Fermer",
    other: "Autre chose",
    skip: "Passer",
    placeholder: "Ou répondez directement…",
    navigate: "pour naviguer",
    select: "pour choisir",
    typeBelow: "ou écrivez ci-dessous",
    skipped: "Ignorée",
  },
  access: {
    credits: (percent: number) => `Il vous reste ${percent} % de vos crédits de démo`,
    invalid: "Ce lien d'invitation n'est pas valide.",
    none: "La recherche en direct nécessite un lien d'invitation.",
  },
  demo: {
    title: "La recherche en direct est sur invitation",
    body: "Chaque recherche utilise de vrais modèles et des recherches web en direct : l'accès passe donc par un compte de démo. Écrivez-moi sur LinkedIn et je vous en crée un.",
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
  when: {
    justNow: "à l'instant",
    minutesAgo: (n: number) => (n === 1 ? "il y a une minute" : `il y a ${n} minutes`),
    hoursAgo: (n: number) => (n === 1 ? "il y a une heure" : `il y a ${n} heures`),
    today: (time: string) => `Aujourd'hui à ${time}`,
    yesterday: (time: string) => `Hier à ${time}`,
    on: (date: string, time: string) => `${date} à ${time}`,
  },
  artifact: {
    back: "Retour aux rapports",
    report: "Rapport",
    closePanel: "Fermer le panneau",
    copy: "Copier le rapport",
    copied: "Copié",
    rerun: "Relancer",
    refresh: "Actualiser le rapport",
    sourcesHead: "Sources",
    cited: (n: number) => `${n} citée${n > 1 ? "s" : ""}`,
    allConsulted: (n: number) => `Les ${n} consultées`,
    onlyCited: (n: number) => `Les ${n} citées seulement`,
    emptyFailed: "Cette recherche n'a pas produit de rapport.",
    emptyNoCite: "Pas de rapport : les agents n'ont rien trouvé à citer pour cette question.",
    emptyPending: "Le rapport apparaîtra ici dès que les agents auront terminé.",
    title: "Rapports",
    noReports: "Aucun rapport pour l'instant. Demandez une recherche approfondie, ou vérifiez un document.",
    running: "En cours…",
    workingFor: (clock: string) => `En cours depuis ${clock}`,
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
    truncated: "tronqué",
    pages: (n: number) => (n === 1 ? "1 page" : `${n} pages`),
    ready: (name: string) =>
      `${name} est joint. Posez une question dessus, ou faites-le vérifier.`,
    uploading: "Envoi",
    reading: "Lecture",
    failedFile: "Échec",
    retry: "Réessayer",
    drop: "Déposez pour joindre",
    dropHint: "PDF, Word ou texte",
    unsupported: "Ce format de fichier n'est pas pris en charge. Essayez-en un autre.",
  },
  account: {
    plan: "Démo",
    menu: "Compte",
    kind: "Compte de démo",
    credits: "Crédits",
    left: (percent: number) => `${percent} % restants`,
    until: (date: string) => `Accès jusqu'au ${date}`,
    stays: "Votre session reste ouverte sur ce navigateur jusqu'à la déconnexion.",
    signOut: "Se déconnecter",
    confirm: "Pour vous reconnecter, il faudra rouvrir votre lien d'invitation. Gardez-le à portée de main.",
    cancel: "Annuler",
  },
  preview: {
    open: (name: string) => `Ouvrir ${name}`,
    close: "Fermer",
    download: "Télécharger",
    newTab: "Ouvrir dans un nouvel onglet",
    loading: "Ouverture du fichier",
    failed: "Le fichier n'a pas pu être ouvert.",
    none: "Pas d'aperçu pour ce type de fichier. Téléchargez-le pour le lire.",
  },
  outputs: {
    ready: (title: string) => `${title} est prêt.`,
    open: "Ouvrir",
    dismiss: "Ignorer",
  },
  notify: {
    title: "Votre rapport est prêt",
    tab: (n: number) => (n === 1 ? "Rapport prêt" : `${n} rapports prêts`),
  },
  tour: {
    title: "Nexus en bref",
    start: "Visite guidée",
    skip: "Passer",
    back: "Retour",
    next: "Suivant",
    done: "Commencer",
    deep: {
      title: "Recherche approfondie",
      body: "Pour les questions complexes qui demandent une recherche poussée. Vous recevez un rapport complet, sources à l'appui. Comptez jusqu'à 25 minutes environ, selon la demande. Vous pouvez continuer à discuter en attendant.",
    },
    attach: {
      title: "Vérifier un document",
      body: "Joignez un document, puis choisissez Vérification. Nexus le confronte à des sources indépendantes sur le web et vous remet un rapport détaillé sur la véracité de ses affirmations.",
    },
    outputs: {
      title: "Vos rapports arrivent ici",
      body: "Dès qu'un rapport est terminé, il s'affiche ici et une notification vous prévient, même si vous êtes dans un autre onglet.",
    },
    history: {
      title: "Vos conversations",
      body: "Toutes vos conversations sont enregistrées ici. Rouvrez-en une pour la reprendre là où vous l'aviez laissée.",
    },
  },
  tips: {
    gotIt: "Compris",
    deep: {
      title: "Votre recherche approfondie est lancée",
      body: "Comptez jusqu'à 25 minutes environ, selon la demande. Le rapport s'affichera ici et une notification vous préviendra dès qu'il sera prêt. D'ici là, vous pouvez continuer à discuter ou changer d'onglet.",
    },
    factcheck: {
      title: "Votre vérification est lancée",
      body: "Nexus confronte votre document à des sources indépendantes pour en établir la véracité. Comptez quelques minutes. Le rapport détaillé s'affichera ici et une notification vous préviendra dès qu'il sera prêt.",
    },
    attach: {
      title: "Votre document est joint",
      body: "Posez toutes vos questions à son sujet, ou choisissez le mode Vérification, ici, pour en évaluer la véracité face à des sources indépendantes.",
    },
  },
  modes: {
    pick: "Mode",
    off: "Revenir à une réponse normale",
    answer: {
      label: "Réponse",
      note: "Une réponse rapide, en quelques secondes.",
    },
    deep: {
      label: "Recherche approfondie",
      note: "Pour les questions complexes. Jusqu'à 25 minutes environ, selon la demande.",
    },
    factcheck: {
      label: "Vérification",
      note: "Évalue la véracité d'un document face à des sources indépendantes.",
      needsFile: "Joignez d'abord un document",
      request: (file: string) => `Vérifie ${file}`,
    },
  },
  effort: {
    pick: "Effort",
    head: "Le temps de réflexion avant de répondre",
    high: {
      label: "Élevé",
      note: "Réfléchit et cite ses sources. Adapté à la plupart des questions.",
    },
    max: {
      label: "Max",
      note: "Son raisonnement le plus poussé, pour les problèmes difficiles. Plus lent : une réponse peut prendre une à deux minutes.",
    },
  },

  modePlaceholder: {
    answer: "",
    deep: "Que doit couvrir le rapport ?",
    factcheck: "Quel document, et sur quoi concentrer la vérification ?",
  } as Record<string, string>,
  cites: {
    label: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
    missing: "Cette source n'est plus répertoriée.",
    prev: "Source précédente",
    next: "Source suivante",
  },
  history: {
    unread: "Rapport non lu",
    recent: "Récent",
    loading: "Chargement…",
    empty: "Aucune conversation pour l'instant.",
    untitled: "Conversation sans titre",
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
    answered: "Réponse rédigée",
    readingDocument: (name: string) => `lecture de ${name}`,
    steering: "transmission de votre modification à la recherche en cours",
    listingClaims: "recensement des affirmations à vérifier",
    deepStarted: (title: string) =>
      `Recherche approfondie lancée${title ? ` : ${title}` : ""}`,
    factCheckStarted: (name: string) => `Vérification lancée${name ? ` : ${name}` : ""}`,
    inOutputs: "dans vos rapports",
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
    think: "Réflexion",
    searchStep: (query: string) => `Recherche « ${query} »`,
    readStep: (domain: string) => `Lecture de ${domain}`,
    documentStep: (name: string) => `Lecture de ${name}`,
    steerStep: "Transmission de votre modification à la recherche en cours",
    researchStep: (question: string) => `Équipe de recherche : ${question}`,
    stepCount: (n: number) => `${n} étape${n > 1 ? "s" : ""}`,
    searching: (query: string) => `recherche « ${query} »`,
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

export let t: Dict = lang === "fr" ? fr : en;

function applyToDocument(): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = lang;
  document.title = t.docTitle;
}
applyToDocument();

const listeners = new Set<() => void>();

// Called on every switch, so the app can re-render. Returns an unsubscribe.
export function onLangChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Persist the choice and switch in place, without a reload.
export function setLang(next: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  lang = next;
  t = next === "fr" ? fr : en;
  applyToDocument();
  listeners.forEach((listener) => listener());
}
