import clsx from "clsx";
import { Check, ExternalLink, Square, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { Phase, RunRow } from "../api/types";
import { formatCost, formatMs, parseTime, shortUrl } from "../lib/format";
import { isLive, PHASES, type RunView } from "../state/runReducer";
import { Button, StatusBadge } from "./ui";

const PHASE_LABEL: Record<Phase, string> = {
  explore: "Explore",
  generate: "Generate tests",
  verify: "Verify",
  report: "Report",
};

function useElapsed(row: RunRow, view: RunView): number | null {
  const live = isLive(view.status);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [live]);
  if (view.summary) return view.summary.elapsed_ms;
  if (row.summary) return row.summary.elapsed_ms;
  if (!row.started_at || !live) return null;
  const started = parseTime(row.started_at);
  return Number.isNaN(started) ? null : Math.max(0, now - started);
}

export function RunHeader({
  row,
  view,
  onCancel,
  onDelete,
  cancelling,
}: {
  row: RunRow;
  view: RunView;
  onCancel: () => void;
  onDelete: () => void;
  cancelling: boolean;
}) {
  const live = isLive(view.status);
  const elapsed = useElapsed(row, view);
  const cost = view.summary?.cost_usd ?? view.usage?.cost_usd ?? row.summary?.cost_usd;
  const maxSteps = view.maxSteps ?? row.max_steps;

  return (
    <header className="border-b border-line bg-surface/60 px-6 pt-4 pb-3">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusBadge status={view.status} />
            <a
              href={row.target_url}
              target="_blank"
              rel="noreferrer"
              className="flex min-w-0 items-center gap-1 font-mono text-[13px] text-ink-2 hover:text-accent"
            >
              <span className="truncate">{shortUrl(row.target_url)}</span>
              <ExternalLink className="size-3 shrink-0" />
            </a>
            {row.control_url && (
              <span className="truncate font-mono text-[12px] text-muted" title="Control build">
                vs {shortUrl(row.control_url)}
              </span>
            )}
          </div>
          <p className="mt-1.5 line-clamp-2 text-[15px] leading-snug text-ink" title={row.story}>
            {row.story}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {live ? (
            <Button variant="danger" onClick={onCancel} disabled={cancelling}>
              <Square className="size-3.5" />
              Stop
            </Button>
          ) : (
            <Button variant="ghost" onClick={onDelete} title="Delete this run">
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <PhaseStepper view={view} />
        <dl className="ml-auto flex items-center gap-5 text-[12px]">
          <Metric label="Steps" value={`${view.step}${maxSteps ? ` / ${maxSteps}` : ""}`} />
          <Metric label="Elapsed" value={elapsed === null ? "–" : formatMs(elapsed)} />
          <Metric label="Cost" value={formatCost(cost)} />
          <Metric label="Model" value={view.model ?? row.model} mono />
        </dl>
      </div>
    </header>
  );
}

function Metric({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className={clsx("tabular text-ink-2", mono && "font-mono text-[11px]")}>{value}</dd>
    </div>
  );
}

function PhaseStepper({ view }: { view: RunView }) {
  const live = isLive(view.status);
  return (
    <ol className="flex items-center gap-1" aria-label="Pipeline">
      {PHASES.map((p, i) => {
        const reached = view.phases.includes(p);
        const current = live && view.phase === p;
        const done = reached && !current && (view.status !== "failed" || view.phase !== p);
        const failed = !live && view.status !== "completed" && view.phase === p;
        return (
          <li key={p} className="flex items-center gap-1">
            {i > 0 && <span className={clsx("h-px w-5", reached ? "bg-accent/60" : "bg-line-strong")} />}
            <span
              className={clsx(
                "flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px]",
                current && "border-accent/60 bg-accent/12 text-accent",
                failed && "border-critical/50 bg-critical/10 text-[#f06a6a]",
                done && !failed && "border-line-strong text-ink-2",
                !reached && "border-line text-muted",
              )}
            >
              {current ? (
                <span className="live-dot size-1.5 rounded-full bg-accent" />
              ) : done && !failed ? (
                <Check className="size-3 text-good" />
              ) : null}
              {PHASE_LABEL[p]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
