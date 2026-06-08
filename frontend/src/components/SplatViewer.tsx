import { useEffect, useRef, useState } from "react";
import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";

// 该库的类型与 tsc 偶有摩擦，这里以 any 引用，运行时行为不变。
const GS: any = GaussianSplats3D;

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
    setLoading(true);
    setProgress(0);
    setError(null);

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
      })
      .catch((e: unknown) => {
        if (disposed) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });

    return () => {
      disposed = true;
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
      {loading && !error && (
        <div className="viewer-status label">
          正在加载高斯泼溅… {Math.round(progress)}%
        </div>
      )}
      {error && <div className="viewer-status viewer-error label">查看器错误：{error}</div>}
    </div>
  );
}
