// Design Lab: a single accent palette drives BOTH light and dark themes (the
// theme still flips background/foreground). Plus a generous set of font choices.
// Selections are applied by writing CSS custom properties onto <html> (inline,
// so they override the theme blocks) and persisted to localStorage.

export type Palette = {
  key: string;
  label: string;
  accent: string; // deep accent (links, emphasis)
  accent2: string; // bright accent
  fluidA: string; // blob gradient bright
  fluidB: string; // blob gradient deep
};

// amber + violet are the site's current light/dark accents; the rest are extra
// variants to try. Each is used for BOTH themes.
export const PALETTES: Palette[] = [
  { key: "amber", label: "Amber", accent: "#ea580c", accent2: "#f97316", fluidA: "#ffae00", fluidB: "#ff5e00" },
  { key: "violet", label: "Violet", accent: "#a855f7", accent2: "#c084fc", fluidA: "#8a2be2", fluidB: "#4b0082" },
  { key: "indigo", label: "Indigo", accent: "#4f46e5", accent2: "#6366f1", fluidA: "#818cf8", fluidB: "#3730a3" },
  { key: "blue", label: "Blue", accent: "#2563eb", accent2: "#3b82f6", fluidA: "#60a5fa", fluidB: "#1e40af" },
  { key: "sky", label: "Sky", accent: "#0284c7", accent2: "#0ea5e9", fluidA: "#38bdf8", fluidB: "#075985" },
  { key: "cyan", label: "Cyan", accent: "#0891b2", accent2: "#06b6d4", fluidA: "#22d3ee", fluidB: "#155e75" },
  { key: "teal", label: "Teal", accent: "#0d9488", accent2: "#14b8a6", fluidA: "#2dd4bf", fluidB: "#0f766e" },
  { key: "emerald", label: "Emerald", accent: "#059669", accent2: "#10b981", fluidA: "#34d399", fluidB: "#065f46" },
  { key: "lime", label: "Lime", accent: "#65a30d", accent2: "#84cc16", fluidA: "#a3e635", fluidB: "#3f6212" },
  { key: "rose", label: "Rose", accent: "#e11d48", accent2: "#f43f5e", fluidA: "#fb7185", fluidB: "#9f1239" },
  { key: "crimson", label: "Crimson", accent: "#dc2626", accent2: "#ef4444", fluidA: "#f87171", fluidB: "#991b1b" },
  { key: "fuchsia", label: "Fuchsia", accent: "#c026d3", accent2: "#d946ef", fluidA: "#e879f9", fluidB: "#86198f" },
  { key: "gold", label: "Gold", accent: "#ca8a04", accent2: "#eab308", fluidA: "#fde047", fluidB: "#a16207" },
];

export type FontChoice = {
  key: string;
  label: string;
  display: string; // headings, brand, buttons
  sans: string; // body
};

const MONO_FALLBACK = "ui-sans-serif, system-ui, sans-serif";
const f = (name: string) => `"${name}", ${MONO_FALLBACK}`;

// Each option swaps the display + body families. Mono (JetBrains) is left alone.
export const FONTS: FontChoice[] = [
  { key: "space", label: "Space Grotesk", display: f("Space Grotesk"), sans: f("Instrument Sans") },
  { key: "hanken", label: "Hanken Grotesk", display: f("Hanken Grotesk"), sans: f("Hanken Grotesk") },
  { key: "sora", label: "Sora", display: f("Sora"), sans: f("Inter Tight") },
  { key: "outfit", label: "Outfit", display: f("Outfit"), sans: f("Outfit") },
  { key: "jakarta", label: "Plus Jakarta Sans", display: f("Plus Jakarta Sans"), sans: f("Plus Jakarta Sans") },
  { key: "bricolage", label: "Bricolage Grotesque", display: f("Bricolage Grotesque"), sans: f("Hanken Grotesk") },
  { key: "manrope", label: "Manrope", display: f("Manrope"), sans: f("Manrope") },
  { key: "intertight", label: "Inter Tight", display: f("Inter Tight"), sans: f("Inter Tight") },
  { key: "schibsted", label: "Schibsted Grotesk", display: f("Schibsted Grotesk"), sans: f("Schibsted Grotesk") },
  { key: "epilogue", label: "Epilogue", display: f("Epilogue"), sans: f("Epilogue") },
  { key: "onest", label: "Onest", display: f("Onest"), sans: f("Onest") },
  { key: "familjen", label: "Familjen Grotesk", display: f("Familjen Grotesk"), sans: f("Familjen Grotesk") },
  { key: "fraunces", label: "Fraunces (serif)", display: f("Fraunces"), sans: f("Inter Tight") },
  { key: "instrument", label: "Instrument Serif", display: f("Instrument Serif"), sans: f("Instrument Sans") },
];

// Dark-mode glow (fluid bloom strength), adjustable via a slider. Light mode
// renders without bloom, so this only affects the dark theme.
export const DEFAULT_BLOOM = 0.1;
export const BLOOM_MIN = 0;
export const BLOOM_MAX = 1.4;
export const BLOOM_STEP = 0.05;

// Dark-mode ambient level in [0, 1] (0 = pure-black void, 1 = a dark accent-hued
// ambient). Drives --bg + the fluid clear color.
export const DEFAULT_DARK_LEVEL = 0.06;
export const DARK_LEVEL_MIN = 0;
export const DARK_LEVEL_MAX = 1;
export const DARK_LEVEL_STEP = 0.02;

