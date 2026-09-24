// When something happened, said the way a person would: "37 minutes ago" while
// it is recent, then the time of day once "5 hours ago" stops being a useful
// number ("Today at 6:05 PM", "Yesterday at 6:05 PM"), then the date.
import { lang, t } from "./i18n";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
// Past this, a count of hours is harder to place than the time itself.
const RELATIVE_FOR = 6 * HOUR;

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

export function when(iso: string, now: Date = new Date(), locale: string = lang): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const ago = now.getTime() - then.getTime();

  if (ago < MINUTE) return t.when.justNow;
  if (ago < HOUR) return t.when.minutesAgo(Math.floor(ago / MINUTE));
  if (ago < RELATIVE_FOR) return t.when.hoursAgo(Math.floor(ago / HOUR));

  const time = then.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  const days = Math.round((startOfDay(now) - startOfDay(then)) / (24 * HOUR));
  if (days === 0) return t.when.today(time);
  if (days === 1) return t.when.yesterday(time);
  const date = then.toLocaleDateString(locale, {
    month: "long",
    day: "numeric",
    ...(then.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
  });
  return t.when.on(date, time);
}

// How long something has been running, as a clock: "3:12", or "1:04:09" past
// the hour.
export function elapsed(fromIso: string, now: Date = new Date()): string {
  const s = Math.max(0, Math.floor((now.getTime() - new Date(fromIso).getTime()) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}
