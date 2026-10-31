import type { Bug, CoverageItem } from "../api/types";
import type { Block } from "../state/runReducer";
import { pathOf } from "./format";

export const ASPECT_LABEL: Record<string, string> = {
  happy_path: "Happy path",
  edge_case: "Edge case",
  validation: "Validation",
  state: "State",
  error_handling: "Error handling",
  accessibility: "Accessibility",
};

export interface ScenarioCheck {
  description: string;
  passed: boolean | null;
}

export interface ScenarioSummary {
  /** The scenario header's block key, so the overview can jump to it in the timeline. */
  key: string;
  id: number;
  name: string;
  url: string;
  aspect: string | null;
  actions: number;
  checks: ScenarioCheck[];
  failed: number;
  bugs: Bug[];
  /** running: the agent is still in it · failed: a check failed or a bug was filed · explored: no checks. */
  status: "running" | "passed" | "failed" | "explored";
}

/** One summary per scenario, from the timeline: what it did, what it asserted and what it found. */
export function summarizeScenarios(blocks: Block[], live: boolean): ScenarioSummary[] {
  const out: ScenarioSummary[] = [];
  for (const b of blocks) {
    if (b.kind === "scenario") {
      out.push({ key: b.key, id: b.id, name: b.name, url: b.url, aspect: b.aspect ?? null, actions: 0, checks: [], failed: 0, bugs: [], status: "passed" });
      continue;
    }
    const current = out[out.length - 1];
    if (!current || b.kind !== "tool" || !b.ui) continue;
    if (b.ui.kind === "action") current.actions += 1;
    else if (b.ui.kind === "check" && b.ui.step) {
      current.checks.push({ description: b.ui.step.description, passed: b.ui.step.passed });
      if (b.ui.step.passed === false) current.failed += 1;
    } else if (b.ui.kind === "bug" && b.ui.bug) current.bugs.push(b.ui.bug);
  }
  out.forEach((s, i) => {
    if (s.failed || s.bugs.length) s.status = "failed";
    else if (live && i === out.length - 1) s.status = "running";
    else if (!s.checks.length) s.status = "explored";
  });
  return out;
}

export interface RunScope {
  /** False until the agent calls `finish`: a session cut short never reported what it covered. */
  finished: boolean;
  coverage: CoverageItem[];
  untested: string | null;
}

/** What the agent said it covered and left out, from its finish call. */
export function scopeOf(blocks: Block[]): RunScope {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.kind === "tool" && b.ui?.kind === "finish") {
      return { finished: true, coverage: b.ui.coverage ?? [], untested: b.ui.untested || null };
    }
  }
  return { finished: false, coverage: [], untested: null };
}

export interface PageVisit {
  path: string;
  /** How many actions and checks ran on it. */
  steps: number;
}

/** Every page the browser was on during the session, in the order it first got there. */
export function pagesVisited(blocks: Block[], base?: string): PageVisit[] {
  const pages = new Map<string, PageVisit>();
  for (const b of blocks) {
    if (b.kind !== "tool" || !b.ui?.url || (b.ui.kind !== "action" && b.ui.kind !== "check")) continue;
    const path = pathOf(b.ui.url, base);
    const page = pages.get(path) ?? { path, steps: 0 };
    page.steps += 1;
    pages.set(path, page);
  }
  return [...pages.values()];
}
