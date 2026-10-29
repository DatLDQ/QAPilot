import clsx from "clsx";
import { Download, FileCode2, FlaskConical } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, artifactUrl, suiteZipUrl } from "../api/client";
import { highlight, type Lang } from "../lib/highlight";
import type { RunView } from "../state/runReducer";
import { CopyButton, Empty, LinkButton, SectionTitle, Spinner } from "./ui";
import { VerifyPanel } from "./VerifyPanel";

export function TestsView({ runId, view, focusTest }: { runId: string; view: RunView; focusTest: string | null }) {
  const suite = view.suite;
  const [lang, setLang] = useState<Lang>("python");

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

  const path = lang === "python" ? suite.python : suite.typescript;
  const focusTitle = suite.tests.find((t) => t.name === focusTest)?.title;
  const runCmd =
    lang === "python"
      ? `pip install pytest-playwright && playwright install chromium\nBASE_URL=${suite.base_url} pytest test_qapilot.py`
      : `npm i -D @playwright/test && npx playwright install chromium\nBASE_URL=${suite.base_url} npx playwright test`;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-5">
      <section>
        <SectionTitle right={<LinkButton href={suiteZipUrl(runId)} download><Download className="size-3.5" /> suite.zip</LinkButton>}>
          Verification
        </SectionTitle>
        <VerifyPanel view={view} />
        <p className="mt-2 text-[12px] leading-relaxed text-muted">
          A test written for a bug asserts the <em>correct</em> behaviour, so it fails while the bug exists and turns green
          once it is fixed. On the control build every test should pass.
        </p>
      </section>

      <section>
        <SectionTitle
          right={
            <div className="flex items-center gap-1">
              <LangTab active={lang === "python"} onClick={() => setLang("python")}>
                Python · pytest
              </LangTab>
              <LangTab active={lang === "typescript"} onClick={() => setLang("typescript")}>
                TypeScript · @playwright/test
              </LangTab>
            </div>
          }
        >
          Generated suite
        </SectionTitle>
        <CodeViewer
          runId={runId}
          path={path}
          lang={lang}
          focus={focusTest ? (lang === "python" ? `def ${focusTest}(` : focusTitle ? `test(${JSON.stringify(focusTitle)}` : null) : null}
        />
        <div className="mt-3 rounded-lg border border-line bg-surface px-3 py-2.5">
          <div className="flex items-center justify-between text-[12px] text-muted">
            Run it yourself
            <CopyButton text={runCmd} label="Copy commands" />
          </div>
          <pre className="mt-1 overflow-x-auto font-mono text-[12px] text-ink-2">{runCmd}</pre>
        </div>
      </section>
    </div>
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
        <span className="ml-auto flex items-center gap-1">
          {text && <CopyButton text={text} label="Copy file" />}
          <a href={artifactUrl(runId, path, true)} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink" title="Download" aria-label="Download file">
            <Download className="size-3.5" />
          </a>
        </span>
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
