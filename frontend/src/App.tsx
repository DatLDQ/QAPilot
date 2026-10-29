import { AlertTriangle, Bug as BugIcon, FileText, FlaskConical, MonitorPlay, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, followRun } from "./api/client";
import type { AppConfig, Health, NewRun, RunDetail, RunRow } from "./api/types";
import { BrowserPane } from "./components/BrowserPane";
import { BugList } from "./components/BugList";
import { Launcher } from "./components/Launcher";
import { ReportView } from "./components/ReportView";
import { RunHeader } from "./components/RunHeader";
import { Sidebar } from "./components/Sidebar";
import { TestsView } from "./components/TestsView";
import { Timeline } from "./components/Timeline";
import { Spinner, Tabs } from "./components/ui";
import { initialRun, isLive, reduceRun, type RunView } from "./state/runReducer";

type Tab = "live" | "bugs" | "tests" | "report";
type RunState = { id: string; view: RunView; detail: RunDetail | null };

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

// The selected run lives in the URL hash (#/runs/<id>) so a run can be linked and reloaded.
const runFromHash = () => /^#\/runs\/([\w-]+)/.exec(window.location.hash)?.[1] ?? null;
const navigate = (id: string | null) => {
  window.location.hash = id ? `/runs/${id}` : "/";
};

