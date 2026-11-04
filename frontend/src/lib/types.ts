/**
 * 一次生成的可调参数。
 *
 * ⚠️ 范围与默认值必须与后端 `backend/app/main.py` 的 `GenParams` 保持一致——
 * 那边用 pydantic 的 ge/le 做校验，这边只是滑块的边界。改一处必须改两处。
 */
export interface GenParams {
  /** 泼溅尺寸整体比例。0.5–2.0 */
  scale: number;
  /** 网格抽样步长 k，保留 1/k² 的泼溅。整数 1–4，1 = 全量 */
  detail: number;
  /** 35mm 等效焦距(mm)。14–85；null = 跟随图片 EXIF */
  focal35: number | null;
  /** 以下五项都是「相对 SHARP 默认值的倍率」，1.0 = 原生效果。0–3 */
  colorGain: number;
  scaleGain: number;
  shapeGain: number;
  opacityGain: number;
  depthGain: number;
  /** 尺度激活上界。1.5–20（必须 > 1，后端会除以 maxScale-1） */
  maxScale: number;
}

export const DEFAULT_PARAMS: GenParams = {
  scale: 1,
  detail: 1,
  focal35: null,
  colorGain: 1,
  scaleGain: 1,
  shapeGain: 1,
  opacityGain: 1,
  depthGain: 1,
  maxScale: 10,
};

/**
 * 把历史记录里的参数回填进面板前先规整：只保留当前认识的字段，缺的用默认值补。
 *
 * 老记录存的是已废弃的 `density`（按不透明度 Top-K 的保留比例）。后端 GenParams 是
 * `extra="forbid"`，原样送回去会被打成 422，所以这里必须把陌生字段丢掉。
 */
export type HistoricalParams = Partial<GenParams> & { density?: number };

export function normalizeParams(raw: HistoricalParams | null | undefined): GenParams {
  const out = { ...DEFAULT_PARAMS };
  if (!raw || typeof raw !== "object") return out;
  const ranges: Record<keyof GenParams, [number, number]> = {
    scale: [.5, 2], detail: [1, 4], focal35: [14, 85], maxScale: [1.5, 20],
    colorGain: [0, 3], scaleGain: [0, 3], shapeGain: [0, 3], opacityGain: [0, 3], depthGain: [0, 3],
  };
  for (const key of Object.keys(DEFAULT_PARAMS) as (keyof GenParams)[]) {
    const v = raw[key];
    const [min, max] = ranges[key];
    if (typeof v === "number" && Number.isFinite(v) && v >= min && v <= max && (key !== "detail" || Number.isInteger(v))) {
      Object.assign(out, { [key]: v });
    }
  }
  return out;
}

/** 无 EXIF 焦距时上游 sharp.utils.io 的兜底值，UI 用来标注「自动」档。 */
export const FALLBACK_FOCAL35 = 30;

export interface Generation {
  id: string;
  originalFilename: string;
  /** 全精度 .ply，供下载与「全精度」查看。 */
  plyUrl: string;
  /** 网页轻量版 .splat；早于该功能的记录为 null，查看器退回 plyUrl。 */
  webUrl: string | null;
  thumbUrl: string;
  numPoints: number | null;
  /** 轻量版的高斯数；老记录为 null。 */
  webPoints: number | null;
  elapsedMs: number | null;
  status: string;
  createdAt: string;
  /** 本次生成用的参数；迁移前的老记录为 null。 */
  params: HistoricalParams | null;
  /** 图片 EXIF 推出的 35mm 等效焦距；老记录为 null。 */
  detectedFocal35: number | null;
}

export interface Health {
  ready: boolean;
  device: string | null;
  error: string | null;
  /** GPU 型号，无 CUDA 时为 null。 */
  deviceName: string | null;
  vramTotalMb: number | null;
  /** 本次进程内的显存分配峰值；未推理过时为 null。 */
  vramPeakMb: number | null;
  cudaAvailable: boolean;
}
