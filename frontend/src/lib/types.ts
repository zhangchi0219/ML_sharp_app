export interface Generation {
  id: string;
  originalFilename: string;
  plyUrl: string;
  thumbUrl: string;
  numPoints: number | null;
  elapsedMs: number | null;
  status: string;
  createdAt: string;
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
