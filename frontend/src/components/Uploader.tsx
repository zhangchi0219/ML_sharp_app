import { useCallback, useRef, useState } from "react";

interface Props {
  onFile: (file: File) => void;
  busy: boolean;
}

const ACCEPT = "image/*,.heic";

export default function Uploader({ onFile, busy }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = () => {
    if (!busy) inputRef.current?.click();
  };

  const handleFiles = (files: FileList | null) => {
    if (busy) return;
    const f = files?.[0];
    if (f) onFile(f);
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (busy) return;
      handleFiles(e.dataTransfer.files);
    },
    [busy],
  );

  return (
    <div className="uploader">
      <div
        className={`dropzone${dragging ? " dragging" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={pick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") pick();
        }}
      >
        <span className="label">{dragging ? "松开以上传" : "拖入照片 / 点击选择"}</span>
        <span className="dropzone-hint">JPG · PNG · WEBP · HEIC</span>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          handleFiles(e.target.files);
          e.currentTarget.value = ""; // 允许再次选择同一文件
        }}
      />
      <button className="cta" onClick={pick} disabled={busy}>
        {busy ? "生成中…" : "上传并生成"}
      </button>
    </div>
  );
}
