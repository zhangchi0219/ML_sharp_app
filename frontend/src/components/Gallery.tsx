import type { Generation } from "../lib/types";

interface Props {
  items: Generation[];
  activeId: string | null;
  onSelect: (g: Generation) => void;
}

export default function Gallery({ items, activeId, onSelect }: Props) {
  if (items.length === 0) {
    return <div className="gallery-empty label">暂无历史 · 上传照片后出现在此</div>;
  }
  return (
    <div className="gallery">
      {items.map((g) => (
        <button
          key={g.id}
          className={`thumb${g.id === activeId ? " active" : ""}`}
          onClick={() => onSelect(g)}
          title={`${g.originalFilename}${g.numPoints ? ` · ${g.numPoints.toLocaleString()} 高斯` : ""}`}
        >
          <img src={g.thumbUrl} alt={g.originalFilename} loading="lazy" />
          {g.numPoints != null && (
            <span className="thumb-meta label">{(g.numPoints / 1e6).toFixed(1)}M</span>
          )}
        </button>
      ))}
    </div>
  );
}
