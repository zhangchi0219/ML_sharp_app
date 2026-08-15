import { useCallback, useEffect, useState } from "react";
import Uploader from "./components/Uploader";
import ParamPanel from "./components/ParamPanel";
import SplatViewer from "./components/SplatViewer";
import Gallery from "./components/Gallery";
import ParamSummary from "./components/ParamSummary";
import { deleteGeneration, generate, getHealth, getHistory, regenerate } from "./lib/api";
import { formatPoints } from "./lib/paramMeta";
import {
  DEFAULT_PARAMS,
  normalizeParams,
  type GenParams,
  type Generation,
  type Health,
} from "./lib/types";

type Status = "idle" | "generating" | "viewing" | "error";

/** 另存为对话框的预填名：用源图名而不是 gen_id，去掉扩展名并清掉 Windows 非法字符。 */
function plyFilename(g: Generation): string {
  const base = (g.originalFilename ?? "").replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "");
  const safe = base.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim();
  return `${safe || g.id}.ply`;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [history, setHistory] = useState<Generation[]>([]);
  const [current, setCurrent] = useState<Generation | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  // 删除失败不能走 status="error"——那会把查看器整个换成错误页；就地提示即可。
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // 参数 state 提在这里：上传、同图重跑、历史回填三个消费方要读写同一份。
  const [params, setParams] = useState<GenParams>(DEFAULT_PARAMS);
  // 查看器默认加载轻量版 .splat；勾上则换成全精度 .ply（几倍的下载量与显存）。
  const [fullPrecision, setFullPrecision] = useState(false);

  // 初次加载：拉取健康状态与历史。
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    getHistory()
      .then((h) => {
        setHistory(h);
        if (h.length > 0) {
          selectGeneration(h[0]);
        }
      })
      .catch(() => {});
    // 只在挂载时跑一次；selectGeneration 只 setState，不依赖任何会变的闭包值。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 选中一条记录：切换查看器，并把它当时的参数回填到面板（老记录没有则保持现状）。 */
  const selectGeneration = (g: Generation) => {
    setCurrent(g);
    setStatus("viewing");
    // 换记录一律回到轻量版：全精度是逐次的显式选择，不该跨记录粘住。
    setFullPrecision(false);
    if (g.params) setParams(normalizeParams(g.params));
  };

  // 生成计时。
  useEffect(() => {
    if (status !== "generating") return;
    const t0 = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 100);
    return () => window.clearInterval(id);
  }, [status]);

  /** 跑一次生成并把结果推进历史。上传与重跑只差调用哪个接口。 */
  const runGeneration = useCallback(async (task: () => Promise<Generation>) => {
    setStatus("generating");
    setError(null);
    try {
      const g = await task();
      setCurrent(g);
      setFullPrecision(false);
      setHistory((prev) => [g, ...prev]);
      setStatus("viewing");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }, []);

  const handleFile = useCallback(
    (file: File) => runGeneration(() => generate(file, params)),
    [runGeneration, params],
  );

  // 同图重跑：复用已存的源图，改完参数约 1 秒出结果，不必重新拖文件。
  const handleRegenerate = useCallback(() => {
    if (!current) return;
    runGeneration(() => regenerate(current.id, params));
  }, [runGeneration, current, params]);

  /** 删除一条历史。产出文件同时被清掉，不可撤销，所以先确认。 */
  const handleDelete = useCallback(
    async (g: Generation) => {
      const ok = window.confirm(
        `删除「${g.originalFilename}」这次生成？\n记录与产出文件都会被永久删除，无法撤销。`,
      );
      if (!ok) return;
      try {
        await deleteGeneration(g.id);
        setHistoryError(null);
        const idx = history.findIndex((h) => h.id === g.id);
        const next = history.filter((h) => h.id !== g.id);
        setHistory(next);
        if (current?.id === g.id) {
          // 优先让原位置顶上来（时间上更早的那条），没有则退到前一条，都没有就回空态。
          const fallback = next[idx] ?? next[idx - 1] ?? null;
          if (fallback) {
            selectGeneration(fallback);
          } else {
            setCurrent(null);
            setStatus("idle");
          }
        }
      } catch (e) {
        setHistoryError(e instanceof Error ? e.message : String(e));
      }
    },
    [history, current],
  );

  const busy = status === "generating";
  // 轻量版是后加的，老记录没有 webUrl，只能退回 .ply。
  const viewerUrl = fullPrecision ? current?.plyUrl : (current?.webUrl ?? current?.plyUrl);
  const viewerPoints = fullPrecision ? current?.numPoints : (current?.webPoints ?? current?.numPoints);
  // 格式取自实际加载的那个 url——老记录退回 .ply 时不能还写 SPLAT。
  const viewerFormat = viewerUrl?.endsWith(".splat") ? "SPLAT" : "PLY";
  const modelState = health?.ready ? "就绪" : health?.error ? "错误" : "加载中";
  // 有 GPU 时显示型号与显存（"NVIDIA GeForce" 前缀太长，去掉），否则退回设备类型。
  const deviceLabel = health?.deviceName
    ? `${health.deviceName.replace(/^NVIDIA GeForce /, "")}${
        health.vramTotalMb ? ` · ${Math.round(health.vramTotalMb / 1024)}GB` : ""
      }`
    : health?.device
      ? health.device.toUpperCase()
      : "…";

  return (
    <div className="layout">
      <aside className="sidebar">
        <div>
          <div className="brand-mark">单张高斯泼溅</div>
          <div className="brand-sub label">照片 → 3D 高斯泼溅</div>
        </div>

        <h1 className="hero">
          一张照片
          <br />
          一秒成景
        </h1>

        <Uploader onFile={handleFile} busy={busy} />

        <ParamPanel
          params={params}
          onChange={setParams}
          busy={busy}
          detectedFocal35={current?.detectedFocal35 ?? null}
        />

        <div className="meta-block">
          <div className="meta-row">
            <span className="label">设备</span>
            <span className="label">{deviceLabel}</span>
          </div>
          <div className="meta-row">
            <span className="label">状态</span>
            <span className="label">{modelState}</span>
          </div>
          {current?.elapsedMs != null && (
            <div className="meta-row">
              <span className="label">上次耗时</span>
              <span className="label">{(current.elapsedMs / 1000).toFixed(2)}S</span>
            </div>
          )}
          {viewerPoints != null && (
            <div className="meta-row">
              <span className="label">查看中</span>
              <span className="label">
                {formatPoints(viewerPoints)} · {viewerFormat}
              </span>
            </div>
          )}
          {health && !health.cudaAvailable && (
            <div className="license-note label warn-note">
              未检测到可用 NVIDIA GPU，将回退到 CPU 推理，单张可能需要数分钟。
            </div>
          )}
        </div>
      </aside>

      <main className="content">
        <header className="content-head">
          <span className="label">查看器 / VIEWER</span>
          <span className="head-actions">
            {current?.webUrl && (
              <button
                type="button"
                className={`label regen-btn${fullPrecision ? " active" : ""}`}
                onClick={() => setFullPrecision((v) => !v)}
                disabled={busy}
                title={
                  fullPrecision
                    ? "切回轻量版 .splat（约 9 MB，秒开）"
                    : "加载全精度 .ply（数十 MB，显存占用高数倍）"
                }
              >
                {fullPrecision ? "◉ 全精度" : "○ 全精度"}
              </button>
            )}
            {current && (
              <button
                type="button"
                className="label regen-btn"
                onClick={handleRegenerate}
                disabled={busy}
                title="用当前参数重跑这张图，结果作为新记录加入历史"
              >
                ↻ 用当前参数重新生成
              </button>
            )}
            {current && (
              <a
                className="label download-link"
                href={current.plyUrl}
                download={plyFilename(current)}
              >
                下载 .PLY ↓
              </a>
            )}
          </span>
        </header>

        <div className="stage">
          {status === "viewing" && current && viewerUrl ? (
            // key 带上 url：切换精度必须整个重建查看器（库不支持替换已加载的场景）。
            <SplatViewer key={viewerUrl} url={viewerUrl} />
          ) : status === "generating" ? (
            <div className="stage-msg">
              <div className="subtitle">正在前向推理…</div>
              <div className="label">{elapsed.toFixed(1)}s · 单次前向</div>
            </div>
          ) : status === "error" ? (
            <div className="stage-msg">
              <div className="subtitle" style={{ color: "var(--hot)" }}>
                生成失败
              </div>
              <div className="label">{error}</div>
            </div>
          ) : (
            <div className="stage-msg">
              <div className="subtitle">拖入一张照片开始</div>
              <div className="label">约 1 秒内生成可旋转的 3D 高斯泼溅</div>
            </div>
          )}
        </div>

        {current && <ParamSummary item={current} />}

        <section className="gallery-section">
          <div className="content-head">
            <span className="label">历史 / HISTORY · {history.length}</span>
            {historyError ? (
              <span className="label" style={{ color: "var(--hot)" }}>
                {historyError}
              </span>
            ) : (
              <span className="label">点击缩略图回看 · 悬停右上角 × 删除</span>
            )}
          </div>
          <Gallery
            items={history}
            activeId={current?.id ?? null}
            onSelect={selectGeneration}
            onDelete={handleDelete}
          />
        </section>
      </main>
    </div>
  );
}
