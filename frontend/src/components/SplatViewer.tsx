import { useEffect, useRef, useState } from "react";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";
import * as THREE from "three";

// 该库的类型与 tsc 偶有摩擦，这里以 any 引用，运行时行为不变。
const GS: any = GaussianSplats3D;

// WASD 飞行速度（单位/秒）。场景尺度约 1~2 单位，0.8 适中；按需调整。
const MOVE_SPEED = 0.8;

interface Props {
  /** .ply（全精度）或 .splat（网页轻量版）。格式按扩展名判定。 */
  url: string;
}

export default function SplatViewer({ url }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let viewer: any = null;
    let disposed = false;
    let flyRaf = 0;
    const pressed = new Set<string>();
    const clearKeys = () => pressed.clear();
    setLoading(true);
    setProgress(null);
    setError(null);

    // 监听 WASD/QE；仅记录按键状态，不调用 preventDefault，故不影响页面其它输入。
    const onKeyDown = (e: KeyboardEvent) => {
      if (document.activeElement !== container) return;
      if (["KeyW", "KeyA", "KeyS", "KeyD", "KeyE", "KeyQ"].includes(e.code)) {
        pressed.add(e.code);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => pressed.delete(e.code);

    const release = () => {
      if (disposed) return;
      disposed = true;
      if (flyRaf) cancelAnimationFrame(flyRaf);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      container.removeEventListener("blur", clearKeys);
      window.removeEventListener("blur", clearKeys);
      document.removeEventListener("visibilitychange", clearKeys);
      pressed.clear();
      // The library aborts its in-flight downloads and terminates workers in dispose().
      // Its final body.removeChild(rootElement) rejects for a supplied React root;
      // renderer, workers and controls have already been released at that point.
      try { viewer?.dispose?.()?.catch?.(() => {}); } catch { /* partial initialization */ }
    };
    container.addEventListener("blur", clearKeys);
    window.addEventListener("blur", clearKeys);
    document.addEventListener("visibilitychange", clearKeys);

    try {
      viewer = new GS.Viewer({
        rootElement: container,
        // SHARP 用 OpenCV 约定（x 右 / y 下 / z 前），场景中心约在 (0,0,+z)。
        // 相机置于原点稍后方、看向 +z；up 取 -y 使画面正立。
        cameraUp: [0, -1, 0],
        initialCameraPosition: [0, 0, -0.4],
        initialCameraLookAt: [0, 0, 1],
        sharedMemoryForWorkers: false, // 免去 COOP/COEP 跨源隔离头要求
      });

      viewer
        .addSplatScene(url, {
          // 库自己也能按扩展名猜，但显式给出更稳：静态目录里两种格式并存。
          format: url.endsWith(".splat") ? GS.SceneFormat.Splat : GS.SceneFormat.Ply,
          showLoadingUI: false,
          progressiveLoad: false,
          onProgress: (pct: number) => { if (!disposed) setProgress(Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : null); },
        })
        .then(() => {
          if (disposed) return;
          viewer.start();
          setLoading(false);

          // ── WASD 自由飞行：叠加在内置 OrbitControls 之上 ──
          // 每帧把 camera.position 与 controls.target 平移同一向量，轨道偏移不变，
          // 库渲染循环里的 controls.update() 不会与之冲突；相机一动即自动重渲染+重排序。
          const camera: THREE.PerspectiveCamera = viewer.camera;
          const controls: any = viewer.controls;
          window.addEventListener("keydown", onKeyDown, false);
          window.addEventListener("keyup", onKeyUp, false);

          const forward = new THREE.Vector3();
          const right = new THREE.Vector3();
          const up = new THREE.Vector3();
          const move = new THREE.Vector3();
          let last = performance.now();

          const tick = () => {
            if (disposed) return;
            flyRaf = requestAnimationFrame(tick);
            const now = performance.now();
            const dt = Math.min((now - last) / 1000, 0.1); // 防止后台标签页累积大跳变
            last = now;
            if (pressed.size === 0 || !camera || !controls) return;

            camera.getWorldDirection(forward); // 已归一化
            right.copy(forward).cross(camera.up).normalize();
            up.copy(camera.up).normalize(); // 屏幕上方向（cameraUp=[0,-1,0]）

            move.set(0, 0, 0);
            if (pressed.has("KeyW")) move.add(forward);
            if (pressed.has("KeyS")) move.sub(forward);
            if (pressed.has("KeyD")) move.add(right);
            if (pressed.has("KeyA")) move.sub(right);
            if (pressed.has("KeyE")) move.add(up);
            if (pressed.has("KeyQ")) move.sub(up);

            if (move.lengthSq() > 0) {
              move.normalize().multiplyScalar(MOVE_SPEED * dt);
              camera.position.add(move);
              controls.target.add(move);
            }
          };
          flyRaf = requestAnimationFrame(tick);
        })
        .catch((e: unknown) => {
          if (disposed) return;
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
          release();
        });

    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
      release();
    }
    return release;
  }, [url]);

  return (
    <div className="viewer-wrap">
      <div ref={containerRef} className="viewer-canvas" tabIndex={0} aria-label="3D 预览，点击或按 Tab 聚焦后使用 WASD 移动，Q E 升降" onPointerDown={() => containerRef.current?.focus()} />
      {!loading && !error && (
        <div className="viewer-hint label">拖拽旋转 · 滚轮缩放 · WASD 移动 · E/Q 升降</div>
      )}
      {loading && !error && (
        <div className="viewer-status label">
          正在加载高斯泼溅… {progress === null ? "" : `${Math.round(progress)}%`}
        </div>
      )}
      {error && <div className="viewer-status viewer-error label">查看器错误：{error}</div>}
    </div>
  );
}
