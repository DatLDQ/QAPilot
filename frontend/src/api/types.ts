// Shapes served by the QAPilot API (backend/app/main.py, runs.py, recorder.py, verify.py).

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type Phase = "explore" | "generate" | "verify" | "report";
export type Severity = "critical" | "high" | "medium" | "low";
export type Verdict = "reproduced" | "stable" | "not_reproduced" | "flaky" | "error";
export type TestActual = "passed" | "failed" | "error" | "skipped" | "missing";

export interface Health {
  status: string;
  model: string;
  effort: string;
  demo_mode: boolean;
  api_key_configured: boolean;
  browser: { status: string; version: string | null };
  active_runs: number;
}

export interface DemoTarget {
  target_url: string;
  control_url: string;
  story: string;
  focus: string;
}

export interface AppConfig {
  model: string;
  effort: string;
  demo_mode: boolean;
  max_steps: number;
  max_concurrent_runs: number;
  allowed_hosts: string[];
  demo: DemoTarget;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  cost_usd: number | null;
}

export interface Stats {
  scenarios: number;
  actions: number;
  checks: number;
  failed_checks: number;
  bugs: number;
}

export interface RunSummary {
  stats: Stats | null;
  bugs_by_severity: Record<Severity, number>;
  reproduced: number;
  not_reproduced: number;
  tests: number;
  control: { passed: number; failed: number } | null;
  steps: number;
  cost_usd: number | null;
  elapsed_ms: number;
}

export interface RunRow {
  id: string;
  target_url: string;
  story: string;
  focus: string | null;
  control_url: string | null;
  max_steps: number;
  model: string;
  status: RunStatus;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: RunSummary | null;
  live: boolean;
}

export interface LocatorOp {
  op: string;
  [key: string]: unknown;
}

export interface Step {
  index: number;
  kind: string;
  description: string;
  locator: LocatorOp[] | null;
  value: unknown;
  assertion: string | null;
  expected: string | null;
  actual: string | null;
  passed: boolean | null;
  bug_ids: string[];
  screenshot: string | null;
  url: string | null;
  locator_ts: string | null;
  locator_py: string | null;
}

export interface Scenario {
  id: number;
  name: string;
  start_url: string | null;
  expected_outcome: "pass" | "fail";
  checks: number;
  failed_checks: number;
  steps: Step[];
}

export interface Bug {
  id: string;
  title: string;
  severity: Severity;
  category: string;
  scenario_id: number | null;
  steps_to_reproduce: string[];
  expected: string;
  actual: string;
  url: string;
  screenshot: string | null;
  evidence: string | null;
  signals: string[];
  check_steps: number[];
  reproduced: boolean | null;
  test?: string | null;
}

export interface Signal {
  seq: number;
  kind: string;
  level: "error" | "warning" | "info";
  text: string;
  url: string | null;
}

export interface GeneratedTest {
  scenario_id: number;
  name: string;
  title: string;
  expected_outcome: "pass" | "fail";
  bug_ids: string[];
}

export interface SuiteManifest {
  base_url: string;
  python: string;
  typescript: string;
  tests: GeneratedTest[];
}

export interface TestOutcome {
  scenario_id: number;
  name: string;
  expected: "pass" | "fail";
  actual: TestActual;
  duration_s: number;
  message: string | null;
  verdict: Verdict;
}

export interface SuiteRun {
  label: "target" | "control";
  base_url: string;
  ok: boolean;
  duration_s: number;
  passed: number;
  failed: number;
  tests: TestOutcome[];
  error: string | null;
  output_tail: string;
}

export interface Artifacts {
  video?: string | null;
  trace?: string | null;
  report?: string;
  bugs?: string;
}

export interface RunResult {
  target_url: string;
  summary: string | null;
  untested: string | null;
  scenarios: Scenario[];
  bugs: Bug[];
  stats: Stats;
  usage: Usage | null;
  steps: number;
  finished: boolean;
  stop_reason: string | null;
  suite: SuiteManifest | null;
  verification: { target: SuiteRun | null; control: SuiteRun | null };
  artifacts: Artifacts;
}

export interface RunDetail extends RunRow {
  result: RunResult | null;
}

export interface NewRun {
  target_url: string;
  story: string;
  focus?: string;
  control_url?: string;
  max_steps?: number;
  verify?: boolean;
}

// What a tool result carries for the UI, by kind (see QAToolExecutor in tools.py).
export interface ToolUI {
  kind?: string;
  step?: Step | null;
  scenario_id?: number | null;
  scenario?: { id: number; name: string; start_url: string };
  screenshot?: string | null;
  url?: string;
  title?: string;
  signals?: Signal[];
  bug?: Bug;
  entries?: NetworkEntry[];
  summary?: string;
  untested?: string | null;
}

export interface NetworkEntry {
  method: string;
  url: string;
  status: number;
  type: string;
  request_body?: string | null;
  response_body?: string | null;
}

interface Base {
  seq: number;
  t: number;
  step: number;
}

export type RunEvent = Base &
  (
    | { type: "run_queued"; position: number }
    | {
        type: "run_start";
        run_id: string;
        target_url: string;
        story: string;
        focus: string | null;
        control_url: string | null;
        max_steps: number;
        verify: boolean;
        model: string;
        started_at: string;
      }
    | { type: "phase"; phase: Phase }
    | { type: "agent_start"; model: string }
    | { type: "thinking_start" }
    | { type: "thinking_delta"; text: string }
    | { type: "text_start" }
    | { type: "text_delta"; text: string }
    | { type: "tool_start"; id: string; name: string }
    | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> | null }
    | {
        type: "tool_result";
        id: string;
        name: string;
        is_error: boolean;
        summary: string;
        ui: ToolUI;
        stats: Stats;
      }
    | { type: "retry"; attempt: number }
    | { type: "error"; message: string }
    | {
        type: "agent_done";
        ok: boolean;
        finished: boolean;
        stop_reason: string | null;
        steps: number;
        model: string;
        summary: string | null;
        stats: Stats;
        usage: Usage;
        elapsed_ms: number;
      }
    | ({ type: "artifacts" } & Artifacts)
    | ({ type: "suite" } & SuiteManifest)
    | { type: "verify_start"; label: "target" | "control"; base_url: string; tests: string[] }
    | { type: "verify_test"; label: "target" | "control"; name: string; actual: TestActual }
    | ({ type: "verify_done" } & SuiteRun)
    | { type: "bugs_verified"; bugs: { id: string; reproduced: boolean | null }[] }
    | { type: "done"; status: RunStatus; error: string | null; summary: RunSummary }
  );

export type RunEventType = RunEvent["type"];
