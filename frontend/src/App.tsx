import { useEffect, useRef, useState } from "react";
import HomePage from "./HomePage";
import ProjectPage from "./ProjectPage";
import SettingsPage from "./SettingsPage";
import CreateProjectPage from "./CreateProjectPage";
import type { ProjectConfig } from "./appOptions";

export type Project = {
  id: number;
  name: string;
  initial_image_path: string | null;
  created_at: string;
  updated_at: string;
  generation_count: number;
  generation_config?: ProjectConfig | null;
};
type Route =
  | { page: "home" | "settings" | "create" }
  | { page: "project"; id: number };
function readRoute(): Route {
  if (window.location.hash === "#/projects/new") return { page: "create" };
  if (window.location.hash === "#/settings") return { page: "settings" };
  const match = /^#\/projects\/([1-9]\d*)$/.exec(window.location.hash);
  if (match && Number.isSafeInteger(Number(match[1])))
    return { page: "project", id: Number(match[1]) };
  return { page: "home" };
}
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);
  const [status, setStatus] = useState("接続を確認しています…");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [breadcrumbHost, setBreadcrumbHost] = useState<HTMLDivElement | null>(
    null,
  );
  const mutating = useRef(false);
  const selectionRequest = useRef(0);

  function navigate(hash: string) {
    window.history.pushState(null, "", hash);
    setRoute(readRoute());
    setSelected(null);
    setError("");
  }
  useEffect(() => {
    const sync = () => {
      setRoute(readRoute());
      setSelected(null);
      setError("");
    };
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  useEffect(() => {
    const events = new EventSource("/api/events");
    const controller = new AbortController();
    let streamFailed = false;
    events.onopen = () => {
      streamFailed = false;
      setStatus("APIに接続しました");
    };
    events.onerror = () => {
      streamFailed = true;
      setStatus("APIとの接続が切れました。再接続を試みています。");
    };
    request<{ status: string }>("/api/health", { signal: controller.signal })
      .then((data) => {
        if (data.status !== "ok") throw new Error("Unexpected health response");
        if (!controller.signal.aborted && !streamFailed)
          setStatus("APIに接続しました");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.error("API connection failed", error);
          setStatus("APIに接続できません。起動状態を確認してください。");
        }
      });
    return () => {
      events.onopen = null;
      events.onerror = null;
      events.close();
      controller.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const version = ++selectionRequest.current;
    if (route.page === "home") {
      request<Project[]>("/api/projects", { signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted) setProjects(data);
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setError("プロジェクト一覧を取得できません。");
        });
    } else if (route.page === "project") {
      request<Project>(`/api/projects/${route.id}`, {
        signal: controller.signal,
      })
        .then((project) => {
          if (
            version === selectionRequest.current &&
            !controller.signal.aborted
          )
            setSelected(project);
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setError("プロジェクトを開けません。一覧から選び直してください。");
        });
    }
    return () => controller.abort();
  }, [route]);

  async function createProject(name: string, config: ProjectConfig) {
    if (mutating.current) return;
    mutating.current = true;
    setBusy(true);
    setError("");
    const version = selectionRequest.current;
    try {
      const project = await request<Project>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, generation_config: config }),
      });
      setProjects((previous) => [project, ...previous]);
      if (version === selectionRequest.current)
        navigate(`#/projects/${project.id}`);
    } catch {
      setError(
        "プロジェクトを作成できません。接続を確認して再試行してください。",
      );
    } finally {
      mutating.current = false;
      setBusy(false);
    }
  }

  async function deleteProject(project: Project) {
    if (
      mutating.current ||
      !window.confirm(
        `「${project.name}」とすべての世代・画像を削除しますか？この操作は取り消せません。`,
      )
    )
      return;
    mutating.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/projects/${project.id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setProjects((previous) =>
        previous.filter((item) => item.id !== project.id),
      );
    } catch {
      setError(
        "プロジェクトを削除できません。生成中の場合は完了後に再試行してください。",
      );
    } finally {
      mutating.current = false;
      setBusy(false);
    }
  }

  function updateProject(project: Project) {
    setProjects((previous) =>
      previous.map((item) => (item.id === project.id ? project : item)),
    );
    setSelected((previous) =>
      previous?.id === project.id ? project : previous,
    );
  }

  return (
    <main>
      <header className="app-header">
        <h1>
          <a
            href="#/"
            onClick={(event) => {
              event.preventDefault();
              navigate("#/");
            }}
          >
            LoopImageGenerator V2
          </a>
        </h1>
        <div className="header-actions">
          <div
            className="api-indicator-wrapper"
            tabIndex={0}
            aria-describedby="api-details"
          >
            <span
              role="status"
              className="api-indicator"
              data-state={
                status === "APIに接続しました"
                  ? "connected"
                  : status === "接続を確認しています…"
                    ? "checking"
                    : "disconnected"
              }
              aria-label={status}
            >
              <span aria-hidden="true">API:</span>
              <span className="api-dot" aria-hidden="true" />
            </span>
            <span id="api-details" className="api-tooltip" role="tooltip">
              {status}
            </span>
          </div>
          <a
            href="#/settings"
            className="settings-link"
            aria-label="設定"
            title="設定"
            aria-current={route.page === "settings" ? "page" : undefined}
            onClick={(event) => {
              event.preventDefault();
              navigate("#/settings");
            }}
          >
            <svg
              viewBox="0 0 24 24"
              width="24"
              height="24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <path
                d="M9 3h6l.6 3 2.4 1.4 2.9-.9 3 5.2-2.3 2.1v2.8l2.3 2.1-3 5.2-2.9-.9-2.4 1.4-.6 3H9l-.6-3L6 21l-2.9.9-3-5.2 2.3-2.1v-2.8L.1 9.7l3-5.2 2.9.9L8.4 4z"
                transform="translate(2 1) scale(.8)"
              />
              <circle cx="12" cy="12" r="3.5" />
            </svg>
          </a>
        </div>
        <div className="header-breadcrumbs" ref={setBreadcrumbHost} />
      </header>
      {error && <p role="alert">{error}</p>}
      {route.page === "home" && (
        <HomePage
          projects={projects}
          busy={busy}
          onNew={() => navigate("#/projects/new")}
          onOpen={(id) => navigate(`#/projects/${id}`)}
          onDelete={(project) => void deleteProject(project)}
        />
      )}
      {route.page === "create" && (
        <CreateProjectPage busy={busy} onCreate={createProject} />
      )}
      {route.page === "settings" && <SettingsPage />}
      {route.page === "project" &&
        (selected ? (
          <ProjectPage
            key={selected.id}
            project={selected}
            breadcrumbHost={breadcrumbHost}
            onSaved={updateProject}
            onCompleted={() => {
              void request<Project>(`/api/projects/${selected.id}`)
                .then(updateProject)
                .catch(() => setError("プロジェクト情報を更新できません。"));
            }}
          />
        ) : (
          !error && <p>プロジェクトを読み込んでいます…</p>
        ))}
    </main>
  );
}
