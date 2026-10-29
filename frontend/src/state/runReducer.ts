/**
 * Folds a run's event stream into everything the run view renders: the agent timeline,
 * the screenshots it took, browser signals, bugs, the generated suite and its replays.
 * Live runs and stored runs go through the same reducer, so they look identical.
 */
import type {
  Artifacts,
  Bug,
  Phase,
  RunEvent,
  RunStatus,
  RunSummary,
  Signal,
  Stats,
  SuiteManifest,
  SuiteRun,
  TestActual,
  ToolUI,
  Usage,
} from "../api/types";

export type ToolStatus = "drafting" | "running" | "done" | "error" | "skipped";

export type Block =
  | { kind: "thinking"; key: string; step: number; text: string }
  | { kind: "text"; key: string; step: number; text: string }
  | {
      kind: "tool";
      key: string;
      step: number;
      id: string;
      name: string;
      status: ToolStatus;
      input: Record<string, unknown> | null;
      summary?: string;
      ui?: ToolUI;
    }
  | { kind: "scenario"; key: string; step: number; id: number; name: string; url: string }
  | { kind: "phase"; key: string; step: number; phase: Phase }
  | { kind: "notice"; key: string; step: number; tone: "error" | "retry"; text: string };

export interface Frame {
  path: string;
  step: number;
  caption: string;
  url?: string;
  failed?: boolean;
}

export interface VerifyState {
  label: "target" | "control";
  baseUrl: string;
  order: string[];
  live: Record<string, TestActual>;
  result: SuiteRun | null;
}

export interface RunView {
  status: RunStatus;
  phase: Phase | null;
  phases: Phase[];
  model?: string;
  targetUrl?: string;
  controlUrl?: string | null;
  maxSteps?: number;
  verifyEnabled: boolean;
  step: number;
  blocks: Block[];
  frames: Frame[];
  signals: Signal[];
  bugs: Bug[];
  stats: Stats | null;
  suite: SuiteManifest | null;
  verify: { target?: VerifyState; control?: VerifyState };
  artifacts: Artifacts;
  usage?: Usage;
  agentSummary?: string | null;
  summary?: RunSummary;
  errors: string[];
  error: string | null;
  lastSeq: number;
  lastT: number;
}

export const PHASES: Phase[] = ["explore", "generate", "verify", "report"];
const MAX_SIGNALS = 200;

export function initialRun(): RunView {
  return {
    status: "queued",
    phase: null,
    phases: [],
    verifyEnabled: true,
    step: 0,
    blocks: [],
    frames: [],
    signals: [],
    bugs: [],
    stats: null,
    suite: null,
    verify: {},
    artifacts: {},
    errors: [],
    error: null,
    lastSeq: -1,
    lastT: 0,
  };
}

let counter = 0;
const key = () => `b${++counter}`;

function appendText(blocks: Block[], kind: "thinking" | "text", step: number, text: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === kind && last.step === step) {
    return [...blocks.slice(0, -1), { ...last, text: last.text + text }];
  }
  return [...blocks, { kind, key: key(), step, text }];
}

type ToolBlock = Extract<Block, { kind: "tool" }>;

function upsertTool(blocks: Block[], id: string, base: Omit<ToolBlock, "key" | "kind">, patch: Partial<ToolBlock>) {
  if (blocks.some((b) => b.kind === "tool" && b.id === id)) {
    return blocks.map((b) => (b.kind === "tool" && b.id === id ? { ...b, ...patch } : b));
  }
  return [...blocks, { kind: "tool" as const, key: key(), ...base, ...patch }];
}

function mergeSignals(current: Signal[], incoming: Signal[] | undefined): Signal[] {
  if (!incoming?.length) return current;
  const seen = new Set(current.map((s) => s.seq));
  const fresh = incoming.filter((s) => !seen.has(s.seq));
  if (!fresh.length) return current;
  return [...current, ...fresh].slice(-MAX_SIGNALS);
}

function frameFor(step: number, name: string, summary: string, ui: ToolUI): Frame | null {
  if (!ui.screenshot) return null;
  return {
    path: ui.screenshot,
    step,
    caption: ui.step?.description || summary || name,
    url: ui.url,
    failed: ui.kind === "check" ? ui.step?.passed === false : ui.kind === "bug",
  };
}

function upsertBug(bugs: Bug[], bug: Bug): Bug[] {
  return bugs.some((b) => b.id === bug.id) ? bugs.map((b) => (b.id === bug.id ? bug : b)) : [...bugs, bug];
}

function enterPhase(state: RunView, phase: Phase, step: number): RunView {
  return {
    ...state,
    phase,
    phases: state.phases.includes(phase) ? state.phases : [...state.phases, phase],
    blocks: phase === "explore" ? state.blocks : [...state.blocks, { kind: "phase", key: key(), step, phase }],
  };
}

export function reduceRun(state: RunView, ev: RunEvent): RunView {
  // Reconnects may resend events; seq makes folding idempotent.
  if (ev.seq <= state.lastSeq) return state;
  const s = reduce(state, ev);
  return { ...s, lastSeq: ev.seq, lastT: ev.t, step: Math.max(s.step, ev.step) };
}

