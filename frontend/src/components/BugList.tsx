import clsx from "clsx";
import { Bug as BugIcon, CircleCheck, CircleHelp, CircleX, ExternalLink, FlaskConical, X } from "lucide-react";
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

/** One-line bug card for the live timeline. */
export function BugSummary({ bug, runId, onOpen }: { bug: Bug; runId: string; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="flex w-full items-start gap-3 text-left">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-critical/20 text-[#f06a6a]">
        <BugIcon className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[11px] text-muted">{bug.id}</span>
          <SeverityBadge severity={bug.severity} />
          <Badge>{bug.category}</Badge>
          {bug.reproduced !== null && <Reproduced value={bug.reproduced} />}
        </span>
        <span className="mt-1 block text-sm font-medium text-ink">{bug.title}</span>
        <span className="mt-0.5 block text-[12px] text-muted">
          <span className="text-ink-2">Expected</span> {bug.expected} <span className="text-ink-2">· Actual</span>{" "}
          <span className="text-[#f06a6a]">{bug.actual}</span>
        </span>
      </span>
      {bug.screenshot && (
        <img src={artifactUrl(runId, bug.screenshot)} alt="" loading="lazy" className="h-12 w-20 shrink-0 rounded border border-line object-cover object-top" />
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
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [zoom, setZoom] = useState<string | null>(null);

  if (!bugs.length) {
    return (
      <Empty icon={<BugIcon className="size-6" />} title={live ? "No bugs reported yet" : "No bugs found"}>
        {live ? "Bugs show up here the moment the agent reports them." : "The agent did not report any bugs on this run."}
      </Empty>
    );
  }

  const counts = Object.fromEntries(ORDER.map((s) => [s, bugs.filter((b) => b.severity === s).length])) as Record<Severity, number>;
  const shown = bugs
    .filter((b) => severity === "all" || b.severity === severity)
    .sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-6 py-5">
      <div className="flex flex-wrap items-center gap-1.5">
        <FilterChip active={severity === "all"} onClick={() => setSeverity("all")}>
          All {bugs.length}
        </FilterChip>
        {ORDER.filter((s) => counts[s]).map((s) => (
          <FilterChip key={s} active={severity === s} onClick={() => setSeverity(s)}>
            <span className="capitalize">{s}</span> {counts[s]}
          </FilterChip>
        ))}
        <span className="ml-auto text-[12px] text-muted">
          {bugs.filter((b) => b.reproduced).length} of {bugs.length} reproduced by a failing test
        </span>
      </div>

      {shown.map((bug) => (
        <BugCard key={bug.id} bug={bug} runId={runId} baseUrl={baseUrl} verifying={verifying} onZoom={setZoom} onOpenTest={onOpenTest} />
      ))}

      {zoom && <Lightbox src={artifactUrl(runId, zoom)} onClose={() => setZoom(null)} />}
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "rounded-full border px-2.5 py-0.5 text-[12px] tabular",
        active ? "border-accent/60 bg-accent/12 text-accent" : "border-line-strong text-ink-2 hover:bg-surface-2",
      )}
    >
      {children}
    </button>
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
  return (
    <article id={bug.id} className="overflow-hidden rounded-xl border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <span className="font-mono text-[12px] text-muted">{bug.id}</span>
        <SeverityBadge severity={bug.severity} />
        <Badge>{bug.category}</Badge>
        <Reproduced value={bug.reproduced} pending={verifying} />
        <h3 className="w-full text-[15px] font-medium text-ink">{bug.title}</h3>
      </header>
      <div className="grid gap-5 px-4 py-4 md:grid-cols-[1fr_16rem]">
        <div className="min-w-0 space-y-4 text-[13px]">
          <section>
            <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Steps to reproduce</h4>
            <ol className="list-decimal space-y-1 pl-5 text-ink-2">
              {bug.steps_to_reproduce.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </section>
          <section className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-good/25 bg-good/5 px-3 py-2">
              <div className="mb-0.5 text-[11px] font-medium text-[#3fcf3f]">Expected</div>
              <div className="text-ink-2">{bug.expected}</div>
            </div>
            <div className="rounded-lg border border-critical/30 bg-critical/6 px-3 py-2">
              <div className="mb-0.5 text-[11px] font-medium text-[#f06a6a]">Actual</div>
              <div className="text-ink-2">{bug.actual}</div>
            </div>
          </section>
          {bug.evidence && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Evidence</h4>
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2.5 font-mono text-[11px] whitespace-pre-wrap text-ink-2">{bug.evidence}</pre>
            </section>
          )}
          {bug.untestable_reason && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">No regression test</h4>
              <p className="text-ink-2">{bug.untestable_reason}</p>
            </section>
          )}
          {bug.signals.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Browser signals</h4>
              <ul className="space-y-0.5 font-mono text-[11px] text-[#f06a6a]">
                {bug.signals.map((s, i) => (
                  <li key={i} className="break-words">
                    {s}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <footer className="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-[12px] text-muted">
            <a href={bug.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-mono hover:text-accent">
              {pathOf(bug.url, baseUrl)} <ExternalLink className="size-3" />
            </a>
            {bug.test && (
              <button type="button" onClick={() => onOpenTest(bug.test!)} className="flex items-center gap-1 hover:text-accent">
                <FlaskConical className="size-3.5" />
                <span className="font-mono">{bug.test}</span>
              </button>
            )}
          </footer>
        </div>
        {bug.screenshot && (
          <button type="button" onClick={() => onZoom(bug.screenshot!)} className="self-start overflow-hidden rounded-lg border border-line hover:border-accent" title="Enlarge">
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
