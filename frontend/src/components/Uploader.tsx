import { useCallback, useRef, useState } from "react";

interface Props {
  onFile: (file: File) => void;
  busy: boolean;
  disabled?: boolean;
}

const ACCEPT = "image/*,.heic";

/** 纯拖拽区 + 触发按钮。生成参数由 ParamPanel 负责（state 提在 App 里，重跑与回填都要读它）。 */
export default function Uploader({ onFile, busy, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = () => {
    if (!busy && !disabled) inputRef.current?.click();
  };

  const handleFiles = (files: FileList | null) => {
    if (busy || disabled) return;
    const f = files?.[0];
    if (f) onFile(f);
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (busy || disabled) return;
      handleFiles(e.dataTransfer.files);
    },
    [busy, disabled, onFile],
  );

  return (
    <div className="uploader">
      <div
        className={`dropzone${dragging ? " dragging" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy && !disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={pick}
        role="button"
        tabIndex={disabled || busy ? -1 : 0}
        aria-disabled={busy || disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
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
      <button className="cta" onClick={pick} disabled={busy || disabled}>
        {busy ? "生成中…" : "上传并生成"}
      </button>
    </div>
  );
}
