"""SHARP 模型封装：进程内常驻一次加载，重复推理。

设计要点：
- 把 third_party/ml-sharp/src 加入 sys.path，直接 import SHARP 的纯 Python 模块。
- 只走「预测」路径（sharp.models / sharp.utils.io / sharp.utils.gaussians），
  不 import sharp.cli.predict / render（它们会牵连 gsplat 这个需编译的 CUDA 扩展）。
- _predict_image 忠实复刻自 sharp/cli/predict.py 的 predict_image，以绕开上面的 import。

性能：上游的导出路径有三处纯 CPU 的瓶颈，对 118 万个高斯来说很致命。
实测 6.69s/张里有 4.50s 花在这三处（见 scripts/profile_predict.py）：

    上游实现                                    实测耗时    本模块的替代
    ─────────────────────────────────────────────────────────────────
    CPU float64 torch.linalg.svd               2.438s    GPU eigh（_decompose_fast）
    scipy Rotation.from_matrix                 0.568s    向量化四元数（同上）
    list(map(tuple, ...)) 逐行造 Python tuple    1.490s    零拷贝结构化数组（_save_ply_fast）

替换方式是在 import 阶段改写 sharp.utils.gaussians 的模块属性，
不修改 third_party —— 它是 gitignore 掉的 git clone，改了会在重新 clone 时丢失。

精度分级：一次推理导出两份——主文件 .ply（全精度，可下载）与网页轻量版 .splat
（网格抽稀 + 32 B/点的定长格式，约 9 MB）。见 _grid_subsample 与 _save_splat_fast。
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import math
import sys
import threading
from pathlib import Path
from typing import NamedTuple

from . import paths

# --- 将 ml-sharp 源码加入 import 路径（src-layout，纯 Python，无构建步骤）---
_SHARP_SRC = paths.sharp_src()
if not _SHARP_SRC.exists():
    raise RuntimeError(
        f"找不到 ml-sharp 源码: {_SHARP_SRC}\n请先运行 scripts/setup.ps1 克隆并安装依赖。"
    )
if str(_SHARP_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARP_SRC))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from plyfile import PlyData, PlyElement  # noqa: E402

from sharp.models import PredictorParams, create_predictor  # noqa: E402
from sharp.utils import color_space as cs_utils  # noqa: E402
from sharp.utils import gaussians as _g  # noqa: E402
from sharp.utils import io  # noqa: E402
from sharp.utils.gaussians import Gaussians3D, unproject_gaussians  # noqa: E402

LOGGER = logging.getLogger("sharp_runner")

DEFAULT_MODEL_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
# 与 sharp/cli/predict.py 一致：模型内部固定在 1536x1536 上推理。
# 这个值不可调：它等于 SPN 的 patch_size*4（sharp/models/encoders/spn_encoder.py），
# 而 split/merge 假设方形网格、金字塔最低层必须正好 384 才能喂给 img_size=384 的 ViT。
_INTERNAL_SHAPE = (1536, 1536)

# 35mm 全画幅对角线，用于 f_px ↔ 等效焦距(mm) 的互转（与 sharp.utils.io 同一套常数）。
_FILM_DIAGONAL_MM = math.hypot(36.0, 24.0)

_predictor = None
_device: str | None = None
# 单 GPU：串行化推理，避免并发显存峰值。
_predict_lock = threading.Lock()
_load_lock = threading.Lock()


def _quaternions_from_rotations(rotations: torch.Tensor) -> torch.Tensor:
    """旋转矩阵 → 四元数（w 在首位），在原设备上向量化计算。

    替代 sharp.utils.linalg.quaternions_from_rotation_matrices（scipy，强制走 CPU）。

    用四候选法：分别以 w/x/y/z 为主元各算一个未归一化的四元数，逐元素取分母最大的那个，
    避开单一公式在 trace ≈ -1 附近除以接近 0 的数。四个候选彼此差一个正的比例因子，
    归一化后等价。整体符号可能与 scipy 相反，但 q 与 -q 表示同一个旋转，
    且下游只用它重建协方差（对符号不敏感）。
    """
    m00, m01, m02 = rotations[..., 0, 0], rotations[..., 0, 1], rotations[..., 0, 2]
    m10, m11, m12 = rotations[..., 1, 0], rotations[..., 1, 1], rotations[..., 1, 2]
    m20, m21, m22 = rotations[..., 2, 0], rotations[..., 2, 1], rotations[..., 2, 2]

    # 四个主元的 4*分量^2，用来挑最稳的那一支。
    diag = torch.stack(
        [1 + m00 + m11 + m22, 1 + m00 - m11 - m22, 1 - m00 + m11 - m22, 1 - m00 - m11 + m22],
        dim=-1,
    )
    candidates = torch.stack(
        [
            torch.stack([diag[..., 0], m21 - m12, m02 - m20, m10 - m01], dim=-1),  # w 主
            torch.stack([m21 - m12, diag[..., 1], m01 + m10, m02 + m20], dim=-1),  # x 主
            torch.stack([m02 - m20, m01 + m10, diag[..., 2], m12 + m21], dim=-1),  # y 主
            torch.stack([m10 - m01, m02 + m20, m12 + m21, diag[..., 3]], dim=-1),  # z 主
        ],
        dim=-2,
    )
    idx = diag.argmax(dim=-1)
    picked = torch.gather(candidates, -2, idx[..., None, None].expand(*idx.shape, 1, 4))
    quaternions = picked.squeeze(-2)
    return quaternions / quaternions.norm(dim=-1, keepdim=True).clamp_min(1e-20)


# cusolver 的批量 syev 一超过某个 batch 就直接报 CUSOLVER_STATUS_INVALID_VALUE
# （RTX 5080 + CUDA 12.8 实测：8192 可以，32768 起必失败；与显存余量无关）。
# 分块规避。实测 1,179,648 个 3×3 的总耗时对比：
#     cusolver 分块 8192   0.155s   ← 采用
#     magma 整批           1.568s
#     CPU float32 eigh     1.531s
#     上游 CPU float64 SVD 2.719s
_EIGH_CHUNK = 8192

# 特征值的下限。取 float32 能正常表示的极小正数：开方后约 1e-19，
# 取 log 后约 -43，是个很负但**有限**的 scale，不会污染下游。
_MIN_EIGENVALUE = 1e-38

# 阈值可能随 GPU / 驱动而变。真遇到失败就整体退回 CPU，慢但不会让用户看到崩溃。
_eigh_use_cpu = False


def _batched_eigh(matrices: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """对 [..., 3, 3] 批量做 eigh，返回展平成 [-1, ...] 的特征值与特征向量。"""
    global _eigh_use_cpu
    flat = matrices.reshape(-1, 3, 3)

    if not _eigh_use_cpu:
        try:
            values, vectors = [], []
            for start in range(0, flat.shape[0], _EIGH_CHUNK):
                w, v = torch.linalg.eigh(flat[start : start + _EIGH_CHUNK])
                values.append(w)
                vectors.append(v)
            return torch.cat(values), torch.cat(vectors)
        except torch.cuda.OutOfMemoryError:
            # 显存不足是暂时的，不该让整个进程永久降级到 CPU——原样抛给上层。
            raise
        except RuntimeError:  # torch._C._LinAlgError 是它的子类
            _eigh_use_cpu = True
            LOGGER.warning("GPU eigh 失败，本进程后续改用 CPU（会慢约 1.4s/张）", exc_info=True)

    w, v = torch.linalg.eigh(flat.cpu())
    return w.to(matrices.device), v.to(matrices.device)


def _decompose_fast(covariance_matrices: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """协方差矩阵 → (四元数, 尺度)，全程留在 GPU 上。

    替代 sharp.utils.gaussians.decompose_covariance_matrices，后者把 118 万个 3×3
    搬到 CPU、升到 float64、做完整 SVD，实测 2.4s。协方差矩阵是对称半正定的，
    用 eigh 即可，不需要 SVD 的一般性。
    """
    dtype = covariance_matrices.dtype
    batch_shape = covariance_matrices.shape[:-2]
    # 对称化：eigh 只读下三角，先对称化可消掉前面矩阵乘累积的微小不对称。
    cov = covariance_matrices.detach()
    cov = 0.5 * (cov + cov.transpose(-1, -2))

    eigenvalues, eigenvectors = _batched_eigh(cov.float())
    eigenvalues = eigenvalues.reshape(*batch_shape, 3)
    eigenvectors = eigenvectors.reshape(*batch_shape, 3, 3)
    # eigh 返回升序，上游的 svd 返回降序——翻转以保持轴序与上游一致。
    eigenvalues = eigenvalues.flip(-1)
    eigenvectors = eigenvectors.flip(-1)

    # 特征向量矩阵可能是反射（det=-1）。翻转最后一列把它变成纯旋转，
    # 与上游 decompose_covariance_matrices 的处理一致。
    reflected = torch.linalg.det(eigenvectors) < 0
    if reflected.any():
        eigenvectors = eigenvectors.clone()
        eigenvectors[..., :, -1] *= torch.where(reflected, -1.0, 1.0)[..., None]

    quaternions = _quaternions_from_rotations(eigenvectors)
    # 特征值理论上非负，但数值上可能出现极小的负数，开方前必须夹住否则得到 NaN。
    # 夹到一个极小的正数而不是 0：save_ply 存的是 log(singular_values)，
    # 夹到 0 会写出 -inf，查看器拿到会得到零体积甚至 NaN 的泼溅。
    # （实测 teaser.jpg 的 354 万个特征值最小 7.2e-10、无一非正，这里纯属兜底。）
    singular_values = eigenvalues.clamp_min(_MIN_EIGENVALUE).sqrt()
    return quaternions.to(dtype), singular_values.to(dtype)


def _save_ply_fast(
    gaussians: Gaussians3D, f_px: float, image_shape: tuple[int, int], path: Path
) -> PlyData:
    """导出 3DGS .ply。逐字复刻 sharp.utils.gaussians.save_ply，只换掉组装 vertex 的方式。

    上游用 `list(map(tuple, arr))` 为 118 万行各造一个 14 元素的 Python tuple，实测 1.49s；
    这里所有字段同为 f4 且内存连续，直接 view 成结构化数组即可，零拷贝。

    其余 7 个元素（extrinsic/intrinsic/image_size/frame/disparity/color_space/version）
    都只有 2–16 项，不是瓶颈，但顺序与内容必须与上游完全一致，否则查看器读不了。
    """

    def _inverse_sigmoid(tensor: torch.Tensor) -> torch.Tensor:
        return torch.log(tensor / (1.0 - tensor))

    xyz = gaussians.mean_vectors.flatten(0, 1)
    scale_logits = torch.log(gaussians.singular_values).flatten(0, 1)
    quaternions = gaussians.quaternions.flatten(0, 1)
    # 与上游一致：导出时强制把 linearRGB 转成 sRGB，以兼容公共查看器。
    colors = _g.convert_rgb_to_spherical_harmonics(
        cs_utils.linearRGB2sRGB(gaussians.colors.flatten(0, 1))
    )
    opacity_logits = _inverse_sigmoid(gaussians.opacities).flatten(0, 1).unsqueeze(-1)

    attributes = torch.cat((xyz, colors, opacity_logits, scale_logits, quaternions), dim=1)

    field_names = (
        ["x", "y", "z"]
        + [f"f_dc_{i}" for i in range(3)]
        + ["opacity"]
        + [f"scale_{i}" for i in range(3)]
        + [f"rot_{i}" for i in range(4)]
    )
    dtype_full = [(name, "f4") for name in field_names]

    num_gaussians = len(xyz)
    arr = attributes.detach().cpu().numpy().astype(np.float32, copy=False)
    # view 要求 C 连续且最后一维正好铺满一条记录（14 个 f4）。
    arr = np.ascontiguousarray(arr)
    assert arr.shape == (num_gaussians, len(field_names)), arr.shape
    elements = arr.view(dtype_full).reshape(num_gaussians)
    vertex_elements = PlyElement.describe(elements, "vertex")

    image_height, image_width = image_shape

    image_size_array = np.empty(2, dtype=[("image_size", "u4")])
    image_size_array[:] = np.array([image_width, image_height])
    image_size_element = PlyElement.describe(image_size_array, "image_size")

    intrinsic_array = np.empty(9, dtype=[("intrinsic", "f4")])
    intrinsic_array[:] = np.array(
        [f_px, 0, image_width * 0.5, 0, f_px, image_height * 0.5, 0, 0, 1]
    ).flatten()
    intrinsic_element = PlyElement.describe(intrinsic_array, "intrinsic")

    extrinsic_array = np.empty(16, dtype=[("extrinsic", "f4")])
    extrinsic_array[:] = np.eye(4).flatten()
    extrinsic_element = PlyElement.describe(extrinsic_array, "extrinsic")

    frame_array = np.empty(2, dtype=[("frame", "i4")])
    frame_array[:] = np.array([1, num_gaussians], dtype=np.int32)
    frame_element = PlyElement.describe(frame_array, "frame")

    disparity_array = np.empty(2, dtype=[("disparity", "f4")])
    disparity = 1.0 / gaussians.mean_vectors[0, ..., -1]
    disparity_array[:] = (
        torch.quantile(disparity, q=torch.tensor([0.1, 0.9], device=disparity.device))
        .float()
        .cpu()
        .numpy()
    )
    disparity_element = PlyElement.describe(disparity_array, "disparity")

    color_space_array = np.empty(1, dtype=[("color_space", "u1")])
    color_space_array[:] = np.array([cs_utils.encode_color_space("sRGB")]).flatten()
    color_space_element = PlyElement.describe(color_space_array, "color_space")

    version_array = np.empty(3, dtype=[("version", "u1")])
    version_array[:] = np.array([1, 5, 0], dtype=np.uint8).flatten()
    version_element = PlyElement.describe(version_array, "version")

    plydata = PlyData(
        [
            vertex_elements,
            extrinsic_element,
            intrinsic_element,
            image_size_element,
            frame_element,
            disparity_element,
            color_space_element,
            version_element,
        ]
    )
    plydata.write(path)
    return plydata


def _save_splat_fast(gaussians: Gaussians3D, path: Path) -> int:
    """导出 .splat（antimatter15 定长格式），返回点数。网页端加载用。

    .ply 每点 14 个 float32 = 56 B；.splat 每点固定 32 B，几乎腰斩，且查看器
    （@mkkellogg/gaussian-splats-3d 的 SplatParser）不必解析 ASCII 头。字段布局：

        偏移  0–11   center    float32 × 3
        偏移 12–23   scale     float32 × 3   ← 线性尺度，不是 .ply 里的 log
        偏移 24–27   color     uint8   × 4   ← RGBA，不是 .ply 里的 SH 系数
        偏移 28–31   rotation  uint8   × 4   ← (w,x,y,z)，编码为 q*128+128

    位置与尺度仍是全精度 float32；被量化到 8 bit 的只有颜色、透明度与旋转——
    这是该格式的固有取舍，所有 .splat 文件都一样。
    """
    xyz = gaussians.mean_vectors.flatten(0, 1)
    scales = gaussians.singular_values.flatten(0, 1)
    # 与 _save_ply_fast 一致：导出时把 linearRGB 转成 sRGB，以兼容公共查看器。
    rgb = cs_utils.linearRGB2sRGB(gaussians.colors.flatten(0, 1))
    alpha = gaussians.opacities.flatten(0, 1).unsqueeze(-1)

    quaternions = gaussians.quaternions.flatten(0, 1)
    # 上游解析器会对读出的四元数再做一次 normalize，但先归一化才能保证 q*128+128
    # 落在 uint8 的表示范围内；这里的输入本就是单位四元数，仅作兜底。
    quaternions = quaternions / quaternions.norm(dim=-1, keepdim=True).clamp_min(1e-20)

    color_u8 = (torch.cat((rgb, alpha), dim=1).clamp(0, 1) * 255).round().to(torch.uint8)
    # q = ±1 会算出 0 / 256，256 溢出 uint8，故夹到 255 再转换（上游用 Uint8ClampedArray
    # 写入，行为相同）。
    rot_u8 = (quaternions * 128 + 128).round().clamp(0, 255).to(torch.uint8)

    record = np.dtype(
        [("center", "<f4", (3,)), ("scale", "<f4", (3,)), ("color", "u1", (4,)), ("rot", "u1", (4,))]
    )
    assert record.itemsize == 32, record.itemsize

    num_gaussians = len(xyz)
    out = np.empty(num_gaussians, dtype=record)
    out["center"] = xyz.detach().cpu().numpy()
    out["scale"] = scales.detach().cpu().numpy()
    out["color"] = color_u8.cpu().numpy()
    out["rot"] = rot_u8.cpu().numpy()

    path.parent.mkdir(parents=True, exist_ok=True)
    out.tofile(path)
    return num_gaussians


# apply_transform 按模块全局名调用 decompose_covariance_matrices，改写模块属性即可生效，
# 不必复刻 apply_transform / unproject_gaussians 本身。
# 保留上游实现的引用，等价性验证脚本要拿它跟新实现对拍。
_ORIG_DECOMPOSE = _g.decompose_covariance_matrices
_ORIG_SAVE_PLY = _g.save_ply
_g.decompose_covariance_matrices = _decompose_fast


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


def device_info() -> dict:
    """当前推理硬件的描述，供 /api/health 暴露给前端与故障诊断。

    不依赖模型是否已加载——CUDA 不可用时也要能告诉用户"将回退 CPU"。
    """
    info: dict = {
        "deviceName": None,
        "vramTotalMb": None,
        "vramPeakMb": None,
        "cudaAvailable": torch.cuda.is_available(),
    }
    if not torch.cuda.is_available():
        return info
    try:
        props = torch.cuda.get_device_properties(0)
        info["deviceName"] = props.name
        info["vramTotalMb"] = round(props.total_memory / 1024**2)
        # 峰值分配量：跑过至少一次推理后才有意义，是判断显存够不够的直接依据。
        peak = torch.cuda.max_memory_allocated()
        info["vramPeakMb"] = round(peak / 1024**2) if peak else None
    except Exception:  # noqa: BLE001 — 诊断信息拿不到不该影响服务
        LOGGER.warning("读取 GPU 信息失败", exc_info=True)
    return info


def warmup(checkpoint_path: str | Path | None = None) -> None:
    """加载一次模型到内存（在 FastAPI 启动时调用）。可重复调用，已加载则跳过。

    未显式传入权重时，优先用随包分发的权重（paths.checkpoint_path()），
    没有则从 Apple CDN 下载并缓存。
    """
    global _predictor, _device
    with _load_lock:
        if _predictor is not None:
            return
        checkpoint_path = checkpoint_path or paths.checkpoint_path()
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


def _f_px_to_focal35(f_px: float, width: int, height: int) -> float:
    """f_px → 35mm 等效焦距(mm)。sharp.utils.io.convert_focallength 的逆运算。"""
    return f_px * _FILM_DIAGONAL_MM / math.hypot(width, height)


# delta_factor 各字段的出厂值（sharp.models.params.DeltaFactor）。UI 传的是「相对默认值的倍率」，
# 这样 1.0× 恒等于原生 SHARP 行为，用户不必理解 0.001 这种数量级。
_DELTA_DEFAULTS = {"color": 0.1, "scale": 1.0, "quaternion": 1.0, "opacity": 1.0, "z": 0.001}
_DEFAULT_MAX_SCALE = 10.0


@contextlib.contextmanager
def _composed_with(gains: dict[str, float], max_scale: float):
    """临时改写 GaussianComposer 的推理参数，退出时还原。必须在 _predict_lock 内调用。

    GaussianComposer（sharp/models/composer.py）不含任何 nn.Parameter / buffer，
    delta_factor 与 max_scale 都是纯 Python 属性，且每次 forward 都重新读
    （见 _forward_mean / _scale_activation / _color_activation），
    所以改属性即刻生效——不必重载那 2.7 GB 权重（重载要 20–30 秒）。

    delta_factor 是一个**共享的 dataclass 实例**，绝不能原地改字段：那会污染后续所有请求。
    这里用 dataclasses.replace 造一个新实例整体换上，finally 换回原对象引用。
    """
    assert _predictor is not None
    composer = _predictor.gaussian_composer

    scaled = {k: _DELTA_DEFAULTS[k] * gains.get(k, 1.0) for k in _DELTA_DEFAULTS}
    unchanged = all(
        abs(scaled[k] - _DELTA_DEFAULTS[k]) < 1e-12 for k in _DELTA_DEFAULTS
    ) and abs(max_scale - _DEFAULT_MAX_SCALE) < 1e-12
    if unchanged:
        # 默认路径零开销，也保证默认参数的输出与改造前逐字节一致。
        yield
        return

    original_delta_factor = composer.delta_factor
    original_max_scale = composer.max_scale
    try:
        composer.delta_factor = dataclasses.replace(original_delta_factor, **scaled)
        composer.max_scale = max_scale
        yield
    finally:
        composer.delta_factor = original_delta_factor
        composer.max_scale = original_max_scale


def _scale_gaussians(gaussians: Gaussians3D, scale_mul: float) -> Gaussians3D:
    """对每个高斯的 3D 尺度（singular_values）乘一个全局系数。

    save_ply 存的是 log(singular_values)，乘法即对数空间平移，安全无副作用。
    """
    if abs(scale_mul - 1.0) <= 1e-6:
        return gaussians
    return gaussians._replace(singular_values=gaussians.singular_values * scale_mul)


# 网页轻量版的抽样步长。294,912 点 × 32 B ≈ 9.0 MB，是「肉眼几乎无损」与「能在网页
# 里秒开」的交点。主文件已经比它更稀时不再二次抽样（见 predict 里的 max）。
_WEB_GRID_STEP = 2


def _grid_shape() -> tuple[int, int]:
    """当前模型的高斯网格形状 (层数, 边长)。必须在 warmup 之后调用。"""
    assert _predictor is not None
    initializer = _predictor.init_model
    return initializer.num_layers, _INTERNAL_SHAPE[0] // initializer.stride


def _grid_subsample(gaussians: Gaussians3D, step: int) -> Gaussians3D:
    """按网格跨步抽稀，保留 1/step² 的高斯，并把尺度放大 step 倍补偿覆盖。

    SHARP 的高斯不是自由点云，而是严格的规则网格：MultiLayerInitializer 在 1536² 的
    内部分辨率上以 stride=2 铺 num_layers=2 层，共 2 × 768 × 768 = 1,179,648 个。
    GaussianComposer.forward 的展平顺序是 `permute(0,2,3,4,1).flatten(1,3)`，即
    layer→row→col，所以 reshape 回 [1, L, S, S, ...] 后按行列跨步切片，
    拿到的就是空间上均匀的降采样，两层都等比保留。

    这比「按不透明度 Top-K」更适合做 LOD：Top-K 会整体偏向表面层，而第二层是补洞层、
    基础不透明度只有 1/num_layers，大比例裁剪时会被整片削掉，一转视角就露背景。

    尺度补偿是必须的：相邻高斯的间距随 step 线性变大，基准尺度本身也正比于 stride
    （`initializer._create_base_scale` 里的 `disparity_scale_factor`），
    不把 singular_values 一并乘 step，抽稀后的画面会出现网格状的缝。
    """
    if step <= 1:
        return gaussians

    layers, side = _grid_shape()
    num = gaussians.opacities.shape[1]
    if num != layers * side * side:
        # 架构参数被改动过（README 记为不可调）。宁可不抽稀也不要按错误的形状 reshape。
        LOGGER.warning("高斯数 %d 与网格 %d×%d×%d 不符，跳过降采样", num, layers, side, side)
        return gaussians

    def _take(tensor: torch.Tensor) -> torch.Tensor:
        # opacities 是 [1, N]，其余是 [1, N, C]；用尾部维度统一处理。
        channels = tensor.shape[2:]
        grid = tensor.reshape(1, layers, side, side, *channels)
        return grid[:, :, ::step, ::step].reshape(1, -1, *channels)

    return Gaussians3D(
        mean_vectors=_take(gaussians.mean_vectors),
        singular_values=_take(gaussians.singular_values) * step,
        quaternions=_take(gaussians.quaternions),
        colors=_take(gaussians.colors),
        opacities=_take(gaussians.opacities),
    )


class PredictResult(NamedTuple):
    """一次生成的产出摘要。"""

    detected_focal35: float
    """图片 EXIF 推出的 35mm 等效焦距（与实际使用的焦距无关）。"""
    num_points: int
    """主文件（.ply）的高斯数。"""
    web_points: int | None
    """轻量文件（.splat）的高斯数；未导出时为 None。"""


def predict(
    image_path: str | Path,
    output_ply_path: str | Path,
    *,
    web_output_path: str | Path | None = None,
    scale_mul: float = 1.0,
    detail: int = 1,
    focal35: float | None = None,
    gains: dict[str, float] | None = None,
    max_scale: float = _DEFAULT_MAX_SCALE,
) -> PredictResult:
    """从一张图片生成 3DGS，写出主文件 .ply 与（可选）网页轻量版 .splat。

    线程安全（单 GPU 串行）。全部参数取默认值时，.ply 与未引入参数功能前逐字节一致。

    **两份产物只跑一次推理。** 前向占了单张 1.01s 里的 0.87s，导出是白送的
    （见 README「性能」），所以轻量版从同一份 Gaussians3D 二次抽样导出，
    不重复推理，也保证两份内容严格对应。

    导出后处理：
        scale_mul：泼溅尺寸整体比例（1.0=原始）。
        detail：主文件的网格抽样步长 k，保留 1/k² 的泼溅（1=全量 118 万）。
            轻量版用 max(detail, _WEB_GRID_STEP)——主文件已经更稀时不再二次抽样。
    推理参数：
        focal35：35mm 等效焦距(mm)。None=沿用图片 EXIF（无 EXIF 时上游按 30mm 兜底）。
            它同时决定 disparity_factor（单目深度→米制）与反投影内参，是影响纵深最大的单一变量。
        gains：delta_factor 各项相对默认值的倍率，见 _DELTA_DEFAULTS。
        max_scale：尺度激活上界。**必须 > 1**，否则 composer._get_scale_activation_constant 会除零。
    """
    if _predictor is None:
        raise RuntimeError("SHARP 模型尚未加载，请先调用 warmup()。")
    if max_scale <= 1.0:
        raise ValueError(f"max_scale 必须 > 1（收到 {max_scale}）")
    if detail < 1:
        raise ValueError(f"detail 必须 ≥ 1（收到 {detail}）")
    image_path = Path(image_path)
    output_ply_path = Path(output_ply_path)
    output_ply_path.parent.mkdir(parents=True, exist_ok=True)

    with _predict_lock:
        from .image_io import load_rgb
        image, _icc, f_px = load_rgb(image_path)
        height, width = image.shape[:2]
        detected_focal35 = _f_px_to_focal35(f_px, width, height)
        if focal35 is not None:
            f_px = io.convert_focallength(width, height, focal35)

        with _composed_with(gains or {}, max_scale):
            gaussians = _predict_image(image, f_px)
        gaussians = _scale_gaussians(gaussians, scale_mul)

        full = _grid_subsample(gaussians, detail)
        _save_ply_fast(full, f_px, (height, width), output_ply_path)

        web_points = None
        if web_output_path is not None:
            web_step = max(detail, _WEB_GRID_STEP)
            # 抽样一律从完整网格出发：full 可能已被抽稀，网格形状不再成立。
            web = full if web_step == detail else _grid_subsample(gaussians, web_step)
            web_points = _save_splat_fast(web, Path(web_output_path))

    return PredictResult(
        detected_focal35=detected_focal35,
        num_points=full.opacities.shape[1],
        web_points=web_points,
    )
