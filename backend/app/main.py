"""FastAPI 应用：上传照片 → SHARP 生成 3DGS .ply → 历史 / 静态服务。"""

from __future__ import annotations

import io as _io
import asyncio
import threading
from datetime import timezone
from functools import wraps
import json
import logging
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from . import db, paths, sharp_runner, image_io
from .models import Generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("sharp_app")

# StaticFiles 在挂载时就要求目录存在，故这里先建好。
paths.ensure_data_dirs()
UPLOAD_DIR = paths.uploads_dir()
GAUSS_DIR = paths.gaussians_dir()
THUMB_DIR = paths.thumbs_dir()

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
MAX_BYTES = 40 * 1024 * 1024  # 40MB

# .splat 不在系统 mime 表里，StaticFiles 猜不出来就会发 text/plain——查看器读 arrayBuffer
# 不受影响，但中间的代理有可能按文本处理。显式登记成二进制。
mimetypes.add_type("application/octet-stream", ".splat")


class GenParams(BaseModel):
    """一次生成的全部可调参数。范围在此唯一定义——前端 lib/types.ts 的滑块要与之同步。

    NaN/Inf 由 pydantic 的 ge/le 直接挡下（与 NaN 的比较恒为 False → 422）。
    这条防线必须留着：手写的 min/max 夹取对 NaN 是恒等的（max(nan, 0.5) 仍是 nan），
    夹取会整个失效，最终写出一份全是 NaN 的 .ply。
    """

    model_config = {"extra": "forbid"}

    # 导出后处理。
    scale: float = Field(1.0, ge=0.5, le=2.0, description="泼溅尺寸整体比例")
    # 网格抽样步长：保留 1/detail² 的泼溅。整数——抽样是在 768×768 的高斯网格上按行列
    # 跨步做的，只有整数步长才能保持空间均匀（见 sharp_runner._grid_subsample）。
    detail: int = Field(1, ge=1, le=4, description="网格抽样步长，保留 1/k² 的泼溅")
    # 推理参数。
    focal35: float | None = Field(None, ge=14.0, le=85.0, description="35mm 等效焦距；None=跟随 EXIF")
    colorGain: float = Field(1.0, ge=0.0, le=3.0, description="色彩修正强度倍率")
    scaleGain: float = Field(1.0, ge=0.0, le=3.0, description="大小变化强度倍率")
    shapeGain: float = Field(1.0, ge=0.0, le=3.0, description="各向异性拉伸强度倍率")
    opacityGain: float = Field(1.0, ge=0.0, le=3.0, description="不透明度对比强度倍率")
    depthGain: float = Field(1.0, ge=0.0, le=3.0, description="深度位移强度倍率")
    # 下界必须 > 1：composer._get_scale_activation_constant 会除以 (max_scale - 1)。
    maxScale: float = Field(10.0, ge=1.5, le=20.0, description="尺度激活上界")

    def to_runner_kwargs(self) -> dict:
        """映射到 sharp_runner.predict 的关键字参数。"""
        return {
            "scale_mul": self.scale,
            "detail": self.detail,
            "focal35": self.focal35,
            "max_scale": self.maxScale,
            "gains": {
                "color": self.colorGain,
                "scale": self.scaleGain,
                "quaternion": self.shapeGain,
                "opacity": self.opacityGain,
                "z": self.depthGain,
            },
        }


