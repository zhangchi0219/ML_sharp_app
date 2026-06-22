@echo off
chcp 65001 >nul
rem 双击启动 SHARP：构建前端(如需) -> 启动单进程服务 -> 自动开浏览器。
rem 传参可透传，例如 "启动 SHARP.bat" -Rebuild 可强制重建前端。
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\app.ps1" %*
