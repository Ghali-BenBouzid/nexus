// Telling the user a report is ready when they are not looking. A deep run
// takes minutes, long enough to go and do something else, so the in-page toast
// alone would mostly announce the news to an empty room.
import { t } from "./i18n";

const supported = () => typeof window !== "undefined" && "Notification" in window;

// Asked once, the first time a long run starts. "default" means never asked;
// a refusal is final and is never asked again.
export function askToAnnounce(): void {
  if (supported() && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
}

export function announceReady(title: string, open: () => void): void {
  // In another tab or window: a system notification, which also carries the
  // system's own sound. Clicking it brings the user straight to the report.
  if (document.hidden && supported() && Notification.permission === "granted") {
    const n = new Notification(t.notify.title, { body: title, icon: "/favicon.svg" });
    n.onclick = () => {
      window.focus();
      open();
      n.close();
    };
    return;
  }
  chime();
}

// Two soft notes, made on the spot rather than shipped as an audio file.
// ponytail: fails silently where the browser has not allowed sound yet.
function chime(): void {
  try {
    const ctx = new AudioContext();
    const start = ctx.currentTime;
    [660, 880].forEach((freq, n) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const at = start + n * 0.14;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(0.12, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, at + 0.5);
      osc.connect(gain).connect(ctx.destination);
      osc.start(at);
      osc.stop(at + 0.5);
    });
    setTimeout(() => ctx.close(), 1000);
  } catch {
    /* no sound is not worth an error */
  }
}
