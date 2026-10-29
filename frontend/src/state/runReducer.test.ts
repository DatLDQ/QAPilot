import { describe, expect, it } from "vitest";
import { parseSSEChunk } from "../api/client";
import type { Bug, RunEvent, Stats } from "../api/types";
import { initialRun, reduceRun, replayRun, testState, verifyProgress } from "./runReducer";

type Ev = RunEvent extends infer E ? (E extends RunEvent ? Omit<E, "seq" | "t" | "step"> : never) : never;

const stats: Stats = { scenarios: 1, actions: 2, checks: 1, failed_checks: 1, bugs: 1 };

const bug: Bug = {
  id: "BUG-1",
  title: "Coupon SAVE10 takes 100% off",
  severity: "high",
  category: "functional",
  scenario_id: 1,
  steps_to_reproduce: ["Add an item", "Apply SAVE10"],
  expected: "10% off",
  actual: "100% off",
  url: "http://localhost:8100/demo/shop/cart",
  screenshot: "shots/004.jpg",
  evidence: null,
  signals: [],
  check_steps: [2],
  reproduced: null,
};

const signal = (seq: number) => ({ seq, kind: "console", level: "error" as const, text: `boom ${seq}`, url: null });

function events(list: [number, Ev][]): RunEvent[] {
  return list.map(([step, e], i) => ({ ...e, seq: i, t: i * 100, step }) as RunEvent);
}

const run = events([
  [0, { type: "run_start", run_id: "r1", target_url: "http://localhost:8100/demo/shop/", story: "Buy a mug", focus: null, control_url: "http://localhost:8100/demo/shop-fixed/", max_steps: 40, verify: true, model: "claude-opus-5-5", started_at: "2026-10-28T12:00:00" }],
  [0, { type: "phase", phase: "explore" }],
  [1, { type: "thinking_start" }],
  [1, { type: "thinking_delta", text: "Start with the " }],
  [1, { type: "thinking_delta", text: "cart flow." }],
  [1, { type: "tool_start", id: "t1", name: "begin_scenario" }],
  [1, { type: "tool_call", id: "t1", name: "begin_scenario", input: { name: "Checkout" } }],
  [1, { type: "tool_result", id: "t1", name: "begin_scenario", is_error: false, summary: "Scenario 1 started", stats, ui: { kind: "scenario", scenario: { id: 1, name: "Checkout", start_url: "http://localhost:8100/demo/shop/" }, screenshot: "shots/001.jpg", signals: [signal(1)] } }],
  [2, { type: "tool_start", id: "t2", name: "click" }],
  [2, { type: "tool_call", id: "t2", name: "click", input: { ref: "e3", description: "Add mug" } }],
  [2, { type: "tool_result", id: "t2", name: "click", is_error: false, summary: "click: Add mug", stats, ui: { kind: "action", screenshot: "shots/002.jpg", url: "http://localhost:8100/demo/shop/", signals: [signal(1), signal(2)] } }],
  [3, { type: "tool_start", id: "t3", name: "report_bug" }],
  [3, { type: "tool_call", id: "t3", name: "report_bug", input: { title: bug.title } }],
  [3, { type: "tool_result", id: "t3", name: "report_bug", is_error: false, summary: "BUG-1 · high", stats, ui: { kind: "bug", bug, screenshot: "shots/004.jpg" } }],
  [4, { type: "text_start" }],
  [4, { type: "text_delta", text: "Done." }],
  [4, { type: "tool_start", id: "t4", name: "finish" }],
  [4, { type: "agent_done", ok: true, finished: true, stop_reason: "end_turn", steps: 4, model: "claude-opus-5-5", summary: "One bug.", stats, usage: { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, cost_usd: 0.01 }, elapsed_ms: 900 }],
  [4, { type: "artifacts", video: "session.webm", trace: "trace.zip" }],
  [4, { type: "phase", phase: "generate" }],
  [4, { type: "suite", base_url: "http://localhost:8100/demo/shop/", python: "tests/test_qapilot.py", typescript: "tests/qapilot.spec.ts", tests: [{ scenario_id: 1, name: "test_checkout", title: "Checkout", expected_outcome: "fail", bug_ids: ["BUG-1"] }, { scenario_id: 2, name: "test_search", title: "Search", expected_outcome: "pass", bug_ids: [] }] }],
  [4, { type: "phase", phase: "verify" }],
  [4, { type: "verify_start", label: "target", base_url: "http://localhost:8100/demo/shop/", tests: ["test_checkout", "test_search"] }],
  [4, { type: "verify_test", label: "target", name: "test_checkout", actual: "failed" }],
]);

