import { useEffect, useState } from "react";

export default function App() {
  const [status, setStatus] = useState("接続を確認しています…");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: unknown = await response.json();
        if (
          typeof data !== "object" ||
          data === null ||
          !("status" in data) ||
          data.status !== "ok"
        ) {
          throw new Error("Unexpected health response");
        }
        setStatus("APIに接続しました");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.error("API connection failed", error);
          setStatus("APIに接続できません。起動状態を確認してください。");
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <p className="eyebrow">画像を選ぶだけで、次の画像が生まれる。</p>
      <h1>LoopImageGenerator V2</h1>
      <p>参考画像から、好き・嫌いを選んで画像を探索するローカルアプリ。</p>
      <p role="status">{status}</p>
      <p className="note">画像探索の機能は今後の工程で追加します。</p>
    </main>
  );
}