function reduce(state: RunView, ev: RunEvent): RunView {
  switch (ev.type) {
    case "run_queued":
      return { ...state, status: "queued" };
    case "run_start":
      return {
        ...state,
        status: "running",
        model: ev.model,
        targetUrl: ev.target_url,
        controlUrl: ev.control_url,
        maxSteps: ev.max_steps,
        verifyEnabled: ev.verify,
      };
    case "phase":
      return enterPhase(state, ev.phase, ev.step);
    case "agent_start":
      return { ...state, model: ev.model };
    case "thinking_start":
      return { ...state, blocks: [...state.blocks, { kind: "thinking", key: key(), step: ev.step, text: "" }] };
    case "thinking_delta":
      return { ...state, blocks: appendText(state.blocks, "thinking", ev.step, ev.text) };
    case "text_start":
      return { ...state, blocks: [...state.blocks, { kind: "text", key: key(), step: ev.step, text: "" }] };
    case "text_delta":
      return { ...state, blocks: appendText(state.blocks, "text", ev.step, ev.text) };
    case "tool_start":
      return {
        ...state,
        blocks: upsertTool(state.blocks, ev.id, { step: ev.step, id: ev.id, name: ev.name, status: "drafting", input: null }, {}),
      };
    case "tool_call":
      return {
        ...state,
        blocks: upsertTool(
          state.blocks,
          ev.id,
          { step: ev.step, id: ev.id, name: ev.name, status: "running", input: ev.input },
          { status: "running", input: ev.input },
        ),
      };
    case "tool_result": {
      const ui = ev.ui ?? {};
      const status: ToolStatus = ui.kind === "skipped" ? "skipped" : ev.is_error ? "error" : "done";
      let blocks = upsertTool(
        state.blocks,
        ev.id,
        { step: ev.step, id: ev.id, name: ev.name, status, input: null },
        { status, summary: ev.summary, ui },
      );
      if (ui.kind === "scenario" && ui.scenario) {
        // The scenario header goes where the scenario begins, replacing its tool card.
        blocks = blocks.map((b) =>
          b.kind === "tool" && b.id === ev.id
            ? { kind: "scenario", key: b.key, step: ev.step, id: ui.scenario!.id, name: ui.scenario!.name, url: ui.scenario!.start_url }
            : b,
        );
      }
      const frame = frameFor(ev.step, ev.name, ev.summary, ui);
      return {
        ...state,
        blocks,
        stats: ev.stats ?? state.stats,
        frames: frame && !state.frames.some((f) => f.path === frame.path) ? [...state.frames, frame] : state.frames,
        signals: mergeSignals(state.signals, ui.signals),
        bugs: ui.kind === "bug" && ui.bug ? upsertBug(state.bugs, ui.bug) : state.bugs,
      };
    }
    case "retry":
      return {
        ...state,
        blocks: [
          ...state.blocks,
          { kind: "notice", key: key(), step: ev.step, tone: "retry", text: `The response stream broke; retrying (attempt ${ev.attempt}).` },
        ],
      };
    case "error":
      return {
        ...state,
        errors: [...state.errors, ev.message],
        blocks: [...state.blocks, { kind: "notice", key: key(), step: ev.step, tone: "error", text: ev.message }],
      };
    case "agent_done":
      return { ...state, usage: ev.usage, stats: ev.stats, agentSummary: ev.summary };
    case "artifacts": {
      const { type: _t, seq: _s, t: _tt, step: _st, ...artifacts } = ev;
      return { ...state, artifacts: { ...state.artifacts, ...artifacts } };
    }
    case "suite": {
      const { type: _t, seq: _s, t: _tt, step: _st, ...suite } = ev;
      return { ...state, suite };
    }
    case "verify_start":
      return {
        ...state,
        verify: {
          ...state.verify,
          [ev.label]: { label: ev.label, baseUrl: ev.base_url, order: ev.tests, live: {}, result: null },
        },
      };
    case "verify_test": {
      const current = state.verify[ev.label];
      if (!current) return state;
      return {
        ...state,
        verify: { ...state.verify, [ev.label]: { ...current, live: { ...current.live, [ev.name]: ev.actual } } },
      };
    }
    case "verify_done": {
      const { type: _t, seq: _s, t: _tt, step: _st, ...result } = ev;
      const current = state.verify[ev.label] ?? {
        label: ev.label,
        baseUrl: ev.base_url,
        order: result.tests.map((t) => t.name),
        live: {},
        result: null,
      };
      return { ...state, verify: { ...state.verify, [ev.label]: { ...current, result } } };
    }
    case "bugs_verified": {
      const verdicts = new Map(ev.bugs.map((b) => [b.id, b.reproduced]));
      return {
        ...state,
        bugs: state.bugs.map((b) => (verdicts.has(b.id) ? { ...b, reproduced: verdicts.get(b.id)! } : b)),
      };
    }
    case "done":
      return {
        ...state,
        status: ev.status,
        error: ev.error,
        summary: ev.summary,
        blocks: state.blocks.map((b) =>
          b.kind === "tool" && (b.status === "drafting" || b.status === "running") ? { ...b, status: "skipped" } : b,
        ),
      };
    default:
      return state;
  }
}

export function replayRun(events: RunEvent[]): RunView {
  return events.reduce(reduceRun, initialRun());
}

/** Where a test stands right now on one build: its final outcome, its streamed result, or still queued. */
export function testState(v: VerifyState | undefined, name: string): TestActual | "running" | "queued" | null {
  if (!v) return null;
  const final = v.result?.tests.find((t) => t.name === name);
  if (final) return final.actual;
  if (v.live[name]) return v.live[name];
  if (v.result) return "missing";
  const pending = v.order.filter((n) => !v.live[n]);
  return pending[0] === name ? "running" : "queued";
}

export function verifyProgress(v: VerifyState | undefined): { done: number; total: number } {
  if (!v) return { done: 0, total: 0 };
  const total = v.order.length;
  return { done: v.result ? total : Math.min(Object.keys(v.live).length, total), total };
}

export const isLive = (status: RunStatus) => status === "queued" || status === "running";
