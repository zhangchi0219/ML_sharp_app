import { useCallback, useEffect, useState } from "react";
import Uploader from "./components/Uploader";
import ParamPanel from "./components/ParamPanel";
import SplatViewer from "./components/SplatViewer";
import Gallery from "./components/Gallery";
import { generate, getHealth, getHistory, regenerate } from "./lib/api";
import { DEFAULT_PARAMS, type GenParams, type Generation, type Health } from "./lib/types";

type Status = "idle" | "generating" | "viewing" | "error";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [history, setHistory] = useState<Generation[]>([]);
  const [current, setCurrent] = useState<Generation | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // 参数 state 提在这里：上传、同图重跑、历史回填三个消费方要读写同一份。
  const [params, setParams] = useState<GenParams>(DEFAULT_PARAMS);

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
    if (g.params) setParams(g.params);
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

  const busy = status === "generating";
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
          <div className="brand-mark">SHARP</div>
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
            <span className="label">引擎</span>
            <span className="label">APPLE ML SHARP</span>
          </div>
          <div className="meta-row">
            <span className="label">设备</span>
            <span className="label">{deviceLabel}</span>
          </div>
          <div className="meta-row">
            <span className="label">模型</span>
            <span className="label">{modelState}</span>
          </div>
          {current?.elapsedMs != null && (
            <div className="meta-row">
              <span className="label">上次耗时</span>
              <span className="label">{(current.elapsedMs / 1000).toFixed(2)}S</span>
            </div>
          )}
          {health && !health.cudaAvailable && (
            <div className="license-note label warn-note">
              未检测到可用 NVIDIA GPU，将回退到 CPU 推理，单张可能需要数分钟。
            </div>
          )}
          <div className="license-note label">
            仅供个人 / 研究用途 · 模型遵循 Apple ML Research 许可（非商用）
          </div>
        </div>
      </aside>

      <main className="content">
        <header className="content-head">
          <span className="label">查看器 / VIEWER</span>
          <span className="head-actions">
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
              <a className="label download-link" href={current.plyUrl} download>
                下载 .PLY ↓
              </a>
            )}
          </span>
        </header>

        <div className="stage">
          {status === "viewing" && current ? (
            <SplatViewer key={current.id} plyUrl={current.plyUrl} />
          ) : status === "generating" ? (
            <div className="stage-msg">
              <div className="subtitle">正在前向推理…</div>
              <div className="label">{elapsed.toFixed(1)}s · SHARP 单次前向</div>
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
              <div className="label">SHARP 将在约 1 秒内生成可旋转的 3D 高斯泼溅</div>
            </div>
          )}
        </div>

        <section className="gallery-section">
          <div className="content-head">
            <span className="label">历史 / HISTORY · {history.length}</span>
            <span className="label">点击缩略图回看并载入当时的参数</span>
          </div>
          <Gallery items={history} activeId={current?.id ?? null} onSelect={selectGeneration} />
        </section>
      </main>
    </div>
  );
}
