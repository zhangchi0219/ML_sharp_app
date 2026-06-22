import { useEffect, useRef, useState } from "react";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";
import * as THREE from "three";

// 该库的类型与 tsc 偶有摩擦，这里以 any 引用，运行时行为不变。
const GS: any = GaussianSplats3D;

// WASD 飞行速度（单位/秒）。场景尺度约 1~2 单位，0.8 适中；按需调整。
const MOVE_SPEED = 0.8;

interface Props {
  plyUrl: string;
}

export default function SplatViewer({ plyUrl }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let viewer: any = null;
    let disposed = false;
    let flyRaf = 0;
    const pressed = new Set<string>();
    setLoading(true);
    setProgress(0);
    setError(null);

    // 监听 WASD/QE；仅记录按键状态，不调用 preventDefault，故不影响页面其它输入。
    const onKeyDown = (e: KeyboardEvent) => {
      if (["KeyW", "KeyA", "KeyS", "KeyD", "KeyE", "KeyQ"].includes(e.code)) {
        pressed.add(e.code);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => pressed.delete(e.code);

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
      .addSplatScene(plyUrl, {
        format: GS.SceneFormat.Ply,
        showLoadingUI: false,
        progressiveLoad: false,
        onProgress: (pct: number) => setProgress(pct ?? 0),
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
      });

    return () => {
      disposed = true;
      if (flyRaf) cancelAnimationFrame(flyRaf);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      pressed.clear();
      try {
        if (viewer && typeof viewer.dispose === "function") {
          viewer.dispose(); // 停止渲染循环并释放 GPU 资源
        }
      } catch {
        /* 忽略卸载竞态 */
      }
    };
  }, [plyUrl]);

  return (
    <div className="viewer-wrap">
      <div ref={containerRef} className="viewer-canvas" />
      {!loading && !error && (
        <div className="viewer-hint label">拖拽旋转 · 滚轮缩放 · WASD 移动 · E/Q 升降</div>
      )}
      {loading && !error && (
        <div className="viewer-status label">
          正在加载高斯泼溅… {Math.round(progress)}%
        </div>
      )}
      {error && <div className="viewer-status viewer-error label">查看器错误：{error}</div>}
    </div>
  );
}
