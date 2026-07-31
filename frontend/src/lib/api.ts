import type { Generation, Health } from "./types";

export async function getHealth(): Promise<Health> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function getHistory(): Promise<Generation[]> {
  const r = await fetch("/api/history");
  if (!r.ok) throw new Error(`history ${r.status}`);
  return r.json();
}

export interface GenerateOptions {
  scale?: number; // 尺寸比例，默认 1
  density?: number; // 泼溅密度（保留比例），默认 1
}

export async function generate(file: File, opts: GenerateOptions = {}): Promise<Generation> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("scale", String(opts.scale ?? 1));
  fd.append("density", String(opts.density ?? 1));
  const r = await fetch("/api/generate", { method: "POST", body: fd });
  if (!r.ok) {
    let msg = `生成失败 (${r.status})`;
    try {
      const j = await r.json();
      if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json();
}
