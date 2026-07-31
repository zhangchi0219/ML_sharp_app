"""端到端冒烟：加载一次 SHARP 模型，对样图生成 .ply，校验输出与热推理。

用法（在已建好的 .venv 下）：
    .venv\\Scripts\\python.exe backend\\smoke.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 让 `import app...` 可用

from app import paths, sharp_runner  # noqa: E402

SAMPLE = paths.sharp_src().parent / "data" / "teaser.jpg"
OUT = paths.data_dir() / "_smoke"


def _header_lines(ply: Path) -> list[str]:
    lines: list[str] = []
    with open(ply, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", "replace").strip()
            if line == "end_header":
                break
            lines.append(line)
    return lines


def main() -> None:
    assert SAMPLE.exists(), f"找不到样图: {SAMPLE}"
    OUT.mkdir(parents=True, exist_ok=True)

    t = time.time()
    sharp_runner.warmup()
    print(f"[warmup] {time.time() - t:.1f}s  device={sharp_runner.device()}")

    out1 = OUT / "teaser.ply"
    t = time.time()
    sharp_runner.predict(SAMPLE, out1)
    dt1 = time.time() - t
    print(f"[predict#1] {dt1:.2f}s -> {out1}  ({out1.stat().st_size / 1e6:.1f} MB)")

    hdr = _header_lines(out1)
    assert any(h.startswith("element vertex") for h in hdr), hdr
    for prop in ("f_dc_0", "scale_0", "rot_0", "opacity"):
        assert any(prop in h for h in hdr), f"PLY 缺少属性 {prop}"
    nverts = next(h for h in hdr if h.startswith("element vertex")).split()[-1]
    print(f"[ply] vertex(高斯)数 = {nverts}")

    t = time.time()
    sharp_runner.predict(SAMPLE, OUT / "teaser2.ply")
    print(f"[predict#2 warm] {time.time() - t:.2f}s")

    # 显存峰值：决定这个应用能在多大的卡上跑，写进 README 的硬件要求。
    info = sharp_runner.device_info()
    if info["vramPeakMb"] is not None:
        print(
            f"[vram] {info['deviceName']} · 峰值 {info['vramPeakMb']} MB "
            f"/ 总量 {info['vramTotalMb']} MB"
        )

    print("SMOKE-OK")


if __name__ == "__main__":
    main()
