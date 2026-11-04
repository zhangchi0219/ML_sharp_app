import { DETAIL_PRESETS, GAIN_CONTROLS, detailPoints, formatPoints } from "../lib/paramMeta";
import { DEFAULT_PARAMS, FALLBACK_FOCAL35, type GenParams } from "../lib/types";

interface Props {
  params: GenParams;
  onChange: (next: GenParams) => void;
  busy: boolean;
  /** 当前图片 EXIF 推出的等效焦距；null = 没有历史记录或老记录。 */
  detectedFocal35: number | null;
}

export default function ParamPanel({ params, onChange, busy, detectedFocal35 }: Props) {
  const set = <K extends keyof GenParams>(key: K, value: GenParams[K]) =>
    onChange({ ...params, [key]: value });

  const autoFocal = params.focal35 === null;
  // 「自动」档实际会用到的焦距：有 EXIF 就是它，否则是上游 30mm 的兜底。
  const effectiveAuto = detectedFocal35 ?? FALLBACK_FOCAL35;
  const isDefault = (Object.keys(DEFAULT_PARAMS) as (keyof GenParams)[]).every(
    (k) => params[k] === DEFAULT_PARAMS[k],
  );

  return (
    <div className="gen-controls">
      {/* 泼溅数量是在 768×768 的高斯网格上按 k 跨步抽稀，不是按不透明度裁剪——
          空间均匀、两层等比保留，抽稀后尺度会自动放大 k 倍补上缝隙。 */}
      <div className="control-row">
        <span className="label">泼溅数量</span>
        <div className="segmented" role="group" aria-label="泼溅数量">
          {DETAIL_PRESETS.map(({ detail, label }) => (
            <button
              key={detail}
              type="button"
              aria-pressed={params.detail === detail}
              className={`seg${params.detail === detail ? " active" : ""}`}
              onClick={() => set("detail", detail)}
              disabled={busy}
              title={`网格 1/${detail}² · ${formatPoints(detailPoints(detail))}个高斯`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <span className="param-hint label">
        {formatPoints(detailPoints(params.detail))}个高斯
        {params.detail === 1 ? "（全量）" : ` · 全量的 1/${params.detail * params.detail}`}
        {params.detail < 2 && " · 网页查看器仍加载 29.5 万的轻量版"}
      </span>

      <div className="control-row">
        <span className="label">尺寸比例</span>
        <span className="label">{params.scale.toFixed(2)}×</span>
      </div>
      <input
        type="range"
        className="scale-slider"
        min={0.5}
        max={2}
        step={0.05}
        value={params.scale}
        onChange={(e) => set("scale", Number(e.target.value))}
        disabled={busy}
        aria-label="尺寸比例"
      />

      {/* 焦距：对纵深的影响大于下面所有参数。多数网图/截图没有 EXIF，
          上游会一律按 30mm 处理，手动档就是给这种情况用的。 */}
      <div className="control-row">
        <span className="label">等效焦距</span>
        <div className="segmented" role="group" aria-label="焦距模式">
          <button
            type="button"
            aria-pressed={autoFocal}
            className={`seg${autoFocal ? " active" : ""}`}
            onClick={() => set("focal35", null)}
            disabled={busy}
          >
            自动
          </button>
          <button
            type="button"
            aria-pressed={!autoFocal}
            className={`seg${!autoFocal ? " active" : ""}`}
            onClick={() => set("focal35", Math.max(14, Math.min(85, Math.round(effectiveAuto))))}
            disabled={busy}
          >
            手动
          </button>
        </div>
      </div>
      {autoFocal ? (
        <span className="param-hint label">
          {detectedFocal35 == null
            ? `无 EXIF 时按 ${FALLBACK_FOCAL35}mm 处理`
            : `${Math.round(detectedFocal35)}mm · 来自 EXIF`}
        </span>
      ) : (
        <>
          <div className="control-row">
            <span className="param-hint label">广角压缩纵深 · 长焦拉开纵深</span>
            <span className="label">{params.focal35}MM</span>
          </div>
          <input
            type="range"
            className="scale-slider"
            min={14}
            max={85}
            step={1}
            value={params.focal35 ?? FALLBACK_FOCAL35}
            onChange={(e) => set("focal35", Number(e.target.value))}
            disabled={busy}
            aria-label="等效焦距"
          />
        </>
      )}

      <details className="advanced">
        <summary className="label">高级 / ADVANCED</summary>
        <div className="advanced-body">
          <p className="param-hint label">
            以下为模型推理参数，1.00× 即模型原生效果。
          </p>

          {GAIN_CONTROLS.map(({ key, label, hint }) => (
            <div key={key}>
              <div className="control-row">
                <span className="label">{label}</span>
                <span className="label">{(params[key] as number).toFixed(2)}×</span>
              </div>
              <input
                type="range"
                className="scale-slider"
                min={0}
                max={3}
                step={0.05}
                value={params[key] as number}
                onChange={(e) => set(key, Number(e.target.value) as GenParams[typeof key])}
                disabled={busy}
                aria-label={label}
              />
              <span className="param-hint label">{hint}</span>
            </div>
          ))}

          <div>
            <div className="control-row">
              <span className="label">尺度上限</span>
              <span className="label">{params.maxScale.toFixed(1)}×</span>
            </div>
            <input
              type="range"
              className="scale-slider"
              min={1.5}
              max={20}
              step={0.5}
              value={params.maxScale}
              onChange={(e) => set("maxScale", Number(e.target.value))}
              disabled={busy}
              aria-label="尺度上限"
            />
            <span className="param-hint label">单个泼溅相对基准尺寸的放大上限</span>
          </div>
        </div>
      </details>

      <button
        type="button"
        className="reset-btn label"
        onClick={() => onChange(DEFAULT_PARAMS)}
        disabled={busy || isDefault}
      >
        恢复默认
      </button>
    </div>
  );
}
