@echo off
chcp 65001 >nul
rem 带前置检查的启动：必要时先构建前端，再用 pythonw 拉起原生窗口（窗口本身无控制台）。
rem 改了前端代码后想更新界面："启动 SHARP.bat" -Rebuild
rem 日常使用建议走桌面快捷方式（scripts\install-shortcut.ps1 生成），那条路径全程无控制台。
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\desktop.ps1" %*
rem 出错时（缺 venv、npm 构建失败…）停下来让用户看清报错——
rem 否则双击运行的 cmd 窗口会立刻关闭，错误信息一闪而过。
if errorlevel 1 (
    echo.
    echo [启动失败] 上面是错误详情。
    pause
)
