/**
 * 参数的中文标签与展示格式化。
 *
 * 参数面板（可调）与参数卡（只读回看）读同一份标签——放在这里是为了改一个名字只改一处，
 * 否则两边会慢慢漂成两套说法。数值范围仍归 lib/types.ts 与后端 GenParams 管。
 */
import { DEFAULT_PARAMS, FALLBACK_FOCAL35, normalizeParams, type HistoricalParams, type GenParams, type Generation } from "./types";

// 原生 2 × 768 × 768 = 1,179,648 个高斯，只能抽稀减少，无法增加。
// detail 是网格抽样步长 k：保留 1/k² 的泼溅（后端 sharp_runner._grid_subsample）。
export const DETAIL_PRESETS: { detail: number; label: string }[] = [
  { detail: 1, label: "精细" },
  { detail: 2, label: "标准" },
  { detail: 3, label: "精简" },
  { detail: 4, label: "极简" },
];

/** 某个步长下的高斯数。768 除以 k 要向上取整——切片 `[::k]` 保留的是 ⌈768/k⌉ 行。 */
export function detailPoints(detail: number): number {
  const side = Math.ceil(768 / detail);
  return 2 * side * side;
}

/** 「29.5 万」这种紧凑写法，滑块与参数卡都放得下。 */
export function formatPoints(n: number): string {
  return n >= 1e4 ? `${(n / 1e4).toFixed(n >= 1e6 ? 0 : 1)} 万` : String(n);
}

// 高级参数：全部是「相对模型默认值的倍率」，1.0× 恒等于原生效果。
// hint 说明的是把滑块推到 0 会发生什么——这是最容易理解的锚点。
export const GAIN_CONTROLS: { key: keyof GenParams; label: string; hint: string }[] = [
  { key: "colorGain", label: "色彩强度", hint: "0 = 直接用原图颜色，不做网络修正" },
  { key: "scaleGain", label: "大小变化", hint: "0 = 所有泼溅一样大" },
  { key: "shapeGain", label: "形状拉伸", hint: "0 = 全是正球，不做各向异性拉伸" },
  { key: "opacityGain", label: "通透对比", hint: "0 = 两层不透明度均匀" },
  { key: "depthGain", label: "深度浮雕", hint: "放大逐点深度位移，过高会撕裂画面" },
];

/** detail 的可读写法：档名 + 实际点数。 */
export function detailLabel(detail: number): string {
  const hit = DETAIL_PRESETS.find((p) => p.detail === detail);
  return `${hit?.label ?? `1/${detail}²`} · ${formatPoints(detailPoints(detail))}`;
}

/**
 * 焦距的可读写法。
 * 「自动」档实际用的值在生成后才知道（EXIF 或上游 30mm 兜底），所以要把它一起显示出来，
 * 不然「自动」这两个字对回看毫无信息量。
 */
export function focalLabel(params: GenParams, detected: number | null): string {
  if (params.focal35 === null) {
    return `自动 · ${Math.round(detected ?? FALLBACK_FOCAL35)}MM`;
  }
  return `${Math.round(params.focal35)}MM · 手动`;
}

/** 参数卡的一行：标签、值、是否偏离默认（偏离的用强调色标出来）。 */
export interface ParamRow {
  label: string;
  value: string;
  changed: boolean;
}

export function paramRows(raw: HistoricalParams, detected: number | null): ParamRow[] {
  const params = normalizeParams(raw);
  const rows: ParamRow[] = [
    {
      label: "泼溅数量",
      // detail 之前叫 density（按不透明度 Top-K 的保留比例）。老记录里没有 detail，
      // 直接报存下来的比例，不硬套成步长——两者的裁剪方式根本不同，换算会撒谎。
      value:
        raw.detail == null && typeof raw.density === "number" && Number.isFinite(raw.density)
          ? `旧版 ${raw.density?.toFixed(2) ?? "?"}`
          : detailLabel(params.detail),
      changed: params.detail !== DEFAULT_PARAMS.detail,
    },
    {
      label: "尺寸比例",
      value: `${params.scale.toFixed(2)}×`,
      changed: params.scale !== DEFAULT_PARAMS.scale,
    },
    {
      label: "等效焦距",
      value: focalLabel(params, detected),
      // 默认是「自动」；手动指定即视为改动，哪怕数值恰好等于 EXIF 值。
      changed: params.focal35 !== DEFAULT_PARAMS.focal35,
    },
    {
      label: "尺度上限",
      value: `${params.maxScale.toFixed(1)}×`,
      changed: params.maxScale !== DEFAULT_PARAMS.maxScale,
    },
  ];
  for (const { key, label } of GAIN_CONTROLS) {
    const v = params[key] as number;
    rows.push({ label, value: `${v.toFixed(2)}×`, changed: v !== DEFAULT_PARAMS[key] });
  }
  return rows;
}

/** 缩略图 hover 的 title：文件名 + 高斯数 + 所有偏离默认的参数。老记录只给前两项。 */
export function summaryLine(g: Generation): string {
  const parts = [g.originalFilename];
  if (g.numPoints != null) parts.push(`${g.numPoints.toLocaleString()} 高斯`);
  if (g.params) {
    const changed = paramRows(g.params, g.detectedFocal35).filter((r) => r.changed);
    parts.push(changed.length === 0 ? "默认参数" : changed.map((r) => `${r.label} ${r.value}`).join(" · "));
  }
  return parts.join(" · ");
}
