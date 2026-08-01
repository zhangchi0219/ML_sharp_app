# ML SHARP App · 照片 → 高斯泼溅

一个本机 Web 应用：上传一张照片，用 **Apple SHARP** 模型在约 1 秒内生成 3D 高斯泼溅（3DGS），
在浏览器里实时旋转/缩放查看，并可下载 `.ply`。历史生成保存在本地画廊里，
可调参数并对同一张图反复重跑（见「可调参数」）。

> **SHARP** = *Sharp Monocular View Synthesis in Less Than a Second*（Apple，2025-12）。
> 单张照片经一次前向推理回归出 3D 高斯表示。论文/项目：<https://github.com/apple/ml-sharp>

> ⚠️ **许可：仅供个人 / 研究用途。** Apple 的模型遵循
> *Apple Machine Learning Research Model License*，仅限非商业的科研用途；
> 切勿用于任何商业产品或服务。代码部分见 `third_party/ml-sharp/LICENSE`。

---

## 架构

```text
原生窗口 (pywebview / WebView2)  ──同进程──>  FastAPI (随机空闲端口)
  · React + Three.js 前端                        · 常驻 SHARP 模型（热推理）
  · 拖拽上传 / GaussianSplats3D 查看器           · SQLite 历史
  · 历史画廊                                      · 静态服务 .ply / 缩略图 / 前端产物
```

日常使用是一个桌面应用（`desktop.py`）：窗口与服务在同一个进程里，无控制台、无地址栏。
开发时也可以退回浏览器模式（`scripts/app.ps1`）或前后端分离热更新（`scripts/dev.ps1`）。

- **后端**（`backend/`）：FastAPI。启动时把 SHARP 模型加载进显存并常驻，热推理约 1 秒（见「性能」）。
  通过把 `third_party/ml-sharp/src` 加入 `sys.path` 直接 import 其**预测路径**
  （`sharp.models` / `sharp.utils`），刻意**不**走 `sharp.cli`（那会牵连仅用于视频渲染的
  `gsplat`，在 Windows 上需编译 CUDA 扩展）。见 `backend/app/sharp_runner.py`。
