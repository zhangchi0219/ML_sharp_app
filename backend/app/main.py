"""FastAPI 应用：上传照片 → SHARP 生成 3DGS .ply → 历史 / 静态服务。"""

from __future__ import annotations

import io as _io
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
from sqlmodel import select

from . import db, sharp_runner
from .models import Generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("sharp_app")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
GAUSS_DIR = DATA_DIR / "gaussians"
THUMB_DIR = DATA_DIR / "thumbs"
for _d in (UPLOAD_DIR, GAUSS_DIR, THUMB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
MAX_BYTES = 40 * 1024 * 1024  # 40MB

# 启动预热若失败，记录原因，让接口给出清晰提示而非整服务崩溃。
_warmup_error: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _warmup_error
    db.init_db()
    try:
        sharp_runner.warmup()
    except Exception as exc:  # noqa: BLE001
        _warmup_error = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("SHARP 模型加载失败")
    yield


app = FastAPI(title="SHARP 高斯泼溅", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态服务：产出的 .ply 与缩略图。
app.mount("/files/gaussians", StaticFiles(directory=GAUSS_DIR), name="gaussians")
app.mount("/files/thumbs", StaticFiles(directory=THUMB_DIR), name="thumbs")


def _to_dict(g: Generation) -> dict:
    return {
        "id": g.id,
        "originalFilename": g.original_filename,
        "plyUrl": f"/files/gaussians/{Path(g.ply_path).name}",
        "thumbUrl": f"/files/thumbs/{Path(g.thumb_path).name}",
        "numPoints": g.num_points,
        "elapsedMs": g.elapsed_ms,
        "status": g.status,
        "createdAt": g.created_at.isoformat(),
    }


def _count_ply_vertices(ply_path: Path) -> int | None:
    """从 PLY 头部读取 vertex 数量（不加载全部数据）。"""
    try:
        with open(ply_path, "rb") as f:
            for raw in f:
                line = raw.decode("ascii", "replace").strip()
                if line == "end_header":
                    break
                if line.startswith("element vertex"):
                    return int(line.split()[-1])
    except Exception:  # noqa: BLE001
        return None
    return None


@app.get("/api/health")
def health() -> dict:
    return {
        "ready": sharp_runner.is_ready(),
        "device": sharp_runner.device(),
        "error": _warmup_error,
    }


@app.get("/api/history")
def history() -> list[dict]:
    with db.get_session() as session:
        rows = session.exec(
            select(Generation).order_by(Generation.created_at.desc())
        ).all()
        return [_to_dict(r) for r in rows]


@app.post("/api/generate")
async def generate(file: UploadFile = File(...)) -> dict:
    if not sharp_runner.is_ready():
        raise HTTPException(503, f"SHARP 模型未就绪：{_warmup_error or '正在加载，请稍候'}")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的图片类型：{ext or '未知'}")

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "图片过大（上限 40MB）")

    gen_id = uuid.uuid4().hex[:12]
    image_path = UPLOAD_DIR / f"{gen_id}{ext}"
    image_path.write_bytes(data)

    # 生成缩略图（用于画廊）。
    thumb_path = THUMB_DIR / f"{gen_id}.jpg"
    try:
        with Image.open(_io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            im.save(thumb_path, "JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"无法读取图片：{exc}") from exc

    # SHARP 推理。
    ply_path = GAUSS_DIR / f"{gen_id}.ply"
    t0 = time.time()
    try:
        sharp_runner.predict(image_path, ply_path)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("生成失败")
        raise HTTPException(500, f"生成失败：{exc}") from exc
    elapsed_ms = int((time.time() - t0) * 1000)

    record = Generation(
        id=gen_id,
        original_filename=file.filename or f"{gen_id}{ext}",
        image_path=image_path.name,
        ply_path=ply_path.name,
        thumb_path=thumb_path.name,
        num_points=_count_ply_vertices(ply_path),
        elapsed_ms=elapsed_ms,
        status="done",
    )
    with db.get_session() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        return _to_dict(record)
