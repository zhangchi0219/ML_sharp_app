# ML SHARP App · 照片 → 高斯泼溅

一个本机 Web 应用：上传一张照片，用 **Apple SHARP** 模型在约 1 秒内生成 3D 高斯泼溅（3DGS），
在浏览器里实时旋转/缩放查看，并可下载 `.ply`。历史生成保存在本地画廊里。

> **SHARP** = *Sharp Monocular View Synthesis in Less Than a Second*（Apple，2025-12）。
> 单张照片经一次前向推理回归出 3D 高斯表示。论文/项目：<https://github.com/apple/ml-sharp>

> ⚠️ **许可：仅供个人 / 研究用途。** Apple 的模型遵循
> *Apple Machine Learning Research Model License*，仅限非商业的科研用途；
> 切勿用于任何商业产品或服务。代码部分见 `third_party/ml-sharp/LICENSE`。

---

## 架构

```
浏览器 (React + Three.js)  ──/api,/files──>  FastAPI (:8000)
  · 拖拽上传                 (vite :5173 代理)   · 常驻 SHARP 模型（热推理）
  · GaussianSplats3D 查看器                       · SQLite 历史
  · 历史画廊                                       · 静态服务 .ply / 缩略图
```

- **后端**（`backend/`）：FastAPI。启动时把 SHARP 模型加载进显存并常驻，重复推理 <1 秒。
  通过把 `third_party/ml-sharp/src` 加入 `sys.path` 直接 import 其**预测路径**
  （`sharp.models` / `sharp.utils`），刻意**不**走 `sharp.cli`（那会牵连仅用于视频渲染的
  `gsplat`，在 Windows 上需编译 CUDA 扩展）。见 `backend/app/sharp_runner.py`。
- **前端**（`frontend/`）：Vite + React + TS。查看器用
  [`@mkkellogg/gaussian-splats-3d`](https://github.com/mkkellogg/GaussianSplats3D)
  直接加载标准 3DGS `.ply`。视觉为 studio house style（Swiss / neo-brutalist）。
  字体用 Fontsource 自托管 woff2（规避 Google CDN），中文走系统 Microsoft YaHei。

## 环境要求

- Windows（本仓库脚本为 PowerShell）；推理需 **NVIDIA GPU**（已在 RTX 5080 / CUDA 12.8 上验证）。
  无 GPU 也能跑（CPU，较慢）。
- 已安装 **Python 3.11+** 与 **Node 18+**。
- 约 8 GB 磁盘（PyTorch + 依赖 + 模型权重）。

## 安装

```powershell
# 1) 克隆 Apple ml-sharp 到 third_party（脚本不会自动 clone）
git clone --depth 1 https://github.com/apple/ml-sharp third_party/ml-sharp

# 2) 建 venv、装 PyTorch(cu128) 与依赖，并校验
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 3) 前端依赖
npm install --prefix frontend
```

> RTX 5080 属 Blackwell(sm_120)，**必须**用 CUDA 12.8 的 PyTorch 轮子
> （`scripts\setup.ps1` 已指定 `--index-url https://download.pytorch.org/whl/cu128`）。
> 模型权重在首次推理时自动从 Apple CDN 下载并缓存到 `~/.cache/torch/hub/checkpoints/`。

## 运行

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 然后打开 http://localhost:5173
```

或手动分别启动：

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
# 前端（另开一个终端）
npm run dev --prefix frontend
```

## 验证 / 冒烟

```powershell
# 端到端验证 SHARP 集成：加载模型 + 对样图生成 .ply + 校验输出
.\.venv\Scripts\python.exe backend\smoke.py
```

## 目录

```
backend/app/        FastAPI 应用：main / sharp_runner(热模型) / db / models
backend/smoke.py    SHARP 集成冒烟脚本
frontend/src/       React 应用：App / components(Uploader/SplatViewer/Gallery) / lib
scripts/            setup.ps1（环境） · dev.ps1（启动）
third_party/ml-sharp  Apple SHARP 源码（git clone，未纳入本仓库）
backend/data/       运行时：uploads/ gaussians/ thumbs/ sharp.db（已 gitignore）
```

## 说明

- **坐标约定**：SHARP 输出遵循 OpenCV（x 右 / y 下 / z 前），场景中心约在 `(0,0,+z)`。
  查看器据此设置 `cameraUp=[0,-1,0]`；外部渲染器查看时可能需自行旋转/缩放居中。
- **不含视频渲染**：SHARP 的 `--render`（环绕视频）需要 `gsplat`，本应用未安装；
  如需该功能，另行 `pip install gsplat`（Windows 需 CUDA Toolkit + MSVC）。
