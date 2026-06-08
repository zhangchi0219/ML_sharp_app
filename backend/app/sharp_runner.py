"""SHARP 模型封装：进程内常驻一次加载，重复推理 <1s。

设计要点：
- 把 third_party/ml-sharp/src 加入 sys.path，直接 import SHARP 的纯 Python 模块。
- 只走「预测」路径（sharp.models / sharp.utils.io / sharp.utils.gaussians），
  不 import sharp.cli.predict / render（它们会牵连 gsplat 这个需编译的 CUDA 扩展）。
- _predict_image 忠实复刻自 sharp/cli/predict.py 的 predict_image，以绕开上面的 import。
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

# --- 将 ml-sharp 源码加入 import 路径（src-layout，纯 Python，无构建步骤）---
_REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/app/sharp_runner.py -> repo root
_SHARP_SRC = _REPO_ROOT / "third_party" / "ml-sharp" / "src"
if not _SHARP_SRC.exists():
    raise RuntimeError(
        f"找不到 ml-sharp 源码: {_SHARP_SRC}\n请先运行 scripts/setup.ps1 克隆并安装依赖。"
    )
if str(_SHARP_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARP_SRC))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from sharp.models import PredictorParams, create_predictor  # noqa: E402
from sharp.utils import io  # noqa: E402
from sharp.utils.gaussians import Gaussians3D, save_ply, unproject_gaussians  # noqa: E402

LOGGER = logging.getLogger("sharp_runner")

DEFAULT_MODEL_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
# 与 sharp/cli/predict.py 一致：模型内部固定在 1536x1536 上推理。
_INTERNAL_SHAPE = (1536, 1536)

_predictor = None
_device: str | None = None
# 单 GPU：串行化推理，避免并发显存峰值。
_predict_lock = threading.Lock()
_load_lock = threading.Lock()


def _select_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def device() -> str | None:
    """返回当前推理设备（未加载时为 None）。"""
    return _device


def is_ready() -> bool:
    """模型是否已加载。"""
    return _predictor is not None


def warmup(checkpoint_path: str | Path | None = None) -> None:
    """加载一次模型到内存（在 FastAPI 启动时调用）。可重复调用，已加载则跳过。"""
    global _predictor, _device
    with _load_lock:
        if _predictor is not None:
            return
        dev = _select_device()
        LOGGER.info("Loading SHARP model on device=%s ...", dev)
        if checkpoint_path:
            state_dict = torch.load(str(checkpoint_path), weights_only=True)
        else:
            # 首次运行自动从 Apple CDN 下载，缓存于 ~/.cache/torch/hub/checkpoints/
            state_dict = torch.hub.load_state_dict_from_url(DEFAULT_MODEL_URL, progress=True)
        predictor = create_predictor(PredictorParams())
        predictor.load_state_dict(state_dict)
        predictor.eval()
        predictor.to(dev)
        _predictor = predictor
        _device = dev
        LOGGER.info("SHARP model ready on device=%s.", dev)


@torch.no_grad()
def _predict_image(image: np.ndarray, f_px: float) -> Gaussians3D:
    """对单图预测 3D 高斯。复刻自 sharp.cli.predict.predict_image（避免 import render→gsplat）。"""
    assert _predictor is not None and _device is not None
    dev = torch.device(_device)

    image_pt = torch.from_numpy(image.copy()).float().to(dev).permute(2, 0, 1) / 255.0
    _, height, width = image_pt.shape
    disparity_factor = torch.tensor([f_px / width]).float().to(dev)

    image_resized = F.interpolate(
        image_pt[None],
        size=(_INTERNAL_SHAPE[1], _INTERNAL_SHAPE[0]),
        mode="bilinear",
        align_corners=True,
    )

    # 预测 NDC 空间高斯。
    gaussians_ndc = _predictor(image_resized, disparity_factor)

    intrinsics = (
        torch.tensor(
            [
                [f_px, 0, width / 2, 0],
                [0, f_px, height / 2, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )
        .float()
        .to(dev)
    )
    intrinsics_resized = intrinsics.clone()
    intrinsics_resized[0] *= _INTERNAL_SHAPE[0] / width
    intrinsics_resized[1] *= _INTERNAL_SHAPE[1] / height

    # 转换到度量空间。
    gaussians = unproject_gaussians(
        gaussians_ndc, torch.eye(4).to(dev), intrinsics_resized, _INTERNAL_SHAPE
    )
    return gaussians


def predict(image_path: str | Path, output_ply_path: str | Path) -> Path:
    """从一张图片生成 3DGS .ply，返回 .ply 路径。线程安全（单 GPU 串行）。"""
    if _predictor is None:
        raise RuntimeError("SHARP 模型尚未加载，请先调用 warmup()。")
    image_path = Path(image_path)
    output_ply_path = Path(output_ply_path)
    output_ply_path.parent.mkdir(parents=True, exist_ok=True)

    with _predict_lock:
        image, _icc, f_px = io.load_rgb(image_path)
        height, width = image.shape[:2]
        gaussians = _predict_image(image, f_px)
        save_ply(gaussians, f_px, (height, width), output_ply_path)
    return output_ply_path
