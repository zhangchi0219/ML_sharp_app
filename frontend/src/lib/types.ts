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
}
