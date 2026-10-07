/**
 * Demo mode: show aliases instead of GitHub user names, e.g. while presenting
 * the enterprise's Copilot usage to outsiders.
 *
 * Purely client side, like the theme: the switch lives in localStorage and
 * every /api response is rewritten in `fetch` before any component sees it,
 * so tables, charts, tooltips, AI replies and console logs all get aliases
 * without each component knowing about it. Requests are rewritten the other
 * way, so filtering by an alias or naming one in the chat still works.
 */

const ENABLED_KEY = "octofinance-demo-mode";
const SALT_KEY = "octofinance-demo-salt";
const UI_STATE_KEY = "octofinance-ui-state";
const ROSTER_URL = "/api/data/user-roster";

const ADJECTIVES = [
  "Amber", "Azure", "Bold", "Brave", "Bright", "Calm", "Clever", "Coral",
  "Crimson", "Daring", "Eager", "Fancy", "Gentle", "Golden", "Happy", "Humble",
  "Ivory", "Jade", "Jolly", "Keen", "Kind", "Lively", "Lucky", "Lunar",
  "Mellow", "Misty", "Noble", "Olive", "Polar", "Proud", "Quick", "Quiet",
  "Rapid", "Rosy", "Royal", "Rustic", "Scarlet", "Silver", "Smart", "Solar",
  "Steady", "Sunny", "Swift", "Teal", "Tidy", "Vivid", "Witty", "Zesty",
];
const ANIMALS = [
  "Badger", "Bear", "Beaver", "Bison", "Cheetah", "Cobra", "Condor", "Crane",
  "Dolphin", "Eagle", "Falcon", "Ferret", "Fox", "Gazelle", "Gecko", "Heron",
  "Ibis", "Jaguar", "Koala", "Lemur", "Leopard", "Lynx", "Marten", "Moose",
  "Narwhal", "Ocelot", "Orca", "Otter", "Owl", "Panda", "Panther", "Pelican",
  "Penguin", "Puffin", "Puma", "Quail", "Raven", "Robin", "Salmon", "Seal",
  "Sparrow", "Swan", "Tiger", "Toucan", "Walrus", "Whale", "Wolf", "Zebra",
];

// Logins that are also everyday words are only aliased when a value is exactly
// the login, never inside sentences, so ordinary text is not garbled.
const COMMON_WORDS = new Set([
  "admin", "all", "api", "bot", "copilot", "data", "demo", "dev", "github", "go",
  "home", "info", "me", "new", "none", "null", "ok", "org", "root", "team",
  "test", "true", "false", "user", "users", "you",
]);