const DEFAULT_PALETTE_KEY = "gold";
const DEFAULT_FONT_KEY = "hanken";
const PALETTE_KEY = "nexus-palette-2";
const FONT_KEY = "nexus-font-2";
const BLOOM_KEY = "nexus-bloom-2";
const DARK_LEVEL_KEY = "nexus-dark-level-7";

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function applyPalette(p: Palette): void {
  const root = document.documentElement.style;
  root.setProperty("--accent", p.accent);
  root.setProperty("--accent-2", p.accent2);
  root.setProperty("--accent-ink", "#ffffff");
  root.setProperty("--accent-soft", hexToRgba(p.accent, 0.15));
}

export function applyFont(c: FontChoice): void {
  const root = document.documentElement.style;
  root.setProperty("--font-display", c.display);
  root.setProperty("--font-sans", c.sans);
}

function parseHex(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

// Mix `b` into `a` by amount t (0..1) and return a hex string.
function mix(a: string, b: string, t: number): string {
  const [ar, ag, ab] = parseHex(a);
  const [br, bg, bb] = parseHex(b);
  const c = (x: number, y: number) => Math.round(x + (y - x) * t);
  const hx = (n: number) => n.toString(16).padStart(2, "0");
  return `#${hx(c(ar, br))}${hx(c(ag, bg))}${hx(c(ab, bb))}`;
}

// The backdrop is derived from the active accent, so every palette gets a
// cohesive dark, and the returned `bg` is also the fluid's clear colour. Light
// stays the neutral stylesheet value, which reads fine across accents.
//
// Dark surfaces are a warm charcoal: grey first, accent second. They used to be
// pure black mixed a fraction toward the accent, which had two problems. The
// fraction was tiny (level 0.06 gave 0.36%), so the page was #010000, and black
// against white text turns every border, glyph edge and antialiased curve into a
// hard line: the interface read as pixelated rather than smooth. And mixing black
// toward the accent can only ever make brown, so there was no way to ask for a
// grey with a hint of gold in it. `level` still lifts the whole set; the accent
// touch is fixed, because it is a tint, not a dimmer.
export type DarkSurfaces = { bg: string; bg2: string; surfaceSolid: string; panel: string };
const LIGHT_BG = "#faf7f2";
// How far off pure black the page sits, and how much accent is mixed into it.
const VOID_GREY = 0.034;
const ACCENT_TOUCH = 0.042;

export function darkSurfaces(p: Palette, level: number): DarkSurfaces {
  const a = p.accent;
  const warm = (l: number) => mix(mix("#000000", "#ffffff", l), a, ACCENT_TOUCH);
  const base = VOID_GREY + Math.max(0, level) * 0.03;
  const panelHex = warm(base + 0.03);
  const [pr, pg, pb] = parseHex(panelHex);
  return {
    bg: warm(base),
    bg2: warm(base + 0.015),
    // Cards and popovers sit a fixed step above the page, so they stay legible
    // whatever the level is set to.
    surfaceSolid: warm(base + 0.055),
    panel: `rgba(${pr}, ${pg}, ${pb}, 0.74)`,
  };
}

// Applies theme-appropriate background vars and returns the fluid clear color.
// Dark: adaptive surfaces (inline, overriding the stylesheet). Light: clears the
// inline overrides so the stylesheet's light vars apply.
export function applyBackground(p: Palette, theme: "dark" | "light", level: number): string {
  const root = document.documentElement.style;
  const keys = ["--bg", "--bg-2", "--surface-solid", "--panel"];
  if (theme === "dark") {
    const s = darkSurfaces(p, level);
    root.setProperty("--bg", s.bg);
    root.setProperty("--bg-2", s.bg2);
    root.setProperty("--surface-solid", s.surfaceSolid);
    root.setProperty("--panel", s.panel);
    return s.bg;
  }
  keys.forEach((k) => root.removeProperty(k));
  return LIGHT_BG;
}

export function getStoredPalette(): Palette {
  let key: string | null = null;
  try {
    key = localStorage.getItem(PALETTE_KEY);
  } catch {
    /* ignore */
  }
  return (
    PALETTES.find((p) => p.key === key) ??
    PALETTES.find((p) => p.key === DEFAULT_PALETTE_KEY) ??
    PALETTES[0]
  );
}

export function getStoredFont(): FontChoice {
  let key: string | null = null;
  try {
    key = localStorage.getItem(FONT_KEY);
  } catch {
    /* ignore */
  }
  return (
    FONTS.find((c) => c.key === key) ??
    FONTS.find((c) => c.key === DEFAULT_FONT_KEY) ??
    FONTS[0]
  );
}

export function storePalette(key: string): void {
  try {
    localStorage.setItem(PALETTE_KEY, key);
  } catch {
    /* ignore */
  }
}

export function storeFont(key: string): void {
  try {
    localStorage.setItem(FONT_KEY, key);
  } catch {
    /* ignore */
  }
}

export function getStoredBloom(): number {
  try {
    const v = localStorage.getItem(BLOOM_KEY);
    if (v != null) {
      const n = parseFloat(v);
      if (!Number.isNaN(n)) return n;
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_BLOOM;
}

export function storeBloom(v: number): void {
  try {
    localStorage.setItem(BLOOM_KEY, String(v));
  } catch {
    /* ignore */
  }
}

export function getStoredDarkLevel(): number {
  try {
    const v = localStorage.getItem(DARK_LEVEL_KEY);
    if (v != null) {
      const n = parseFloat(v);
      if (!Number.isNaN(n)) return n;
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_DARK_LEVEL;
}

export function storeDarkLevel(v: number): void {
  try {
    localStorage.setItem(DARK_LEVEL_KEY, String(v));
  } catch {
    /* ignore */
  }
}
