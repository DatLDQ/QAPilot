import clsx from "clsx";
import { Check, Copy, Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { RunStatus, Severity, Verdict } from "../api/types";

export function IconButton({
  label,
  onClick,
  active,
  children,
  className,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        "rounded-md p-1.5 transition-colors",
        active ? "bg-surface-3 text-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin", className)} />;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      label={copied ? "Copied" : label}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}
    </IconButton>
  );
}

const buttonClass = (variant: "primary" | "secondary" | "ghost" | "danger", className?: string) =>
  clsx(
    "inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
    variant === "primary" && "bg-accent-strong text-white hover:bg-accent",
    variant === "secondary" && "border border-line-strong bg-surface-2 text-ink hover:bg-surface-3",
    variant === "ghost" && "text-ink-2 hover:bg-surface-2 hover:text-ink",
    variant === "danger" && "border border-critical/40 text-critical hover:bg-critical/10",
    className,
  );

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  className,
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={buttonClass(variant, className)}>
      {children}
    </button>
  );
}

/** A download/open link styled like a button. */
export function LinkButton({
  href,
  children,
  download,
  variant = "secondary",
  className,
}: {
  href: string;
  children: ReactNode;
  download?: boolean;
  variant?: "primary" | "secondary" | "ghost";
  className?: string;
}) {
  return (
    <a
      href={href}
      download={download || undefined}
      target={download ? undefined : "_blank"}
      rel="noreferrer"
      className={buttonClass(variant, clsx("py-1.5 text-[13px]", className))}
    >
      {children}
    </a>
  );
}

type Tone = "neutral" | "accent" | "good" | "warning" | "critical" | "orange";

const TONES: Record<Tone, string> = {
  neutral: "border-line-strong bg-surface-2 text-ink-2",
  accent: "border-accent/40 bg-accent/10 text-accent",
  good: "border-good/40 bg-good/10 text-[#3fcf3f]",
  warning: "border-warning/40 bg-warning/10 text-warning",
  critical: "border-critical/45 bg-critical/12 text-[#f06a6a]",
  orange: "border-[#ec835a]/45 bg-[#ec835a]/10 text-[#ec835a]",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-px text-[11px] leading-[18px] font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: "critical",
  high: "orange",
  medium: "warning",
  low: "neutral",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge tone={SEVERITY_TONE[severity]} className="uppercase tracking-wide">
      {severity}
    </Badge>
  );
}

const STATUS: Record<RunStatus, { tone: Tone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "accent", label: "Running" },
  completed: { tone: "good", label: "Completed" },
  failed: { tone: "critical", label: "Failed" },
  cancelled: { tone: "warning", label: "Cancelled" },
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone}>
      {status === "running" && <span className="live-dot size-1.5 rounded-full bg-accent" />}
      {s.label}
    </Badge>
  );
}

export const STATUS_DOT: Record<RunStatus, string> = {
  queued: "bg-muted",
  running: "bg-accent live-dot",
  completed: "bg-good",
  failed: "bg-critical",
  cancelled: "bg-warning",
};

const VERDICT: Record<Verdict, { tone: Tone; label: string; hint: string }> = {
  reproduced: { tone: "critical", label: "Bug reproduced", hint: "The test fails on this build, exactly where the bug predicts." },
  stable: { tone: "good", label: "Passes", hint: "The test passes, as expected on this build." },
  not_reproduced: { tone: "warning", label: "Did not reproduce", hint: "Expected to fail on the bug, but it passed." },
  flaky: { tone: "warning", label: "Unexpected failure", hint: "Expected to pass, but it failed." },
  error: { tone: "neutral", label: "Could not run", hint: "The test errored, was skipped or never reported." },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict];
  return (
    <Badge tone={v.tone} title={v.hint}>
      {v.label}
    </Badge>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number; icon?: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={t.id === value}
          onClick={() => onChange(t.id)}
          className={clsx(
            "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors",
            t.id === value ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.icon}
          {t.label}
          {t.count !== undefined && (
            <span
              className={clsx(
                "tabular rounded px-1.5 text-[11px]",
                t.id === value ? "bg-accent/15 text-accent" : "bg-surface-3 text-muted",
              )}
            >
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="text-muted">{icon}</div>
      <div className="text-sm font-medium text-ink-2">{title}</div>
      {children && <div className="max-w-sm text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 pb-2">
      <h3 className="text-[11px] font-semibold tracking-wider text-muted uppercase">{children}</h3>
      {right}
    </div>
  );
}
