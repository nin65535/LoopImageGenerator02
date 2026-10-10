import { useRef, useState } from "react";

export default function ReferenceImage({
  projectId,
  registered,
  onSaved,
}: {
  projectId: number;
  registered: boolean;
  onSaved: (project: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const uploading = useRef(false);

  async function upload(files: FileList | null) {
    if (uploading.current || registered) return;
    setError("");
    if (!files || files.length !== 1) {
      setError("参考画像を1枚選んでください。");
      return;
    }
    const file = files[0];
    if (!file.size || file.size > 20 * 1024 * 1024) {
      setError("空でない20MiB以下の画像を選んでください。");
      return;
    }
    uploading.current = true;
    setBusy(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/initial-image`, {
        method: "PUT",
        body: file,
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "画像を保存できません。",
        );
      onSaved(result);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "画像を保存できません。再試行してください。",
      );
    } finally {
      uploading.current = false;
      setBusy(false);
    }
  }

  if (registered)
    return (
      <img
        className="reference-image"
        src={`/api/projects/${projectId}/initial-image`}
        alt="初期参考画像"
      />
    );

  return (
    <div
      className="image-drop"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        void upload(event.dataTransfer.files);
      }}
    >
      <p>参考画像をここにドロップ、またはファイルを選択してください。</p>
      <p className="note">PNG・JPEG・WebPの静止画像 / 最大20MiB・2,500万画素</p>
      <label htmlFor={`reference-${projectId}`}>参考画像を選択</label>{" "}
      <input
        id={`reference-${projectId}`}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        disabled={busy}
        onChange={(event) => {
          void upload(event.target.files);
          event.target.value = "";
        }}
      />
      {busy && <p>画像を保存しています…</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
