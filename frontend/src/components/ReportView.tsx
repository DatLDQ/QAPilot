import { Download, FileJson, FileText, Film, Route } from "lucide-react";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, artifactUrl, suiteZipUrl } from "../api/client";
import type { RunView } from "../state/runReducer";
import { CopyButton, Empty, LinkButton, SectionTitle, Spinner } from "./ui";

export function ReportView({ runId, view }: { runId: string; view: RunView }) {
  const { report, bugs, video, trace } = view.artifacts;
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!report) return;
    let alive = true;
    api
      .artifactText(runId, report)
      .then((t) => alive && setMarkdown(t))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [runId, report]);

  const live = view.status === "running" || view.status === "queued";
  if (!report && !video && !trace) {
    return (
      <Empty icon={<FileText className="size-6" />} title={live ? "The report is written at the end of the run" : "No report for this run"}>
        {live ? "It includes every bug with evidence, the verification results and links to the recordings." : view.error}
      </Empty>
    );
  }

  const traceCmd = `npx playwright show-trace ${trace ? "trace.zip" : ""}`;

  return (
    <div className="mx-auto grid max-w-6xl gap-6 px-6 py-5 lg:grid-cols-[1fr_22rem]">
      <article className="min-w-0 rounded-xl border border-line bg-surface px-6 py-5">
        {report ? (
          error ? (
            <p className="text-[13px] text-[#f06a6a]">{error}</p>
          ) : markdown === null ? (
            <p className="flex items-center gap-2 text-[13px] text-muted">
              <Spinner className="size-3.5" /> Loading report…
            </p>
          ) : (
            <div className="md">
              <Markdown
                remarkPlugins={[remarkGfm]}
                urlTransform={(url) => (/^(https?:|#|\/)/.test(url) ? url : artifactUrl(runId, url))}
                components={{ img: ({ src, alt }) => <img src={typeof src === "string" ? src : undefined} alt={alt ?? ""} className="my-2 max-w-full rounded-lg border border-line" /> }}
              >
                {markdown}
              </Markdown>
            </div>
          )
        ) : (
          <p className="text-[13px] text-muted">The run stopped before the report was written.</p>
        )}
      </article>

      <aside className="space-y-5">
        {video && (
          <section>
            <SectionTitle>
              <span className="flex items-center gap-1.5">
                <Film className="size-3.5" /> Session recording
              </span>
            </SectionTitle>
            <video src={artifactUrl(runId, video)} controls className="w-full rounded-xl border border-line bg-black" />
          </section>
        )}

        <section>
          <SectionTitle>Downloads</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {report && (
              <LinkButton href={artifactUrl(runId, report, true)} download>
                <FileText className="size-3.5" /> report.md
              </LinkButton>
            )}
            {bugs && (
              <LinkButton href={artifactUrl(runId, bugs, true)} download>
                <FileJson className="size-3.5" /> bugs.json
              </LinkButton>
            )}
            {view.suite && (
              <LinkButton href={suiteZipUrl(runId)} download>
                <Download className="size-3.5" /> suite.zip
              </LinkButton>
            )}
            {video && (
              <LinkButton href={artifactUrl(runId, video, true)} download>
                <Film className="size-3.5" /> session.webm
              </LinkButton>
            )}
            {trace && (
              <LinkButton href={artifactUrl(runId, trace, true)} download>
                <Route className="size-3.5" /> trace.zip
              </LinkButton>
            )}
          </div>
        </section>

        {trace && (
          <section className="rounded-xl border border-line bg-surface px-3 py-2.5">
            <div className="flex items-center justify-between text-[12px] text-ink-2">
              Playwright trace
              <CopyButton text={traceCmd} label="Copy command" />
            </div>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              Step through every action with DOM snapshots, network and console, or drop the file on{" "}
              <a href="https://trace.playwright.dev" target="_blank" rel="noreferrer" className="text-accent hover:underline">
                trace.playwright.dev
              </a>
              .
            </p>
            <pre className="mt-1.5 overflow-x-auto font-mono text-[12px] text-ink-2">{traceCmd}</pre>
          </section>
        )}
      </aside>
    </div>
  );
}
