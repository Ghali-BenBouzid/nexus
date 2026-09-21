import { Fragment, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import { Conversation } from "./components/Conversation";
import { DemoDialog } from "./components/DemoDialog";
import { Hero } from "./components/Hero";
import { History } from "./components/History";
import { Nav } from "./components/Nav";
import { Toast } from "./components/Toast";
import { About, Footer, HowItWorks } from "./components/Sections";
import {
  cancelQuery,
  createConversation,
  deleteDocument,
  factCheckDocument,
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
import { isUnread, loadSeen, markSeen, saveSeen, type Seen } from "./lib/unread";
import type { Doc, LayoutMode, Output, Result, Theme, Turn, View } from "./types";

// Which outputs this browser has already announced. A per-viewer convenience,
// so it lives in localStorage and a failure to read it is not worth a thought.
const ANNOUNCED_KEY = "nexus-announced";

function storedAnnounced(): number[] {
  try {
    const raw = localStorage.getItem(ANNOUNCED_KEY);
    return raw ? (JSON.parse(raw) as number[]) : [];
  } catch {
    return [];
  }
}

function rememberAnnounced(ids: Set<number>): void {
  try {
    localStorage.setItem(ANNOUNCED_KEY, JSON.stringify([...ids].slice(-50)));
  } catch {
    /* ignore */
  }
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "light",
  );
  // The URL is the source of truth for the view; a deep link or reload on
  // /chat/:id starts on the chat view and the conversation is loaded on mount.
  const [view, setView] = useState<View>(() => getRoute().view);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [layout, setLayout] = useState<LayoutMode>("thread");
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
  // The Recent column is hidden by default; the user's open/closed choice is
  // remembered across sessions.
  const [chatHistoryOpen, setChatHistoryOpen] = useState(() => {
    try {
      // On mobile the Recent column is a drawer opened from a corner button; it
      // always lands closed, regardless of the remembered desktop preference.
      if (window.matchMedia("(max-width: 920px)").matches) return false;
      return localStorage.getItem("nexus-history-open") === "true";
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
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const setActiveConversation = (id: number | null) => setActiveConversationId(id);

  // Live research needs an invite (see lib/api). Without one, or once it has been
  // revoked or has expired, a live build asks for a demo account instead.
  const [live, setLive] = useState(isLive);
  const [account, setAccount] = useState<Account | null>(null);
  // Why an invite link did not work, shown under the composer for this session.
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);

  // The right-hand panel. Outputs are account-wide, because a background run
  // outlives the conversation that started it; documents belong to the open one.
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [openOutputId, setOpenOutputId] = useState<number | null>(null);
  const [openOutputResult, setOpenOutputResult] = useState<Result | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Files picked in the composer but not sent yet. They are uploaded when the
  // message goes, so a file can be the first thing in a chat.
  const [staged, setStaged] = useState<File[]>([]);
  // Which finished outputs the user has already been told about, so a report is
  // announced once per browser and not again on every reload.
  const announced = useRef<Set<number>>(new Set(storedAnnounced()));
  const [ready, setReady] = useState<Output[]>([]);
  // Which reports this browser has read, so a finished one is marked new until
  // it is opened, and marked new again when a refresh rewrites it.
  const [seen, setSeen] = useState<Seen>(loadSeen);

  const turnSeq = useRef(0);
  const cancelled = useRef<Set<number>>(new Set());
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

  // Tell the user once when a report they are no longer watching is ready. Two
  // can land in the same poll, so they queue rather than overwrite each other.
  useEffect(() => {
    const finished = outputs.filter(
      (o) => o.status === "complete" && !announced.current.has(o.id),
    );
    if (finished.length === 0) return;
    for (const o of finished) announced.current.add(o.id);
    rememberAnnounced(announced.current);
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

  // Update only one turn; turns run independently and never clobber each other.
  const patchTurn = (id: number, fn: (t: Turn) => Turn) =>
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));

  // The live callbacks for a turn, shared by a fresh run and a resumed poll.
  const callbacksFor = (id: number): ResearchCallbacks => ({
    onEvent: (e) => {
      if (cancelled.current.has(id)) return;
      // Stamp the arrival time: the progress bar times each step from it.
      patchTurn(id, (t) => ({
        ...t,
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
        patchTurn(id, (t) => ({ ...t, streamed: (t.streamed ?? "") + text }));
    },
    onThought: (text) => {
      if (!cancelled.current.has(id))
        patchTurn(id, (t) => ({ ...t, thinking: (t.thinking ?? "") + text }));
    },
    isCancelled: () => cancelled.current.has(id),
    onQueryId: (qid) => patchTurn(id, (t) => ({ ...t, queryId: qid })),
    onConversation: (cid) => {
      setActiveConversation(cid);
      // A fresh chat has no files yet; a follow-up in an existing one may, and
      // the panel is the only place they show.
      listDocuments(cid).then(setDocuments).catch(() => {});
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

  async function startResearch(prompt: string, opts?: { fresh?: boolean }) {
    if (askForDemoAccount()) return;
    const fresh = opts?.fresh ?? false;
    // One run at a time: ignore a follow-up while another is in flight. A fresh
    // hero submission replaces the workspace, so it is never blocked this way.
    if (!fresh && turns.some((t) => t.status === "running" || t.status === "pending")) return;
    const id = ++turnSeq.current;
    const turn: Turn = {
      id,
      query: prompt,
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
      setLayout("thread");
      setTurns([turn]);
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
        if (conversationId == null) {
          conversationId = await createConversation();
          setActiveConversation(conversationId);
          navigate(`/chat/${conversationId}`, { replace: true });
        }
        attached = await uploadStaged(conversationId);
        patchTurn(id, (t) => ({ ...t, attachments: attached }));
      }
      const res = await runResearch(
        prompt,
        callbacksFor(id),
        conversationId,
        attached.map((doc) => doc.id),
      );
      if (cancelled.current.has(id)) return;
      applyOutcome(id, res);
    } catch (err) {
      if (!cancelled.current.has(id)) failTurn(id, err);
    }
  }

  // Upload everything staged in the composer, keeping what fails visible rather
  // than dropping it silently. Returns what actually landed.
  async function uploadStaged(conversationId: number): Promise<Doc[]> {
    const files = staged;
    setStaged([]);
    setUploadError(null);
    const uploaded: Doc[] = [];
    for (const file of files) {
      try {
        uploaded.push(await uploadDocument(conversationId, file));
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : t.uploads.failed);
      }
    }
    if (uploaded.length) setDocuments((docs) => [...docs, ...uploaded]);
    return uploaded;
  }

  function stopResearch() {
    setTurns((prev) =>
      prev.map((t) => {
        if (t.status === "running" || t.status === "pending") {
          cancelled.current.add(t.id); // the run loop bails at its next checkpoint
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

  // Open one report in the panel, loading its body on demand.
  async function showOutput(id: number | null) {
    setOpenOutputId(id);
    setOpenOutputResult(null);
    if (id == null) return;
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
    if (activeConversationId == null) {
      setStaged((files) => [...files, file]);
      return;
    }
    setUploadError(null);
    try {
      const doc = await uploadDocument(activeConversationId, file);
      setDocuments((docs) => [...docs, doc]);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : t.uploads.failed);
    }
  }

  async function removeDocument(doc: Doc) {
    setDocuments((docs) => docs.filter((d) => d.id !== doc.id));
    await deleteDocument(doc.id);
  }

  // Fact-check a document from the panel: the same sub-agent the supervisor
  // calls, started from the file itself. It lands in Outputs like any other run.
  async function factCheck(doc: Doc) {
    try {
      const output = await factCheckDocument(doc.id);
      setOutputs((current) => [output, ...current]);
      setLayout("split");
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : t.uploads.failed);
    }
  }

  const chooseLayout = (m: LayoutMode) => setLayout(m);

  function goHome() {
    navigate("/");
    setView("home");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Open a past conversation from the sidebar: load its whole thread and make it
  // the active conversation. Anything running in the current chat is cancelled.
  async function openHistory(conversationId: number) {
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
    setUploadError(null);
    refreshOutputs();
    setFocusedId(null);
    setOpenOutputId(null);
    setView("chat");
    setLayout("thread");
    resumeInFlight(loaded);
  }

  function newChat() {
    turns.forEach((t) => cancelled.current.add(t.id));
    setTurns([]);
    setDocuments([]); // documents belong to a conversation, not to the account
    setStaged([]);
    setUploadError(null);
    setFocusedId(null);
    setOpenOutputId(null);
    setLayout("thread");
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
  // The reports that finished and have not been opened since, for the dot in the
  // Outputs list and the count on the button that opens it.
  const unread = new Set(outputs.filter((o) => isUnread(o, seen)).map((o) => o.id));

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
        />
      )}

      {live && (
        <History open={historyOpen} onClose={() => setHistoryOpen(false)} onOpen={openHistory} />
      )}

      {view === "home" && (
        <Fragment>
          <Hero
            onSubmit={heroSubmit}
            note={accessNote}
            staged={live ? staged : undefined}
            onAttach={(files) => setStaged((current) => [...current, ...files])}
            onUnstage={(index) => setStaged((current) => current.filter((_, i) => i !== index))}
            attachError={uploadError}
          />
          <About />
          <HowItWorks />
          <Footer />
        </Fragment>
      )}

      {view === "chat" && (
        <Conversation
          turns={turns}
          now={now}
          layout={layout}
          onLayout={chooseLayout}
          focusedId={focusedId}
          onFocus={setFocusedId}
          onSubmit={startResearch}
          onStop={stopResearch}
          onExit={goHome}
          outputs={outputs}
          documents={documents}
          openOutputId={openOutputId}
          openOutputResult={openOutputResult}
          onOpenOutput={showOutput}
          unread={unread}
          onRefreshOutput={refreshOutput}
          staged={staged}
          onAttach={(files) => setStaged((current) => [...current, ...files])}
          onUnstage={(index) => setStaged((current) => current.filter((_, i) => i !== index))}
          onUpload={addDocument}
          onRemoveDocument={removeDocument}
          onFactCheck={factCheck}
          uploadError={uploadError}
          running={anyRunning}
          onNewChat={newChat}
          accessNote={accessNote}
          historyOpen={chatHistoryOpen}
          onToggleHistory={toggleChatHistory}
          onOpenHistory={live ? openHistory : undefined}
          theme={theme}
          toggleTheme={toggleTheme}
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
              onOpen={() => {
                dismiss(output.id);
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
