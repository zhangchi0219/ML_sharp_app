"""SHARP 桌面入口：一个原生窗口 + 进程内的 FastAPI 服务。

与 `scripts/app.ps1` 的区别：
- 无控制台窗口、无浏览器地址栏（pywebview 用 Windows 自带的 WebView2）。
- 端口自动选取空闲值，不再硬编码 8000——同时开两份或 8000 被占都不冲突。
- 窗口**立刻**出现并显示启动页，模型在后台加载；就绪后自动切到应用。
  （`app.main` 的 lifespan 里 warmup 是阻塞的，加载期间服务不响应，
   所以不能一上来就 load 应用 URL，否则用户会看到几十秒的连接失败。）

调试时想看服务日志，仍然用 `scripts/app.ps1`。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "backend"))  # 让 `import app.main` 可用

from app import paths  # noqa: E402

LOGGER = logging.getLogger("desktop")

TITLE = "SHARP · 照片转高斯泼溅"
# 首次运行要从 Apple CDN 拉 2.7GB 权重，超时必须给得足够宽。
READY_TIMEOUT_S = 30 * 60


def _setup_logging() -> Path:
    """日志写文件。pythonw 下 sys.stdout/stderr 都是 None，控制台日志会全部丢失，
    出了问题这个文件是唯一线索——也是把应用发给别人之后唯一能让对方回传的东西。

    必须最先调用：在它之前抛的异常没有任何落点（无控制台、无日志、无窗口）。
    也必须在 import app.main 之前调好：root 上已有 handler 时，
    app.main 里的 logging.basicConfig() 会自动让位。
    """
    try:
        log_dir = paths.data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 数据目录不可写（只读安装、权限不足）时退到临时目录，总比没有日志强。
        log_dir = Path(tempfile.gettempdir()) / "sharp-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "desktop.log"
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    return log_file


def _fatal(message: str) -> None:
    """记录并弹一个系统对话框。

    pythonw 没有控制台，窗口又可能还没建起来，MessageBox 是唯一保证用户能看见的途径。
    没有它的话，比如 venv 里缺 pywebview，双击图标就是「什么都没发生」。
    """
    logging.getLogger("desktop").error(message)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, f"{TITLE} · 启动失败", 0x10)
    except Exception:  # noqa: BLE001 — 弹窗失败也不能再抛，日志已经记下了
        pass


def _free_port() -> int:
    """向系统要一个空闲端口。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# 服务线程里的异常：daemon 线程的异常会走 threading.excepthook 写 stderr，
# 而 pythonw 下 stderr 是 None，等于被吞掉。这里存下来交给主线程展示。
_server_error: BaseException | None = None


def _serve(port: int) -> None:
    """在后台线程里跑 uvicorn（uvicorn 会自行跳过非主线程的信号处理器安装）。"""
    global _server_error
    try:
        import uvicorn

        from app.main import app

        # log_config=None：不让 uvicorn 装自己那套写 stdout 的 handler，
        # 否则 pythonw 下 stream 是 None，日志既进不了文件也会一路报错。
        uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", log_config=None)
        ).run()
    except BaseException as exc:  # noqa: BLE001 — SystemExit 也要抓：端口被抢时 uvicorn 走这条
        _server_error = exc
        LOGGER.exception("服务线程异常退出")


