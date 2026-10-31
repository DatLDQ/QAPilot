import { ChevronDown, Download, FileJson, FileText, Film, FolderArchive, Route } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { artifactUrl, suiteZipUrl } from "../api/client";
import type { RunView } from "../state/runReducer";

interface Item {
  href: string;
  icon: ReactNode;
  label: string;
  why: string;
}

/**
 * Everything the run produced, as files. All of it is already on screen (Bugs, Tests, Report, the session
 * video); the files are for taking it elsewhere: an issue tracker, CI, a ticket, the trace viewer.
 */
export function ExportMenu({ runId, view }: { runId: string; view: RunView }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const { report, bugs, video, trace } = view.artifacts;

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const items = ([
    bugs && { href: artifactUrl(runId, bugs, true), icon: <FileJson />, label: "Bugs (JSON)", why: "For an issue tracker or a CI gate" },
    view.suite && { href: suiteZipUrl(runId), icon: <FolderArchive />, label: "Test suite (.zip)", why: "Python and TypeScript tests to run in CI" },
    report && { href: artifactUrl(runId, report, true), icon: <FileText />, label: "Report (Markdown)", why: "To paste into a ticket or pull request" },
    video && { href: artifactUrl(runId, video, true), icon: <Film />, label: "Session video", why: "To share the recording" },
    trace && {
      href: artifactUrl(runId, trace, true),
      icon: <Route />,
      label: "Playwright trace",
      why: "DOM, network and console per step, in npx playwright show-trace",
    },
  ] as (Item | false | null | undefined | "")[]).filter((i): i is Item => !!i);
  if (!items.length) return null;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-1.5 rounded-lg border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[13px] text-ink-2 hover:text-ink"
      >
        <Download className="size-3.5" /> Export <ChevronDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1.5 w-80 overflow-hidden rounded-xl border border-line-strong bg-surface-2 py-1 shadow-xl">
          <p className="px-3 pt-1.5 pb-2 text-[11px] leading-snug text-muted">
            Everything here is already shown in the tabs. Download only to use it somewhere else.
          </p>
          {items.map((i) => (
            <a
              key={i.label}
              role="menuitem"
              href={i.href}
              download
              onClick={() => setOpen(false)}
              className="flex items-start gap-2.5 px-3 py-2 hover:bg-surface-3 [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted"
            >
              {i.icon}
              <span className="min-w-0">
                <span className="block text-[13px] text-ink">{i.label}</span>
                <span className="block text-[12px] text-muted">{i.why}</span>
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
