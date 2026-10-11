import { useEffect, useState } from "react";
export type ImageSize = { width: number; height: number };
export type AppOptions = {
  model_whitelist: string[];
  fixed_sizes: ImageSize[];
  extra_sizes: ImageSize[];
};
export type ProjectConfig = ImageSize & { checkpoint: string };
export function useAppOptions() {
  const [options, setOptions] = useState<AppOptions | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setOptions(null);
    setError("");
    Promise.all([
      fetch("/api/settings", { signal: controller.signal }),
      fetch("/api/settings/models", { signal: controller.signal }),
    ])
      .then(async ([settings, inventory]) => {
        if (!settings.ok || !inventory.ok) throw new Error();
        const [data, installed] = await Promise.all([
          settings.json(),
          inventory.json(),
        ]);
        if (!controller.signal.aborted) {
          setOptions(data);
          setModels(installed.models);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "設定・モデル一覧を取得できません。ComfyUIの起動状態を確認してください。",
          );
      });
    return () => controller.abort();
  }, [retry]);
  return {
    options,
    models,
    error,
    reload: () => setRetry((value) => value + 1),
  };
}
