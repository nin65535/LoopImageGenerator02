import type { Project } from "./App";

export default function HomePage({
  projects,
  busy,
  onNew,
  onOpen,
  onDelete,
}: {
  projects: Project[];
  busy: boolean;
  onNew: () => void;
  onOpen: (id: number) => void;
  onDelete: (project: Project) => void;
}) {
  return (
    <>
      <a
        className="new-project-link"
        href="#/projects/new"
        onClick={(event) => {
          event.preventDefault();
          onNew();
        }}
      >
        <span aria-hidden="true">＋</span>
        新規プロジェクト
      </a>
      <section aria-labelledby="list-title">
        <h2 id="list-title">プロジェクトを選んで再開</h2>
        {projects.length === 0 ? (
          <p className="note">プロジェクトはまだありません。</p>
        ) : (
          <ul className="projects">
            {projects.map((project) => (
              <li key={project.id}>
                <button onClick={() => onOpen(project.id)}>
                  {project.name}（#{project.id}）を開く
                </button>
                <span>
                  {project.generation_count}世代 · 更新{" "}
                  {new Date(project.updated_at).toLocaleString("ja-JP")}
                </span>
                <button
                  className="delete-project"
                  disabled={busy}
                  aria-label={`${project.name}（#${project.id}）を削除`}
                  onClick={() => onDelete(project)}
                >
                  削除
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
