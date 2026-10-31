import clsx from "clsx";
import {
  AlertTriangle,
  Bug as BugIcon,
  CircleCheck,
  CircleX,
  Flag,
  Globe,
  Keyboard,
  ListChecks,
  MousePointer2,
  MousePointerClick,
  SquareCheck,
  TextCursorInput,
  Wrench,
} from "lucide-react";
import { useMemo, type ReactNode } from "react";
import type { CoverageItem, Phase } from "../api/types";
import { pathOf, plural } from "../lib/format";
import { ASPECT_LABEL, pagesVisited, scopeOf, summarizeScenarios } from "../lib/scenarios";
import { isLive, type Block, type RunView } from "../state/runReducer";
import { BugSummary } from "./BugList";
import { anchorId, ScenarioOverview } from "./ScenarioOverview";
import { Badge, Spinner } from "./ui";
import { VerifyPanel } from "./VerifyPanel";

type ToolBlock = Extract<Block, { kind: "tool" }>;

const TOOL_ICONS: Record<string, ReactNode> = {
  navigate: <Globe className="size-3.5" />,
  click: <MousePointerClick className="size-3.5" />,
  fill: <TextCursorInput className="size-3.5" />,
  select_option: <ListChecks className="size-3.5" />,
  set_checked: <SquareCheck className="size-3.5" />,
  press_key: <Keyboard className="size-3.5" />,
  hover: <MousePointer2 className="size-3.5" />,
};

// Tools the agent uses to look around rather than to act; they add noise, not information.
const HIDDEN_TOOLS = new Set(["snapshot", "screenshot", "inspect_network"]);

interface Props {
  runId: string;
  view: RunView;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}

/** What the agent did, one line per action, with failed checks and bugs called out. */
export function Timeline({ runId, view, onFrame, onOpenBugs }: Props) {
  const shown = view.blocks.filter(visible);
  const last = shown[shown.length - 1];
  const busy = view.status === "running" && !(last?.kind === "tool" && (last.status === "drafting" || last.status === "running"));
  const live = isLive(view.status);
  const scenarios = useMemo(() => summarizeScenarios(view.blocks, live), [view.blocks, live]);
  const scope = useMemo(() => scopeOf(view.blocks), [view.blocks]);
  const pages = useMemo(() => pagesVisited(view.blocks, view.targetUrl), [view.blocks, view.targetUrl]);
  return (
    <>
      <ScenarioOverview scenarios={scenarios} scope={scope} pages={pages} live={live} targetUrl={view.targetUrl} />
      <ol className="space-y-1">
        {shown.map((b) => (
          <li key={b.key}>
            <BlockView block={b} runId={runId} view={view} onFrame={onFrame} onOpenBugs={onOpenBugs} />
          </li>
        ))}
        {view.status === "queued" && <Working text="Waiting for a free browser slot…" />}
        {busy && <Working text={shown.length ? "Working…" : "Opening the browser…"} />}
      </ol>
    </>
  );
}

function visible(b: Block): boolean {
  if (b.kind === "thinking" || b.kind === "text") return false;
  if (b.kind === "notice") return b.tone === "error";
  if (b.kind === "tool") return !HIDDEN_TOOLS.has(b.name) || b.status === "error";
  return true;
}

function Working({ text }: { text: string }) {
  return (
    <li className="flex items-center gap-2 px-1.5 py-2 text-[13px] text-muted">
      <Spinner className="size-3.5" /> {text}
    </li>
  );
}

function BlockView({
  block: b,
  runId,
  view,
  onFrame,
  onOpenBugs,
}: {
  block: Block;
  runId: string;
  view: RunView;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}) {
  switch (b.kind) {
    case "scenario":
      return (
        <div id={anchorId(b.key)} className="mt-4 mb-1 flex scroll-mt-3 items-center gap-2 border-b border-line pb-1.5">
          <span className="text-[11px] text-muted tabular">#{b.id}</span>
          <span className="text-sm font-medium text-ink">{b.name}</span>
          {b.aspect && <Badge>{ASPECT_LABEL[b.aspect] ?? b.aspect}</Badge>}
          <span className="ml-auto truncate font-mono text-[11px] text-muted">{pathOf(b.url, view.targetUrl)}</span>
        </div>
      );
    case "tool":
      return <ToolRow block={b} runId={runId} onFrame={onFrame} onOpenBugs={onOpenBugs} />;
    case "notice":
      return (
        <div className="flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/10 px-3 py-2 text-[13px] text-[#f06a6a]">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0 break-words">{b.text}</span>
        </div>
      );
    case "phase":
      return <PhaseBlock phase={b.phase} view={view} onOpenBugs={onOpenBugs} />;
    default:
      return null;
  }
}

function toolLabel(b: ToolBlock): string {
  if (b.ui?.step?.description) return b.ui.step.description;
  if (b.summary) return b.summary;
  const input = b.input ?? {};
  const pick = (k: string) => (typeof input[k] === "string" ? (input[k] as string) : undefined);
  return pick("description") ?? pick("title") ?? pick("url") ?? b.name.replace(/_/g, " ");
}

