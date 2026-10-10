import { useEffect, useLayoutEffect, useRef, useState } from "react";

type Generation = {
  id: number;
  parent_id: number | null;
  selection: { liked: number[]; disliked: number[] } | null;
  parameters: { width?: number; height?: number };
  images: { id: number; position: number; url: string }[];
};
type Rating = "liked" | "disliked";

function Candidates({
  generation,
  busy,
  snapshot,
  onGenerate,
}: {
  generation: Generation;
  snapshot?: Generation;
  busy: boolean;
  onGenerate: (
    parentId: number,
    selection: { liked: number[]; disliked: number[] },
  ) => void;
}) {
  const [ratings, setRatings] = useState<Record<number, Rating>>(() =>
    Object.fromEntries([
      ...(snapshot?.selection?.liked ?? []).map((id) => [id, "liked"]),
      ...(snapshot?.selection?.disliked ?? []).map((id) => [id, "disliked"]),
    ]),
  );
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
      <h3>Generation #{generation.id}</h3>
      <p className="note">
        {generation.parent_id
          ? `親 Generation #${generation.parent_id}`
          : "参考画像から生成"}
        {snapshot
          ? ` · Generation #${snapshot.id}を生成した評価を表示（変更して新しい枝を作れます）`
          : " · この世代から次の候補を生成できます"}
      </p>
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
  const history = useRef<HTMLDivElement>(null);
  const scrollRestore = useRef<{
    id?: string;
    top: number;
    y: number;
    bottom: boolean;
  } | null>(null);
  function rememberScroll(follow = false) {
    const cards = Array.from(
      history.current?.querySelectorAll<HTMLElement>("[data-generation]") ?? [],
    );
    const anchor = cards.find(
      (card) => card.getBoundingClientRect().bottom > 0,
    );
    scrollRestore.current = {
      id: anchor?.dataset.generation,
      top: anchor?.getBoundingClientRect().top ?? 0,
      y: window.scrollY,
      bottom:
        follow &&
        document.documentElement.scrollHeight -
          window.innerHeight -
          window.scrollY <
          100,
    };
  }
  useLayoutEffect(() => {
    const saved = scrollRestore.current;
    if (!saved) return;
    scrollRestore.current = null;
    const anchor = Array.from(
      history.current?.querySelectorAll<HTMLElement>("[data-generation]") ?? [],
    ).find((card) => card.dataset.generation === saved.id);
    window.scrollTo(
      0,
      saved.bottom
        ? document.documentElement.scrollHeight
        : anchor
          ? window.scrollY + anchor.getBoundingClientRect().top - saved.top
          : saved.y,
    );
  }, [selected, generations]);
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
      if (response.status === 409) {
        // A reload or another tab can leave an existing request running on the server.
        let running = true;
        while (running && alive.current) {
          const status = await fetch(
            `/api/projects/${projectId}/generation-status`,
          );
          if (!status.ok) throw new Error("Status retrieval failed");
          running = ((await status.json()) as { running: boolean }).running;
          if (running)
            await new Promise((resolve) => setTimeout(resolve, 1000));
        }
        if (alive.current) setRetry((value) => value + 1);
        return;
      }
      if (!response.ok) throw new Error("Generation failed");
      const completed = (await response.json()) as { id: number };
      if (!alive.current) return;
      const list = await fetch(`/api/projects/${projectId}/generations`);
      if (!list.ok) throw new Error("Retrieval failed");
      const data = (await list.json()) as Generation[];
      if (!alive.current) return;
      rememberScroll(true);
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
    let timer: ReturnType<typeof setTimeout>;
    async function pollStatus() {
      try {
        const response = await fetch(
          `/api/projects/${projectId}/generation-status`,
          {
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error("Status retrieval failed");
        const status = (await response.json()) as { running: boolean };
        if (controller.signal.aborted) return;
        if (status.running) timer = setTimeout(pollStatus, 1000);
        else setRetry((value) => value + 1);
      } catch {
        if (!controller.signal.aborted) {
          setBusy(false);
          setError("生成状況を取得できません。保存結果を再読込してください。");
        }
      }
    }
    setState("loading");
    fetch(`/api/projects/${projectId}/generations`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Generation retrieval failed");
        const running =
          response.headers?.get("X-Generation-Running") === "true";
        if (!controller.signal.aborted) {
          setBusy(running);
          if (running) timer = setTimeout(pollStatus, 1000);
        }
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
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [projectId, retry]);
  const generation = generations.find((item) => item.id === selected);
  const byId = new Map(generations.map((item) => [item.id, item]));
  const children = new Map<number, Generation[]>();
  for (const item of generations) {
    if (item.parent_id !== null) {
      const siblings = children.get(item.parent_id) ?? [];
      siblings.push(item);
      children.set(item.parent_id, siblings);
    }
  }
  const path: Generation[] = [];
  const visited = new Set<number>();
  let cursor = generation;
  while (cursor && !visited.has(cursor.id)) {
    visited.add(cursor.id);
    path.push(cursor);
    cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
  }
  path.reverse();
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
            onChange={(event) => {
              rememberScroll();
              setSelected(Number(event.target.value));
            }}
          >
            {generations.map((item) => (
              <option key={item.id} value={item.id}>
                Generation #{item.id}（{item.images.length}枚・
                {item.parent_id ? `親 #${item.parent_id}` : "最初の世代"}）
              </option>
            ))}
          </select>
          <p className="note">
            表示中の経路: {path.map((item) => `#${item.id}`).join(" → ")} ·
            過去の世代で評価を確定すると新しい枝を作成します。
          </p>
          <div ref={history} className="generation-history">
            {path.map((item, index) => (
              <div key={item.id} data-generation={item.id}>
                <Candidates
                  key={`${item.id}-${path[index + 1]?.id ?? "leaf"}`}
                  generation={item}
                  snapshot={path[index + 1]}
                  busy={busy}
                  onGenerate={(id, selection) => void generate(id, selection)}
                />
                {children.has(item.id) && (
                  <nav aria-label={`Generation #${item.id}の子世代`}>
                    {children.get(item.id)!.map((child) => (
                      <button
                        key={child.id}
                        disabled={busy}
                        aria-pressed={path[index + 1]?.id === child.id}
                        onClick={() => {
                          rememberScroll();
                          setSelected(child.id);
                        }}
                      >
                        枝 #{child.id}を開く
                      </button>
                    ))}
                  </nav>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
