import type { AppConfig, Health, NewRun, RunDetail, RunEvent, RunRow } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    // FastAPI validation errors: report the first field's message.
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = String(body.detail[0].msg).replace(/^Value error, /, "");
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) throw await errorFrom(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const encodePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

export const artifactUrl = (runId: string, path: string, download = false) =>
  `/api/runs/${runId}/artifacts/${encodePath(path)}${download ? "?download=1" : ""}`;

export const suiteZipUrl = (runId: string) => `/api/runs/${runId}/suite.zip`;

export const api = {
  health: () => request<Health>("/health"),
  config: () => request<AppConfig>("/config"),

  listRuns: () => request<RunRow[]>("/runs"),
  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),
  createRun: (body: NewRun) => request<RunRow>("/runs", { method: "POST", ...json(body) }),
  cancelRun: (id: string) => request<{ cancelled: boolean }>(`/runs/${id}/cancel`, { method: "POST" }),
  deleteRun: (id: string) => request<void>(`/runs/${id}`, { method: "DELETE" }),

  artifactText: async (runId: string, path: string) => {
    const res = await fetch(artifactUrl(runId, path));
    if (!res.ok) throw await errorFrom(res);
    return res.text();
  },
};

/** Parse a text/event-stream buffer into events, returning the unparsed tail. Exported for tests. */
export function* parseSSEChunk(buffer: string): Generator<RunEvent, string> {
  let rest = buffer;
  let idx: number;
  while ((idx = rest.indexOf("\n\n")) !== -1) {
    const frame = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    const data = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart())
      .join("\n");
    if (data) yield JSON.parse(data) as RunEvent;
  }
  return rest;
}

/** Stream a run's events after `after`. Ends when the server closes the stream. */
export async function* streamEvents(runId: string, after: number, signal: AbortSignal): AsyncGenerator<RunEvent> {
  const res = await fetch(`/api/runs/${runId}/events?after=${after}`, { signal });
  if (!res.ok || !res.body) throw await errorFrom(res);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    const it = parseSSEChunk(buffer);
    let r = it.next();
    while (!r.done) {
      yield r.value;
      r = it.next();
    }
    buffer = r.value;
  }
}

/**
 * Follow a run until its `done` event, reconnecting after dropped connections from the last
 * event seen. Stored runs replay and close; a stream that ends without `done` is retried
 * only while the server still reports the run as live.
 */
export async function followRun(
  runId: string,
  onEvent: (ev: RunEvent) => void,
  signal: AbortSignal,
  after = -1,
): Promise<void> {
  let last = after;
  let failures = 0;
  while (!signal.aborted) {
    let finished = false;
    try {
      for await (const ev of streamEvents(runId, last, signal)) {
        last = Math.max(last, ev.seq);
        failures = 0;
        onEvent(ev);
        if (ev.type === "done") finished = true;
      }
    } catch (e) {
      if (signal.aborted) return;
      if (e instanceof ApiError && e.status === 404) throw e;
      failures++;
    }
    if (finished || signal.aborted) return;
    try {
      const row = await api.getRun(runId);
      if (!row.live) return;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) throw e;
    }
    await sleep(Math.min(1000 * 2 ** failures, 8000), signal);
  }
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const id = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(id);
      resolve();
    });
  });
