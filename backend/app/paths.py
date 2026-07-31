"""路径解析：全应用唯一的路径真相来源。

开发态与安装态的差别**只在本模块体现**，其余模块一律通过这里取路径。

两个根是分开的概念，开发态碰巧重合（都在仓库里），装到只读目录后才分开：

- 资源根 `app_root()`：**只读**。放 `frontend/dist`、`third_party/ml-sharp`。
- 数据根 `data_dir()`：**必须可写**。放 SQLite、uploads、gaussians、thumbs。

判定安装态的两个信号（任一成立即可）：
    1. `sys.frozen`（PyInstaller 之类的冻结打包）
    2. 资源根下存在 `.installed` 标记文件（分发"剪枝 venv 目录"时由安装器写入）

以下环境变量可逐项覆盖，安装器与调试都用它：
    SHARP_APP_ROOT · SHARP_DATA_DIR · SHARP_SRC · SHARP_DIST · SHARP_CHECKPOINT
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def _env_path(name: str) -> Path | None:
    """读取环境变量里的路径；未设置或为空串时返回 None。"""
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


@lru_cache(maxsize=None)
def app_root() -> Path:
    """资源根（只读）。开发态为仓库根目录。"""
    if (override := _env_path("SHARP_APP_ROOT")) is not None:
        return override
    if getattr(sys, "frozen", False):
        # PyInstaller onefile 解包到 _MEIPASS；onedir 则用 exe 所在目录。
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    # backend/app/paths.py -> backend/app -> backend -> 仓库根
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=None)
def is_installed() -> bool:
    """是否运行在"已安装"形态（资源根只读，数据必须另寻可写位置）。"""
    return bool(getattr(sys, "frozen", False)) or (app_root() / ".installed").exists()


@lru_cache(maxsize=None)
def data_dir() -> Path:
    """数据根（可写）。开发态沿用 `backend/data`，保持既有落盘位置不变。"""
    if (override := _env_path("SHARP_DATA_DIR")) is not None:
        return override
    if is_installed():
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) / "SHARP" if base else Path.home() / ".sharp") / "data"
    return app_root() / "backend" / "data"


@lru_cache(maxsize=None)
def sharp_src() -> Path:
    """Apple ml-sharp 的 src-layout 源码目录（加入 sys.path 后可 import sharp.*）。"""
    if (override := _env_path("SHARP_SRC")) is not None:
        return override
    return app_root() / "third_party" / "ml-sharp" / "src"


@lru_cache(maxsize=None)
def frontend_dist() -> Path:
    """前端构建产物目录（`npm run build` 的输出）。"""
    if (override := _env_path("SHARP_DIST")) is not None:
        return override
    return app_root() / "frontend" / "dist"


@lru_cache(maxsize=None)
def checkpoint_path() -> Path | None:
    """随包分发的模型权重；返回 None 表示走 torch.hub 从 Apple CDN 下载并缓存。"""
    if (override := _env_path("SHARP_CHECKPOINT")) is not None:
        return override if override.exists() else None
    bundled = app_root() / "models" / "sharp.pt"
    return bundled if bundled.exists() else None


# ── 数据根下的具体位置 ──


def db_path() -> Path:
    return data_dir() / "sharp.db"


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def gaussians_dir() -> Path:
    return data_dir() / "gaussians"


def thumbs_dir() -> Path:
    return data_dir() / "thumbs"


def ensure_data_dirs() -> None:
    """创建数据根及其全部子目录。幂等，可重复调用。"""
    for d in (data_dir(), uploads_dir(), gaussians_dir(), thumbs_dir()):
        d.mkdir(parents=True, exist_ok=True)
