import { useState } from "react";
import { useAppOptions, type ProjectConfig } from "./appOptions";
export default function CreateProjectPage({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (name: string, config: ProjectConfig) => Promise<void>;
}) {
  const { options, models, error, reload } = useAppOptions();
  const [name, setName] = useState("");
  const [checkpoint, setCheckpoint] = useState("");
  const [size, setSize] = useState("");
  const allowed = (options?.model_whitelist ?? []).filter((model) =>
    models.includes(model),
  );
  const sizes = options ? [...options.fixed_sizes, ...options.extra_sizes] : [];
  const chosenModel = allowed.includes(checkpoint)
    ? checkpoint
    : (allowed[0] ?? "");
  const chosenSize =
    sizes.find((item) => `${item.width}x${item.height}` === size) ?? sizes[0];
  return (
    <section aria-labelledby="create-title">
      <h2 id="create-title">新規プロジェクト</h2>
      {error && (
        <>
          <p role="alert">{error}</p>
          <button onClick={reload}>再試行</button>
        </>
      )}
      {!options && !error && <p>設定を読み込んでいます…</p>}
      {options && (
        <form
          className="project-create-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && name.trim() && chosenModel && chosenSize)
              void onCreate(name.trim(), {
                checkpoint: chosenModel,
                ...chosenSize,
              });
          }}
        >
          <label htmlFor="project-name">プロジェクト名</label>
          <input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            required
            disabled={busy}
          />
          <label htmlFor="project-model">モデル</label>
          <select
            id="project-model"
            value={chosenModel}
            onChange={(event) => setCheckpoint(event.target.value)}
            disabled={busy || !allowed.length}
          >
            {!allowed.length && (
              <option value="">利用可能なモデルがありません</option>
            )}
            {allowed.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
          {!allowed.length && (
            <p role="alert">
              設定ページでモデルのホワイトリストを登録してください。
            </p>
          )}
          <label htmlFor="project-size">画像サイズ</label>
          <select
            id="project-size"
            value={chosenSize ? `${chosenSize.width}x${chosenSize.height}` : ""}
            onChange={(event) => setSize(event.target.value)}
            disabled={busy}
          >
            {sizes.map((item) => (
              <option
                key={`${item.width}x${item.height}`}
                value={`${item.width}x${item.height}`}
              >
                {item.width} × {item.height}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy || !name.trim() || !chosenModel || !chosenSize}
          >
            {busy ? "作成中…" : "作成する"}
          </button>
        </form>
      )}
    </section>
  );
}
