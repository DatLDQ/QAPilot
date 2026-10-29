import clsx from "clsx";
import { ChevronDown, Compass, FileCode2, FileText, Play, ShieldCheck, ShoppingBag } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import type { AppConfig, NewRun } from "../api/types";
import { Button, Spinner } from "./ui";

interface Props {
  config: AppConfig | null;
  starting: boolean;
  error: string | null;
  onStart: (run: NewRun) => void;
}

const PHASES: { icon: ReactNode; title: string; body: string }[] = [
  {
    icon: <Compass className="size-4" />,
    title: "Explore",
    body: "Claude drives a real Chromium through your user story, in scenarios with fresh storage, asserting what it sees.",
  },
  {
    icon: <FileCode2 className="size-4" />,
    title: "Generate",
    body: "Every scenario becomes a Playwright test, in Python and TypeScript, with resilient role-based locators.",
  },
  {
    icon: <ShieldCheck className="size-4" />,
    title: "Verify",
    body: "The suite is replayed headless. A bug only counts as reproduced if its test fails on the target build.",
  },
  {
    icon: <FileText className="size-4" />,
    title: "Report",
    body: "Bug reports with evidence, a session video, a Playwright trace and a downloadable test suite.",
  },
];

export function Launcher({ config, starting, error, onStart }: Props) {
  const [targetUrl, setTargetUrl] = useState("");
  const [story, setStory] = useState("");
  const [focus, setFocus] = useState("");
  const [controlUrl, setControlUrl] = useState("");
  const [maxSteps, setMaxSteps] = useState<number | "">("");
  const [verify, setVerify] = useState(true);
  const [advanced, setAdvanced] = useState(false);

  const useDemo = () => {
    if (!config) return;
    setTargetUrl(config.demo.target_url);
    setStory(config.demo.story);
    setFocus(config.demo.focus);
    setControlUrl(config.demo.control_url);
    setVerify(true);
    setAdvanced(true);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onStart({
      target_url: targetUrl.trim(),
      story: story.trim(),
      focus: focus.trim() || undefined,
      control_url: controlUrl.trim() || undefined,
      max_steps: maxSteps === "" ? undefined : maxSteps,
      verify,
    });
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-12">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Test a web app with an AI QA engineer</h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-2">
          Give QAPilot a URL and a user story. It explores the app in a real browser, files evidence-backed bug
          reports, and hands you a Playwright suite that proves each bug.
        </p>

        {config?.demo_mode && (
          <div className="mt-5 rounded-lg border border-warning/35 bg-warning/8 px-4 py-3 text-[13px] text-ink-2">
            <span className="font-medium text-warning">Demo mode.</span> No <code className="font-mono">ANTHROPIC_API_KEY</code> (or{" "}
            <code className="font-mono">GEMINI_API_KEY</code>) is set, so a scripted agent stands in for Claude. The browser, test generation and verification are all
            real. Try it on the bundled demo shop.
          </div>
        )}

        <form onSubmit={submit} className="mt-6 space-y-4 rounded-xl border border-line bg-surface p-5">
          <div className="flex items-end justify-between gap-3">
            <Field label="App URL" htmlFor="target" className="flex-1">
              <input
                id="target"
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
                placeholder="http://localhost:3000/"
                autoComplete="off"
                spellCheck={false}
                className={inputClass("font-mono text-[13px]")}
              />
            </Field>
            <Button onClick={useDemo} disabled={!config} title="Fill the form with the bundled demo shop, which has seeded bugs">
              <ShoppingBag className="size-4" />
              Use demo shop
            </Button>
          </div>

          <Field label="User story" htmlFor="story" hint="What a user should be able to do. The agent plans scenarios from this.">
            <textarea
              id="story"
              value={story}
              onChange={(e) => setStory(e.target.value)}
              rows={3}
              placeholder="As a shopper I can search the catalogue, add items to my cart and check out."
              className={inputClass("resize-y leading-relaxed")}
            />
          </Field>

          <Field label="Focus" htmlFor="focus" optional hint="Areas to dig into, e.g. validation, pricing, accessibility.">
            <input
              id="focus"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="Form validation and console errors"
              className={inputClass()}
            />
          </Field>

          <div>
            <button
              type="button"
              onClick={() => setAdvanced((v) => !v)}
              className="flex items-center gap-1 text-[13px] text-muted hover:text-ink"
              aria-expanded={advanced}
            >
              <ChevronDown className={clsx("size-4 transition-transform", !advanced && "-rotate-90")} />
              Verification and limits
            </button>
            {advanced && (
              <div className="mt-3 grid grid-cols-[1fr_9rem] gap-4">
                <Field
                  label="Control build URL"
                  htmlFor="control"
                  optional
                  hint="A build where the bugs are fixed. Bug tests should pass there, which shows they fail for the right reason."
                >
                  <input
                    id="control"
                    value={controlUrl}
                    onChange={(e) => setControlUrl(e.target.value)}
                    placeholder="http://localhost:3001/"
                    spellCheck={false}
                    className={inputClass("font-mono text-[13px]")}
                  />
                </Field>
                <Field label="Max steps" htmlFor="steps" hint={`Default ${config?.max_steps ?? 60}`}>
                  <input
                    id="steps"
                    type="number"
                    min={3}
                    max={150}
                    value={maxSteps}
                    onChange={(e) => setMaxSteps(e.target.value === "" ? "" : Number(e.target.value))}
                    placeholder={String(config?.max_steps ?? 60)}
                    className={inputClass("tabular")}
                  />
                </Field>
                <label className="col-span-2 flex items-center gap-2 text-sm text-ink-2">
                  <input
                    type="checkbox"
                    checked={verify}
                    onChange={(e) => setVerify(e.target.checked)}
                    className="size-4 accent-[#3987e5]"
                  />
                  Replay the generated suite to verify every bug
                </label>
              </div>
            )}
          </div>

          {error && (
            <p role="alert" className="rounded-lg border border-critical/40 bg-critical/10 px-3 py-2 text-[13px] text-[#f06a6a]">
              {error}
            </p>
          )}

          <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
            <p className="text-xs text-muted">
              The browser stays on the target's host
              {config?.allowed_hosts.length ? ` (plus ${config.allowed_hosts.join(", ")})` : ""}.
            </p>
            <Button type="submit" variant="primary" disabled={starting}>
              {starting ? <Spinner className="size-4" /> : <Play className="size-4" />}
              Start run
            </Button>
          </div>
        </form>

        <ol className="mt-8 grid grid-cols-2 gap-3">
          {PHASES.map((p, i) => (
            <li key={p.title} className="rounded-xl border border-line bg-surface/60 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-ink">
                <span className="flex size-6 items-center justify-center rounded-md bg-surface-3 text-accent">{p.icon}</span>
                <span className="text-muted tabular">{i + 1}</span>
                {p.title}
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">{p.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

const inputClass = (extra?: string) =>
  clsx(
    "w-full rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-muted/70 focus:border-accent focus:outline-none",
    extra,
  );

function Field({
  label,
  htmlFor,
  hint,
  optional,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  optional?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1.5 flex items-baseline gap-1.5 text-[13px] font-medium text-ink-2">
        {label}
        {optional && <span className="text-[11px] font-normal text-muted">optional</span>}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}
