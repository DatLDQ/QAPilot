import type { Action } from "../state/runReducer";

// Seconds of video kept around each action, so a jump lands just before the page changes.
const LEAD = 0.6;
const TAIL = 1.2;
// Shorter pauses than this play through; skipping them would only make the video jumpy.
const MIN_GAP = 1.5;

/**
 * The recording runs in real time, so most of it is a still page while the agent thinks.
 * When `time` falls in such a pause, return where the next action begins; otherwise null.
 */
export function skipIdle(actions: Action[], time: number): number | null {
  for (const a of actions) {
    if (time < a.start - LEAD) {
      const target = a.start - LEAD;
      return target - time >= MIN_GAP ? target : null;
    }
    if (time <= a.end + TAIL) return null;
  }
  return null;
}

/** The action on screen at `time`: the last one that has started. */
export function actionAt(actions: Action[], time: number): Action | null {
  let current: Action | null = null;
  for (const a of actions) {
    if (a.start - LEAD > time) break;
    current = a;
  }
  return current;
}
