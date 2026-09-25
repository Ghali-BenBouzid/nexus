import { Fragment, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { Conversation } from "./components/Conversation";
import { DeepDive } from "./components/DeepDive";
import { DemoDialog } from "./components/DemoDialog";
import { Hero } from "./components/Hero";
import { History } from "./components/History";
import { Nav } from "./components/Nav";
import { Toast } from "./components/Toast";
import { Tip } from "./components/Tip";
import { Tour } from "./components/Tour";
import { About, Footer, HowItWorks } from "./components/Sections";
import {
  cancelQuery,
  createConversation,
  deleteDocument,
  getAccount,
  listDocuments,
  listOutputs,
  loadConversation,
  openOutput,
  redeemInvite,
  resumeRun,
  uploadDocument,
  type Account,
  type LoadedTurn,
} from "./lib/api";
import { creditsLeft } from "./lib/credits";
import { t } from "./lib/i18n";
import { outcomeFor } from "./lib/outcome";
import { getRoute, inviteFromUrl, navigate, onPopState, type Route } from "./lib/router";
import {
  applyBackground,
  applyFont,
  applyPalette,
  getStoredBloom,
  getStoredDarkLevel,
  getStoredFont,
  getStoredPalette,
} from "./lib/design";
import { initFluidBackground, type FluidHandle } from "./lib/fluidBackground";
import { isLive, LIVE_MODE, runResearch, type ResearchCallbacks } from "./lib/research";
import { formatAnswers } from "./lib/ask";
import { markTipSeen, tipSeen, tourSeen, type Tip as TipDef, type TipId } from "./lib/tour";
import { isUnread, loadSeen, markSeen, saveSeen, type Seen } from "./lib/unread";
import { DocPreview, type PreviewTarget } from "./components/DocPreview";
import type {
  Answered,
  ConversationId,
  Doc,
  LayoutMode,
  Mode,
  Output,
  Result,
  Theme,
  Turn,
  View,
} from "./types";

// A file the user just picked, as a document, before the server has seen it.
// Negative ids keep it apart from anything real: a placeholder can be listed and
// removed, but never fetched, deleted or fact-checked.
let heldSeq = 0;

function placeholder(file: File): Doc {
  return {
    id: -++heldSeq,
    filename: file.name,
    mediaType: file.type || "application/octet-stream",
    sizeBytes: file.size,
    pages: null,
    chars: 0,
    truncated: false,
    ocr: false,
    state: "uploading",
  };
}

const pending = (doc: Doc) => doc.id < 0;

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "light",
  );
  // The URL is the source of truth for the view; a deep link or reload on
  // /chat/:id starts on the chat view and the conversation is loaded on mount.
  const [view, setView] = useState<View>(() => getRoute().view);
  const [turns, setTurns] = useState<Turn[]>([]);
  // Both side panels start open on a desktop, because a panel nobody opens is a
  // feature nobody knows exists: the Outputs list is how a visitor learns that
  // background runs land somewhere. On a phone they are sheets over the thread,
  // so there they stay shut.
  const [layout, setLayout] = useState<LayoutMode>(() => {
    try {
      if (window.matchMedia("(max-width: 920px)").matches) return "thread";
      const stored = localStorage.getItem("nexus-outputs-open");
      return stored === null || stored === "true" ? "split" : "thread";
    } catch {
      return "thread";
    }
  });
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [scrolled, setScrolled] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Locked design (the live Design Lab was removed): one accent palette for both
  // themes, a font, the dark-mode glow and background level. Applied once on mount.
  const [palette] = useState(getStoredPalette);
  const [font] = useState(getStoredFont);
  const [bloom] = useState(getStoredBloom);
  const [darkLevel] = useState(getStoredDarkLevel);
  // The Recent column starts open on a desktop and the user's choice is
  // remembered from then on.
  const [chatHistoryOpen, setChatHistoryOpen] = useState(() => {
    try {
      // On mobile the Recent column is a drawer opened from a corner button; it
      // always lands closed, regardless of the remembered desktop preference.
      if (window.matchMedia("(max-width: 920px)").matches) return false;
      const stored = localStorage.getItem("nexus-history-open");
      return stored === null ? true : stored === "true";
    } catch {
      return false;
    }
  });
  const toggleChatHistory = () =>
    setChatHistoryOpen((open) => {
      const next = !open;
      try {
        localStorage.setItem("nexus-history-open", String(next));
      } catch {
        /* ignore */
      }
      return next;
    });

  // The live conversation this chat belongs to (null = a fresh, unsaved chat).
  // A page refresh starts fresh and lands on home; the previous conversation
  // stays saved server-side and is reopened on demand from Recent/history.
  const [activeConversationId, setActiveConversationId] = useState<ConversationId | null>(
    null,
  );
  const setActiveConversation = (id: ConversationId | null) => setActiveConversationId(id);

  // Live research needs an invite (see lib/api). Without one, or once it has been
  // revoked or has expired, a live build asks for a demo account instead.
  const [live, setLive] = useState(isLive);
  const [account, setAccount] = useState<Account | null>(null);
  // Why an invite link did not work, shown under the composer for this session.
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);

  // Every report this account has. The list is account-wide because a background
  // run outlives the turn that started it and has to be announced wherever the
  // user went; the panel only ever shows the open conversation's share of it.
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [documents, setDocuments] = useState<Doc[]>([]);
  // The file open in the viewer, if any. It sits over everything, so it lives
  // here rather than in whichever of the four places it was opened from.
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const previewDoc = (doc: Doc) =>
    !doc.state && setPreview({ name: doc.filename, bytes: doc.sizeBytes, docId: doc.id });
  const previewFile = (file: File) => setPreview({ name: file.name, bytes: file.size, file });
  const [openOutputId, setOpenOutputId] = useState<number | null>(null);
  const [openOutputResult, setOpenOutputResult] = useState<Result | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Files picked in the composer but not sent yet. They are uploaded when the
  // message goes, so a file can be the first thing in a chat.
  const [staged, setStaged] = useState<File[]>([]);
  // Deep research mode: the next message starts a research run instead of a
  // chat turn. It belongs to the chat it was switched on in, and is dropped on
  // the way to any other one: it spends minutes and real money, so it is only
  // ever on because the user just said so, never because they said so earlier
  // somewhere else.
  const [mode, setMode] = useState<Mode>("answer");
  // The quick tour, for someone handed a demo account who would otherwise never
  // find deep research or fact check. Auto once per browser, replayable from the
  // nav. It waits a beat so it lands on a settled page, not a half-painted one.
  const [tour, setTour] = useState(false);
  // One-time tips waiting to be shown, one at a time: a fact check can start a
  // second after its document was attached, and two bubbles would talk over
  // each other.
  const [tips, setTips] = useState<TipDef[]>([]);
  const offerTip = (id: TipId, targets: string[], around?: string) => {
    if (!live || tipSeen(id)) return;
    setTips((queue) => (queue.some((q) => q.id === id) ? queue : [...queue, { id, targets, around }]));
  };
  const doneTip = (id: TipId) => {
    markTipSeen(id);
    setTips((queue) => queue.filter((q) => q.id !== id));
  };
  // Doing what a tip suggests is as good as "Got it". Only a tip that is up or
  // waiting counts: acting before a tip was ever offered leaves it to come later.
  const actedOn = (done: (tip: TipDef) => boolean) => {
    for (const tip of tips) if (done(tip)) markTipSeen(tip.id);
    setTips((queue) => queue.filter((q) => !done(q)));
  };
  // Runs this tab has seen working. Only those are announced when they finish:
  // a report that was already done when the page loaded is not news, and it
  // still carries its unread mark in Outputs. Remembering announcements in the
  // browser instead announced every past run at once on a new device.
  const watching = useRef<Set<number>>(new Set());
  // Background runs we have already shown the panel for. Once per run: if the
  // user shuts the panel while one is still working, that is an answer, and
  // reopening it every five seconds would be the app arguing with them.
  const revealed = useRef<Set<number>>(new Set());
  const [ready, setReady] = useState<Output[]>([]);
  // Which reports this browser has read, so a finished one is marked new until
  // it is opened, and marked new again when a refresh rewrites it.
  const [seen, setSeen] = useState<Seen>(loadSeen);

  const turnSeq = useRef(0);
  const cancelled = useRef<Set<number>>(new Set());
  // The uploads a turn is still sending, so Stop reaches them too: a long PDF
  // is read before the message is even sent, and stopping only the turn left it
  // reading on and attached anyway.
  const uploads = useRef<Map<number, AbortController>>(new Map());
  const fluidRef = useRef<FluidHandle | null>(null);

  // Map a rehydrated backend turn into the conversation's Turn shape. A turn that
  // was still in flight when the snapshot was taken keeps a null endedAt so its
  // timer runs (and a resumed poll, below, drives it to completion).
  const turnFromLoaded = (lt: LoadedTurn): Turn => {
    const inFlight = lt.status === "running" || lt.status === "pending";
    return {
      id: ++turnSeq.current,
      queryId: lt.queryId ?? undefined,
      query: lt.query,
      attachments: lt.attachments,
      answers: lt.answers,
      ask: lt.ask,
      title: lt.title,
      status: lt.status,
      events: [],
      reply: lt.reply,
      result: lt.result,
      outcome: outcomeFor(lt.status, lt.reply ?? "", lt.result.sources.length),
      error: lt.error,
      stopped: lt.stopped,
      startedAt: performance.now(),
      endedAt: inFlight ? null : performance.now(),
    };
  };

  // Re-attach a poll to any turn that was still running when its conversation was
  // snapshotted (e.g. reopened mid-planning), so it keeps progressing to the plan
  // prompt or the report instead of sticking on "running" with nothing driving it.
  const resumeInFlight = (loaded: Turn[]) => {
    loaded.forEach((turn) => {
      if (turn.queryId == null) return;
      if (turn.status !== "running" && turn.status !== "pending") return;
      const id = turn.id;
      setNow(performance.now());
      resumeRun(turn.queryId, callbacksFor(id))
        .then((res) => {
          if (!cancelled.current.has(id)) applyOutcome(id, res);
        })
        .catch((err) => {
          if (!cancelled.current.has(id)) failTurn(id, err);
        });
    });
  };

  // Mount the WebGL fluid background on the canvas declared in index.html.
  useEffect(() => {
    const canvas = document.getElementById("fluid-canvas") as HTMLCanvasElement | null;
    if (!canvas) return;
    fluidRef.current = initFluidBackground(canvas, theme);
    return () => {
      fluidRef.current?.dispose();
      fluidRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Lift the boot splash (the opaque anti-flash cover in index.html) once the app
  // has mounted and painted a frame. Two rAFs guarantee at least one real paint,
  // so the splash only fades to the dark app, never to a white intermediate. The
  // fade + removal is done directly on the node (not a CSS attribute toggle) so it
  // is unconditional: the cover can never get stuck over the app.
  useEffect(() => {
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        const splash = document.getElementById("boot-splash");
        if (!splash) return;
        splash.style.opacity = "0";
        setTimeout(() => splash.remove(), 300); // after the 0.25s fade
      });
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, []);

  // Theme side-effects: persist, set the attribute, recolor the fluid.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("nexus-theme-2", theme);
    } catch {
      /* ignore */
    }
    fluidRef.current?.setTheme(theme);
  }, [theme]);

  // Apply the locked palette (CSS accent vars + the fluid blob colors) and font.
  // Runs after the theme effect so the fluid override wins.
  useEffect(() => {
    applyPalette(palette);
    fluidRef.current?.setPalette(palette.fluidA, palette.fluidB);
  }, [palette]);
  // Adaptive backdrop: dark bg is derived from the accent; the same color drives
  // the fluid's clear color. Re-runs on theme so it tracks dark/light.
  useEffect(() => {
    const clear = applyBackground(palette, theme, darkLevel);
    fluidRef.current?.setBackground(clear);
  }, [palette, theme, darkLevel]);
  useEffect(() => {
    fluidRef.current?.setBloom(bloom);
  }, [bloom]);
  useEffect(() => {
    applyFont(font);
  }, [font]);

  // Body stage dims the fluid behind dense content.
  useEffect(() => {
    // The fluid background belongs to the landing page; the deep dive reads like
    // a document, so it gets the chat's quiet backdrop.
    document.body.dataset.stage = view === "home" ? "home" : "chat";
  }, [view]);

  // A shared clock that ticks only while a run is in flight, so every running
  // turn's elapsed timer advances without a per-turn interval.
  const anyRunning = turns.some((t) => t.status === "running" || t.status === "pending");
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => setNow(performance.now()), 150);
    return () => clearInterval(id);
  }, [anyRunning]);

  // The composer shows the budget left: fetch it once access is granted and again
  // each time a run settles, since every run spends from it.
  useEffect(() => {
    if (!live || anyRunning) return;
    getAccount().then((acc) => {
      setAccount(acc);
      setLive(isLive()); // an expired account drops the invite on this call
    });
  }, [live, anyRunning]);

  // Outputs are polled while any of them is still working: a deep run or a fact
  // check finishes on its own, often after the user has moved to another chat.
  const anyOutputRunning = outputs.some(
    (o) => o.status === "running" || o.status === "pending",
  );
  useEffect(() => {
    if (!live) return;
    refreshOutputs();
    if (!anyOutputRunning) return;
    const id = setInterval(refreshOutputs, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, anyOutputRunning, view]);

  // A deep run or a fact check leaves the conversation and works on its own for
  // minutes. Nothing in the thread shows that, so the panel where it will land
  // opens as it starts: the run is visible as running, rather than as silence
  // followed by a report out of nowhere.
  useEffect(() => {
    const starting = outputs.find(
      (o) => (o.status === "running" || o.status === "pending") && !revealed.current.has(o.id),
    );
    if (!starting) return;
    revealed.current.add(starting.id);
    setLayout("split");
    // The panel opening is movement at the edge of the eye, and the first time
    // it happens nobody knows what it means. Only for this chat's own run: one
    // from another chat is not in the panel to point at.
    if (starting.conversationId === activeConversationId) {
      offerTip(starting.kind === "deep_research" ? "deep" : "factcheck", [
        `output-${starting.id}`,
        "outputs",
      ]);
    }
  }, [outputs]);

  // Tell the user once when a report they are no longer watching is ready. Two
  // can land in the same poll, so they queue rather than overwrite each other.
  useEffect(() => {
    for (const o of outputs) {
      if (o.status === "running" || o.status === "pending") watching.current.add(o.id);
    }
    const finished = outputs.filter(
      (o) => o.status === "complete" && watching.current.has(o.id),
    );
    if (finished.length === 0) return;
    for (const o of finished) watching.current.delete(o.id);
    setReady((current) => [...current, ...finished]);
  }, [outputs]);

  const dismiss = (id: number) => setReady((current) => current.filter((o) => o.id !== id));

  // Nav shadow on scroll + hero-focal fluid fade: the blob is full behind the
  // hero and fades out over the first ~70vh as the sections rise. On chat stages
  // the body pins --fluid-op low (CSS), which wins over this since it's closer.
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 16);
      const fade = Math.max(0.12, 1 - y / (window.innerHeight * 0.7));
      document.documentElement.style.setProperty("--fluid-op", fade.toFixed(3));
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Keep the view in sync with the URL on back/forward (and the phone back
  // gesture). A ref holds the latest handler so the listener is registered once
  // but always reads current state.
  const syncRoute = (route: Route) => {
    if (route.view === "how") {
      setView("how");
      window.scrollTo({ top: 0 });
      return;
    }
    if (route.view === "home") {
      setView("home");
      window.scrollTo({ top: 0 });
      return;
    }
    if (route.conversationId == null) {
      setView("chat"); // /chat: a fresh chat
      return;
    }
    if (route.conversationId === activeConversationId) {
      setView("chat"); // already loaded; just show it again
      return;
    }
    if (live) openHistory(route.conversationId);
    else {
      navigate("/", { replace: true });
      setView("home");
    }
  };
  const syncRouteRef = useRef(syncRoute);
  syncRouteRef.current = syncRoute;

  // On mount, redeem an invite link or load a deep-linked /chat/:id (redirecting
  // home if it isn't the user's), then wire popstate to the same sync.
  useEffect(() => {
    const invite = inviteFromUrl();
    if (invite) {
      // An invite link lands on the landing page, where the hero shows the budget
      // (or why the link did not work). The token leaves the URL at once.
      navigate("/", { replace: true });
      redeemInvite(invite)
        .catch((err) => setInviteError(err instanceof Error ? err.message : t.access.invalid))
        .finally(() => setLive(isLive()));
    }
    const route = getRoute();
    if (route.view === "chat" && route.conversationId != null) {
      if (isLive()) openHistory(route.conversationId);
      else {
        navigate("/", { replace: true });
        setView("home");
      }
    }
    return onPopState((r) => syncRouteRef.current(r));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Files staged in a chat belong to that chat's composer. Leaving the chat, by
  // whatever route (the exit button, the logo, the browser's back button),
  // leaves them behind rather than carrying them into the landing page's bar,
  // where they sat looking attached to a question nobody had asked. Watching
  // the view instead of each exit is what keeps a future exit from missing it.
  // The other direction is untouched: a file staged on the landing page is
  // meant to go with the first message into the chat it creates.
  const lastView = useRef(view);
  useEffect(() => {
    if (lastView.current === "chat" && view !== "chat") {
      setStaged([]);
      setUploadError(null);
    }
    lastView.current = view;
  }, [view]);

  // Update only one turn; turns run independently and never clobber each other.
  const patchTurn = (id: number, fn: (t: Turn) => Turn) =>
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

  // Anything arriving from a run is proof it is alive, so it resets the clock
  // that decides whether the run looks stuck. The server only sends a heartbeat
  // frame when the stream has been quiet (bus.IDLE_SECONDS), so a run streaming
  // its thinking or its answer sends no heartbeats at all: without this, the
  // busiest part of a run is exactly when it would be called stuck.
  const alive = () => ({ heartbeatAge: 0, heartbeatSeenAt: performance.now() });

  // The live callbacks for a turn, shared by a fresh run and a resumed poll.
  const callbacksFor = (id: number): ResearchCallbacks => ({
    onEvent: (e) => {
      if (cancelled.current.has(id)) return;
      // Stamp the arrival time: the progress bar times each step from it.
      patchTurn(id, (t) => ({
        ...t,
        ...alive(),
        events: [...t.events, { ...e, at: performance.now() }],
        // A new model call replaces whatever the last one streamed. That is
        // what makes a retry safe: the failed attempt's half-written answer
        // does not stay on screen next to the real one.
        ...(e.kind === "thinking" ? { streamed: undefined, thinking: undefined } : {}),
      }));
    },
    onHeartbeat: (secondsSince) => {
      if (!cancelled.current.has(id))
        patchTurn(id, (t) => ({ ...t, heartbeatAge: secondsSince, heartbeatSeenAt: performance.now() }));
    },
    onStatus: (s) => {
      if (!cancelled.current.has(id)) patchTurn(id, (t) => ({ ...t, status: s }));
    },
    onToken: (text) => {
      if (!cancelled.current.has(id))
        patchTurn(id, (t) => ({
          ...t,
          ...alive(),
          streamed: (t.streamed ?? "") + text,
        }));
    },
    isCancelled: () => cancelled.current.has(id),
    onQueryId: (qid) => patchTurn(id, (t) => ({ ...t, queryId: qid })),
    onConversation: (cid) => {
      setActiveConversation(cid);
      // A fresh chat has no files yet; a follow-up in an existing one may, and
      // the panel is the only place they show.
      listDocuments(cid)
        // Anything still on its way up outlives the refresh: the server does
        // not know about it yet, and dropping it would blank a tile the user
        // is watching.
        .then((docs) => setDocuments((prev) => [...docs, ...prev.filter(pending)]))
        .catch(() => {});
      // The fresh /chat now has a real id: rewrite the URL in place (no extra
      // history entry) so a reload or back/forward resolves to this conversation.
      navigate(`/chat/${cid}`, { replace: true });
    },
    onTitle: (title) => patchTurn(id, (t) => ({ ...t, title })),
  });

  // Apply a finished run's outcome to its turn: a paused plan awaiting confirmation,
  // a direct reply, a research report, or nothing if the run was superseded.
  const applyOutcome = (id: number, res: Awaited<ReturnType<typeof runResearch>>) => {
    if (!res) {
      patchTurn(id, (t) => ({ ...t, endedAt: performance.now() }));
      return;
    }
    patchTurn(id, (t) => ({
      ...t,
      reply: res.reply ?? t.reply,
      ask: res.ask,
      // The stored reply replaces what was streamed; a retried call can have
      // streamed text that no longer exists.
      streamed: undefined,
      result: res.result,
      outcome: res.outcome,
      title: res.title ?? t.title,
      error: res.error ?? null,
      status: res.outcome === "failed" ? "failed" : "complete",
      endedAt: performance.now(),
    }));
    // A finished turn may have started a background run, so refresh what the
    // Outputs panel shows rather than waiting for the next poll.
    refreshOutputs();
  };

  const failTurn = (id: number, err: unknown) => {
    patchTurn(id, (t) => ({
      ...t,
      status: "failed",
      outcome: "failed",
      error: err instanceof Error ? err.message : "The research run failed.",
      endedAt: performance.now(),
    }));
    setLive(isLive()); // a refusal for an expired account drops the invite
  };

  // The hero always opens a brand-new conversation: launching from the landing
  // page starts a fresh chat rather than appending to whatever was open last.
  // Live research spends real credits, so a live build without an invite asks for
  // a demo account instead of running anything. True when it asked.
  const askForDemoAccount = () => {
    if (!LIVE_MODE || isLive()) return false;
    setDemoOpen(true);
    return true;
  };

  function heroSubmit(prompt: string) {
    if (askForDemoAccount()) return;
    turns.forEach((t) => cancelled.current.add(t.id));
    setActiveConversation(null);
    navigate("/chat"); // a fresh chat; becomes /chat/:id once the backend assigns one
    startResearch(prompt, { fresh: true });
  }

  async function startResearch(
    prompt: string,
    opts?: { fresh?: boolean; mode?: Mode; answers?: Answered[] },
  ) {
    if (askForDemoAccount()) return;
    const fresh = opts?.fresh ?? false;
    // One run at a time: ignore a follow-up while another is in flight. A fresh
    // hero submission replaces the workspace, so it is never blocked this way.
    if (!fresh && turns.some((t) => t.status === "running" || t.status === "pending")) return;
    const id = ++turnSeq.current;
    // A fresh submission from the hero starts a new chat, and the hero has no
    // mode control: whatever the last chat was switched into does not follow
    // the user here, any more than it follows them into an existing one.
    // Every mode is a message to the supervisor, which decides what it calls
    // for and answers in the thread: the mode says what the user is after, it
    // never starts a run behind the supervisor's back.
    const runMode: Mode = fresh || !isLive() ? "answer" : (opts?.mode ?? mode);
    const turn: Turn = {
      id,
      query: prompt,
      answers: opts?.answers,
      status: "running",
      events: [],
      result: null,
      outcome: "ok",
      error: null,
      startedAt: performance.now(),
      endedAt: null,
    };
    setNow(turn.startedAt);
    setView("chat");
    // Fresh: drop the previous thread and start a new conversation; the explicit
    // null below means this run never appends to the prior conversation.
    if (fresh) {
      setFocusedId(null);
      setOpenOutputId(null); // a report from the old chat is not this one's
      setTurns([turn]);
      setMode("answer");
    } else {
      setTurns((prev) => [...prev, turn]);
    }
    let conversationId = fresh ? null : activeConversationId;

    try {
      // The staged files go up first: a file belongs to a conversation, so if
      // this is the first message, the conversation is created for them and the
      // message follows, carrying their ids.
      let attached: Doc[] = [];
      if (staged.length && isLive()) {
        // The files show on the message and in the panel before a single byte
        // has moved. Reading a long PDF takes real seconds, and a message that
        // carries nothing for those seconds reads as a message that lost them.
        const files = staged;
        const holding = files.map(placeholder);
        setStaged([]);
        setUploadError(null);
        patchTurn(id, (t) => ({ ...t, attachments: holding }));
        setDocuments((docs) => [...docs, ...holding]);
        if (conversationId == null) {
          conversationId = await createConversation();
          setActiveConversation(conversationId);
          navigate(`/chat/${conversationId}`, { replace: true });
        }
        const upload = new AbortController();
        uploads.current.set(id, upload);
        try {
          attached = await uploadStaged(conversationId, files, holding, id, upload.signal);
        } finally {
          uploads.current.delete(id);
        }
        // Stopped while the files went up: the stop covers everything this
        // message submitted, so nothing is sent and no file stays behind.
        if (cancelled.current.has(id)) {
          const dropped = new Set([...holding, ...attached].map((doc) => doc.id));
          setDocuments((docs) => docs.filter((doc) => !dropped.has(doc.id)));
          patchTurn(id, (t) => ({ ...t, attachments: [] }));
          attached.forEach((doc) => deleteDocument(doc.id).catch(() => {}));
          return;
        }
      }
      // A fact check is one document's; the next message is back to normal.
      if (runMode === "factcheck") setMode("answer");
      const res = await runResearch(
        prompt,
        callbacksFor(id),
        conversationId,
        attached.map((doc) => doc.id),
        runMode,
        opts?.answers,
      );
      if (cancelled.current.has(id)) return;
      applyOutcome(id, res);
    } catch (err) {
      if (!cancelled.current.has(id)) failTurn(id, err);
    }
  }

  // Send the staged files, replacing each placeholder with what came back.
  // A file that fails keeps its tile and says so: dropping it would leave the
  // user asking about a document that is not there. Returns what landed.
  async function uploadStaged(
    conversationId: ConversationId,
    files: File[],
    holding: Doc[],
    turnId: number,
    signal: AbortSignal,
  ): Promise<Doc[]> {
    const uploaded: Doc[] = [];
    for (let i = 0; i < files.length; i++) {
      if (signal.aborted) break;
      const held = holding[i];
      let landed: Doc;
      try {
        landed = await uploadDocument(conversationId, files[i], signal);
        uploaded.push(landed);
      } catch (err) {
        landed = {
          ...held,
          state: "failed",
          error: err instanceof Error ? err.message : t.uploads.failed,
        };
      }
      settle(held.id, landed, turnId);
    }
    return uploaded;
  }

  // Swap a placeholder for its outcome, wherever it is shown.
  function settle(heldId: number, landed: Doc, turnId?: number) {
    const swap = (docs: Doc[]) => docs.map((d) => (d.id === heldId ? landed : d));
    setDocuments(swap);
    if (turnId != null) {
      patchTurn(turnId, (t) => ({ ...t, attachments: swap(t.attachments ?? []) }));
    }
  }

  function stopResearch() {
    setTurns((prev) =>
      prev.map((t) => {
        if (t.status === "running" || t.status === "pending") {
          cancelled.current.add(t.id); // the run loop bails at its next checkpoint
          uploads.current.get(t.id)?.abort(); // and a file still going up stops too
          // Tell the backend to actually stop the job, so it stops spending quota
          // instead of running on in the background after the user stops it.
          if (t.queryId != null) cancelQuery(t.queryId);
          return { ...t, status: "failed", stopped: true, endedAt: performance.now() };
        }
        return t;
      }),
    );
  }

  // --- outputs and uploads ---------------------------------------------------

  // The reports this account has, refreshed whenever one might have changed: a
  // background run finishes on its own, minutes after the turn that started it.
  const refreshOutputs = () => {
    if (!isLive()) return;
    listOutputs().then(setOutputs).catch(() => {});
    // A deep run or a fact check spends from the demo budget while it works, so
    // the credits line follows the same poll rather than waiting for a reload.
    getAccount().then(setAccount).catch(() => {});
  };

  // What the panel shows: this chat's reports and no others. A report belongs to
  // the conversation that asked for it, the same way its documents do, so
  // switching chats must not carry the last one's outputs along.
  const conversationOutputs = outputs.filter(
    (output) => output.conversationId === activeConversationId,
  );

  // Open one report in the panel, loading its body on demand.
  async function showOutput(id: number | null) {
    setOpenOutputId(id);
    setOpenOutputResult(null);
    if (id == null) return;
    // However the report was reached, its "ready" toast has done its job, and so
    // has the tip pointing at it.
    dismiss(id);
    actedOn((tip) => tip.targets.includes(`output-${id}`));
    setLayout("split");
    const output = outputs.find((o) => o.id === id);
    if (output) {
      setSeen((current) => {
        const next = markSeen(current, output);
        saveSeen(next);
        return next;
      });
    }
    const result = await openOutput(id);
    setOpenOutputResult(result);
  }

  async function refreshOutput(id: number) {
    setOpenOutputResult(await openOutput(id));
    refreshOutputs();
  }

  // Attaching from the Outputs panel, for a file the user wants in the
  // conversation without asking anything about it yet. Before the first message
  // there is no conversation to put it in, so it is staged like a composer pick.
  async function addDocument(file: File) {
    offerTip("attach", ["mode"], "composer");
    if (activeConversationId == null) {
      setStaged((files) => [...files, file]);
      return;
    }
    setUploadError(null);
    const held = placeholder(file);
    setDocuments((docs) => [...docs, held]);
    try {
      settle(held.id, await uploadDocument(activeConversationId, file));
    } catch (err) {
      settle(held.id, {
        ...held,
        state: "failed",
        error: err instanceof Error ? err.message : t.uploads.failed,
      });
    }
  }

  async function removeDocument(doc: Doc) {
    setDocuments((docs) => docs.filter((d) => d.id !== doc.id));
    // Nothing to delete for a file that never reached the server.
    if (!pending(doc)) await deleteDocument(doc.id);
  }

  // Fact-check a document from the panel. It is a message like any other, so
  // the request and the supervisor's answer sit in the thread where the user
  // can see what was asked and what happened.
  function factCheck(doc: Doc) {
    startResearch(t.modes.factcheck.request(doc.filename), { mode: "factcheck" });
  }

  const chooseLayout = (m: LayoutMode) => {
    setLayout(m);
    try {
      localStorage.setItem("nexus-outputs-open", String(m === "split"));
    } catch {
      /* ignore */
    }
  };

  // Only for a signed-in demo account: the tour shows recent chats, modes and
  // outputs, none of which exist without one, so a visitor would be walked
  // past controls that are not there. Keyed on `live`, so someone arriving by
  // an invite link gets it once the link has been redeemed.
  useEffect(() => {
    if (!live || tourSeen()) return;
    const id = setTimeout(() => setTour(true), 900);
    return () => clearTimeout(id);
  }, [live]);

  // The tour walks from the landing page into a chat, because half of what it
  // has to show does not exist on the landing page. It opens the chat itself
  // rather than asking the user to find it.
  const tourView = (next: "home" | "chat") => {
    setView((current) => {
      if (current === next) return current;
      navigate(next === "home" ? "/" : "/chat");
      return next;
    });
  };

  function goHome() {
    navigate("/");
    setView("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // The long version of "how it works", on its own page so the landing page can
  // stay one screen of what Nexus is.
  function showDeepDive() {
    navigate("/how");
    setView("how");
    window.scrollTo({ top: 0 });
  }

  // Open a past conversation from the sidebar: load its whole thread and make it
  // the active conversation. Anything running in the current chat is cancelled.
  async function openHistory(conversationId: ConversationId) {
    setHistoryOpen(false);
    const conv = await loadConversation(conversationId);
    // Missing or not owned by this user: the API 404s and we land back on home
    // rather than showing an empty chat for a conversation that isn't theirs.
    if (!conv) {
      navigate("/", { replace: true });
      setView("home");
      return;
    }
    navigate(`/chat/${conv.id}`);
    turns.forEach((t) => {
      if (t.status === "running" || t.status === "pending") cancelled.current.add(t.id);
    });
    const loaded = conv.turns.map(turnFromLoaded);
    setTurns(loaded);
    setActiveConversation(conv.id);
    setDocuments(conv.documents);
    setStaged([]);
    // The mode was switched on for another chat, not this one. Unless this one
    // ends on a question: its answer belongs in the mode it was asked in, or a
    // brainstorm reopened after a reload would be answered as a plain question.
    const last = conv.turns[conv.turns.length - 1];
    setMode(last?.ask?.length && last.mode ? last.mode : "answer");
    setUploadError(null);
    refreshOutputs();
    setFocusedId(null);
    setOpenOutputId(null);
    setView("chat");
    resumeInFlight(loaded);
  }

  function newChat() {
    turns.forEach((t) => cancelled.current.add(t.id));
    setTurns([]);
    setDocuments([]); // documents belong to a conversation, not to the account
    setStaged([]);
    setMode("answer"); // a new chat starts in the ordinary mode, like every other
    setUploadError(null);
    setFocusedId(null);
    setOpenOutputId(null);
    setActiveConversation(null); // a fresh chat starts a new conversation
    navigate("/chat"); // becomes /chat/:id once the backend assigns one
    setView("chat"); // land on a fresh, empty conversation, not the hero
  }

  // Cross-fade between themes. The View Transitions API snapshots the whole
  // viewport (CSS chrome + the fluid canvas) and fades old into new; flushSync
  // commits the theme synchronously so the "after" snapshot is the new theme.
  // Browsers without the API just switch instantly.
  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const start = (
      document as Document & { startViewTransition?: (cb: () => void) => void }
    ).startViewTransition?.bind(document);
    if (start) {
      start(() => flushSync(() => setTheme(next)));
    } else {
      setTheme(next);
    }
  };

  // One line under the composer, keeping the demo's terms visible: the share of
  // credits left for an invited visitor, or why their invite did not work.
  // Local simulated-only builds show nothing.
  // This chat's reports that finished and have not been opened since, for the
  // dot in the Outputs list and the count on the button that opens it. Only
  // this chat's: the panel lists no others, so a count of the rest would point
  // at nothing the user can find there.
  const unread = new Set(conversationOutputs.filter((o) => isUnread(o, seen)).map((o) => o.id));
  // Every chat with such a report, for the dot next to it in Recent.
  const unreadChats = new Set(
    outputs.flatMap((o) => (o.conversationId != null && isUnread(o, seen) ? [o.conversationId] : [])),
  );

  const accessNote = !LIVE_MODE
    ? null
    : live
      ? account && t.access.credits(creditsLeft(account.remaining_usd, account.budget_usd))
      : inviteError;

  return (
    <Fragment>
      {/* Only the landing page has a nav; the chat's left column carries the brand. */}
      {view === "home" && (
        <Nav
          theme={theme}
          toggleTheme={toggleTheme}
          onLogo={goHome}
          scrolled={scrolled}
          onHistory={live ? () => setHistoryOpen(true) : undefined}
          onStart={() => document.querySelector<HTMLTextAreaElement>(".prompt textarea")?.focus()}
          onTour={live ? () => setTour(true) : undefined}
        />
      )}

      {live && (
        <History
          open={historyOpen}
          onClose={() => setHistoryOpen(false)}
          onOpen={openHistory}
          onNewChat={() => {
            setHistoryOpen(false);
            newChat();
          }}
        />
      )}

      {view === "home" && (
        <Fragment>
          <Hero
            onSubmit={heroSubmit}
            note={accessNote}
            staged={live ? staged : undefined}
            onAttach={(files) => setStaged((current) => [...current, ...files])}
            onUnstage={(index) => setStaged((current) => current.filter((_, i) => i !== index))}
            onPreview={previewFile}
            attachError={uploadError}
          />
          <About />
          <HowItWorks onDeepDive={showDeepDive} />
          <Footer />
        </Fragment>
      )}

      {preview && <DocPreview target={preview} onClose={() => setPreview(null)} />}

      {tour && <Tour onView={tourView} onFinish={() => setTour(false)} />}

      {/* The tour already says everything a tip would, so tips wait it out. */}
      {!tour && tips[0] && <Tip key={tips[0].id} tip={tips[0]} onDone={() => doneTip(tips[0].id)} />}

      {view === "how" && <DeepDive onBack={goHome} />}

      {view === "chat" && (
        <Conversation
          turns={turns}
          now={now}
          layout={layout}
          onLayout={chooseLayout}
          focusedId={focusedId}
          onFocus={setFocusedId}
          onSubmit={startResearch}
          onAnswer={(answers) => startResearch(formatAnswers(answers), { answers })}
          onStop={stopResearch}
          onExit={goHome}
          mode={mode}
          // Live only: a demo build has no deep run to start, and offering a
          // mode that cannot do anything is worse than not offering it.
          onMode={
            live
              ? (next) => {
                  setMode(next);
                  actedOn((tip) => tip.id === "attach");
                }
              : undefined
          }
          outputs={conversationOutputs}
          documents={documents}
          openOutputId={openOutputId}
          openOutputResult={openOutputResult}
          onOpenOutput={showOutput}
          unread={unread}
          unreadChats={unreadChats}
          onRefreshOutput={refreshOutput}
          staged={staged}
          onAttach={(files) => {
            setStaged((current) => [...current, ...files]);
            offerTip("attach", ["mode"], "composer");
          }}
          onUnstage={(index) => setStaged((current) => current.filter((_, i) => i !== index))}
          onUpload={addDocument}
          onRemoveDocument={removeDocument}
          onFactCheck={factCheck}
          onPreviewDoc={previewDoc}
          onPreviewFile={previewFile}
          uploadError={uploadError}
          running={anyRunning}
          onNewChat={newChat}
          accessNote={accessNote}
          historyOpen={chatHistoryOpen}
          onToggleHistory={toggleChatHistory}
          onOpenHistory={live ? openHistory : undefined}
          theme={theme}
          toggleTheme={toggleTheme}
          account={live ? account : null}
        />
      )}

      {/* A background run finishes on its own, so it says so wherever the user
          happens to be, with one tap to go and read it. It sits in the corner the
          Outputs panel opens from, and never over the composer. */}
      {ready.length > 0 && (
        <div className="toasts">
          {ready.map((output) => (
            <Toast
              key={output.id}
              title={output.title}
              onOpen={async () => {
                dismiss(output.id);
                // The run may have finished while the user was in another chat,
                // and the panel only holds the open one's reports. Go to the
                // chat that asked for it first, then open it there.
                if (
                  output.conversationId != null &&
                  output.conversationId !== activeConversationId
                ) {
                  await openHistory(output.conversationId);
                }
                setView("chat");
                showOutput(output.id);
              }}
              onDismiss={() => dismiss(output.id)}
            />
          ))}
        </div>
      )}

      <DemoDialog open={demoOpen} onClose={() => setDemoOpen(false)} />
    </Fragment>
  );
}
