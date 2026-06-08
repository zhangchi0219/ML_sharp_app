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

export async function generate(file: File): Promise<Generation> {
  const fd = new FormData();
  fd.append("file", file);
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