describe("runReducer", () => {
  const view = replayRun(run);

  it("tracks run metadata and phases", () => {
    expect(view.status).toBe("running");
    expect(view.model).toBe("claude-opus-5-5");
    expect(view.maxSteps).toBe(40);
    expect(view.phase).toBe("verify");
    expect(view.phases).toEqual(["explore", "generate", "verify"]);
    expect(view.step).toBe(4);
  });

  it("builds the timeline: merged thinking, scenario header, tool cards, phase dividers", () => {
    expect(view.blocks.map((b) => b.kind)).toEqual(["thinking", "scenario", "tool", "tool", "text", "tool", "phase", "phase"]);
    expect(view.blocks[0]).toMatchObject({ kind: "thinking", text: "Start with the cart flow." });
    expect(view.blocks[1]).toMatchObject({ kind: "scenario", id: 1, name: "Checkout" });
    expect(view.blocks[2]).toMatchObject({ kind: "tool", name: "click", status: "done", input: { ref: "e3" } });
    expect(view.blocks[5]).toMatchObject({ kind: "tool", name: "finish", status: "drafting" });
  });

  it("collects frames, deduplicated signals and bugs", () => {
    expect(view.frames.map((f) => f.path)).toEqual(["shots/001.jpg", "shots/002.jpg", "shots/004.jpg"]);
    expect(view.frames[2].failed).toBe(true);
    expect(view.signals.map((s) => s.seq)).toEqual([1, 2]);
    expect(view.bugs).toHaveLength(1);
    expect(view.artifacts).toEqual({ video: "session.webm", trace: "trace.zip" });
    expect(view.suite?.tests).toHaveLength(2);
    expect(view.usage?.cost_usd).toBe(0.01);
  });

  it("streams verification per test", () => {
    const target = view.verify.target;
    expect(testState(target, "test_checkout")).toBe("failed");
    expect(testState(target, "test_search")).toBe("running");
    expect(verifyProgress(target)).toEqual({ done: 1, total: 2 });
    expect(testState(view.verify.control, "test_checkout")).toBeNull();
  });

  it("finishes with verdicts and closes dangling tool cards", () => {
    const tail = events([
      [4, { type: "verify_done", label: "target", base_url: "x", ok: true, duration_s: 3, passed: 1, failed: 1, error: null, output_tail: "", tests: [{ scenario_id: 1, name: "test_checkout", expected: "fail", actual: "failed", duration_s: 1, message: null, verdict: "reproduced" }, { scenario_id: 2, name: "test_search", expected: "pass", actual: "passed", duration_s: 1, message: null, verdict: "stable" }] }],
      [4, { type: "bugs_verified", bugs: [{ id: "BUG-1", reproduced: true }] }],
      [4, { type: "done", status: "completed", error: null, summary: { stats, bugs_by_severity: { critical: 0, high: 1, medium: 0, low: 0 }, reproduced: 1, not_reproduced: 0, tests: 2, control: null, steps: 4, cost_usd: 0.01, elapsed_ms: 5000 } }],
    ]).map((e, i) => ({ ...e, seq: run.length + i }));
    const done = tail.reduce(reduceRun, view);
    expect(done.status).toBe("completed");
    expect(done.bugs[0].reproduced).toBe(true);
    expect(testState(done.verify.target, "test_search")).toBe("passed");
    expect(verifyProgress(done.verify.target)).toEqual({ done: 2, total: 2 });
    expect(done.blocks.find((b) => b.kind === "tool" && b.name === "finish")).toMatchObject({ status: "skipped" });
  });

  it("ignores events it has already folded", () => {
    const again = run.slice(3, 5).reduce(reduceRun, view);
    expect(again).toBe(view);
  });

  it("records errors as notices", () => {
    const [ev] = events([[0, { type: "error", message: "Could not start the browser" }]]);
    const s = reduceRun(initialRun(), ev);
    expect(s.errors).toEqual(["Could not start the browser"]);
    expect(s.blocks[0]).toMatchObject({ kind: "notice", tone: "error" });
  });
});

describe("parseSSEChunk", () => {
  it("parses id/data frames, skips comments and retry hints, and keeps the tail", () => {
    const body = 'retry: 2000\n\n: ping\n\nid: 0\ndata: {"type":"phase","phase":"explore","seq":0,"t":0,"step":0}\n\nid: 1\ndata: {"ty';
    const it = parseSSEChunk(body);
    const out: RunEvent[] = [];
    let r = it.next();
    while (!r.done) {
      out.push(r.value);
      r = it.next();
    }
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ type: "phase", phase: "explore" });
    expect(r.value).toBe('id: 1\ndata: {"ty');
  });
});
