import clsx from "clsx";
import { ChevronLeft, ChevronRight, FastForward, Image as ImageIcon, Radio, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { artifactUrl } from "../api/client";
import { actionAt, skipIdle } from "../lib/video";
import { isLive, type Action, type RunView } from "../state/runReducer";
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

  // Picking a screenshot elsewhere (the timeline) brings the screenshots back.
  useEffect(() => {
    if (pinned) setMode("shots");
  }, [pinned]);

  const go = (delta: number) => {
    const next = frames[Math.min(frames.length - 1, Math.max(0, index + delta))];
    if (next) onPin(next.path === frames[frames.length - 1].path && live ? null : next.path);
  };

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted">
          {mode === "video" ? "Session recording" : (frame?.url ?? view.targetUrl ?? "about:blank")}
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
        <SessionVideo src={artifactUrl(runId, video)} actions={view.actions} />
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
          <Caption failed={frame.failed} text={frame.caption} right={`${index + 1}/${frames.length}`} />
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
                title={f.caption}
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
  );
}

const SPEEDS = [1, 2, 4];

/**
 * The recording runs in real time, mostly a still page while the agent thinks. Playback skips
 * those pauses and names the action on screen, so the video reads as a sequence of steps.
 */
function SessionVideo({ src, actions }: { src: string; actions: Action[] }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [speed, setSpeed] = useState(2);
  // Older runs did not record when the video started, so there is nothing to skip by.
  const canSkip = actions.length > 0;
  const [skip, setSkip] = useState(true);
  const [current, setCurrent] = useState<Action | null>(null);

  useEffect(() => {
    if (ref.current) ref.current.playbackRate = speed;
  }, [speed]);

  const onTime = () => {
    const v = ref.current;
    if (!v) return;
    if (skip && canSkip && !v.paused && !v.seeking) {
      const target = skipIdle(actions, v.currentTime);
      if (target !== null) v.currentTime = target;
    }
    setCurrent(actionAt(actions, v.currentTime));
  };

  return (
    <>
      <video
        ref={ref}
        key={src}
        src={src}
        controls
        onLoadedMetadata={(e) => (e.currentTarget.playbackRate = speed)}
        onTimeUpdate={onTime}
        onSeeked={onTime}
        className="aspect-[16/10] w-full bg-black"
      />
      <Caption
        failed={current?.failed}
        text={current?.caption ?? (canSkip ? "Press play to watch the session" : "Session recording")}
        right={
          <span className="flex items-center gap-2">
            {canSkip && (
              <button
                type="button"
                onClick={() => setSkip((v) => !v)}
                aria-pressed={skip}
                title="Skip the pauses while the agent thinks"
                className={clsx("flex items-center gap-1 rounded px-1.5 py-0.5", skip ? "bg-accent/15 text-accent" : "hover:text-ink")}
              >
                <FastForward className="size-3" /> Skip pauses
              </button>
            )}
            <span className="flex rounded border border-line-strong">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpeed(s)}
                  aria-pressed={speed === s}
                  className={clsx("px-1.5 py-0.5 tabular", speed === s ? "bg-surface-3 text-ink" : "hover:text-ink")}
                >
                  {s}×
                </button>
              ))}
            </span>
          </span>
        }
      />
    </>
  );
}

function Caption({ text, failed, right }: { text: string; failed?: boolean; right: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 border-t border-line px-3 py-1.5 text-[12px]">
      <span className={clsx("min-w-0 flex-1 truncate", failed ? "text-[#f06a6a]" : "text-ink-2")}>{text}</span>
      <span className="shrink-0 text-muted tabular">{right}</span>
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
