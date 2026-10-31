import clsx from "clsx";
import { ChevronDown, CircleCheck, CircleX, Code2, FileCode2, FlaskConical } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { GeneratedTest } from "../api/types";
import { highlight, type Lang } from "../lib/highlight";
import { ASPECT_LABEL, summarizeScenarios, type ScenarioSummary } from "../lib/scenarios";
import { isLive, type RunView } from "../state/runReducer";
import { Badge, CopyButton, Empty, SectionTitle, Spinner } from "./ui";
import { VerifyPanel } from "./VerifyPanel";

export function TestsView({ runId, view, focusTest }: { runId: string; view: RunView; focusTest: string | null }) {
  const suite = view.suite;
  const [lang, setLang] = useState<Lang>("python");
  // The code is there for whoever runs the suite; the page leads with what each test checks.
  const [codeFor, setCodeFor] = useState<string | null>(focusTest);
  const [showCode, setShowCode] = useState(!!focusTest);
  const code = useRef<HTMLElement>(null);
  const scenarios = useMemo(() => summarizeScenarios(view.blocks, isLive(view.status)), [view.blocks, view.status]);

  useEffect(() => {
    if (!focusTest) return;
    setCodeFor(focusTest);
    setShowCode(true);
  }, [focusTest]);

  if (!suite) {
    const live = view.status === "running" || view.status === "queued";
    return (
      <Empty icon={<FlaskConical className="size-6" />} title={live ? "Tests are generated after exploration" : "No tests were generated"}>
        {live
          ? "Once the agent finishes exploring, every recorded scenario becomes a Playwright test."
          : "The run ended before any scenario was recorded."}
      </Empty>
    );
  }

  const openCode = (name: string) => {
    setCodeFor(name);
    setShowCode(true);
    requestAnimationFrame(() => code.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const path = lang === "python" ? suite.python : suite.typescript;
  const focusTitle = suite.tests.find((t) => t.name === codeFor)?.title;
  const runCmd =
    lang === "python"
      ? `pip install pytest-playwright && playwright install chromium\nBASE_URL=${suite.base_url} pytest test_qapilot.py`
      : `npm i -D @playwright/test && npx playwright install chromium\nBASE_URL=${suite.base_url} npx playwright test`;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-5">
      <section className="rounded-xl border border-line bg-surface px-4 py-3.5 text-[13px] leading-relaxed text-ink-2">
        <div className="font-medium text-ink">What this suite is for</div>
        <p className="mt-1">
          Each scenario from the session became a standalone Playwright test ({suite.tests.length} in total), in Python and
          TypeScript. Keep them in your repo and run them after a fix or in CI on every change, so a bug that was fixed
          cannot quietly come back.
        </p>
        <p className="mt-1.5 text-muted">
          A test written for a bug checks the <em>correct</em> behaviour: it fails while the bug is there and passes once it
          is fixed. When it fails on this build, the bug counts as reproduced. On a control build every test should pass.
        </p>
      </section>

      <section>
        <SectionTitle>Replay on this build</SectionTitle>
        <VerifyPanel view={view} />
      </section>

      <section>
        <SectionTitle>What each test checks</SectionTitle>
        <ol className="space-y-2">
          {suite.tests.map((t) => (
            <TestCard key={t.name} test={t} scenario={scenarios.find((s) => s.id === t.scenario_id)} onCode={() => openCode(t.name)} />
          ))}
        </ol>
      </section>

      <section ref={code} className="scroll-mt-4">
        <SectionTitle
          right={
            showCode && (
              <div className="flex items-center gap-1">
                <LangTab active={lang === "python"} onClick={() => setLang("python")}>
                  Python · pytest
                </LangTab>
                <LangTab active={lang === "typescript"} onClick={() => setLang("typescript")}>
                  TypeScript · @playwright/test
                </LangTab>
              </div>
            )
          }
        >
          <button
            type="button"
            onClick={() => setShowCode((v) => !v)}
            aria-expanded={showCode}
            className="flex items-center gap-1 tracking-wider uppercase hover:text-ink"
          >
            <ChevronDown className={clsx("size-3.5 transition-transform", !showCode && "-rotate-90")} />
            Code
          </button>
        </SectionTitle>
        {showCode ? (
          <>
            <CodeViewer
              runId={runId}
              path={path}
              lang={lang}
              focus={codeFor ? (lang === "python" ? `def ${codeFor}(` : focusTitle ? `test(${JSON.stringify(focusTitle)}` : null) : null}
            />
            <div className="mt-3 rounded-lg border border-line bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between text-[12px] text-muted">
                Run it yourself
                <CopyButton text={runCmd} label="Copy commands" />
              </div>
              <pre className="mt-1 overflow-x-auto font-mono text-[12px] text-ink-2">{runCmd}</pre>
            </div>
          </>
        ) : (
          <p className="text-[12px] text-muted">
            Only needed to run the suite yourself. Open one test&apos;s code from its card, or take the whole suite from Export.
          </p>
        )}
      </section>
    </div>
  );
}

function TestCard({ test, scenario, onCode }: { test: GeneratedTest; scenario?: ScenarioSummary; onCode: () => void }) {
  return (
    <li className="rounded-lg border border-line bg-surface px-3.5 py-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-medium text-ink">{test.title}</span>
            {scenario?.aspect && <Badge>{ASPECT_LABEL[scenario.aspect] ?? scenario.aspect}</Badge>}
          </div>
          <div className="mt-0.5 text-[12px]">
            {test.expected_outcome === "fail" ? (
              <span className="text-[#f06a6a]">Fails until {test.bug_ids.join(", ")} is fixed</span>
            ) : (
              <span className="text-muted">Should pass: guards behaviour that works today</span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onCode}
          className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[12px] text-muted hover:bg-surface-2 hover:text-ink"
        >
          <Code2 className="size-3.5" /> Code
        </button>
      </div>
      {scenario && scenario.checks.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[12px]">
          {scenario.checks.map((c, i) => (
            <li key={i} className="flex items-start gap-1.5">
              {c.passed === false ? (
                <CircleX className="mt-0.5 size-3.5 shrink-0 text-[#f06a6a]" />
              ) : (
                <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-[#3fcf3f]" />
              )}
              <span className={c.passed === false ? "text-ink" : "text-ink-2"}>{c.description}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function LangTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx("rounded-md px-2 py-1 text-[12px]", active ? "bg-surface-3 text-ink" : "text-muted hover:text-ink")}
    >
      {children}
    </button>
  );
}

function CodeViewer({ runId, path, lang, focus }: { runId: string; path: string; lang: Lang; focus: string | null }) {
  const [source, setSource] = useState<{ path: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    api
      .artifactText(runId, path)
      .then((text) => alive && setSource({ path, text }))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [runId, path]);

  const text = source?.path === path ? source.text : null;
  const lines = useMemo(() => (text === null ? [] : highlight(text, lang)), [text, lang]);
  const focusLine = useMemo(() => (focus && text ? text.split("\n").findIndex((l) => l.includes(focus)) : -1), [focus, text]);

  useEffect(() => {
    if (focusLine < 0 || !box.current) return;
    const row = box.current.querySelector<HTMLElement>(`[data-line="${focusLine}"]`);
    if (row) box.current.scrollTop = row.offsetTop - 48;
  }, [focusLine, lines]);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <FileCode2 className="size-3.5 text-muted" />
        <span className="font-mono text-[12px] text-ink-2">{path}</span>
        <span className="ml-auto flex items-center gap-1">{text && <CopyButton text={text} label="Copy file" />}</span>
      </div>
      <div ref={box} className="relative max-h-[34rem] overflow-auto py-2">
        {error ? (
          <p className="px-4 text-[13px] text-[#f06a6a]">{error}</p>
        ) : text === null ? (
          <p className="flex items-center gap-2 px-4 text-[13px] text-muted">
            <Spinner className="size-3.5" /> Loading…
          </p>
        ) : (
          <pre className="code">
            {lines.map((tokens, i) => (
              <div key={i} data-line={i} className={clsx("pr-4", i === focusLine && "bg-accent/12")}>
                <span className="ln">{i + 1}</span>
                {tokens.map((t, j) =>
                  t.kind ? (
                    <span key={j} className={`tok-${t.kind}`}>
                      {t.text}
                    </span>
                  ) : (
                    t.text
                  ),
                )}
              </div>
            ))}
          </pre>
        )}
      </div>
    </div>
  );
}
