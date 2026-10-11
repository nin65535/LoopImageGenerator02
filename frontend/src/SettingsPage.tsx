import { useEffect, useState } from "react";
import { useAppOptions, type ImageSize } from "./appOptions";
export default function SettingsPage() {
  const { options, models, error, reload } = useAppOptions();
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [extraSizes, setExtraSizes] = useState<ImageSize[]>([]);
  const [width, setWidth] = useState("");
  const [height, setHeight] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (options) {
      setWhitelist(options.model_whitelist);
      setExtraSizes(options.extra_sizes);
    }
  }, [options]);
  async function save() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_whitelist: whitelist,
          extra_sizes: extraSizes,
        }),
      });
      if (!response.ok) throw new Error();
      setMessage("設定を保存しました。");
    } catch {
      setFailed(true);
      setMessage(
        "設定を保存できません。モデルの存在・サイズを確認して再試行してください。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="settings-title">
      <h2 id="settings-title">設定</h2>
      {error && (
        <>
          <p role="alert">{error}</p>
          <button onClick={reload}>再試行</button>
        </>
      )}
      {!options && !error && <p>設定を読み込んでいます…</p>}
      {options && (
        <>
          <fieldset disabled={busy} className="model-whitelist">
            <legend>モデルのホワイトリスト</legend>
            {[...new Set([...models, ...whitelist])].map((model) => (
              <label key={model}>
                <input
                  type="checkbox"
                  checked={whitelist.includes(model)}
                  onChange={(event) => {
                    setMessage("");
                    setWhitelist((previous) =>
                      event.target.checked
                        ? [...previous, model]
                        : previous.filter((item) => item !== model),
                    );
                  }}
                />
                {model}
                {!models.includes(model) && "（ファイルが見つかりません）"}
              </label>
            ))}
          </fieldset>
          <h3>画像サイズ</h3>
          <ul className="size-presets">
            {options.fixed_sizes.map((size) => (
              <li key={`${size.width}x${size.height}`}>
                {size.width} × {size.height}（固定）
              </li>
            ))}
            {extraSizes.map((size) => (
              <li key={`${size.width}x${size.height}`}>
                {size.width} × {size.height}{" "}
                <button
                  disabled={busy}
                  aria-label={`${size.width} × ${size.height}を削除`}
                  onClick={() => {
                    setMessage("");
                    setExtraSizes((previous) =>
                      previous.filter((item) => item !== size),
                    );
                  }}
                >
                  削除
                </button>
              </li>
            ))}
          </ul>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (busy) return;
              const w = Number(width),
                h = Number(height);
              if (
                !Number.isInteger(w) ||
                !Number.isInteger(h) ||
                w < 16 ||
                h < 16 ||
                w > 16384 ||
                h > 16384 ||
                w % 8 ||
                h % 8
              ) {
                setFailed(true);
                setMessage("幅・高さは16～16384の8の倍数にしてください。");
                return;
              }
              if (
                [...options.fixed_sizes, ...extraSizes].some(
                  (item) => item.width === w && item.height === h,
                )
              ) {
                setFailed(true);
                setMessage("画像サイズが重複しています。");
                return;
              }
              setExtraSizes((previous) => [
                ...previous,
                { width: w, height: h },
              ]);
              setWidth("");
              setHeight("");
              setMessage("");
            }}
          >
            <label htmlFor="size-width">幅</label>
            <input
              id="size-width"
              type="number"
              min={16}
              max={16384}
              step={8}
              required
              value={width}
              disabled={busy}
              onChange={(event) => setWidth(event.target.value)}
            />
            <label htmlFor="size-height">高さ</label>
            <input
              id="size-height"
              type="number"
              min={16}
              max={16384}
              step={8}
              required
              value={height}
              disabled={busy}
              onChange={(event) => setHeight(event.target.value)}
            />
            <button disabled={busy || extraSizes.length >= 100}>
              サイズを追加
            </button>
          </form>
          <button
            className="save-settings"
            disabled={busy}
            onClick={() => void save()}
          >
            {busy ? "保存中…" : "設定を保存"}
          </button>
        </>
      )}
      {message && <p role={failed ? "alert" : "status"}>{message}</p>}
    </section>
  );
}
