"""验证优化后的导出路径与上游实现数值等价。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\verify_equivalence.py

对拍两件事：
  1) _decompose_fast  vs  上游 decompose_covariance_matrices（CPU float64 SVD）
     四元数与特征向量都有符号/方向的自由度，不能逐位比。真正的不变量是
     **重建出的协方差矩阵** R·diag(s²)·Rᵀ —— 它才是下游渲染真正用到的东西。
  2) _save_ply_fast   vs  上游 save_ply
     同一份高斯分别导出，比 PLY 头部结构与每个字段的数值。
     这条路径没换算法，只换了组装方式，应当逐位相同。
"""

from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

import numpy as np
import torch
from plyfile import PlyData

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app import sharp_runner  # noqa: E402
from sharp.utils import gaussians as _g  # noqa: E402
from sharp.utils.gaussians import compose_covariance_matrices  # noqa: E402

SAMPLE = _ROOT / "third_party" / "ml-sharp" / "data" / "teaser.jpg"
OUT = Path(os.environ.get("SHARP_EQUIV_DIR", str(Path(tempfile.gettempdir()) / "sharp_equiv")))

_failures: list[str] = []


def check(label: str, ok: bool, detail: str) -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {label:<44} {detail}")
    if not ok:
        _failures.append(label)


def check_decompose() -> None:
    print("\n=== 1) 协方差分解：新实现 vs 上游 CPU float64 SVD ===")
    torch.manual_seed(0)
    dev = sharp_runner.device() or "cpu"

    # 造一批有代表性的协方差矩阵：随机旋转 + 跨 4 个数量级的尺度，
    # 再额外塞入退化情形（各向同性、近似退化的双重特征值）。
    n = 200_000
    quats = torch.randn(1, n, 4, device=dev)
    quats = quats / quats.norm(dim=-1, keepdim=True)
    scales = torch.rand(1, n, 3, device=dev) * 0.999 + 1e-3
    scales[0, :1000] = 0.05                      # 各向同性（特征值三重重根）
    scales[0, 1000:2000, :2] = 0.2               # 双重重根
    cov = compose_covariance_matrices(quats, scales)

    q_new, s_new = sharp_runner._decompose_fast(cov)
    q_old, s_old = sharp_runner._ORIG_DECOMPOSE(cov)

    # 尺度是排序后的特征值开方，两边都应降序，可直接比。
    s_err = (s_new.float() - s_old.float()).abs().max().item()
    check("尺度（奇异值）最大绝对误差", s_err < 1e-4, f"{s_err:.3e}  (阈值 1e-4)")

    # 四元数逐位比没有意义（q 与 -q 等价，重根时特征向量方向任意），
    # 比重建出的协方差——这才是渲染真正用到的量。
    cov_new = compose_covariance_matrices(q_new, s_new)
    cov_old = compose_covariance_matrices(q_old, s_old)
    err_new = (cov_new - cov).abs().max().item()
    err_old = (cov_old - cov).abs().max().item()
    check("新实现重建协方差 vs 原始", err_new < 1e-5, f"{err_new:.3e}  (阈值 1e-5)")
    check("上游重建协方差 vs 原始（参照）", True, f"{err_old:.3e}")
    check("新实现不差于上游", err_new <= max(err_old * 10, 1e-5), f"new={err_new:.3e} old={err_old:.3e}")
    check("无 NaN / Inf", bool(torch.isfinite(q_new).all() and torch.isfinite(s_new).all()), "")
    check("四元数已归一化", (q_new.norm(dim=-1) - 1).abs().max().item() < 1e-5, "")


