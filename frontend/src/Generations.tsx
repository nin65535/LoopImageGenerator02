import { useEffect, useRef, useState } from "react";

type Generation = {
  id: number;
  parameters: { width?: number; height?: number };
  images: { id: number; position: number; url: string }[];
};
type Rating = "liked" | "disliked";

function Candidates({
  generation,
  busy,
  onGenerate,
}: {
  generation: Generation;
  busy: boolean;
  onGenerate: (
    parentId: number,
    selection: { liked: number[]; disliked: number[] },
  ) => void;
}) {
  const [ratings, setRatings] = useState<Record<number, Rating>>({});
  const [message, setMessage] = useState("");
  const liked = Object.values(ratings).filter(
    (value) => value === "liked",
  ).length;
  const disliked = Object.values(ratings).filter(
    (value) => value === "disliked",
  ).length;

  function rate(id: number, rating?: Rating) {
    setRatings((previous) => {
      const next = { ...previous };
      if (!rating || previous[id] === rating) delete next[id];
      else next[id] = rating;
      return next;
    });
    setMessage("");
  }

  return (
    <section aria-label={`Generation #${generation.id}の画像評価`}>
      <p>
        好き {liked}枚 · 嫌い {disliked}枚 · 未評価{" "}
        {generation.images.length - liked - disliked}枚
      </p>
      <div className="candidate-grid">
        {generation.images.map((image) => (
          <article
            className="candidate"
            data-rating={ratings[image.id] ?? "unrated"}
            key={image.id}
            aria-label={`画像 ${image.position + 1}`}
          >
            <img
              src={image.url}
              alt={`候補画像 ${image.position + 1}`}
              loading="lazy"
              style={{
                aspectRatio:
                  generation.parameters.width && generation.parameters.height
                    ? `${generation.parameters.width} / ${generation.parameters.height}`
                    : undefined,
              }}
            />
            <p>
              画像 {image.position + 1} ·{" "}
              {ratings[image.id] === "liked"
                ? "好き"
                : ratings[image.id] === "disliked"
                  ? "嫌い"
                  : "未評価"}
            </p>
            <div className="rating-buttons">
              <button
                disabled={busy}
                aria-pressed={ratings[image.id] === "liked"}
                onClick={() => rate(image.id, "liked")}
              >
                好き
              </button>
              <button
                disabled={busy}
                aria-pressed={ratings[image.id] === "disliked"}
                onClick={() => rate(image.id, "disliked")}
              >
                嫌い
              </button>
              <button
                disabled={busy}
                aria-pressed={!ratings[image.id]}
                onClick={() => rate(image.id)}
              >
                未評価
              </button>
            </div>
          </article>
        ))}
      </div>
      <p className="note">
        好き・嫌いを最低1枚選んでください。同じ評価を再クリックすると解除できます。未確定の評価は画面を閉じると解除されます。確定した評価は子世代に保存されます。
      </p>
      <button
        disabled={busy}
        onClick={() => {
          if (!liked && !disliked) {
            setMessage("好き・嫌いを最低1枚選んでください。");
            return;
          }
          onGenerate(generation.id, {
            liked: generation.images
              .filter((image) => ratings[image.id] === "liked")
              .map((image) => image.id),
            disliked: generation.images
              .filter((image) => ratings[image.id] === "disliked")
              .map((image) => image.id),
          });
        }}
      >
        評価を確定して次世代を生成
      </button>
      {message && <p role={liked + disliked ? "status" : "alert"}>{message}</p>}
    </section>
  );
}

export default function Generations({
  projectId,
  registered = false,
  onCompleted,
}: {
  projectId: number;
  registered?: boolean;
  onCompleted?: () => void;
}) {
  const [generations, setGenerations] = useState<Generation[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [state, setState] = useState("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const alive = useRef(true);
  const added = useRef<number[]>([]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function generate(
    parentId?: number,
    selection?: { liked: number[]; disliked: number[] },
  ) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/projects/${projectId}/generations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parent_id: parentId ?? null,
          selection: selection ?? null,
        }),
      });
      if (!response.ok) throw new Error("Generation failed");
      const completed = (await response.json()) as { id: number };
      if (!alive.current) return;
      const list = await fetch(`/api/projects/${projectId}/generations`);
      if (!list.ok) throw new Error("Retrieval failed");
      const data = (await list.json()) as Generation[];
      if (!alive.current) return;
      if (parentId && !added.current.includes(parentId))
        added.current.push(parentId);
      added.current.push(completed.id);
      setGenerations(data);
      setSelected(completed.id);
      onCompleted?.();
    } catch {
      if (alive.current)
        setError(
          "生成または結果取得に失敗しました。ComfyUIの状態を確認してください。保存済みの結果は再読込で確認できます。",
        );
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    fetch(`/api/projects/${projectId}/generations`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Generation retrieval failed");
        return response.json() as Promise<Generation[]>;
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        setGenerations(data);
        setSelected(data.at(-1)?.id ?? null);
        setState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => controller.abort();
  }, [projectId, retry]);
  const generation = generations.find((item) => item.id === selected);
  return (
    <section aria-labelledby="generations-title">
      <h2 id="generations-title">候補画像を評価</h2>
      {busy && (
        <p role="status">画像生成・タグ付け中です…完了後に保存します。</p>
      )}
      {error && (
        <>
          <p role="alert">{error}</p>
          <button
            disabled={busy}
            onClick={() => setRetry((value) => value + 1)}
          >
            保存結果を再読込
          </button>
        </>
      )}
      {state === "loading" ? (
        <p>候補画像を読み込んでいます…</p>
      ) : state === "error" ? (
        <>
          <p role="alert">候補画像を取得できません。</p>
          <button onClick={() => setRetry((value) => value + 1)}>再試行</button>
        </>
      ) : !generation ? (
        <>
          <p>保存済みのGenerationはまだありません。</p>
          <button
            disabled={busy || !registered}
            onClick={() => void generate()}
          >
            参考画像から候補を生成
          </button>
        </>
      ) : (
        <>
          <label htmlFor="generation-choice">表示するGeneration</label>{" "}
          <select
            disabled={busy}
            id="generation-choice"
            value={selected ?? ""}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {generations.map((item) => (
              <option key={item.id} value={item.id}>
                Generation #{item.id}（{item.images.length}枚）
              </option>
            ))}
          </select>
          {generations
            .filter(
              (item) =>
                item.id === generation.id || added.current.includes(item.id),
            )
            .map((item) => (
              <Candidates
                key={item.id}
                generation={item}
                busy={busy}
                onGenerate={(id, selection) => void generate(id, selection)}
              />
            ))}
        </>
      )}
    </section>
  );
}
