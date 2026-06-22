#Requires -Version 5.1
<#
  install-shortcut.ps1 — 在桌面创建“SHARP 高斯泼溅”快捷方式（运行一次即可）。
    快捷方式指向仓库根目录的「启动 SHARP.bat」，最小化运行，关闭窗口即停止服务。
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $RepoRoot '启动 SHARP.bat'
if (-not (Test-Path $Bat)) { throw "未找到启动脚本：$Bat" }

$Desktop = [Environment]::GetFolderPath('Desktop')
$LnkPath = Join-Path $Desktop 'SHARP 高斯泼溅.lnk'

$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($LnkPath)
$lnk.TargetPath       = $Bat
$lnk.WorkingDirectory = $RepoRoot
$lnk.WindowStyle      = 7  # 最小化启动（日志窗口在任务栏，关闭即停止服务）
$lnk.IconLocation     = "$env:SystemRoot\System32\shell32.dll,13"
$lnk.Description       = 'SHARP · 照片转高斯泼溅（单进程启动）'
$lnk.Save()

Write-Host "已创建桌面快捷方式：$LnkPath" -ForegroundColor Green
Write-Host "双击它即可启动；图标可在快捷方式属性里自行更换。" -ForegroundColor DarkGray
