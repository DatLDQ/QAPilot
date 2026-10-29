export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return rest === 60 ? `${m + 1}m 00s` : `${m}m ${String(rest).padStart(2, "0")}s`;
}

export function formatSeconds(s: number): string {
  return formatMs(s * 1000);
}

export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "n/a";
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(3)}`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86400],
  ["month", 30 * 86400],
  ["week", 7 * 86400],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "just now", "5 minutes ago", "yesterday" for an ISO timestamp (the API sends UTC). */
/** Epoch ms for an API timestamp; naive ISO strings are UTC. NaN when unparseable. */
export const parseTime = (iso: string) => Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

export function timeAgo(iso: string, now = Date.now()): string {
  const then = parseTime(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.round((then - now) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(secs) >= size) return relative.format(Math.round(secs / size), unit);
  }
  return "just now";
}

/** host[:port] plus path, without the scheme or a trailing slash. */
export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname;
    return `${u.host}${path}${u.search}`;
  } catch {
    return url;
  }
}

/** Path relative to `base` when the URL is on the same origin, else the short form. */
export function pathOf(url: string, base?: string): string {
  try {
    const u = new URL(url);
    if (base && new URL(base).origin === u.origin) return `${u.pathname}${u.search}${u.hash}` || "/";
    return shortUrl(url);
  } catch {
    return url;
  }
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
