import { useEffect, useRef, useState } from "react";
import ReferenceImage from "./ReferenceImage";
import Generations from "./Generations";

type Project = {
  id: number;
  name: string;
  initial_image_path: string | null;
  created_at: string;
  updated_at: string;
  generation_count: number;
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export default function App() {
  const [status, setStatus] = useState("接続を確認しています…");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selectionRequest = useRef(0);

  useEffect(() => {
    const events = new EventSource("/api/events");
    const controller = new AbortController();
    request<{ status: string }>("/api/health", { signal: controller.signal })
      .then((data) => {
        if (data.status !== "ok") throw new Error("Unexpected health response");
        setStatus("APIに接続しました");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.error("API connection failed", error);
          setStatus("APIに接続できません。起動状態を確認してください。");
        }
      });
    request<Project[]>("/api/projects", { signal: controller.signal })
      .then(setProjects)
      .catch(() => {
        if (!controller.signal.aborted)
          setError("プロジェクト一覧を取得できません。");
      });
    return () => {
      events.close();
      controller.abort();
    };
  }, []);

  async function createProject(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    const version = ++selectionRequest.current;
    try {
      const project = await request<Project>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      setProjects((previous) => [project, ...previous]);
      setName("");
      if (version === selectionRequest.current) setSelected(project);
    } catch {
      setError(
        "プロジェクトを作成できません。接続を確認して再試行してください。",
      );
    } finally {
      setBusy(false);
    }
  }

  async function openProject(id: number) {
    const version = ++selectionRequest.current;
    setSelected(null);
    setError("");
    try {
      const project = await request<Project>(`/api/projects/${id}`);
      if (version === selectionRequest.current) setSelected(project);
    } catch {
      if (version === selectionRequest.current)
        setError("プロジェクトを開けません。一覧から選び直してください。");
    }
  }

  return (
    <main>
      <p className="eyebrow">画像を選ぶだけで、次の画像が生まれる。</p>
      <h1>LoopImageGenerator V2</h1>
      <p>参考画像から、好き・嫌いを選んで画像を探索するローカルアプリ。</p>
      <p role="status">{status}</p>
      <section aria-labelledby="create-title">
        <h2 id="create-title">新規プロジェクト</h2>
        <form onSubmit={createProject}>
          <label htmlFor="project-name">プロジェクト名</label>
          <input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            required
            disabled={busy}
          />
          <button type="submit" disabled={busy || !name.trim()}>
            {busy ? "作成中…" : "作成する"}
          </button>
        </form>
      </section>
      {error && <p role="alert">{error}</p>}
      <section aria-labelledby="list-title">
        <h2 id="list-title">プロジェクトを選んで再開</h2>
        {projects.length === 0 ? (
          <p className="note">プロジェクトはまだありません。</p>
        ) : (
          <ul className="projects">
            {projects.map((project) => (
              <li key={project.id}>
                <button
                  onClick={() => void openProject(project.id)}
                  aria-pressed={selected?.id === project.id}
                >
                  {project.name}（#{project.id}）を開く
                </button>
                <span>
                  {project.generation_count}世代 · 更新{" "}
                  {new Date(project.updated_at).toLocaleString("ja-JP")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {selected && (
        <section aria-labelledby="selected-title" className="selected">
          <h2 id="selected-title">{selected.name}</h2>
          <p>
            プロジェクト #{selected.id} · 保存済み {selected.generation_count}
            世代
          </p>
          <p>
            {selected.initial_image_path
              ? "参考画像は登録済みです。"
              : "参考画像はまだ登録されていません。"}
          </p>
          <ReferenceImage
            key={selected.id}
            projectId={selected.id}
            registered={Boolean(selected.initial_image_path)}
            onSaved={(value) => {
              const project = value as Project;
              setProjects((previous) =>
                previous.map((item) =>
                  item.id === project.id ? project : item,
                ),
              );
              setSelected((previous) =>
                previous?.id === project.id ? project : previous,
              );
            }}
          />
          <Generations
            key={`generations-${selected.id}`}
            projectId={selected.id}
            registered={Boolean(selected.initial_image_path)}
            onCompleted={() => {
              const id = selected.id;
              void request<Project>(`/api/projects/${id}`)
                .then((project) => {
                  setProjects((previous) =>
                    previous.map((item) => (item.id === id ? project : item)),
                  );
                  setSelected((previous) =>
                    previous?.id === id ? project : previous,
                  );
                })
                .catch(() => setError("プロジェクト情報を更新できません。"));
            }}
          />
        </section>
      )}
    </main>
  );
}
