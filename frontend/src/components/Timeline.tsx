import clsx from "clsx";
import {
  AlertTriangle,
  Brain,
  Bug as BugIcon,
  Camera,
  ChevronRight,
  CircleCheck,
  CircleX,
  FileCode2,
  FileText,
  Flag,
  Globe,
  Keyboard,
  ListChecks,
  MousePointer2,
  MousePointerClick,
  Network,
  RefreshCw,
  ScanEye,
  ShieldCheck,
  SquareCheck,
  TextCursorInput,
  Wrench,
} from "lucide-react";
import { memo, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { artifactUrl } from "../api/client";
import type { NetworkEntry, Phase } from "../api/types";
import { pathOf, plural } from "../lib/format";
import type { Block, RunView } from "../state/runReducer";
import { BugSummary } from "./BugList";
import { Spinner } from "./ui";
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
  snapshot: <ScanEye className="size-3.5" />,
  screenshot: <Camera className="size-3.5" />,
  expect: <CircleCheck className="size-3.5" />,
  inspect_network: <Network className="size-3.5" />,
  report_bug: <BugIcon className="size-3.5" />,
  finish: <Flag className="size-3.5" />,
};

interface Props {
  runId: string;
  view: RunView;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}

export function Timeline({ runId, view, onFrame, onOpenBugs }: Props) {
  const live = view.status === "running" || view.status === "queued";
  const lastText = [...view.blocks].reverse().find((b) => b.kind === "text" || b.kind === "thinking");
  return (
    <ol className="space-y-1.5">
      {view.blocks.map((b) => (
        <li key={b.key}>
          <BlockView
            block={b}
            runId={runId}
            view={view}
            streaming={live && b === lastText && b === view.blocks[view.blocks.length - 1]}
            onFrame={onFrame}
            onOpenBugs={onOpenBugs}
          />
        </li>
      ))}
      {view.status === "queued" && (
        <li className="flex items-center gap-2 px-1 py-3 text-sm text-muted">
          <Spinner className="size-4" /> Waiting for a free browser slot…
        </li>
      )}
      {view.status === "running" && view.blocks.length === 0 && (
        <li className="flex items-center gap-2 px-1 py-3 text-sm text-muted">
          <Spinner className="size-4" /> Launching Chromium and recording the session…
        </li>
      )}
    </ol>
  );
}

function BlockView({
  block: b,
  runId,
  view,
  streaming,
  onFrame,
  onOpenBugs,
}: {
  block: Block;
  runId: string;
  view: RunView;
  streaming: boolean;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}) {
  switch (b.kind) {
    case "thinking":
      return <Thinking text={b.text} streaming={streaming} />;
    case "text":
      return b.text.trim() ? (
        <div className={clsx("px-1 py-1", streaming && "streaming-text")}>
          <MarkdownText text={b.text} />
        </div>
      ) : null;
    case "scenario":
      return (
        <div className="mt-4 mb-1 flex items-center gap-2 border-b border-line pb-1.5">
          <span className="rounded bg-accent/15 px-1.5 text-[11px] font-semibold text-accent tabular">S{b.id}</span>
          <span className="text-sm font-medium text-ink">{b.name}</span>
          <span className="ml-auto truncate font-mono text-[11px] text-muted">{pathOf(b.url, view.targetUrl)}</span>
        </div>
      );
    case "tool":
      return <ToolCard block={b} runId={runId} baseUrl={view.targetUrl} onFrame={onFrame} onOpenBugs={onOpenBugs} />;
    case "notice":
      return (
        <div
          className={clsx(
            "flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px]",
            b.tone === "error" ? "border-critical/40 bg-critical/10 text-[#f06a6a]" : "border-warning/30 bg-warning/8 text-warning",
          )}
        >
          {b.tone === "error" ? <AlertTriangle className="mt-0.5 size-4 shrink-0" /> : <RefreshCw className="mt-0.5 size-4 shrink-0" />}
          <span className="min-w-0 break-words">{b.text}</span>
        </div>
      );
    case "phase":
      return <PhaseBlock phase={b.phase} view={view} />;
  }
}

const MarkdownText = memo(function MarkdownText({ text }: { text: string }) {
  return (
    <div className="md narration">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
});

function Thinking({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text.trim() && !streaming) return null;
  const expanded = open || streaming;
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="flex w-full items-start gap-2 rounded-lg px-1 py-1 text-left text-[13px] text-muted hover:text-ink-2"
      aria-expanded={expanded}
    >
      <Brain className="mt-0.5 size-3.5 shrink-0" />
      <span className={clsx("min-w-0 flex-1 leading-relaxed whitespace-pre-wrap italic", !expanded && "line-clamp-2", streaming && "caret")}>
        {text.trim() || "Thinking"}
      </span>
    </button>
  );
}

function toolLabel(b: ToolBlock): string {
  if (b.summary) return b.summary;
  const input = b.input ?? {};
  const pick = (k: string) => (typeof input[k] === "string" ? (input[k] as string) : undefined);
  return pick("description") ?? pick("title") ?? pick("url") ?? pick("name") ?? b.name.replace(/_/g, " ");
}

