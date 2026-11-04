import { formatPoints, paramRows } from "../lib/paramMeta";
import type { Generation } from "../lib/types";

interface Props {
  item: Generation;
}

/** 后端 created_at 是 UTC aware，isoformat 带 +00:00，Date 能正确解析成本地时间。 */
function formatTime(iso: string): string {
  const d = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * 选中记录的只读参数卡：这次生成到底用了什么。
 * 同一张图重跑多次时，画廊里的缩略图完全一样，这块是唯一能区分它们的地方——
 * 所以偏离默认的项要用强调色标出来，一眼看出「这次改了什么」。
 */
export default function ParamSummary({ item }: Props) {
  const rows = item.params ? paramRows(item.params, item.detectedFocal35) : null;
  const stats = [
    formatTime(item.createdAt),
    item.elapsedMs != null ? `${(item.elapsedMs / 1000).toFixed(2)}S` : null,
    item.numPoints != null ? `${formatPoints(item.numPoints)} 高斯` : null,
    item.webPoints != null ? `轻量 ${formatPoints(item.webPoints)}` : null,
  ].filter(Boolean);

  return (
    <details className="param-summary">
      <summary className="content-head">
        <span className="label">参数 / PARAMS</span>
        <span className="label">{stats.join(" · ")}</span>
      </summary>
      {rows ? (
        <div className="param-grid">
          {rows.map(({ label, value, changed }) => (
            <div key={label} className="param-cell">
              <span className="label">{label}</span>
              <span className={`label${changed ? " changed" : ""}`}>{value}</span>
            </div>
          ))}
        </div>
      ) : (
        // 参数留存是后加的功能，之前的记录 params 为 null。
        <div className="param-grid-empty label">该记录早于参数留存功能，无参数信息</div>
      )}
    </details>
  );
}
