import { summaryLine } from "../lib/paramMeta";
import type { Generation } from "../lib/types";

interface Props {
  items: Generation[];
  activeId: string | null;
  onSelect: (g: Generation) => void;
  onDelete: (g: Generation) => void;
}

export default function Gallery({ items, activeId, onSelect, onDelete }: Props) {
  if (items.length === 0) {
    return <div className="gallery-empty label">暂无历史 · 上传照片后出现在此</div>;
  }
  return (
    <div className="gallery">
      {items.map((g) => (
        // 删除键是 .thumb 的兄弟而非子元素：button 套 button 是非法 HTML，浏览器会拆掉 DOM。
        <div key={g.id} className="thumb-wrap">
          <button
            type="button"
            className={`thumb${g.id === activeId ? " active" : ""}`}
            onClick={() => onSelect(g)}
            title={summaryLine(g)}
          >
            <img src={g.thumbUrl} alt={g.originalFilename} loading="lazy" />
            {g.numPoints != null && (
              <span className="thumb-meta label">{(g.numPoints / 1e6).toFixed(1)}M</span>
            )}
          </button>
          <button
            type="button"
            className="thumb-del"
            onClick={() => onDelete(g)}
            title="删除这条记录"
            aria-label={`删除 ${g.originalFilename}`}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
