import { describe, expect, it } from "vitest";
import type { Bug, Step } from "../api/types";
import type { Block } from "../state/runReducer";
import { pagesVisited, scopeOf, summarizeScenarios } from "./scenarios";

let n = 0;
const scenario = (id: number, name: string, aspect?: string): Block => ({ kind: "scenario", key: `s${id}`, step: 0, id, name, url: "/", aspect });
const tool = (ui: NonNullable<Extract<Block, { kind: "tool" }>["ui"]>): Block => ({
  kind: "tool",
  key: `t${++n}`,
  step: 0,
  id: `t${n}`,
  name: "x",
  status: "done",
  input: null,
  ui,
});
const check = (description: string, passed: boolean) => tool({ kind: "check", step: { description, passed } as Step });

describe("summarizeScenarios", () => {
  const blocks: Block[] = [
    tool({ kind: "action" }), // before any scenario: ignored
    scenario(1, "Search ignores case", "edge_case"),
    tool({ kind: "action" }),
    tool({ kind: "action" }),
    check("Results show the mug", true),
    scenario(2, "Subtotal uses quantity", "happy_path"),
    tool({ kind: "action" }),
    check("Subtotal is $24", false),
    tool({ kind: "bug", bug: { id: "BUG-1" } as Bug }),
    scenario(3, "Remove has a name"),
    tool({ kind: "action" }),
  ];

  it("counts what each scenario did and found", () => {
    const [a, b, c] = summarizeScenarios(blocks, false);
    expect(a).toMatchObject({ name: "Search ignores case", aspect: "edge_case", actions: 2, failed: 0, status: "passed" });
    expect(a.checks).toEqual([{ description: "Results show the mug", passed: true }]);
    expect(b).toMatchObject({ actions: 1, failed: 1, status: "failed" });
    expect(b.bugs.map((x) => x.id)).toEqual(["BUG-1"]);
    expect(c).toMatchObject({ aspect: null, status: "explored" });
  });

  it("marks the last scenario as running while the run is live", () => {
    expect(summarizeScenarios(blocks, true).map((s) => s.status)).toEqual(["passed", "failed", "running"]);
  });

  it("reads the scope from the finish call", () => {
    expect(scopeOf(blocks)).toEqual({ finished: false, coverage: [], untested: null });
    const row = { area: "Pay", status: "not_tested" as const, scenarios: [], note: "Needs a card" };
    expect(scopeOf([...blocks, tool({ kind: "finish", untested: "Payment", coverage: [row] })])).toEqual({
      finished: true,
      coverage: [row],
      untested: "Payment",
    });
  });
});

describe("pagesVisited", () => {
  it("lists each page once, in visit order, with its step count", () => {
    const at = (kind: string, url: string) => tool({ kind, url });
    const visits = pagesVisited(
      [
        at("action", "http://shop.test/"),
        at("check", "http://shop.test/cart"),
        at("action", "http://shop.test/"),
        at("snapshot", "http://shop.test/ignored"),
        at("action", "http://other.test/help"),
      ],
      "http://shop.test/",
    );
    expect(visits).toEqual([
      { path: "/", steps: 2 },
      { path: "/cart", steps: 1 },
      { path: expect.stringContaining("other.test"), steps: 1 },
    ]);
  });
});