// A run of characters a GitHub login can contain (EMU logins add `_shortcode`)
const TOKEN = /[A-Za-z0-9_-]+/g;
// Avatars identify a person just as well as the login does
const AVATAR = /https?:\/\/(?:avatars\.[^\s"')]+|(?:[a-z0-9-]+\.)?gravatar\.com\/[^\s"')]*)/gi;

interface RosterUser {
  login: string;
  name: string;
}

interface Aliases {
  /** lower-case login or display name -> alias */
  forward: Map<string, string>;
  /** display names, longest first, replaced as whole words */
  names: [RegExp, string][];
  /** alias -> login, matched case-insensitively */
  reverse: RegExp | null;
  reverseMap: Map<string, string>;
}

let aliases: Aliases | null = null;
let loading: Promise<void> | null = null;
let loadedAt = 0;
let failedAt = 0;

// A sync can bring in new users; refresh the roster so they are aliased too
const ROSTER_MAX_AGE_MS = 60_000;
// A regular user (403) cannot read the roster: do not ask on every request.
// Before sign-in (401) it is retried at once, so data loaded right after an
// administrator signs in is never shown with real names.
const ROSTER_RETRY_MS = 10_000;

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function isDemoMode(): boolean {
  return storageGet(ENABLED_KEY) === "on";
}

/**
 * Turn demo mode on or off. Data already on screen was fetched without (or
 * with) aliases, so the page reloads to fetch it again; view, session and
 * filters survive in localStorage.
 */
export function setDemoMode(on: boolean): void {
  try {
    if (on) localStorage.setItem(ENABLED_KEY, "on");
    else localStorage.removeItem(ENABLED_KEY);
    // A remembered user filter holds a real login or an alias that means
    // nothing in the other mode: start unfiltered.
    const raw = localStorage.getItem(UI_STATE_KEY);
    if (raw) {
      const state = JSON.parse(raw);
      localStorage.setItem(UI_STATE_KEY, JSON.stringify({ ...state, dashboardUser: "", csvDashUser: "" }));
    }
  } catch {
    // storage unavailable: nothing to persist
  }
  window.location.reload();
}

function salt(): string {
  let value = storageGet(SALT_KEY);
  if (!value) {
    value = Math.random().toString(36).slice(2) + Date.now().toString(36);
    try {
      localStorage.setItem(SALT_KEY, value);
    } catch {
      // aliases then change on every load, which is still anonymous
    }
  }
  return value;
}

/** 32-bit FNV-1a */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Deterministic per browser (salted, so aliases cannot be reversed by hashing known logins). */
export function buildAliases(users: RosterUser[], seed: string): Aliases {
  const forward = new Map<string, string>();
  const reverseMap = new Map<string, string>();
  const names: [string, string][] = [];
  const sorted = [...users].sort((a, b) => a.login.toLowerCase().localeCompare(b.login.toLowerCase()));
  for (const user of sorted) {
    const key = user.login.toLowerCase();
    if (forward.has(key)) continue;
    const h = hash(`${seed}:${key}`);
    const base = `${ADJECTIVES[h % ADJECTIVES.length]} ${ANIMALS[(h >>> 8) % ANIMALS.length]}`;
    let alias = base;
    for (let n = 2; reverseMap.has(alias.toLowerCase()); n++) alias = `${base} ${n}`;
    forward.set(key, alias);
    reverseMap.set(alias.toLowerCase(), user.login);
    if (user.name && user.name.toLowerCase() !== key) names.push([user.name, alias]);
  }
  names.sort((a, b) => b[0].length - a[0].length);
  // Latin names must stand alone ("Akira", not the middle of "Akiratown");
  // CJK text has no spaces between words, so those match anywhere.
  const nameRules: [RegExp, string][] = names.map(([name, alias]) => [
    /^[A-Za-z0-9 .,'_-]*$/.test(name)
      ? new RegExp(`(?<![A-Za-z0-9])${escapeRegExp(name)}(?![A-Za-z0-9])`, "g")
      : new RegExp(escapeRegExp(name), "g"),
    alias,
  ]);
  const patterns = [...reverseMap.keys()].sort((a, b) => b.length - a.length).map(escapeRegExp);
  const reverse = patterns.length
    ? new RegExp(`(?<![A-Za-z0-9])(?:${patterns.join("|")})(?![A-Za-z0-9])`, "gi")
    : null;
  return { forward, names: nameRules, reverse, reverseMap };
}

export function setAliasesForTest(next: Aliases | null): void {
  aliases = next;
}

/** Replace logins, display names and avatar URLs in a piece of text. */
export function aliasText(text: string, table: Aliases | null = aliases): string {
  if (!table || !text) return text;
  let result = text.replace(AVATAR, "");
  for (const [rule, alias] of table.names) result = result.replace(rule, alias);
  const whole = result.toLowerCase();
  return result.replace(TOKEN, (run) => {
    const core = run.replace(/^[-_]+|[-_]+$/g, "");
    const alias = table.forward.get(core.toLowerCase());
    if (!alias) return run;
    if (COMMON_WORDS.has(core.toLowerCase()) && whole !== core.toLowerCase()) return run;
    return run.replace(core, alias);
  });
}

/** Map aliases typed or selected in the UI back to the real logins. */
export function unaliasText(text: string, table: Aliases | null = aliases): string {
  if (!table?.reverse || !text) return text;
  return text.replace(table.reverse, (alias) => table.reverseMap.get(alias.toLowerCase()) ?? alias);
}

export function aliasValue(value: unknown, table: Aliases | null = aliases): unknown {
  if (typeof value === "string") return aliasText(value, table);
  if (Array.isArray(value)) return value.map((item) => aliasValue(item, table));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) out[aliasText(key, table)] = aliasValue(item, table);
    return out;
  }
  return value;
}

function unaliasUrl(url: string): string {
  const parsed = new URL(url, window.location.origin);
  const path = parsed.pathname
    .split("/")
    .map((segment) => encodeURIComponent(unaliasText(decodeURIComponent(segment))))
    .join("/");
  const params = new URLSearchParams();
  parsed.searchParams.forEach((value, key) => params.append(key, unaliasText(value)));
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}${parsed.hash}`;
}

/**
 * Rewrite an SSE body event by event. Streamed text deltas are held back up
 * to the last word boundary, so a login split across two deltas is still
 * recognised instead of flashing on screen in two halves.
 */
function aliasEventStream(body: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";
  const pending: Record<string, string> = {};

  const flush = (out: string[]) => {
    for (const [type, text] of Object.entries(pending)) {
      if (text) out.push(`data: ${JSON.stringify({ type, content: aliasText(text) })}`);
      delete pending[type];
    }
  };

  const handleLine = (line: string, out: string[]) => {
    if (!line.startsWith("data: ")) {
      out.push(line);
      return;
    }
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(line.slice(6));
    } catch {
      out.push(aliasText(line));
      return;
    }
    const type = event.type;
    if ((type === "delta" || type === "thinking_delta") && typeof event.content === "string") {
      const text = (pending[type] ?? "") + event.content;
      const cut = text.search(/[A-Za-z0-9_-]*$/);
      // Hold back an unfinished word, unless it is implausibly long for a login
      const keep = text.length - cut <= 64 ? text.slice(cut) : "";
      const ready = text.slice(0, text.length - keep.length);
      pending[type] = keep;
      if (ready) out.push(`data: ${JSON.stringify({ ...event, content: aliasText(ready) })}`);
      return;
    }
    flush(out);
    out.push(`data: ${JSON.stringify(aliasValue(event))}`);
  };

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read();
      const out: string[] = [];
      if (done) {
        if (buffer) handleLine(buffer, out);
        flush(out);
        if (out.length) controller.enqueue(encoder.encode(out.join("\n") + "\n\n"));
        controller.close();
        return;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) handleLine(line, out);
      if (out.length) controller.enqueue(encoder.encode(out.join("\n") + "\n"));
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
}

async function ensureAliases(fetchFn: typeof fetch): Promise<void> {
  const now = Date.now();
  if (aliases && now - loadedAt < ROSTER_MAX_AGE_MS) return;
  if (!aliases && now - failedAt < ROSTER_RETRY_MS) return;
  loading ??= (async () => {
    try {
      const res = await fetchFn(ROSTER_URL);
      if (!res.ok) {
        failedAt = res.status === 403 ? Date.now() : 0;
        return;
      }
      const data = await res.json();
      aliases = buildAliases(data.users ?? [], salt());
      loadedAt = Date.now();
    } catch {
      failedAt = Date.now();
    } finally {
      loading = null;
    }
  })();
  await loading;
}

async function aliasResponse(res: Response): Promise<Response> {
  if (!res.body || res.status === 204 || res.status === 304) return res;
  const type = res.headers.get("content-type") ?? "";
  const headers = new Headers(res.headers);
  headers.delete("content-length");
  headers.delete("content-encoding");
  const init = { status: res.status, statusText: res.statusText, headers };
  if (type.includes("text/event-stream")) return new Response(aliasEventStream(res.body), init);
  if (type.includes("application/json")) {
    const text = await res.text();
    try {
      return new Response(JSON.stringify(aliasValue(JSON.parse(text))), init);
    } catch {
      return new Response(aliasText(text), init);
    }
  }
  if (type.startsWith("text/")) return new Response(aliasText(await res.text()), init);
  return res;
}

/** Wrap window.fetch; a no-op for every request while demo mode is off. */
export function installDemoFetch(): void {
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (!isDemoMode() || input instanceof Request) return original(input, init);
    const url = input instanceof URL ? input.href : input;
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin !== window.location.origin || !parsed.pathname.startsWith("/api/") || parsed.pathname === ROSTER_URL) {
      return original(input, init);
    }
    await ensureAliases(original);
    if (!aliases) return original(input, init);
    const body = typeof init?.body === "string" ? unaliasText(init.body) : init?.body;
    const res = await original(unaliasUrl(url), init ? { ...init, body } : init);
    return aliasResponse(res);
  };
}
