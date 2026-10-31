import clsx from "clsx";
import { Bug as BugIcon, ChevronDown, CircleCheck, CircleHelp, CircleX, ExternalLink, FlaskConical, X } from "lucide-react";
import { useEffect, useState } from "react";
import { artifactUrl } from "../api/client";
import type { Bug, Severity } from "../api/types";
import { pathOf } from "../lib/format";
import { Badge, Empty, SeverityBadge } from "./ui";

const ORDER: Severity[] = ["critical", "high", "medium", "low"];

export function Reproduced({ value, pending }: { value: boolean | null; pending?: boolean }) {
  if (value === true)
    return (
      <Badge tone="critical" title="Its generated test fails on the target build at the assertion that found the bug">
        <CircleCheck className="size-3" /> Reproduced
      </Badge>
    );
  if (value === false)
    return (
      <Badge tone="warning" title="Its generated test passed on replay, so the agent may have been wrong">
        <CircleX className="size-3" /> Not reproduced
      </Badge>
    );
  return (
    <Badge title={pending ? "Waiting for the suite replay" : "The suite was not replayed"}>
      <CircleHelp className="size-3" /> {pending ? "Verifying…" : "Unverified"}
    </Badge>
  );
}

/** Compact bug card for the session timeline. */
export function BugSummary({ bug, runId, onOpen }: { bug: Bug; runId: string; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="flex w-full items-start gap-3 text-left">
      <BugIcon className="mt-0.5 size-4 shrink-0 text-[#f06a6a]" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={bug.severity} />
          <span className="text-sm font-medium text-ink">{bug.title}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-[12px] text-[#f06a6a]">{bug.actual}</span>
      </span>
      {bug.screenshot && (
        <img src={artifactUrl(runId, bug.screenshot)} alt="" loading="lazy" className="h-10 w-16 shrink-0 rounded border border-line object-cover object-top" />
      )}
    </button>
  );
}

export function BugList({
  bugs,
  runId,
  baseUrl,
  verifying,
  live,
  onOpenTest,
}: {
  bugs: Bug[];
  runId: string;
  baseUrl?: string;
  verifying: boolean;
  live: boolean;
  onOpenTest: (name: string) => void;
}) {
  const [zoom, setZoom] = useState<string | null>(null);

  if (!bugs.length) {
    return (
      <Empty icon={<BugIcon className="size-6" />} title={live ? "No bugs reported yet" : "No bugs found"}>
        {live ? "Bugs show up here the moment the agent reports them." : "The agent did not report any bugs on this run."}
      </Empty>
    );
  }

  const shown = [...bugs].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));
  return (
    <div className="mx-auto max-w-3xl space-y-3 px-6 py-5">
      {shown.map((bug) => (
        <BugCard key={bug.id} bug={bug} runId={runId} baseUrl={baseUrl} verifying={verifying} onZoom={setZoom} onOpenTest={onOpenTest} />
      ))}
      {zoom && <Lightbox src={artifactUrl(runId, zoom)} onClose={() => setZoom(null)} />}
    </div>
  );
}

function BugCard({
  bug,
  runId,
  baseUrl,
  verifying,
  onZoom,
  onOpenTest,
}: {
  bug: Bug;
  runId: string;
  baseUrl?: string;
  verifying: boolean;
  onZoom: (path: string) => void;
  onOpenTest: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const extra = bug.evidence || bug.signals.length > 0 || bug.untestable_reason;
  return (
    <article id={bug.id} className="rounded-xl border border-line bg-surface px-4 py-3.5">
      <div className="flex gap-4">
        <div className="min-w-0 flex-1 space-y-2.5 text-[13px]">
          <header className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={bug.severity} />
            {(bug.reproduced !== null || verifying) && <Reproduced value={bug.reproduced} pending={verifying} />}
            <h3 className="w-full text-[15px] font-medium text-ink">{bug.title}</h3>
          </header>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted">Expected</dt>
            <dd className="text-ink-2">{bug.expected}</dd>
            <dt className="text-muted">Actual</dt>
            <dd className="text-[#f06a6a]">{bug.actual}</dd>
          </dl>
          <ol className="list-decimal space-y-0.5 pl-5 text-ink-2">
            {bug.steps_to_reproduce.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          <footer className="flex flex-wrap items-center gap-3 text-[12px] text-muted">
            <a href={bug.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-mono hover:text-accent">
              {pathOf(bug.url, baseUrl)} <ExternalLink className="size-3" />
            </a>
            {bug.test && (
              <button type="button" onClick={() => onOpenTest(bug.test!)} className="flex items-center gap-1 hover:text-accent">
                <FlaskConical className="size-3.5" /> View test
              </button>
            )}
            {extra && (
              <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-0.5 hover:text-ink">
                Details <ChevronDown className={clsx("size-3.5 transition", open && "rotate-180")} />
              </button>
            )}
          </footer>
          {open && (
            <div className="space-y-2 border-t border-line pt-2.5 text-[12px]">
              {bug.evidence && <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2.5 font-mono text-[11px] whitespace-pre-wrap text-ink-2">{bug.evidence}</pre>}
              {bug.signals.length > 0 && (
                <ul className="space-y-0.5 font-mono text-[11px] text-[#f06a6a]">
                  {bug.signals.map((s, i) => (
                    <li key={i} className="break-words">
                      {s}
                    </li>
                  ))}
                </ul>
              )}
              {bug.untestable_reason && <p className="text-muted">No regression test: {bug.untestable_reason}</p>}
            </div>
          )}
        </div>
        {bug.screenshot && (
          <button
            type="button"
            onClick={() => onZoom(bug.screenshot!)}
            className="w-44 shrink-0 self-start overflow-hidden rounded-lg border border-line hover:border-accent"
            title="Enlarge"
          >
            <img src={artifactUrl(runId, bug.screenshot)} alt={`Screenshot for ${bug.id}`} loading="lazy" className="w-full" />
          </button>
        )}
      </div>
    </article>
  );
}

function Lightbox({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-modal className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-8" onClick={onClose}>
      <button type="button" onClick={onClose} className="absolute top-4 right-4 rounded-full bg-surface-3 p-2 text-ink" aria-label="Close">
        <X className="size-4" />
      </button>
      <img src={src} alt="" className="max-h-full max-w-full rounded-lg shadow-2xl" />
    </div>
  );
}
