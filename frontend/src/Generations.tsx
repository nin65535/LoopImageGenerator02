import { useEffect, useState } from "react";

type Generation = {
  id: number;
  parameters: { width?: number; height?: number };
  images: { id: number; position: number; url: string }[];
};
type Rating = "liked" | "disliked";

function Candidates({ generation }: { generation: Generation }) {
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
                aria-pressed={ratings[image.id] === "liked"}
                onClick={() => rate(image.id, "liked")}
              >
                好き
              </button>
              <button
                aria-pressed={ratings[image.id] === "disliked"}
                onClick={() => rate(image.id, "disliked")}
              >
                嫌い
              </button>
              <button
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
        好き・嫌いを最低1枚選んでください。同じ評価を再クリックすると解除できます。評価は保存されず、画面を閉じると解除されます。
      </p>
      <button
        onClick={() =>
          setMessage(
            liked + disliked
              ? "評価を確認しました。評価はまだ保存されていません。"
              : "好き・嫌いを最低1枚選んでください。",
          )
        }
      >
        評価を確認
      </button>
      {message && <p role={liked + disliked ? "status" : "alert"}>{message}</p>}
    </section>
  );
}

export default function Generations({ projectId }: { projectId: number }) {
  const [generations, setGenerations] = useState<Generation[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [state, setState] = useState("loading");
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
      {state === "loading" ? (
        <p>候補画像を読み込んでいます…</p>
      ) : state === "error" ? (
        <>
          <p role="alert">候補画像を取得できません。</p>
          <button onClick={() => setRetry((value) => value + 1)}>再試行</button>
        </>
      ) : !generation ? (
        <p>保存済みのGenerationはまだありません。</p>
      ) : (
        <>
          <label htmlFor="generation-choice">表示するGeneration</label>{" "}
          <select
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
          <Candidates key={generation.id} generation={generation} />
        </>
      )}
    </section>
  );
}
