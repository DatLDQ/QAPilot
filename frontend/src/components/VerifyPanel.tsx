import clsx from "clsx";
import { CircleCheck, CircleDashed, CircleX, MinusCircle } from "lucide-react";
import type { GeneratedTest, TestOutcome } from "../api/types";
import { formatSeconds, shortUrl } from "../lib/format";
import { testState, verifyProgress, type RunView, type VerifyState } from "../state/runReducer";
import { Spinner, VerdictBadge } from "./ui";

/** Live per-test replay results on the target build and, when given, the control build. */
export function VerifyPanel({ view, compact }: { view: RunView; compact?: boolean }) {
  const { target, control } = view.verify;
  const tests: Pick<GeneratedTest, "name" | "title" | "expected_outcome" | "bug_ids">[] =
    view.suite?.tests ??
    (target?.order ?? []).map((name) => ({ name, title: name, expected_outcome: "pass" as const, bug_ids: [] }));

  if (!target) {
    if (!view.verifyEnabled) return <p className="px-1 text-[13px] text-muted">Verification was turned off for this run.</p>;
    return (
      <p className="flex items-center gap-2 px-1 text-[13px] text-muted">
        <Spinner className="size-3.5" /> Starting pytest…
      </p>
    );
  }

  return (
    <div className={clsx("overflow-hidden rounded-lg border border-line", !compact && "bg-surface")}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-line bg-surface-2/60 px-3 py-2 text-[12px]">
        <BuildProgress label="Target" v={target} />
        {control && <BuildProgress label="Control" v={control} />}
      </div>
      {/* Fixed layout so long test titles truncate instead of pushing the result columns out. */}
      <table className="w-full table-fixed text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11px] text-muted">
            <th className="py-1.5 pl-3 font-medium">Test</th>
            {!compact && <th className="w-32 py-1.5 font-medium">Expects</th>}
            <th className={clsx("py-1.5 font-medium", compact ? "w-38" : "w-44")}>Target</th>
            {control && <th className={clsx("py-1.5 pr-3 font-medium", compact ? "w-38" : "w-44")}>Control</th>}
          </tr>
        </thead>
        <tbody>
          {tests.map((t) => (
            <tr key={t.name} className="border-b border-line/60 last:border-0">
              <td className="py-1.5 pr-2 pl-3">
                <div className="truncate text-ink-2" title={t.name}>
                  {t.title}
                </div>
                {compact ? (
                  <div className="truncate text-[11px]">
                    <Expects test={t} />
                  </div>
                ) : (
                  <div className="truncate font-mono text-[11px] text-muted">{t.name}</div>
                )}
              </td>
              {!compact && (
                <td className="truncate py-1.5 pr-2 text-[12px]">
                  <Expects test={t} />
                </td>
              )}
              <td className="py-1.5">
                <Cell v={target} name={t.name} />
              </td>
              {control && (
                <td className="py-1.5 pr-3">
                  <Cell v={control} name={t.name} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {[target, control].map(
        (v) =>
          v?.result?.error && (
            <p key={v.label} className="border-t border-line px-3 py-2 text-[12px] text-[#f06a6a]">
              {v.label}: {v.result.error}
            </p>
          ),
      )}
    </div>
  );
}

function Expects({ test }: { test: Pick<GeneratedTest, "expected_outcome" | "bug_ids"> }) {
  return test.expected_outcome === "fail" ? (
    <span className="text-[#f06a6a]" title="This test asserts the correct behaviour, so it fails while the bug exists">
      fail · {test.bug_ids.join(", ")}
    </span>
  ) : (
    <span className="text-muted">pass</span>
  );
}

function BuildProgress({ label, v }: { label: string; v: VerifyState }) {
  const { done, total } = verifyProgress(v);
  return (
    <span className="flex items-center gap-2">
      <span className="font-medium text-ink-2">{label}</span>
      <span className="font-mono text-muted">{shortUrl(v.baseUrl)}</span>
      <span className="tabular text-muted">
        {done}/{total}
      </span>
      {v.result ? (
        <span className="tabular text-muted">· {formatSeconds(v.result.duration_s)}</span>
      ) : (
        <span className="h-1 w-16 overflow-hidden rounded-full bg-surface-3">
          <span className="block h-full bg-accent transition-all" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
        </span>
      )}
    </span>
  );
}

function Cell({ v, name }: { v: VerifyState; name: string }) {
  const outcome: TestOutcome | undefined = v.result?.tests.find((t) => t.name === name);
  if (outcome) {
    return (
      <span className="flex items-center gap-1.5" title={outcome.message ?? undefined}>
        <ActualIcon actual={outcome.actual} />
        <VerdictBadge verdict={outcome.verdict} />
      </span>
    );
  }
  const state = testState(v, name);
  if (state === "running") {
    return (
      <span className="flex items-center gap-1.5 text-[12px] text-accent">
        <Spinner className="size-3.5" /> running
      </span>
    );
  }
  if (state === "queued" || state === null) {
    return (
      <span className="flex items-center gap-1.5 text-[12px] text-muted">
        <CircleDashed className="size-3.5" /> queued
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-[12px] text-ink-2">
      <ActualIcon actual={state} /> {state}
    </span>
  );
}

function ActualIcon({ actual }: { actual: string }) {
  if (actual === "passed") return <CircleCheck className="size-3.5 shrink-0 text-good" />;
  if (actual === "failed") return <CircleX className="size-3.5 shrink-0 text-critical" />;
  return <MinusCircle className="size-3.5 shrink-0 text-muted" />;
}