function ToolRow({
  block: b,
  runId,
  onFrame,
  onOpenBugs,
}: {
  block: ToolBlock;
  runId: string;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}) {
  const ui = b.ui;
  const check = ui?.kind === "check" ? ui.step : null;
  const failed = check?.passed === false;

  if (ui?.kind === "bug" && ui.bug) {
    return (
      <div className="my-1 rounded-lg border border-critical/35 bg-critical/6 px-3 py-2.5">
        <BugSummary bug={ui.bug} runId={runId} onOpen={onOpenBugs} />
      </div>
    );
  }
  if (ui?.kind === "finish" || b.name === "finish") {
    return (
      <div className="mt-2 flex items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2.5 text-[13px]">
        <Flag className="mt-0.5 size-3.5 shrink-0 text-good" />
        <div className="min-w-0">
          <div className="text-ink-2">{ui?.summary || "Exploration finished."}</div>
          {ui?.coverage && ui.coverage.length > 0 && (
            <div className="mt-1 text-[12px] text-muted">
              {coverageCounts(ui.coverage)}. The scope is listed part by part at the top of this tab.
            </div>
          )}
          {ui?.untested && <div className="mt-1 text-[12px] text-muted">Also not tested: {ui.untested}</div>}
        </div>
      </div>
    );
  }

  const busy = b.status === "drafting" || b.status === "running";
  const icon = check ? (
    failed ? <CircleX className="size-3.5" /> : <CircleCheck className="size-3.5" />
  ) : (
    TOOL_ICONS[b.name] ?? <Wrench className="size-3.5" />
  );
  const shot = ui?.screenshot;

  return (
    <div className={clsx("rounded-lg text-[13px]", failed && "border border-critical/35 bg-critical/6")}>
      <button
        type="button"
        disabled={!shot}
        onClick={() => shot && onFrame(shot)}
        title={shot ? "Show the screenshot of this step" : undefined}
        className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left enabled:hover:bg-surface-2"
      >
        <span
          className={clsx(
            "flex size-5 shrink-0 items-center justify-center rounded",
            failed ? "text-[#f06a6a]" : check ? "text-[#3fcf3f]" : b.status === "error" ? "text-warning" : "text-muted",
          )}
        >
          {busy ? <Spinner className="size-3" /> : icon}
        </span>
        <span
          className={clsx(
            "min-w-0 flex-1 truncate",
            failed ? "font-medium text-ink" : b.status === "error" ? "text-warning" : "text-ink-2",
            b.status === "skipped" && "text-muted line-through",
          )}
        >
          {toolLabel(b)}
        </span>
      </button>
      {failed && check && (
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 px-9 pb-2 text-[12px]">
          <span className="text-muted">Expected</span>
          <span className="break-words text-ink-2">{check.expected}</span>
          <span className="text-muted">Actual</span>
          <span className="break-words text-[#f06a6a]">{check.actual}</span>
        </div>
      )}
    </div>
  );
}

function PhaseBlock({ phase, view, onOpenBugs }: { phase: Phase; view: RunView; onOpenBugs: () => void }) {
  if (phase === "verify") {
    return (
      <div className="mt-5">
        <Heading>Replaying the tests</Heading>
        <VerifyPanel view={view} compact />
      </div>
    );
  }
  if (phase === "generate") {
    return (
      <Line pending={!view.suite}>
        {view.suite ? `${plural(view.suite.tests.length, "Playwright test")} generated from the session.` : "Writing Playwright tests…"}
      </Line>
    );
  }
  const s = view.summary;
  if (!s) return <Line pending>Writing the report…</Line>;
  const bugs = s.stats?.bugs ?? view.bugs.length;
  return (
    <div className="mt-5 flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2.5 text-[13px]">
      <BugIcon className={clsx("size-4 shrink-0", bugs ? "text-[#f06a6a]" : "text-good")} />
      <span className="min-w-0 flex-1 text-ink-2">
        {bugs ? `${plural(bugs, "bug")} found` : "No bugs found"}
        {s.reproduced > 0 && <span className="text-muted"> · {s.reproduced} reproduced by a failing test</span>}
      </span>
      {bugs > 0 && (
        <button type="button" onClick={onOpenBugs} className="shrink-0 rounded-md bg-accent/15 px-2.5 py-1 text-[12px] font-medium text-accent hover:bg-accent/25">
          View bugs
        </button>
      )}
    </div>
  );
}

function Heading({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-[12px] font-medium tracking-wide text-muted uppercase">{children}</div>;
}

function Line({ pending, children }: { pending?: boolean; children: ReactNode }) {
  return (
    <p className="mt-5 flex items-center gap-2 px-1.5 text-[13px] text-muted">
      {pending ? <Spinner className="size-3.5" /> : <CircleCheck className="size-3.5 text-good" />}
      {children}
    </p>
  );
}

function coverageCounts(rows: CoverageItem[]): string {
  const n = (status: CoverageItem["status"]) => rows.filter((r) => r.status === status).length;
  const parts = [`${n("tested")} tested`, n("partly") ? `${n("partly")} partly tested` : null, `${n("not_tested")} not tested`];
  return `${plural(rows.length, "part")} of the story: ${parts.filter(Boolean).join(", ")}`;
}
