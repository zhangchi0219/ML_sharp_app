"""一次性诊断脚本：查清 sharp_runner.predict() 的每一段时间花在哪。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\profile_predict.py [重复次数]

两种互相印证的测法：
  1) 分段计时——手工复刻 predict() 的流程，每段前后插 torch.cuda.synchronize()。
     不插同步的话前向是异步返回的，它的耗时会被错误地记到后面第一个 .cpu() 上。
  2) cProfile——对完整的 predict() 做函数级归因，这样不用改 third_party
     也能看到 decompose_covariance_matrices / save_ply 各自占多少。

不进生产路径，输出全部写 scratchpad，不污染 backend/data。
"""

from __future__ import annotations

import cProfile
import io as _io
import pstats
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

import torch  # noqa: E402

from app import sharp_runner  # noqa: E402
from sharp.utils import io  # noqa: E402
from sharp.utils.gaussians import unproject_gaussians  # noqa: E402

# 注意：导出必须用 sharp_runner._save_ply_fast，也就是 predict() 真正走的那个。
# 直接 import 上游的 save_ply 会测到未优化的实现（sharp_runner 只替换了
# decompose_covariance_matrices 的模块属性，save_ply 是在 predict 里直接换掉的）。
save_ply = sharp_runner._save_ply_fast

SAMPLE = _ROOT / "third_party" / "ml-sharp" / "data" / "teaser.jpg"
OUT = Path(tempfile.gettempdir()) / "sharp_profile"

_timings: dict[str, float] = {}


def _sync() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


@contextmanager
def stage(name: str):
    """给一段代码计时，两端都同步，保证 GPU 工作真的做完了才停表。"""
    _sync()
    t0 = time.perf_counter()
    yield
    _sync()
    _timings[name] = time.perf_counter() - t0


@torch.no_grad()
def staged_predict(image_path: Path, out_ply: Path) -> None:
    """复刻 sharp_runner.predict() 的流程，但逐段计时。

    必须与 sharp_runner._predict_image / predict 保持一致，否则测的不是同一件事。
    """
    dev = torch.device(sharp_runner.device())
    predictor = sharp_runner._predictor
    shape = sharp_runner._INTERNAL_SHAPE

    with stage("1. load_rgb 读图"):
        image, _icc, f_px = io.load_rgb(image_path)
    height, width = image.shape[:2]

    with stage("2. 上传GPU + resize"):
        image_pt = torch.from_numpy(image.copy()).float().to(dev).permute(2, 0, 1) / 255.0
        disparity_factor = torch.tensor([f_px / width]).float().to(dev)
        image_resized = torch.nn.functional.interpolate(
            image_pt[None], size=(shape[1], shape[0]), mode="bilinear", align_corners=True
        )

    with stage("3. 前向推理 (神经网络)"):
        gaussians_ndc = predictor(image_resized, disparity_factor)

    intrinsics = torch.tensor(
        [[f_px, 0, width / 2, 0], [0, f_px, height / 2, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    ).float().to(dev)
    intrinsics_resized = intrinsics.clone()
    intrinsics_resized[0] *= shape[0] / width
    intrinsics_resized[1] *= shape[1] / height

    with stage("4. unproject (含CPU SVD+四元数)"):
        gaussians = unproject_gaussians(
            gaussians_ndc, torch.eye(4).to(dev), intrinsics_resized, shape
        )

    with stage("5. postprocess"):
        gaussians = sharp_runner._postprocess_gaussians(gaussians)

    with stage("6. save_ply 导出"):
        save_ply(gaussians, f_px, (height, width), out_ply)


def run_staged(repeats: int) -> None:
    print(f"\n{'=' * 62}\n分段计时（{repeats} 次取中位数，已插 cuda.synchronize）\n{'=' * 62}")
    runs: list[dict[str, float]] = []
    for i in range(repeats):
        _timings.clear()
        t0 = time.perf_counter()
        staged_predict(SAMPLE, OUT / f"staged_{i}.ply")
        total = time.perf_counter() - t0
        _timings["__total__"] = total
        runs.append(dict(_timings))
        print(f"  第 {i + 1} 次：{total:.2f}s")

    names = [k for k in runs[0] if k != "__total__"]
    med = {n: statistics.median(r[n] for r in runs) for n in names}
    total_med = statistics.median(r["__total__"] for r in runs)
    seg_sum = sum(med.values())

    print(f"\n  {'阶段':<34}{'耗时':>9}{'占比':>9}")
    print(f"  {'-' * 52}")
    for n in names:
        print(f"  {n:<34}{med[n]:>8.3f}s{med[n] / total_med * 100:>8.1f}%")
    print(f"  {'-' * 52}")
    print(f"  {'分段合计':<34}{seg_sum:>8.3f}s")
    print(f"  {'predict 总耗时':<34}{total_med:>8.3f}s")
    drift = abs(total_med - seg_sum) / total_med * 100
    print(f"  {'未计入的差值':<34}{total_med - seg_sum:>8.3f}s ({drift:.1f}%)")
    if drift >= 5:
        print("  ⚠ 差值超过 5%，说明有没测到的段，结论不可全信")


def run_cprofile() -> None:
    print(f"\n{'=' * 62}\ncProfile 函数级归因（完整 predict，按累计时间排序）\n{'=' * 62}")
    pr = cProfile.Profile()
    pr.enable()
    sharp_runner.predict(SAMPLE, OUT / "profiled.ply")
    pr.disable()
    s = _io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(28)
    # 只保留表格部分，去掉冗长的头部。
    lines = s.getvalue().splitlines()
    start = next((i for i, ln in enumerate(lines) if "ncalls" in ln), 0)
    print("\n".join(lines[start : start + 30]))


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    assert SAMPLE.exists(), f"找不到样图: {SAMPLE}"
    OUT.mkdir(parents=True, exist_ok=True)

    t = time.perf_counter()
    sharp_runner.warmup()
    print(f"[warmup] {time.perf_counter() - t:.1f}s  device={sharp_runner.device()}")

    # 先跑一次丢弃：首次推理要建 CUDA 上下文、分配显存池、加载 cuDNN 内核。
    sharp_runner.predict(SAMPLE, OUT / "discard.ply")
    print("[丢弃首次运行完成，下面的数字才是热态]")

    run_staged(repeats)
    run_cprofile()

    info = sharp_runner.device_info()
    if info["vramPeakMb"]:
        print(f"\n[显存] 峰值 {info['vramPeakMb']} MB / 总量 {info['vramTotalMb']} MB")
    print(f"[输出] {OUT}")


if __name__ == "__main__":
    main()
