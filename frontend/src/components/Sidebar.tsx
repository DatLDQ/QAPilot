import clsx from "clsx";
import { Bug, Globe, Plus, Trash2 } from "lucide-react";
import type { Health, RunRow } from "../api/types";
import { shortUrl, timeAgo } from "../lib/format";
import { Badge, STATUS_DOT } from "./ui";

interface Props {
  runs: RunRow[];
  selected: string | null;
  health: Health | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#222221" />
        <circle cx="14" cy="14" r="7" fill="none" stroke="#3987e5" strokeWidth="3" />
        <path d="M19 19l6 6" stroke="#3987e5" strokeWidth="3" strokeLinecap="round" />
        <path d="M10.5 14l2.5 2.5 4.5-5" fill="none" stroke="#199e70" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div>
        <div className="text-[15px] leading-tight font-semibold text-ink">QAPilot</div>
        <div className="text-[11px] leading-tight text-muted">Autonomous QA agent</div>
      </div>
    </div>
  );
}

export function Sidebar({ runs, selected, health, onNew, onSelect, onDelete }: Props) {
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-surface">
      <div className="px-4 pt-4 pb-3">
        <Logo />
      </div>

      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={onNew}
          className={clsx(
            "flex w-full items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium transition-colors",
            selected === null ? "bg-accent-strong text-white hover:bg-accent" : "border border-line-strong text-ink hover:bg-surface-2",
          )}
        >
          <Plus className="size-4" />
          New test run
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-label="Test runs">
        <div className="px-2 pt-1 pb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Runs</div>
        {runs.length === 0 && <p className="px-2 py-1 text-xs text-muted">No runs yet. Start one against the demo shop.</p>}
        {runs.map((r) => (
          <RunItem
            key={r.id}
            run={r}
            active={r.id === selected}
            onClick={() => onSelect(r.id)}
            onDelete={() => onDelete(r.id)}
          />
        ))}
      </nav>

      <HealthFooter health={health} />
    </aside>
  );
}

function RunItem({ run, active, onClick, onDelete }: { run: RunRow; active: boolean; onClick: () => void; onDelete: () => void }) {
  const bugs = run.summary?.stats?.bugs ?? run.summary?.reproduced;
  const live = run.live || run.status === "running" || run.status === "queued";
  return (
    <div
      className={clsx(
        "group relative flex rounded-lg text-sm",
        active ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      <button type="button" onClick={onClick} className="flex min-w-0 flex-1 flex-col gap-0.5 px-2.5 py-2 text-left">
        <span className="flex min-w-0 items-center gap-2">
          <span className={clsx("size-2 shrink-0 rounded-full", STATUS_DOT[run.status])} aria-label={run.status} />
          <span className="min-w-0 flex-1 truncate">{run.story}</span>
        </span>
        <span className="flex items-center gap-2 pl-4 text-[11px] text-muted">
          <span className="min-w-0 truncate">{shortUrl(run.target_url)}</span>
          <span className="ml-auto shrink-0">{timeAgo(run.created_at)}</span>
          {bugs !== undefined && bugs > 0 && (
            <span className="tabular flex shrink-0 items-center gap-0.5 text-[#f06a6a]">
              <Bug className="size-3" />
              {bugs}
            </span>
          )}
        </span>
      </button>
      {!live && (
        <button
          type="button"
          onClick={() => {
            if (confirm("Delete this run and its recordings?")) onDelete();
          }}
          className="absolute top-1.5 right-1 rounded bg-surface-3 p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-critical focus:opacity-100"
          aria-label="Delete run"
          title="Delete run"
        >
          <Trash2 className="size-3.5" />
        </button>
      )}
    </div>
  );
}

function HealthFooter({ health }: { health: Health | null }) {
  if (!health) {
    return (
      <div className="border-t border-line px-4 py-2.5 text-[11px] text-critical">Backend unreachable on :8100</div>
    );
  }
  const status = health.browser.status;
  const browser =
    status === "ready"
      ? { text: "ready", cls: "text-good" }
      : status === "idle"
        ? { text: "starts on first run", cls: "text-muted" }
        : status === "starting"
          ? { text: "starting…", cls: "text-accent" }
          : { text: "failed to start", cls: "text-critical" };
  return (
    <div className="space-y-1.5 border-t border-line px-4 py-2.5 text-[11px] text-muted">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-ink-2">{health.model}</span>
        <span>· {health.effort}</span>
        {health.demo_mode && (
          <Badge tone="warning" className="ml-auto" title="No API key configured: a scripted agent drives the demo shop.">
            Demo mode
          </Badge>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <Globe className="size-3.5" />
        <span className="truncate">Chromium {health.browser.version ?? ""}</span>
        <span className={clsx("ml-auto shrink-0", browser.cls)} title={status}>
          {browser.text}
        </span>
      </div>
    </div>
  );
}
