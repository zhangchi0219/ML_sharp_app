import type { GenParams, Generation, Health } from "./types";

export async function getHealth(): Promise<Health> {
  const r = await fetch("/api/health", { signal: AbortSignal.timeout(5000) });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function getHistory(): Promise<Generation[]> {
  const r = await fetch("/api/history", { signal: AbortSignal.timeout(5000) });
  if (!r.ok) throw new Error(`history ${r.status}`);
  return r.json();
}

/** 删除一条记录：后端同时清掉 .ply，以及不再被其他记录引用的源图与缩略图。 */
export async function deleteGeneration(id: string): Promise<void> {
  const r = await fetch(`/api/history/${id}`, { method: "DELETE" });
  if (!r.ok) await readError(r, "删除");
}

/** 从响应里取出后端给的中文错误说明（FastAPI 放在 detail 里）。 */
async function readError(r: Response, what = "生成"): Promise<never> {
  let msg = `${what}失败 (${r.status})`;
  try {
    const j = await r.json();
    if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* 响应不是 JSON，沿用状态码文案 */
  }
  throw new Error(msg);
}

export async function generate(file: File, params: GenParams): Promise<Generation> {
  const fd = new FormData();
  fd.append("file", file);
  // 参数走单个 JSON 字段，加参数时前后端各只改一处。
  fd.append("params", JSON.stringify(params));
  const r = await fetch("/api/generate", { method: "POST", body: fd });
  if (!r.ok) return readError(r);
  return r.json();
}

/** 用新参数重跑已有记录的源图，产出一条新记录（原记录保留，便于对比）。 */
export async function regenerate(sourceId: string, params: GenParams): Promise<Generation> {
  const fd = new FormData();
  fd.append("params", JSON.stringify(params));
  const r = await fetch(`/api/regenerate/${sourceId}`, { method: "POST", body: fd });
  if (!r.ok) return readError(r);
  return r.json();
}
