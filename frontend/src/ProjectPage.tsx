import ReferenceImage from "./ReferenceImage";
import Generations from "./Generations";
import type { Project } from "./App";

export default function ProjectPage({
  project,
  onSaved,
  onCompleted,
  breadcrumbHost,
}: {
  project: Project;
  onSaved: (project: Project) => void;
  onCompleted: () => void;
  breadcrumbHost: HTMLElement | null;
}) {
  return (
    <section aria-labelledby="selected-title" className="selected">
      <h2 id="selected-title">{project.name}</h2>
      <p>
        プロジェクト #{project.id} · 保存済み {project.generation_count}世代
      </p>
      {project.generation_config && (
        <p>
          {project.generation_config.checkpoint} ·{" "}
          {project.generation_config.width} × {project.generation_config.height}
        </p>
      )}
      <p>
        {project.initial_image_path
          ? "参考画像は登録済みです。"
          : "参考画像はまだ登録されていません。"}
      </p>
      <ReferenceImage
        projectId={project.id}
        registered={Boolean(project.initial_image_path)}
        onSaved={(value) => onSaved(value as Project)}
      />
      <Generations
        projectId={project.id}
        registered={Boolean(project.initial_image_path)}
        onCompleted={onCompleted}
        breadcrumbHost={breadcrumbHost}
      />
    </section>
  );
}