def _parse_params(raw: str) -> GenParams:
    """解析前端传来的 params JSON 字符串；无效时抛 400 并带上字段级原因。"""
    try:
        return GenParams.model_validate_json(raw)
    except ValidationError as exc:
        details = "；".join(
            f"{'.'.join(str(x) for x in e['loc']) or '参数'}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(400, f"参数不合法 —— {details}") from exc

# 启动预热若失败，记录原因，让接口给出清晰提示而非整服务崩溃。
_warmup_error: str | None = None
_mutation_lock = threading.RLock()


def coordinated(fn):
    @wraps(fn)
    def locked(*args, **kwargs):
        with _mutation_lock:
            return fn(*args, **kwargs)
    return locked



@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _warmup_error
    db.init_db()
    _warmup_error = None
    async def load():
        global _warmup_error
        try:
            await run_in_threadpool(sharp_runner.warmup)
        except Exception as exc:
            _warmup_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("SHARP model loading failed")
    task = asyncio.create_task(load())
    try:
        yield
    finally:
        await task



app = FastAPI(title="单张高斯泼溅", lifespan=lifespan)
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
        # 网页轻量版；早于本功能的记录为 null，前端退回 plyUrl。
        "webUrl": f"/files/gaussians/{Path(g.web_path).name}" if g.web_path else None,
        "thumbUrl": f"/files/thumbs/{Path(g.thumb_path).name}",
        "numPoints": g.num_points,
        "webPoints": g.web_points,
        "elapsedMs": g.elapsed_ms,
        "status": g.status,
        "createdAt": (g.created_at.replace(tzinfo=timezone.utc) if g.created_at.tzinfo is None else g.created_at.astimezone(timezone.utc)).isoformat(),
        # 迁移前的老记录没有这两项，返回 null；前端用默认值兜住。
        "params": json.loads(g.params) if g.params else None,
        "detectedFocal35": g.detected_focal35,
    }


@app.get("/api/health")
def health() -> dict:
    """就绪状态 + 硬件信息。硬件信息是把应用发给别人后最需要的诊断依据。"""
    return {
        "ready": sharp_runner.is_ready(),
        "device": sharp_runner.device(),
        "error": _warmup_error,
        **sharp_runner.device_info(),
    }


@app.get("/api/history")
def history() -> list[dict]:
    with db.get_session() as session:
        rows = session.exec(
            select(Generation).order_by(Generation.created_at.desc())
        ).all()
        return [_to_dict(r) for r in rows]