- **前端**（`frontend/`）：Vite + React + TS。查看器用
  [`@mkkellogg/gaussian-splats-3d`](https://github.com/mkkellogg/GaussianSplats3D)
  直接加载标准 3DGS `.ply`。视觉为 studio house style（Swiss / neo-brutalist）。
  字体用 Fontsource 自托管 woff2（规避 Google CDN），中文走系统 Microsoft YaHei。

## 环境要求

- Windows（本仓库脚本为 PowerShell）。桌面窗口用系统自带的 **WebView2**（Win11 已预装）。
- 已安装 **Python 3.11+** 与 **Node 18+**。
- 约 10 GB 磁盘（venv 7.5 GB + 模型权重 2.7 GB）。
- **显卡**：不限于某一型号。装的是 CUDA 12.8 轮子，`torch.cuda.get_arch_list()` 覆盖
  `sm_61 … sm_120`，即 GTX 10 系一直到 RTX 50 系都能用，**换卡不需要改任何代码**。
  - **显存 ≥ 8 GB**：实测单张推理峰值 **7061 MB**（RTX 5080，1536×1536 内部分辨率）。
    6 GB 的卡大概率 OOM。
  - 无 NVIDIA GPU 时自动回退 CPU（界面会明确提示），能跑但慢很多。
  - RTX 50 系（Blackwell, sm_120）**必须**用 cu128 轮子，`scripts\setup.ps1` 已指定。

## 安装

```powershell
# 1) 克隆 Apple ml-sharp 到 third_party（脚本不会自动 clone）
git clone --depth 1 https://github.com/apple/ml-sharp third_party/ml-sharp

# 2) 建 venv、装 PyTorch(cu128) 与依赖，并校验
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 3) 前端依赖
npm install --prefix frontend
```

> 模型权重在首次推理时自动从 Apple CDN 下载并缓存到 `~/.cache/torch/hub/checkpoints/`
> （约 2.7 GB，只下一次）。

## 运行

### 桌面应用（推荐）

```powershell
# 双击根目录的「启动 SHARP.bat」，或在终端：
powershell -ExecutionPolicy Bypass -File scripts\desktop.ps1
# 前端产物缺失时会自动 npm run build；改了前端代码要更新界面：加 -Rebuild
```

窗口会**立刻**出现并显示启动页，模型在后台加载（约 20–30 秒，首次还要先下权重），
就绪后自动切到应用界面。端口自动选空闲值，同时开两份也不冲突。关窗即退出。

想要桌面图标，运行一次：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-shortcut.ps1
# 在桌面生成「SHARP 高斯泼溅」快捷方式，直接指向 pythonw desktop.py，全程无控制台
```

### 浏览器模式（要看服务日志时用）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\app.ps1
# FastAPI 单进程托管前端，模型就绪后自动打开 http://localhost:8000
# 控制台可见，方便排查；强制重建前端：scripts\app.ps1 -Rebuild
```

### 开发模式（前后端分离，热更新）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 后端 :8000、前端 :5173（Vite 代理 /api 与 /files），打开 http://localhost:5173
```

或手动分别启动：

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
# 前端（另开一个终端）
npm run dev --prefix frontend
```

## 可调参数

侧栏面板可以在生成前调参；生成后点「用当前参数重新生成」会**复用已存的源图**重跑（约 1 秒），
产出一条**新**记录而非覆盖原来的，因此可在画廊里并排对比。点历史缩略图会回看该次结果，
并把当时的参数回填进面板。参数随记录存进 SQLite。

参数分两类。**导出后处理**不重新推理，只改写结果：

| 参数 | 范围 / 默认 | 作用 |
| --- | --- | --- |
| 泼溅数量 | 0.25 / 0.6 / 1.0 | 按不透明度 Top-K 裁剪。原生 118 万个只能减少，无法增加 |
| 尺寸比例 | 0.5–2.0，默认 1.0 | 所有高斯的 3D 尺度整体缩放 |

**推理参数**真正参与前向计算。它们改写的是 `GaussianComposer` 与 `MultiLayerInitializer`
的属性——这两个模块**不含任何权重**，属性是纯 Python 值且每次 forward 都重读，
所以能逐次请求临时改写再还原，**不必重载那 2.7 GB 权重**（见 `sharp_runner._composed_with`）。

| 参数 | 范围 / 默认 | 映射到 | 作用 |
| --- | --- | --- | --- |
| 等效焦距 | 14–85mm；默认跟随 EXIF | `f_px` | **对纵深影响最大的单一变量**。广角压缩纵深、长焦拉开纵深 |
| 色彩强度 | 0–3×，默认 1× | `delta_factor.color` | 0 = 直接用原图下采样色，不做网络修正 |
| 大小变化 | 0–3×，默认 1× | `delta_factor.scale` | 0 = 所有泼溅一样大 |
| 形状拉伸 | 0–3×，默认 1× | `delta_factor.quaternion` | 0 = 全是正球，无各向异性 |
| 通透对比 | 0–3×，默认 1× | `delta_factor.opacity` | 0 = 两层不透明度均匀 |
| 深度浮雕 | 0–3×，默认 1× | `delta_factor.z` | 放大逐点深度位移，过高会撕裂画面 |
| 尺度上限 | 1.5–20，默认 10 | `max_scale` | 单个泼溅相对基准尺寸的放大上限 |

后五项在 UI 上是**相对 SHARP 默认值的倍率**，故 `1.00×` 恒等于原生效果（默认参数的输出与
引入本功能前**逐字节相同**）。范围唯一定义在 `backend/app/main.py` 的 `GenParams`，
前端 `lib/types.ts` 的滑块边界必须与之同步。

> **焦距为什么值得单独调**：`sharp.utils.io.load_rgb` 从 EXIF 读 35mm 等效焦距，
> **读不到就一律按 30mm 处理**。网图、截图、社交平台压缩过的图基本都没有 EXIF，
> 而这个值同时决定 `disparity_factor`（单目深度→米制换算）与反投影内参。
> 「自动」档会显示实际用到的值。

### 不可调的部分（已核实）

- **架构参数**（`dims_decoder` / `preset` / `stride` / `num_layers` / `norm_type`）——
  改了 `load_state_dict` 直接失败。
- **内部分辨率 1536**——等于 SPN 的 `patch_size*4`（`spn_encoder.py`），而 `split`/`merge`
  假设方形网格、金字塔最低层必须正好 384 才能喂给 `img_size=384` 的 ViT；且显存峰值已 7 GB。
- **死参数**：`low_pass_filter_eps`（只被 `utils/gsplat.py` 的渲染器读，本应用未装 gsplat）、
  `use_predicted_mean`（`create_predictor` 根本没读它）、`initializer.base_depth`
  （默认 `surface_min` 下不生效）、`AlignmentParams` 全家（推理时 `depth=None`，对齐分支不走）。
- `initializer.scale_factor` 与「尺寸比例」**数学上等价**（同为 base scale 的线性因子），故不重复暴露。

## 验证 / 冒烟

```powershell
# 端到端验证 SHARP 集成：加载模型 + 对样图生成 .ply + 校验输出
.\.venv\Scripts\python.exe backend\smoke.py
```

## 目录

```text
desktop.py          桌面入口：pywebview 窗口 + 进程内 uvicorn（日常启动走这里）
backend/app/        FastAPI 应用：main / sharp_runner(热模型) / db / models / paths
backend/smoke.py    SHARP 集成冒烟脚本（含显存峰值实测）
frontend/src/       React 应用：App / components(Uploader/ParamPanel/SplatViewer/Gallery) / lib
scripts/            setup.ps1（环境） · desktop.ps1（桌面） · app.ps1（浏览器） · dev.ps1（开发）
                    profile_predict.py（分段计时） · verify_equivalence.py（等价校验）
                    prune-runtime.ps1（venv 瘦身，默认 dry-run）
third_party/ml-sharp  Apple SHARP 源码（git clone，未纳入本仓库）
backend/data/       运行时：uploads/ gaussians/ thumbs/ logs/ sharp.db（已 gitignore）
```

## 性能

RTX 5080、1536×1536 内部分辨率、1,179,648 个高斯、GPU 空闲时实测（5 次取中位数）：

| 阶段 | 耗时 | 占比 |
| --- | --- | --- |
| 读图 + 上传 GPU | 0.012s | 1.2% |
| **前向推理（神经网络）** | **0.865s** | **85.5%** |
| unproject（协方差分解） | 0.082s | 8.1% |
| 导出 .ply（66 MB） | 0.049s | 4.9% |
| **合计** | **1.01s** | |

上游 `ml-sharp` 的导出路径原本要 **5.29s**，其中 4.2s 耗在三处与模型无关的 CPU 瓶颈上。
`backend/app/sharp_runner.py` 在 import 阶段把它们替换掉（不修改 `third_party`）：

| 上游实现 | 本仓库的替代 | 提速 |
| --- | --- | --- |
| 118 万个 3×3 搬到 CPU 做 float64 `svd` | GPU 分块 `eigh`（`_decompose_fast`） | 10.4× |
| scipy `Rotation.from_matrix` 转四元数 | 向量化四元数（同上，一并消除） | — |
| `list(map(tuple, ...))` 逐行造 Python tuple | 零拷贝结构化数组（`_save_ply_fast`） | 6.6× |

端到端 **5.29s → 1.03s（5.1×）**。与上游输出的差异（teaser.jpg，118 万个高斯实测）：

- `x/y/z`、`f_dc_*`、`opacity` —— **逐位相同**（这些量不经过特征分解）。
- `scale_*` —— 最大差 2.0e-5（float32 `eigh` 与 float64 `svd` 的数值差异）。
- `rot_*` —— 可能整体差一个符号（最大差 √2）。四元数 q 与 −q 表示同一个旋转，
  真正的不变量是重建出的协方差 R·diag(s²)·Rᵀ，实测与原始协方差差 8.9e-7
  （上游自己是 5.4e-7，同一量级）。

- 复算耗时：`.\.venv\Scripts\python.exe scripts\profile_predict.py 5`
- 验证等价：`.\.venv\Scripts\python.exe scripts\verify_equivalence.py`

> cusolver 的批量 `syev` 在本机（CUDA 12.8）超过约 3 万的 batch 就报
> `CUSOLVER_STATUS_INVALID_VALUE`，与显存余量无关，故按 8192 分块；
> 若在别的 GPU 上仍失败会自动退回 CPU（慢约 1.4s/张，不会崩）。

## 数据与路径

所有路径由 `backend/app/paths.py` 统一解析，代码里不再有 `__file__` 反推的硬编码。
开发态数据落在 `backend/data/`；下列环境变量可逐项覆盖（打包分发时会用到）：

| 变量 | 作用 |
| --- | --- |
| `SHARP_DATA_DIR` | 数据根：SQLite、uploads、gaussians、thumbs、logs |
| `SHARP_APP_ROOT` | 资源根（只读） |
| `SHARP_SRC` | ml-sharp 源码目录 |
| `SHARP_DIST` | 前端构建产物目录 |
| `SHARP_CHECKPOINT` | 随包分发的模型权重；未设置则走 CDN 下载 |

桌面模式下 `sys.stdout/stderr` 为 None（pythonw 无控制台），日志写入
`<数据根>/logs/desktop.log`（2 MB 轮转，保留 2 份）。出问题先看这个文件。

## 瘦身（分发用）

`.venv` 有 7.50 GB，其中约 2.9 GB 运行时根本用不到：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prune-runtime.ps1          # 只看清单
powershell -ExecutionPolicy Bypass -File scripts\prune-runtime.ps1 -Apply   # 真删
.\.venv\Scripts\python.exe backend\smoke.py                                 # 删完必须验证
```

删 `*.lib`（2.62 GB，静态链接库，纯编译期产物）、`__pycache__`（211 MB，会自动重建）、
`imageio_ffmpeg`（84 MB，预测路径不碰视频），**7.50 GB → 4.59 GB**。
默认保留 `pip`/`setuptools`（只值 24 MB，删了就装不了新包），做分发副本时可加 `-IncludePip`。

刻意不动 `torch\lib` 里的 CUDA DLL（cusparse 362 MB、cufft 263 MB 等）——
torch 在 Windows 上 import 时会预加载，删了可能直接起不来。

## 说明

- **坐标约定**：SHARP 输出遵循 OpenCV（x 右 / y 下 / z 前），场景中心约在 `(0,0,+z)`。
  查看器据此设置 `cameraUp=[0,-1,0]`；外部渲染器查看时可能需自行旋转/缩放居中。
- **不含视频渲染**：SHARP 的 `--render`（环绕视频）需要 `gsplat`，本应用未安装；
  如需该功能，另行 `pip install gsplat`（Windows 需 CUDA Toolkit + MSVC）。
