import { useCallback, useRef, useState } from "react";

export interface GenOptions {
  scale: number;
  density: number;
}

interface Props {
  onFile: (file: File, opts: GenOptions) => void;
  busy: boolean;
}

const ACCEPT = "image/*,.heic";

type Quality = "light" | "standard" | "fine";

// 质量预设 → 保留比例（density）。原生约 120 万高斯只能裁剪减少。
const PRESET_DENSITY: Record<Quality, number> = {
  light: 0.25,
  standard: 0.6,
  fine: 1,
};

const QUALITY_LABELS: { key: Quality; label: string }[] = [
  { key: "light", label: "精简" },
  { key: "standard", label: "标准" },
  { key: "fine", label: "精细" },
];

export default function Uploader({ onFile, busy }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [quality, setQuality] = useState<Quality>("fine");
  const [scale, setScale] = useState(1);

  const pick = () => {
    if (!busy) inputRef.current?.click();
  };

  const handleFiles = (files: FileList | null) => {
    if (busy) return;
    const f = files?.[0];
    if (f) onFile(f, { scale, density: PRESET_DENSITY[quality] });
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (busy) return;
      handleFiles(e.dataTransfer.files);
    },
    [busy, quality, scale],
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

      <div className="gen-controls">
        <div className="control-row">
          <span className="label">泼溅数量</span>
          <div className="segmented" role="group" aria-label="泼溅数量">
            {QUALITY_LABELS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className={`seg${quality === key ? " active" : ""}`}
                onClick={() => setQuality(key)}
                disabled={busy}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="control-row">
          <span className="label">尺寸比例</span>
          <span className="label">{scale.toFixed(2)}×</span>
        </div>
        <input
          type="range"
          className="scale-slider"
          min={0.5}
          max={2}
          step={0.05}
          value={scale}
          onChange={(e) => setScale(Number(e.target.value))}
          disabled={busy}
          aria-label="尺寸比例"
        />
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
