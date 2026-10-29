import clsx from "clsx";
import { ChevronLeft, ChevronRight, Image as ImageIcon, Radio, Terminal, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { artifactUrl } from "../api/client";
import type { Signal } from "../api/types";
import { pathOf } from "../lib/format";
import { isLive, type RunView } from "../state/runReducer";
import { Empty } from "./ui";

interface Props {
  runId: string;
  view: RunView;
  /** Pinned screenshot path, or null to follow the newest one. */
  pinned: string | null;
  onPin: (path: string | null) => void;
}

export function BrowserPane({ runId, view, pinned, onPin }: Props) {
  const live = isLive(view.status);
  const frames = view.frames;
  const [mode, setMode] = useState<"shots" | "video">("shots");
  const index = pinned ? frames.findIndex((f) => f.path === pinned) : frames.length - 1;
  const frame = frames[index] ?? frames[frames.length - 1];
  const strip = useRef<HTMLDivElement>(null);
  const video = view.artifacts.video && !live ? view.artifacts.video : null;

  useEffect(() => {
    strip.current?.querySelector<HTMLElement>(`[data-active="true"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [index, frames.length]);

  const go = (delta: number) => {
    const next = frames[Math.min(frames.length - 1, Math.max(0, index + delta))];
    if (next) onPin(next.path === frames[frames.length - 1].path && live ? null : next.path);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface">
        <div className="flex items-center gap-2 border-b border-line px-3 py-2">
          <span className="flex gap-1" aria-hidden>
            <span className="size-2.5 rounded-full bg-[#ff5f57]/70" />
            <span className="size-2.5 rounded-full bg-[#febc2e]/70" />
            <span className="size-2.5 rounded-full bg-[#28c840]/70" />
          </span>
          <div className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-2.5 py-1 font-mono text-[11px] text-ink-2">
            {mode === "video" ? "session.webm" : (frame?.url ?? view.targetUrl ?? "about:blank")}
          </div>
          {video && (
            <div className="flex rounded-md border border-line-strong p-0.5">
              <ModeButton active={mode === "shots"} onClick={() => setMode("shots")} label="Screenshots">
                <ImageIcon className="size-3.5" />
              </ModeButton>
              <ModeButton active={mode === "video"} onClick={() => setMode("video")} label="Session video">
                <Video className="size-3.5" />
              </ModeButton>
            </div>
          )}
          {live && (
            <button
              type="button"
              onClick={() => onPin(null)}
              className={clsx(
                "flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px]",
                pinned ? "text-muted hover:text-ink" : "bg-accent/15 text-accent",
              )}
              title="Follow the newest screenshot"
            >
              <Radio className="size-3" /> Live
            </button>
          )}
        </div>

        {mode === "video" && video ? (
          <video key={video} src={artifactUrl(runId, video)} controls className="aspect-[16/10] w-full bg-black" />
        ) : frame ? (
          <>
            <div className="relative bg-black/40">
              <img
                key={frame.path}
                src={artifactUrl(runId, frame.path)}
                alt={frame.caption}
                className={clsx("aspect-[16/10] w-full object-contain object-top", frame.failed && "outline-2 -outline-offset-2 outline-critical/70")}
              />
              {frames.length > 1 && (
                <>
                  <NavButton side="left" disabled={index <= 0} onClick={() => go(-1)} />
                  <NavButton side="right" disabled={index >= frames.length - 1} onClick={() => go(1)} />
                </>
              )}
            </div>
            <div className="flex items-center gap-2 border-t border-line px-3 py-1.5 text-[12px]">
              <span className="font-mono text-[10px] text-muted tabular">#{frame.step}</span>
              <span className={clsx("min-w-0 flex-1 truncate", frame.failed ? "text-[#f06a6a]" : "text-ink-2")}>{frame.caption}</span>
              <span className="shrink-0 text-muted tabular">
                {index + 1}/{frames.length}
              </span>
            </div>
            <div ref={strip} className="flex gap-1.5 overflow-x-auto border-t border-line px-2 py-2">
              {frames.map((f, i) => (
                <button
                  key={f.path}
                  type="button"
                  data-active={i === index}
                  onClick={() => onPin(i === frames.length - 1 && live ? null : f.path)}
                  className={clsx(
                    "shrink-0 overflow-hidden rounded border-2",
                    i === index ? "border-accent" : f.failed ? "border-critical/60" : "border-transparent opacity-70 hover:opacity-100",
                  )}
                  title={`#${f.step} ${f.caption}`}
                >
                  <img src={artifactUrl(runId, f.path)} alt="" loading="lazy" className="h-10 w-16 object-cover object-top" />
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="aspect-[16/10]">
            <Empty icon={<ImageIcon className="size-6" />} title={live ? "Waiting for the first page" : "No screenshots"}>
              {live ? "Screenshots appear here as the agent acts." : undefined}
            </Empty>
          </div>
        )}
      </div>

      <Signals signals={view.signals} baseUrl={view.targetUrl} />
    </div>
  );
}

function ModeButton({ active, onClick, label, children }: { active: boolean; onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={clsx("rounded px-1.5 py-0.5", active ? "bg-surface-3 text-ink" : "text-muted hover:text-ink")}
    >
      {children}
    </button>
  );
}

function NavButton({ side, disabled, onClick }: { side: "left" | "right"; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={side === "left" ? "Previous screenshot" : "Next screenshot"}
      className={clsx(
        "absolute top-1/2 -translate-y-1/2 rounded-full bg-black/60 p-1 text-white/80 hover:bg-black/80 hover:text-white disabled:hidden",
        side === "left" ? "left-2" : "right-2",
      )}
    >
      {side === "left" ? <ChevronLeft className="size-4" /> : <ChevronRight className="size-4" />}
    </button>
  );
}

function Signals({ signals, baseUrl }: { signals: Signal[]; baseUrl?: string }) {
  const [onlyErrors, setOnlyErrors] = useState(false);
  const list = useRef<HTMLUListElement>(null);
  const shown = onlyErrors ? signals.filter((s) => s.level === "error") : signals;
  const errors = signals.filter((s) => s.level === "error").length;

  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <div className="flex min-h-36 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5 text-[12px]">
        <Terminal className="size-3.5 text-muted" />
        <span className="font-medium text-ink-2">Console & network</span>
        <span className="text-muted tabular">{signals.length}</span>
        {errors > 0 && <span className="rounded bg-critical/15 px-1 text-[11px] text-[#f06a6a] tabular">{errors} errors</span>}
        <label className="ml-auto flex items-center gap-1.5 text-muted">
          <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} className="size-3.5 accent-[#3987e5]" />
          Errors only
        </label>
      </div>
      <ul ref={list} className="min-h-0 flex-1 overflow-y-auto py-1 font-mono text-[11px]">
        {shown.length === 0 && <li className="px-3 py-2 font-sans text-[12px] text-muted">Nothing logged yet.</li>}
        {shown.map((s) => (
          <li key={s.seq} className="flex gap-2 px-3 py-0.5 hover:bg-surface-2">
            <span
              className={clsx(
                "w-14 shrink-0",
                s.level === "error" ? "text-[#f06a6a]" : s.level === "warning" ? "text-warning" : "text-muted",
              )}
            >
              {s.kind}
            </span>
            <span className="min-w-0 flex-1 break-words text-ink-2">
              {s.text}
              {s.url && s.kind !== "network" && <span className="text-muted"> · {pathOf(s.url, baseUrl)}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