def check_save_ply() -> None:
    print("\n=== 2) PLY 导出：新实现 vs 上游 save_ply（同一份高斯）===")
    OUT.mkdir(parents=True, exist_ok=True)
    sharp_runner.warmup()

    image, _icc, f_px = sharp_runner.io.load_rgb(SAMPLE)
    height, width = image.shape[:2]
    gaussians = sharp_runner._predict_image(image, f_px)

    p_new = OUT / "new.ply"
    p_old = OUT / "old.ply"
    sharp_runner._save_ply_fast(gaussians, f_px, (height, width), p_new)
    sharp_runner._ORIG_SAVE_PLY(gaussians, f_px, (height, width), p_old)

    d_new, d_old = PlyData.read(p_new), PlyData.read(p_old)

    names_new = [e.name for e in d_new.elements]
    names_old = [e.name for e in d_old.elements]
    check("元素名称与顺序一致", names_new == names_old, f"{names_new}")

    v_new, v_old = d_new["vertex"], d_old["vertex"]
    check("vertex 字段名与顺序一致", v_new.data.dtype.names == v_old.data.dtype.names,
          f"{len(v_new.data.dtype.names)} 个字段")
    check("vertex 数量一致", len(v_new.data) == len(v_old.data), f"{len(v_new.data):,}")

    worst = 0.0
    for name in v_new.data.dtype.names:
        diff = np.abs(v_new.data[name].astype(np.float64) - v_old.data[name].astype(np.float64))
        worst = max(worst, float(diff.max()))
    check("vertex 所有字段逐位相同", worst == 0.0, f"最大差值 {worst:.3e}")

    for name in names_new:
        if name == "vertex":
            continue
        a, b = d_new[name].data, d_old[name].data
        same = a.dtype == b.dtype and np.array_equal(a, b)
        check(f"元素 {name} 完全一致", same, f"{a.dtype.names} × {len(a)}")

    check("文件大小一致", p_new.stat().st_size == p_old.stat().st_size,
          f"{p_new.stat().st_size / 1e6:.1f} MB")


def check_end_to_end() -> None:
    """整条路径对拍：旧 decompose + 旧 save_ply  vs  新 decompose + 新 save_ply。

    这条是必要的——check_save_ply 给两个导出函数喂的是**同一份**高斯，
    因此测不出 decompose 换算法带来的差异。真实分发出去的是这里比的东西。
    """
    print("\n=== 3) 端到端：完整旧路径 vs 完整新路径 ===")
    sharp_runner.warmup()
    image, _icc, f_px = sharp_runner.io.load_rgb(SAMPLE)
    height, width = image.shape[:2]

    _g.decompose_covariance_matrices = sharp_runner._ORIG_DECOMPOSE
    g_old = sharp_runner._predict_image(image, f_px)
    _g.decompose_covariance_matrices = sharp_runner._decompose_fast
    g_new = sharp_runner._predict_image(image, f_px)

    # 不经过特征分解的量必须逐位相同。
    for field in ("mean_vectors", "colors", "opacities"):
        d = (getattr(g_old, field) - getattr(g_new, field)).abs().max().item()
        check(f"{field} 逐位相同", d == 0.0, f"{d:.3e}")

    d_s = (g_old.singular_values - g_new.singular_values).abs().max().item()
    check("singular_values 差异在容差内", d_s < 1e-4, f"{d_s:.3e}  (阈值 1e-4)")

    # 四元数有符号自由度，比重建出的协方差才有意义。
    cov_old = compose_covariance_matrices(g_old.quaternions, g_old.singular_values)
    cov_new = compose_covariance_matrices(g_new.quaternions, g_new.singular_values)
    d_cov = (cov_old - cov_new).abs().max().item()
    check("重建协方差差异在容差内", d_cov < 1e-5, f"{d_cov:.3e}  (阈值 1e-5)")

    # 防回归：clamp 到 0 会让 save_ply 的 log() 写出 -inf。
    sv = g_new.singular_values
    check("singular_values 全为正", bool((sv > 0).all()), f"min={sv.min().item():.3e}")
    check("log(singular_values) 全有限", bool(torch.isfinite(torch.log(sv)).all()), "")

    out = OUT / "e2e_new.ply"
    sharp_runner._save_ply_fast(g_new, f_px, (height, width), out)
    v = PlyData.read(out)["vertex"].data
    bad = {n: int((~np.isfinite(v[n])).sum()) for n in v.dtype.names}
    total_bad = sum(bad.values())
    check("导出的 PLY 无 NaN/Inf", total_bad == 0,
          f"{total_bad} 个" + (f" -> {[k for k, c in bad.items() if c]}" if total_bad else ""))


def main() -> None:
    assert SAMPLE.exists(), f"找不到样图: {SAMPLE}"
    check_decompose()
    check_save_ply()
    check_end_to_end()
    print()
    if _failures:
        print(f"EQUIV-FAIL：{len(_failures)} 项不通过 -> {_failures}")
        sys.exit(1)
    print("EQUIV-OK：新旧路径数值等价")


if __name__ == "__main__":
    main()