def _safe_unlink(path: Path) -> None:
    """删文件，失败只记日志不抛。

    Windows 上 StaticFiles 可能正握着一个下载到一半的 .ply；删不掉最多留个孤儿文件，
    不该让整个删除请求失败——数据库那行已经删了，用户看到的结果是对的。
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # noqa: PERF203
        LOGGER.warning("删除文件失败 %s: %s", path, exc)


@app.delete("/api/history/{gen_id}")
@coordinated
def delete_generation(gen_id: str) -> dict:
    """删除一条记录及其产出文件。

    ⚠️ regenerate 刻意让多条记录**共用**同一份源图与缩略图（见 _run_generation 的说明），
    只有 .ply 是一对一的。所以源图/缩略图必须先确认没有兄弟记录还在引用才能删，
    否则同图重跑的另一条记录会在画廊里变成裂图。
    """
    with db.get_session() as session:
        row = session.get(Generation, gen_id)
        if row is None:
            raise HTTPException(404, "找不到该生成记录")
        image_name, thumb_name, ply_name = row.image_path, row.thumb_path, row.ply_path
        web_name = row.web_path
        session.delete(row)
        session.commit()
        # 行已删掉，此刻还引用同一张源图的就是兄弟记录。
        # image_path 与 thumb_path 在 _run_generation 里总是成对复用，判一次即可覆盖两者。
        still_used = (
            session.exec(select(Generation).where(Generation.image_path == image_name)).first()
            is not None
        )

    # 一律取 .name：路径来自库里，但与 _to_dict 保持同一道防穿越姿势。
    # .ply 与 .splat 都是一对一的，跟着记录一起删。
    _safe_unlink(GAUSS_DIR / Path(ply_name).name)
    if web_name:
        _safe_unlink(GAUSS_DIR / Path(web_name).name)
    if not still_used:
        _safe_unlink(UPLOAD_DIR / Path(image_name).name)
        _safe_unlink(THUMB_DIR / Path(thumb_name).name)
    return {"deleted": gen_id}


def _run_generation(
    *,
    gen_id: str,
    image_name: str,
    thumb_name: str,
    original_filename: str,
    params: GenParams,
) -> dict:
    """跑一次推理并落库，返回给前端的记录。generate / regenerate 共用。

    image_name / thumb_name 是数据目录下的文件名——regenerate 直接复用源记录的那两份，
    不再复制文件，因此同一张图的多次生成在画廊里共用缩略图，可并排对比。
    """
    if not sharp_runner.is_ready():
        raise HTTPException(503, f"SHARP 模型未就绪：{_warmup_error or '正在加载，请稍候'}")

    ply_path = GAUSS_DIR / f"{gen_id}.ply"
    web_path = GAUSS_DIR / f"{gen_id}.splat"
    t0 = time.perf_counter()
    try:
        result = sharp_runner.predict(
            UPLOAD_DIR / image_name,
            ply_path,
            web_output_path=web_path,
            **params.to_runner_kwargs(),
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("生成失败")
        _safe_unlink(ply_path)
        _safe_unlink(web_path)
        raise HTTPException(500, f"生成失败：{exc}") from exc
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    record = Generation(
        id=gen_id,
        original_filename=original_filename,
        image_path=image_name,
        ply_path=ply_path.name,
        thumb_path=thumb_name,
        num_points=result.num_points,
        elapsed_ms=elapsed_ms,
        status="done",
        params=params.model_dump_json(),
        detected_focal35=result.detected_focal35,
        web_path=web_path.name,
        web_points=result.web_points,
    )
    try:
        with db.get_session() as session:
            session.add(record)
            response = _to_dict(record)
            session.commit()
            return response
    except Exception:
        _safe_unlink(ply_path)
        _safe_unlink(web_path)
        raise



@app.post("/api/generate")
async def generate(
    file: UploadFile = File(...),
    # 参数集中在一个 JSON 字段里，而不是逐个 Form(...)：加参数时前后端各只改一处。
    params: str = Form("{}"),
) -> dict:
    if not sharp_runner.is_ready():
        raise HTTPException(503, f"SHARP 模型未就绪：{_warmup_error or '正在加载，请稍候'}")

    gen_params = _parse_params(params)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的图片类型：{ext or '未知'}")

    try:
        data = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "图片过大（上限 40MB）")

    return await run_in_threadpool(_generate_upload, data, ext, file.filename, gen_params)


@coordinated
def _generate_upload(data: bytes, ext: str, filename: str | None, params: GenParams) -> dict:
    try:
        im, _ = image_io.decode_image(_io.BytesIO(data))
    except Exception as exc:
        raise HTTPException(400, f"无法读取图片：{exc}") from exc
    gen_id = uuid.uuid4().hex
    image_path = UPLOAD_DIR / f"{gen_id}{ext}"
    thumb_path = THUMB_DIR / f"{gen_id}.jpg"
    created = [image_path, thumb_path, GAUSS_DIR / f"{gen_id}.ply", GAUSS_DIR / f"{gen_id}.splat"]
    try:
        image_path.write_bytes(data)
        im.thumbnail((512, 512))
        im.save(thumb_path, "JPEG", quality=85)
        return _run_generation(gen_id=gen_id, image_name=image_path.name,
            thumb_name=thumb_path.name, original_filename=filename or image_path.name, params=params)
    except Exception:
        for path in created:
            _safe_unlink(path)
        raise


@app.post("/api/regenerate/{source_id}")
@coordinated
def regenerate(source_id: str, params: str = Form("{}")) -> dict:
    """用新参数重跑已有记录的源图，产出一条**新**记录（不覆盖原来的，便于对比）。"""
    gen_params = _parse_params(params)

    with db.get_session() as session:
        source = session.get(Generation, source_id)
        if source is None:
            raise HTTPException(404, "找不到该生成记录")
        image_name, thumb_name = source.image_path, source.thumb_path
        original_filename = source.original_filename

    if not (UPLOAD_DIR / image_name).exists():
        raise HTTPException(404, f"源图已不存在：{image_name}")

    return _run_generation(
        gen_id=uuid.uuid4().hex,
        image_name=image_name,
        thumb_name=thumb_name,
        original_filename=original_filename,
        params=gen_params,
    )


# ── 便捷启动：托管已构建的前端（单进程·单端口）──
# 若 frontend/dist 存在（已 `npm run build`），把它挂到 "/"——这样后端一个进程即可
# 同时提供 API、静态产物与前端页面，无需再单独跑 Vite。必须在所有 /api、/files
# 之后挂载，否则 "/" 会抢占它们（Starlette 按注册顺序匹配）。
FRONTEND_DIST = paths.frontend_dist()
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    LOGGER.info("已挂载前端静态目录：%s", FRONTEND_DIST)
else:
    LOGGER.info("未找到前端构建产物（%s）；单进程托管前请先 `npm run build`。", FRONTEND_DIST)