function useSelectedRun() {
  const [selected, setSelected] = useState(runFromHash);
  useEffect(() => {
    const onHash = () => setSelected(runFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return selected;
}

export default function App() {
  const selected = useSelectedRun();
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  // Keyed by run id so events from a run we just navigated away from are dropped.
  const [run, setRun] = useState<RunState | null>(null);
  const [tab, setTab] = useState<Tab>("live");
  const [pinned, setPinned] = useState<string | null>(null);
  const [focusTest, setFocusTest] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const fail = useCallback((e: unknown) => setToast(message(e)), []);

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await api.listRuns());
    } catch {
      /* the health footer already reports an unreachable backend */
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  // ---- app data -----------------------------------------------------------
  useEffect(() => {
    void refreshHealth();
    void refreshRuns();
    const id = setInterval(() => void refreshHealth(), 10_000);
    return () => clearInterval(id);
  }, [refreshHealth, refreshRuns]);

  useEffect(() => {
    if (health && !config) api.config().then(setConfig).catch(fail);
  }, [health, config, fail]);

  // Keep the sidebar current while anything is running.
  const anyLive = runs.some((r) => r.live);
  useEffect(() => {
    if (!anyLive) return;
    const id = setInterval(() => void refreshRuns(), 3000);
    return () => clearInterval(id);
  }, [anyLive, refreshRuns]);

  // ---- the selected run ---------------------------------------------------
  useEffect(() => {
    setTab("live");
    setPinned(null);
    setFocusTest(null);
    setCancelling(false);
    stickToBottom.current = true;
    if (!selected) {
      setRun(null);
      return;
    }
    const id = selected;
    setRun({ id, view: initialRun(), detail: null });
    const controller = new AbortController();
    const patch = (fn: (r: RunState) => RunState) =>
      setRun((r) => (r && r.id === id ? fn(r) : r));
    const loadDetail = () =>
      api.getRun(id).then((detail) => {
        if (!controller.signal.aborted) patch((r) => ({ ...r, detail }));
      });

    const notFound = (e: unknown) => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status === 404) {
        setToast("That run no longer exists.");
        navigate(null);
      } else fail(e);
    };

    loadDetail().catch(notFound);
    followRun(id, (ev) => patch((r) => ({ ...r, view: reduceRun(r.view, ev) })), controller.signal)
      .then(() => {
        if (controller.signal.aborted) return;
        // The stored result carries what the stream doesn't (bug ↔ test links), so refetch it.
        void loadDetail().catch(() => undefined);
        void refreshRuns();
        void refreshHealth();
      })
      .catch(notFound);
    return () => controller.abort();
  }, [selected, fail, refreshRuns, refreshHealth]);

  const streamed = run?.view;
  const detail = run?.detail ?? null;
  const live = isLive(streamed?.status ?? "queued");
  // Finished runs: the stored result is authoritative for artifacts too.
  const stored = !live ? detail?.result?.artifacts : undefined;
  const view = useMemo(() => {
    const v = streamed ?? initialRun();
    return stored ? { ...v, artifacts: { ...v.artifacts, ...stored } } : v;
  }, [streamed, stored]);
  const row = detail ?? runs.find((r) => r.id === selected) ?? null;
  // Finished runs: the stored bugs know which generated test covers them.
  const bugs = !live && detail?.result?.bugs.length ? detail.result.bugs : view.bugs;

  useEffect(() => {
    document.title = row ? `${row.story.slice(0, 60)} · QAPilot` : "QAPilot — Autonomous QA Agent";
  }, [row]);

  // ---- actions ------------------------------------------------------------
  const start = async (body: NewRun) => {
    setStarting(true);
    setLaunchError(null);
    try {
      const created = await api.createRun(body);
      setRuns((prev) => [created, ...prev.filter((r) => r.id !== created.id)]);
      navigate(created.id);
    } catch (e) {
      setLaunchError(message(e));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!selected) return;
    setCancelling(true);
    try {
      await api.cancelRun(selected);
    } catch (e) {
      fail(e);
      setCancelling(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteRun(id);
      setRuns((prev) => prev.filter((r) => r.id !== id));
      if (id === selected) navigate(null);
    } catch (e) {
      fail(e);
    }
  };

  const openTest = (name: string) => {
    setFocusTest(name);
    setTab("tests");
  };

  // ---- auto-scroll --------------------------------------------------------
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [view.blocks, tab]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const tabs = useMemo(
    () => [
      { id: "live" as const, label: live ? "Live" : "Session", icon: <MonitorPlay className="size-3.5" /> },
      { id: "bugs" as const, label: "Bugs", count: bugs.length, icon: <BugIcon className="size-3.5" /> },
      { id: "tests" as const, label: "Tests", count: view.suite?.tests.length, icon: <FlaskConical className="size-3.5" /> },
      { id: "report" as const, label: "Report", icon: <FileText className="size-3.5" /> },
    ],
    [live, bugs.length, view.suite],
  );

  // ---- render -------------------------------------------------------------
  return (
    <div className="flex h-full bg-page text-ink">
      <Sidebar
        runs={runs}
        selected={selected}
        health={health}
        onNew={() => navigate(null)}
        onSelect={(id) => navigate(id)}
        onDelete={(id) => void remove(id)}
      />

      <main className="relative flex min-w-0 flex-1 flex-col">
        {!selected ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Launcher config={config} starting={starting} error={launchError} onStart={(b) => void start(b)} />
          </div>
        ) : !row || !run ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
            <Spinner className="size-4" /> Loading run…
          </div>
        ) : (
          <>
            <RunHeader
              row={row}
              view={view}
              cancelling={cancelling && live}
              onCancel={() => void cancel()}
              onDelete={() => {
                if (confirm("Delete this run and its recordings?")) void remove(row.id);
              }}
            />
            <div className="border-b border-line px-4">
              <Tabs tabs={tabs} value={tab} onChange={setTab} />
            </div>

            {tab === "live" ? (
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
                <div ref={scroller} onScroll={onScroll} className="min-w-0 flex-1 px-5 py-4 lg:overflow-y-auto">
                  <Timeline runId={row.id} view={view} onFrame={setPinned} onOpenBugs={() => setTab("bugs")} />
                </div>
                <aside className="shrink-0 border-t border-line p-4 lg:w-[44%] lg:max-w-[48rem] lg:border-t-0 lg:border-l">
                  <BrowserPane runId={row.id} view={view} pinned={pinned} onPin={setPinned} />
                </aside>
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {tab === "bugs" && (
                  <BugList
                    bugs={bugs}
                    runId={row.id}
                    baseUrl={row.target_url}
                    verifying={live && view.verifyEnabled}
                    live={live}
                    onOpenTest={openTest}
                  />
                )}
                {tab === "tests" && <TestsView runId={row.id} view={view} focusTest={focusTest} />}
                {tab === "report" && <ReportView runId={row.id} view={view} />}
              </div>
            )}
          </>
        )}

        {toast && (
          <div
            role="alert"
            className="absolute top-4 left-1/2 z-40 flex max-w-lg -translate-x-1/2 items-start gap-2 rounded-lg border border-critical/40 bg-surface-2 px-3 py-2 text-sm text-ink shadow-xl"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-critical" />
            <span className="min-w-0 flex-1">{toast}</span>
            <button type="button" onClick={() => setToast(null)} className="text-muted hover:text-ink" aria-label="Dismiss">
              <X className="size-4" />
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
