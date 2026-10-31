import { describe, expect, it } from "vitest";
import type { Action } from "../state/runReducer";
import { actionAt, skipIdle } from "./video";

const act = (start: number, end: number, caption: string): Action => ({ start, end, step: 0, caption, failed: false });
const actions = [act(10, 11, "Open the shop"), act(12, 12.5, "Click Add to cart"), act(40, 41, "Check the total")];

describe("session video", () => {
  it("skips the pauses while the agent thinks", () => {
    expect(skipIdle(actions, 0)).toBeCloseTo(9.4);
    expect(skipIdle(actions, 15)).toBeCloseTo(39.4);
  });

  it("plays through actions and short pauses", () => {
    expect(skipIdle(actions, 10.5)).toBeNull();
    expect(skipIdle(actions, 11.6)).toBeNull();
    expect(skipIdle([act(10, 11, "a"), act(14, 15, "b")], 12.3)).toBeNull(); // the next one is too close to skip to
    expect(skipIdle(actions, 38.5)).toBeNull();
    expect(skipIdle(actions, 50)).toBeNull(); // nothing left to jump to
    expect(skipIdle([], 5)).toBeNull();
  });

  it("names the action on screen", () => {
    expect(actionAt(actions, 5)).toBeNull();
    expect(actionAt(actions, 12.2)?.caption).toBe("Click Add to cart");
    expect(actionAt(actions, 30)?.caption).toBe("Click Add to cart");
    expect(actionAt(actions, 39.5)?.caption).toBe("Check the total");
  });
});
