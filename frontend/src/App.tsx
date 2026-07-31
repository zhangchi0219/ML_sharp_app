import { useCallback, useEffect, useState } from "react";
import Uploader, { type GenOptions } from "./components/Uploader";
import SplatViewer from "./components/SplatViewer";
import Gallery from "./components/Gallery";
import { generate, getHealth, getHistory } from "./lib/api";
import type { Generation, Health } from "./lib/types";

type Status = "idle" | "generating" | "viewing" | "error";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [history, setHistory] = useState<Generation[]>([]);
  const [current, setCurrent] = useState<Generation | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // 初次加载：拉取健康状态与历史。
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    getHistory()
      .then((h) => {
        setHistory(h);
        if (h.length > 0) {
          setCurrent(h[0]);
          setStatus("viewing");
        }
      })
      .catch(() => {});
  }, []);

  // 生成计时。
  useEffect(() => {
    if (status !== "generating") return;
    const t0 = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 100);
    return () => window.clearInterval(id);
  }, [status]);

  const handleFile = useCallback(async (file: File, opts: GenOptions) => {
    setStatus("generating");
    setError(null);
    try {
      const g = await generate(file, opts);
      setCurrent(g);
      setHistory((prev) => [g, ...prev]);
      setStatus("viewing");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }, []);

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
          {current && (
            <a className="label download-link" href={current.plyUrl} download>
              下载 .PLY ↓
            </a>
          )}
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
            <span className="label">点击缩略图回看</span>
          </div>
          <Gallery
            items={history}
            activeId={current?.id ?? null}
            onSelect={(g) => {
              setCurrent(g);
              setStatus("viewing");
            }}
          />
        </section>
      </main>
    </div>
  );
}