function ToolCard({
  block: b,
  runId,
  baseUrl,
  onFrame,
  onOpenBugs,
}: {
  block: ToolBlock;
  runId: string;
  baseUrl?: string;
  onFrame: (path: string) => void;
  onOpenBugs: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ui = b.ui;
  const check = ui?.kind === "check" ? ui.step : null;
  const failedCheck = check?.passed === false;
  const errors = ui?.signals?.filter((s) => s.level === "error").length ?? 0;

  if (ui?.kind === "bug" && ui.bug) {
    return (
      <div className="rounded-lg border border-critical/35 bg-critical/6 p-3">
        <BugSummary bug={ui.bug} runId={runId} onOpen={onOpenBugs} />
      </div>
    );
  }
  if (ui?.kind === "finish") {
    return (
      <div className="mt-2 rounded-lg border border-line bg-surface px-3 py-2.5">
        <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
          <Flag className="size-3.5 text-good" /> Exploration finished
        </div>
        {ui.summary && <div className="mt-1.5"><MarkdownText text={ui.summary} /></div>}
        {ui.untested && (
          <p className="mt-2 text-[12px] text-muted">
            <span className="font-medium text-ink-2">Not covered: </span>
            {ui.untested}
          </p>
        )}
      </div>
    );
  }

  const icon = check ? (
    failedCheck ? <CircleX className="size-3.5" /> : <CircleCheck className="size-3.5" />
  ) : (
    TOOL_ICONS[b.name] ?? <Wrench className="size-3.5" />
  );

  return (
    <div
      className={clsx(
        "group rounded-lg border text-[13px]",
        failedCheck ? "border-critical/35 bg-critical/6" : b.status === "error" ? "border-warning/30 bg-warning/5" : "border-transparent hover:border-line",
      )}
    >
      <div className="flex items-center gap-2 px-1.5 py-1">
        <button type="button" onClick={() => setOpen((v) => !v)} className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={open}>
          <span className="w-7 shrink-0 text-right font-mono text-[10px] text-muted tabular">#{b.step}</span>
          <span
            className={clsx(
              "flex size-5 shrink-0 items-center justify-center rounded",
              failedCheck ? "bg-critical/15 text-[#f06a6a]" : check ? "bg-good/15 text-[#3fcf3f]" : "bg-surface-3 text-ink-2",
            )}
          >
            {b.status === "drafting" || b.status === "running" ? <Spinner className="size-3" /> : icon}
          </span>
          <span className={clsx("min-w-0 flex-1 truncate", b.status === "error" ? "text-warning" : "text-ink-2", b.status === "skipped" && "text-muted line-through")}>
            {toolLabel(b)}
          </span>
          {errors > 0 && (
            <span className="shrink-0 rounded bg-critical/15 px-1 text-[10px] text-[#f06a6a]" title="New console or network errors">
              {plural(errors, "error")}
            </span>
          )}
          {ui?.url && ui.kind !== "check" && (
            <span className="hidden max-w-48 shrink-0 truncate font-mono text-[11px] text-muted xl:inline">{pathOf(ui.url, baseUrl)}</span>
          )}
          <ChevronRight className={clsx("size-3.5 shrink-0 text-muted opacity-0 transition group-hover:opacity-100", open && "rotate-90 opacity-100")} />
        </button>
        {ui?.screenshot && (
          <button
            type="button"
            onClick={() => onFrame(ui.screenshot!)}
            className="shrink-0 overflow-hidden rounded border border-line hover:border-accent"
            title="Show this screenshot"
          >
            <img src={artifactUrl(runId, ui.screenshot)} alt="" loading="lazy" className="h-6 w-10 object-cover object-top" />
          </button>
        )}
      </div>
      {check && failedCheck && !open && (
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 px-11 pb-2 text-[12px]">
          <span className="text-muted">Expected</span>
          <span className="font-mono break-words text-ink-2">{check.expected}</span>
          <span className="text-muted">Actual</span>
          <span className="font-mono break-words text-[#f06a6a]">{check.actual}</span>
        </div>
      )}
      {open && <ToolDetails block={b} />}
    </div>
  );
}

function ToolDetails({ block: b }: { block: ToolBlock }) {
  const ui = b.ui;
  return (
    <div className="space-y-2 border-t border-line/70 px-11 py-2 text-[12px]">
      {ui?.step?.locator_ts && (
        <div>
          <div className="mb-0.5 text-muted">Locator</div>
          <code className="block font-mono break-all text-ink-2">{ui.step.locator_ts}</code>
        </div>
      )}
      {ui?.kind === "check" && ui.step && (
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          <span className="text-muted">Assertion</span>
          <span className="font-mono text-ink-2">{ui.step.assertion}</span>
          <span className="text-muted">Expected</span>
          <span className="font-mono break-words text-ink-2">{ui.step.expected}</span>
          <span className="text-muted">Actual</span>
          <span className={clsx("font-mono break-words", ui.step.passed ? "text-ink-2" : "text-[#f06a6a]")}>{ui.step.actual}</span>
        </div>
      )}
      {ui?.kind === "network" && <NetworkTable entries={ui.entries ?? []} />}
      {!!ui?.signals?.length && (
        <ul className="space-y-0.5">
          {ui.signals.map((s) => (
            <li key={s.seq} className={clsx("font-mono break-words", s.level === "error" ? "text-[#f06a6a]" : "text-warning")}>
              [{s.kind}] {s.text}
            </li>
          ))}
        </ul>
      )}
      {b.input && (
        <details>
          <summary className="cursor-pointer text-muted hover:text-ink-2">Tool input</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 font-mono text-[11px] text-ink-2">{JSON.stringify(b.input, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

export function NetworkTable({ entries }: { entries: NetworkEntry[] }) {
  if (!entries.length) return <p className="text-muted">No matching requests.</p>;
  return (
    <table className="w-full table-fixed font-mono text-[11px]">
      <tbody>
        {entries.map((e, i) => (
          <tr key={i} className="border-b border-line/50 align-top last:border-0">
            <td className="w-12 py-0.5 text-muted">{e.method}</td>
            <td className={clsx("w-10 py-0.5 tabular", e.status >= 400 ? "text-[#f06a6a]" : "text-good")}>{e.status}</td>
            <td className="truncate py-0.5 text-ink-2" title={e.url}>
              {pathOf(e.url)}
              {e.response_body && <div className="truncate text-muted">{e.response_body}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PhaseBlock({ phase, view }: { phase: Phase; view: RunView }) {
  const head = (icon: ReactNode, title: string, right?: ReactNode) => (
    <div className="mt-5 mb-2 flex items-center gap-2 text-sm font-medium text-ink">
      <span className="flex size-6 items-center justify-center rounded-md bg-surface-3 text-accent">{icon}</span>
      {title}
      <span className="h-px flex-1 bg-line" />
      {right}
    </div>
  );
  if (phase === "generate") {
    const suite = view.suite;
    return (
      <div>
        {head(<FileCode2 className="size-3.5" />, "Generating Playwright tests")}
        {suite ? (
          <p className="px-1 text-[13px] text-ink-2">
            {plural(suite.tests.length, "test")} from the recorded scenarios:{" "}
            <span className="text-muted">
              {suite.tests.filter((t) => t.expected_outcome === "fail").length} expected to fail on a bug,{" "}
              {suite.tests.filter((t) => t.expected_outcome === "pass").length} regression guards.
            </span>{" "}
            <code className="font-mono text-[12px] text-muted">{suite.python}</code> and{" "}
            <code className="font-mono text-[12px] text-muted">{suite.typescript}</code>
          </p>
        ) : (
          <p className="flex items-center gap-2 px-1 text-[13px] text-muted">
            <Spinner className="size-3.5" /> Writing the suite…
          </p>
        )}
      </div>
    );
  }
  if (phase === "verify") {
    return (
      <div>
        {head(<ShieldCheck className="size-3.5" />, "Replaying the suite headless")}
        <VerifyPanel view={view} compact />
      </div>
    );
  }
  return (
    <div>
      {head(<FileText className="size-3.5" />, "Report")}
      {view.summary ? (
        <ReportSummary view={view} />
      ) : (
        <p className="flex items-center gap-2 px-1 text-[13px] text-muted">
          <Spinner className="size-3.5" /> Writing report.md and bugs.json…
        </p>
      )}
    </div>
  );
}

function ReportSummary({ view }: { view: RunView }) {
  const s = view.summary!;
  const sev = s.bugs_by_severity;
  return (
    <div className="grid grid-cols-4 gap-2 px-1">
      <Stat label="Bugs" value={String(s.stats?.bugs ?? view.bugs.length)} hint={`${sev.critical} critical · ${sev.high} high · ${sev.medium} med · ${sev.low} low`} />
      <Stat label="Reproduced" value={`${s.reproduced}`} hint={s.not_reproduced ? `${s.not_reproduced} did not reproduce` : "by a failing test"} tone={s.reproduced ? "critical" : undefined} />
      <Stat label="Tests" value={String(s.tests)} hint="Python + TypeScript" />
      <Stat
        label="Control build"
        value={s.control ? `${s.control.passed}/${s.control.passed + s.control.failed}` : "–"}
        hint={s.control ? "tests pass on the fixed build" : "no control URL given"}
        tone={s.control ? (s.control.failed ? "warning" : "good") : undefined}
      />
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: "critical" | "good" | "warning" }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div
        className={clsx(
          "text-xl font-semibold tabular",
          tone === "critical" ? "text-[#f06a6a]" : tone === "good" ? "text-[#3fcf3f]" : tone === "warning" ? "text-warning" : "text-ink",
        )}
      >
        {value}
      </div>
      <div className="truncate text-[11px] text-muted" title={hint}>
        {hint}
      </div>
    </div>
  );
}
