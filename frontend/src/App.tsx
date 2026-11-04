import { useCallback, useEffect, useRef, useState } from "react";
import Uploader from "./components/Uploader";
import ParamPanel from "./components/ParamPanel";
import SplatViewer from "./components/SplatViewer";
import Gallery from "./components/Gallery";
import ParamSummary from "./components/ParamSummary";
import { deleteGeneration, generate, getHealth, getHistory, regenerate } from "./lib/api";
import { formatPoints } from "./lib/paramMeta";
import { DEFAULT_PARAMS, normalizeParams, type GenParams, type Generation, type Health } from "./lib/types";

type Connection = "connecting" | "loading" | "ready" | "offline" | "error";
const CONNECTION_LABELS: Record<Connection, string> = {
  connecting: "连接中", loading: "模型加载中", ready: "就绪", offline: "连接失败", error: "模型错误",
};
function plyFilename(g: Generation): string {
  const base = g.originalFilename.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "");
  return `${base.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim() || g.id}.ply`;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [history, setHistory] = useState<Generation[]>([]);
  const [current, setCurrent] = useState<Generation | null>(null);
  const [busy, setBusy] = useState(false);
  const mutation = useRef(false);
  const interacted = useRef(false);
  const historyRequest = useRef(0);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [params, setParams] = useState<GenParams>({ ...DEFAULT_PARAMS });
  const [fullPrecision, setFullPrecision] = useState(false);

  const selectGeneration = (g: Generation) => {
    if (mutation.current) return;
    interacted.current = true;
    setCurrent(g);
    setFullPrecision(false);
    setParams(normalizeParams(g.params));
    setError(null);
  };
  const loadHistory = useCallback(async () => {
    const request = ++historyRequest.current;
    setHistoryError(null);
    try {
      const records = await getHistory();
      if (request !== historyRequest.current || mutation.current) return;
      setHistory(records);
      if (!interacted.current && records[0]) selectGeneration(records[0]);
    } catch (e) {
      if (request === historyRequest.current) setHistoryError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      let ready = false;
      try {
        const value = await getHealth();
        if (stopped) return;
        ready = value.ready;
        setHealth(value);
        setConnection(value.error ? "error" : value.ready ? "ready" : "loading");
      } catch {
        if (stopped) return;
        setConnection("offline");
      }
      timer = window.setTimeout(poll, ready ? 10000 : 2000);
    };
    void poll();
    void loadHistory();
    return () => { stopped = true; clearTimeout(timer); ++historyRequest.current; };
  }, [loadHistory]);

  useEffect(() => {
    if (!busy) return;
    const start = performance.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed((performance.now() - start) / 1000), 100);
    return () => clearInterval(timer);
  }, [busy]);

  const runGeneration = async (task: () => Promise<Generation>) => {
    if (mutation.current || connection !== "ready") return;
    mutation.current = true;
    interacted.current = true;
    ++historyRequest.current;
    setBusy(true);
    setError(null);
    try {
      const result = await task();
      setCurrent(result);
      setFullPrecision(false);
      setHistory(previous => [result, ...previous]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };

  const handleDelete = async (g: Generation) => {
    if (mutation.current || !window.confirm(`删除「${g.originalFilename}」这次生成？记录与产出文件将永久删除。`)) return;
    mutation.current = true;
    interacted.current = true;
    ++historyRequest.current;
    setDeleting(true);
    try {
      await deleteGeneration(g.id);
      setHistoryError(null);
      const next = history.filter(item => item.id !== g.id);
      setHistory(next);
      if (current?.id === g.id) {
        setCurrent(next[0] ?? null);
        setFullPrecision(false);
        setParams(normalizeParams(next[0]?.params));
      }
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : String(e));
    } finally {
      mutation.current = false;
      setDeleting(false);
    }
  };

  const viewerUrl = fullPrecision ? current?.plyUrl : (current?.webUrl ?? current?.plyUrl);
  const viewerPoints = fullPrecision ? current?.numPoints : (current?.webPoints ?? current?.numPoints);
  const deviceLabel = health?.deviceName?.replace(/^NVIDIA GeForce /, "") ?? health?.device?.toUpperCase() ?? "等待连接";
  const locked = busy || deleting;

  return (
    <div className="layout">
      <header className="brand panel">
        <div className="brand-line"><h1>SHARP<span>单张成景</span></h1><span className="brand-symbol" aria-hidden="true">✳</span></div>
        <p className="label">照片 → 3D 高斯泼溅</p>
      </header>
      <section className="upload-panel panel" aria-label="上传照片">
        <div className="section-title"><span>源图</span><span className="label">最大 40 MB</span></div>
        <Uploader onFile={file => void runGeneration(() => generate(file, params))} busy={busy} disabled={connection !== "ready" || deleting} />
      </section>
      <section className="gallery-section panel" aria-label="历史记录">
        <div className="section-title"><h2>历史记录</h2><span className="label">{String(history.length).padStart(2, "0")}</span></div>
        {historyError && <div className="inline-error" role="alert">历史操作失败：{historyError}<button onClick={() => void loadHistory()} disabled={locked}>重试</button></div>}
        <Gallery items={history} activeId={current?.id ?? null} onSelect={selectGeneration} onDelete={handleDelete} disabled={locked} />
      </section>
      <aside className="device-panel panel" aria-label="设备状态">
        <div className="meta-row"><span className="label">设备</span><span>{deviceLabel}</span></div>
        <div className="meta-row"><span className="label">模型</span><span className={`connection ${connection}`} role="status">{CONNECTION_LABELS[connection]}</span></div>
        {connection === "error" && <p className="inline-error">{health?.error}</p>}
        {connection === "offline" && <p>无法连接本机服务，正在自动重试。</p>}
        {health && !health.cudaAvailable && <p>CPU 推理可能需要数分钟。</p>}
      </aside>
      <main className="content panel">
        <header className="content-head">
          <div className="file-title"><span className="label">3D 预览</span><h2 title={current?.originalFilename}>{current?.originalFilename ?? "等待源图"}</h2></div>
          <div className="head-actions">
            {current?.webUrl && <button type="button" className={`regen-btn label${fullPrecision ? " active" : ""}`} aria-pressed={fullPrecision} onClick={() => setFullPrecision(v => !v)} disabled={locked}>{fullPrecision ? "全精度" : "轻量预览"}</button>}
            {current && <a className="download-link label" href={current.plyUrl} download={plyFilename(current)}>下载 PLY ↓</a>}
          </div>
        </header>
        <div className="stage" aria-busy={busy}>
          {current && viewerUrl ? <SplatViewer key={viewerUrl} url={viewerUrl} /> : <div className="stage-msg"><div className="empty-symbol" aria-hidden="true">✳</div><div className="subtitle">从一张照片开始</div><p>上传照片，探索画面中的空间。</p></div>}
          {busy && <div className="task-overlay" role="status"><span>正在生成场景</span><strong>{elapsed.toFixed(1)}<small> s</small></strong><span>解码、推理与导出中</span></div>}
        </div>
        <div className="viewer-footer label"><span>{viewerPoints != null ? `${formatPoints(viewerPoints)} 个高斯 · ${viewerUrl?.endsWith('.splat') ? 'SPLAT' : 'PLY'}` : "预览工作区"}</span><span>{current?.elapsedMs != null ? `生成 ${(current.elapsedMs / 1000).toFixed(2)} s` : "SHARP"}</span></div>
        {error && <div role="alert" className="inline-error">生成失败：{error}。可调整参数后重试。</div>}
        {current && <ParamSummary item={current} />}
      </main>
      <aside className="parameters panel" aria-label="生成参数">
        <div className="section-title"><h2>生成参数</h2><span className="label">PARAMETERS</span></div>
        <ParamPanel params={params} onChange={setParams} busy={locked} detectedFocal35={current?.detectedFocal35 ?? null} />
        <button type="button" className="rerun" onClick={() => current && void runGeneration(() => regenerate(current.id, params))} disabled={!current || locked || connection !== "ready"}>↻ 重新生成</button>
        <p className="parameter-note">调整参数后重新生成，结果会作为新记录保留。</p>
      </aside>
    </div>
  );
}