def _wait_ready(url: str, timeout_s: float, server: threading.Thread) -> str | None:
    """轮询 /api/health，就绪返回 None，否则返回一句给用户看的原因。

    同时盯着服务线程是否还活着——它要是挂了（third_party 缺失、端口被抢…），
    再怎么轮询也不会有结果，不能让用户对着启动页干等半小时。
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2):
                return None
        except (urllib.error.URLError, OSError, TimeoutError):
            if not server.is_alive():
                if _server_error is not None:
                    return f"{type(_server_error).__name__}: {_server_error}"
                return "服务进程已退出，但没有留下异常信息。"
            time.sleep(0.4)
    return f"服务未在 {int(timeout_s / 60)} 分钟内就绪。"


def _page(heading: str, body: str, *, spin: bool = False) -> str:
    """启动页 / 错误页。内联样式，因为这时前端资源还没接管。"""
    dots = '<div class="dots"><i></i><i></i><i></i></div>' if spin else ""
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>{TITLE}</title><style>
  :root {{ --canvas:#EBE4D6; --ink:#2A241E; --muted:#8A7E6D; --hot:#BE6A4A; }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ height:100vh; display:grid; place-items:center; background:var(--canvas);
         color:var(--ink); font-family:"Microsoft YaHei",system-ui,sans-serif; }}
  .wrap {{ text-align:center; padding:0 48px; max-width:640px; }}
  .mark {{ font-size:.75rem; letter-spacing:.32em; color:var(--muted); margin-bottom:24px; }}
  h1 {{ font-size:2rem; font-weight:700; line-height:1.2; margin-bottom:16px; }}
  p {{ font-size:.8125rem; line-height:1.7; color:var(--muted); white-space:pre-line; }}
  .dots {{ display:flex; gap:8px; justify-content:center; margin-top:32px; }}
  .dots i {{ width:8px; height:8px; border-radius:50%; background:var(--hot);
             animation:b 1.2s ease-in-out infinite; }}
  .dots i:nth-child(2) {{ animation-delay:.15s }} .dots i:nth-child(3) {{ animation-delay:.3s }}
  @keyframes b {{ 0%,80%,100%{{opacity:.2;transform:translateY(0)}} 40%{{opacity:1;transform:translateY(-5px)}} }}
</style></head><body><div class="wrap">
  <div class="mark">SHARP</div><h1>{heading}</h1><p>{body}</p>{dots}
</div></body></html>"""


SPLASH = _page(
    "正在启动…",
    "首次运行需要把 SHARP 模型加载进显存，约 20–30 秒。\n"
    "如果是第一次使用，还会先从 Apple 下载约 2.7 GB 的模型权重，请耐心等待。",
    spin=True,
)


def main() -> int:
    # 日志必须最先建起来，之后任何异常才有地方落。
    log_file = _setup_logging()
    LOGGER.info("SHARP 桌面启动 · 数据目录=%s", paths.data_dir())

    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        # 最典型的情形：venv 是旧 setup.ps1 建的，里面没有 pywebview。
        # 这时窗口根本建不起来，只能靠系统对话框告诉用户，否则就是「双击了没反应」。
        _fatal(
            f"缺少桌面窗口依赖 pywebview：{exc}\n\n"
            f"请重新运行 scripts\\setup.ps1（或 pip install pywebview）。\n"
            f"日志：{log_file}"
        )
        return 1

    dist = paths.frontend_dist()
    if not (dist / "index.html").exists():
        webview.create_window(
            TITLE,
            html=_page("前端尚未构建", f"缺少 {dist}\n请先运行：npm run build --prefix frontend"),
            width=900,
            height=600,
        )
        webview.start()
        return 1

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    server = threading.Thread(target=_serve, args=(port,), daemon=True)
    server.start()

    window = webview.create_window(TITLE, html=SPLASH, width=1440, height=900, min_size=(960, 640))

    def on_start() -> None:
        reason = _wait_ready(url, READY_TIMEOUT_S, server)
        if reason is None:
            window.load_url(url)
        else:
            LOGGER.error("启动失败：%s", reason)
            window.load_html(_page("启动失败", f"{reason}\n\n日志：{log_file}"))

    webview.start(on_start)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except BaseException as exc:  # noqa: BLE001 — 兜底：没有它，pythonw 下崩溃是完全无声的
        _fatal(f"启动时发生未处理的异常：\n{type(exc).__name__}: {exc}")
        code = 1
    # 服务线程是 daemon，但 uvicorn 持有的 socket 偶尔会拖住退出——直接了断。
    logging.shutdown()
    os._exit(code)
