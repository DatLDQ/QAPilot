import { FileText } from "lucide-react";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, artifactUrl } from "../api/client";
import type { RunView } from "../state/runReducer";
import { Empty, Spinner } from "./ui";

export function ReportView({ runId, view }: { runId: string; view: RunView }) {
  const { report, video, trace } = view.artifacts;
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
        {live ? undefined : view.error}
      </Empty>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-6 py-5">
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
    </div>
  );
}
