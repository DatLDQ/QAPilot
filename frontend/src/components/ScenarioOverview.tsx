import clsx from "clsx";
import { CircleCheck, CircleDashed, CircleX } from "lucide-react";
import type { CoverageItem } from "../api/types";
import { pathOf, plural } from "../lib/format";
import { ASPECT_LABEL, type PageVisit, type RunScope, type ScenarioSummary } from "../lib/scenarios";
import { Badge, Spinner } from "./ui";

const COVERAGE: Record<CoverageItem["status"], { label: string; tone: "good" | "warning" | "neutral" }> = {
  tested: { label: "Tested", tone: "good" },
  partly: { label: "Partly", tone: "warning" },
  not_tested: { label: "Not tested", tone: "neutral" },
};

/**
 * The session at a glance: which parts of the story the agent tested and which it did not, the scenarios it
 * ran and how each went, and the pages it was on. Clicking a scenario jumps to it in the timeline below.
 */
export function ScenarioOverview({
  scenarios,
  scope,
  pages,
  live,
  targetUrl,
}: {
  scenarios: ScenarioSummary[];
  scope: RunScope;
  pages: PageVisit[];
  live: boolean;
  targetUrl?: string;
}) {
  if (!scenarios.length && !scope.coverage.length) return null;
  const jump = (key: string) => document.getElementById(anchorId(key))?.scrollIntoView({ behavior: "smooth", block: "start" });
  const keyOf = (id: number) => scenarios.find((s) => s.id === id)?.key;
  const aspects = [...new Set(scenarios.map((s) => s.aspect).filter((a): a is string => !!a))];

  return (
    <section className="mb-5 overflow-hidden rounded-xl border border-line bg-surface">
      <div className="border-b border-line px-3.5 py-3">
        <div className="text-[13px] font-medium text-ink">What was tested</div>
        <p className="mt-1 text-[12px] leading-relaxed text-muted">
          The agent split the user story into {plural(scenarios.length, "scenario")}. Each one starts from a clean
          browser (cookies and storage cleared), checks one behaviour, and becomes one regression test on the Tests tab.
        </p>
        {aspects.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
            Covers
            {aspects.map((a) => (
              <Badge key={a}>{ASPECT_LABEL[a] ?? a}</Badge>
            ))}
          </div>
        )}
      </div>
      {scope.coverage.length > 0 && (
        <div className="border-b border-line px-3.5 py-3">
          <div className="text-[12px] font-medium text-ink-2">Scope: the user story, part by part</div>
          <ul className="mt-2 space-y-1.5">
            {scope.coverage.map((row) => (
              <li key={row.area} className="flex items-start gap-2.5 text-[13px]">
                <Badge tone={COVERAGE[row.status].tone} className="mt-px w-[74px] justify-center">
                  {COVERAGE[row.status].label}
                </Badge>
                <span className="min-w-0 flex-1">
                  <span className={clsx(row.status === "not_tested" ? "text-muted" : "text-ink-2")}>{row.area}</span>
                  {row.scenarios.map((id) => {
                    const key = keyOf(id);
                    return (
                      <button
                        key={id}
                        type="button"
                        disabled={!key}
                        onClick={() => key && jump(key)}
                        className="ml-1.5 text-[11px] text-accent tabular hover:underline disabled:text-muted disabled:no-underline"
                      >
                        #{id}
                      </button>
                    );
                  })}
                  {row.note && <span className="block text-[11px] leading-relaxed text-muted">{row.note}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ol className="divide-y divide-line">
        {scenarios.map((s) => (
          <li key={s.key}>
            <button
              type="button"
              onClick={() => jump(s.key)}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[13px] hover:bg-surface-2"
            >
              <span className="w-4 shrink-0 text-right text-[11px] text-muted tabular">{s.id}</span>
              <StatusIcon status={s.status} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className={clsx("truncate", s.status === "failed" ? "font-medium text-ink" : "text-ink-2")}>{s.name}</span>
                  {s.aspect && <Badge className="hidden sm:inline-flex">{ASPECT_LABEL[s.aspect] ?? s.aspect}</Badge>}
                </span>
                <span className="mt-0.5 block truncate text-[11px] text-muted">
                  {counts(s)} · <span className="font-mono">{pathOf(s.url, targetUrl)}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="space-y-1.5 border-t border-line px-3.5 py-2.5 text-[12px] text-muted">
        {pages.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-ink-2">Pages visited</span>
            {pages.map((p) => (
              <Badge key={p.path} title={plural(p.steps, "action or check", "actions and checks")}>
                <span className="font-mono">{p.path}</span>
                <span className="text-muted tabular">×{p.steps}</span>
              </Badge>
            ))}
          </div>
        )}
        {scope.untested && (
          <p>
            <span className="text-ink-2">Also not tested:</span> {scope.untested}
          </p>
        )}
        {!scope.finished && !live && (
          <p>
            The agent stopped before it reported its scope (step budget, error or cancel), so parts of the story may
            not have been reached. Only the scenarios above were tested.
          </p>
        )}
        <p>
          Anything not listed here, such as other pages, browsers or screen sizes, was not tested in this session.
        </p>
      </div>
    </section>
  );
}

export const anchorId = (key: string) => `scenario-${key}`;

function counts(s: ScenarioSummary): string {
  const passed = s.checks.filter((c) => c.passed).length;
  const parts = [
    plural(s.actions, "action"),
    s.checks.length ? `${passed}/${plural(s.checks.length, "check")} passed` : "no checks",
    s.bugs.length ? plural(s.bugs.length, "bug") : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

function StatusIcon({ status }: { status: ScenarioSummary["status"] }) {
  if (status === "running") return <Spinner className="size-3.5 shrink-0" />;
  if (status === "failed") return <CircleX className="size-4 shrink-0 text-[#f06a6a]" />;
  if (status === "explored") return <CircleDashed className="size-4 shrink-0 text-muted" />;
  return <CircleCheck className="size-4 shrink-0 text-[#3fcf3f]" />;
}
